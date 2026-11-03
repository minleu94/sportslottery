"""Default suite stays offline; live network checks require an explicit opt-in.
All tests run against isolated temporary databases to protect production war chest data.
"""
import sqlite3
from pathlib import Path
import pytest
import requests
import urllib.request


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False,
                     help="run tests marked live that make real network requests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live network test; pass --run-live to opt in")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def reject_unmarked_network_calls(request, monkeypatch):
    if request.config.getoption("--run-live"):
        return

    def reject(*args, **kwargs):
        raise AssertionError("Network access is disabled in the default offline test suite.")

    monkeypatch.setattr(requests.sessions.Session, "request", reject)
    monkeypatch.setattr(urllib.request, "urlopen", reject)


@pytest.fixture(autouse=True)
def isolate_database_for_tests(tmp_path_factory, monkeypatch):
    """
    Ensure all tests run against a temporary isolated database and NEVER touch production DB.
    Production DB path (war_chest.sqlite3) is protected by a strict safety guard.
    """
    test_storage = tmp_path_factory.mktemp("test_storage")
    import core.storage_config as sc
    production_root = sc.resolve_storage_path_bundle().root
    storage_paths = sc.resolve_storage_path_bundle(test_storage)
    test_db = storage_paths.wallet_db
    research_root = storage_paths.research_root

    # 1. Patch the process storage bundle and its compatibility helpers.
    monkeypatch.setattr(sc, "get_storage_path_bundle", lambda: storage_paths)
    monkeypatch.setattr(sc, "get_storage_root", lambda: storage_paths.root)
    monkeypatch.setattr(sc, "get_db_path", lambda: storage_paths.wallet_db)
    monkeypatch.setattr(sc, "get_research_root", lambda: storage_paths.research_root)

    # 2. Patch core.profile_manager
    import core.profile_manager as pm
    monkeypatch.setattr(pm, "DEFAULT_DB_PATH", test_db)
    monkeypatch.setattr(pm, "get_db_path", lambda: test_db)

    # 3. Patch core.wallet
    import core.wallet as cw
    monkeypatch.setattr(cw, "DEFAULT_DB_PATH", test_db)
    monkeypatch.setattr(cw, "get_db_path", lambda: test_db)

    # 4. Patch core.war_chest
    import core.war_chest as cwc
    monkeypatch.setattr(cwc, "DEFAULT_DB_PATH", test_db)
    monkeypatch.setattr(cwc, "get_db_path", lambda: test_db)

    # Default research writers and SettlementEngine may be created without an
    # explicit path. Redirect every import-time default into this test's bundle.
    from core.research_paths import research_paths
    import core.snapshot_logger as snapshot_logger
    import core.shadow_parlay_logger as shadow_parlay_logger
    import core.odds_watcher as odds_watcher
    import core.line_movement as line_movement
    import core.model_acceptance as model_acceptance
    monkeypatch.setattr(snapshot_logger, "SNAPSHOT_FILE", research_paths(research_root)["snapshots"])
    monkeypatch.setattr(shadow_parlay_logger, "PARLAY_SNAPSHOT_FILE", research_paths(research_root)["parlays"])
    monkeypatch.setattr(odds_watcher, "ODDS_HISTORY_FILE", research_paths(research_root)["odds"])
    monkeypatch.setattr(line_movement, "DEFAULT_ODDS_HISTORY_FILE", research_paths(research_root)["odds"])
    monkeypatch.setattr(model_acceptance, "SNAPSHOT_PATH", research_paths(research_root)["snapshots"])

    # SettlementEngine may construct a shadow portfolio even when a test only
    # exercises research settlement. Keep its SQLite and default snapshot paths
    # isolated too; the production default is under the data Junction.
    import core.shadow_portfolio as csp
    monkeypatch.setattr(csp, "SHADOW_DIR", storage_paths.shadow_root)
    monkeypatch.setattr(csp, "SHADOW_DB_PATH", storage_paths.shadow_db)
    monkeypatch.setattr(
        csp,
        "DEFAULT_SNAPSHOT_PATH",
        research_paths(research_root)["snapshots"],
    )

    # 5. Reset the API service registry so every service resolves the isolated test paths.
    import server.service_registry as service_registry
    monkeypatch.setattr(service_registry, "_profile_mgr", pm.ProfileManager(db_path=test_db))
    monkeypatch.setattr(service_registry, "_shared_services", None)

    # 6. Resolve SQLite paths through Junctions before blocking production data.
    orig_connect = sqlite3.connect
    protected_roots = {
        Path(sc.DEFAULT_DATA_DIR).resolve(),
        Path(sc.DEFAULT_F_PATH).resolve(),
        production_root,
    }

    def guarded_connect(database, *args, **kwargs):
        db_str = str(database or "")
        if db_str.startswith("file:"):
            db_str = db_str[5:].split("?", 1)[0]
        if db_str and db_str != ":memory:":
            from urllib.parse import unquote
            db_str = unquote(db_str)
            resolved = Path(db_str).expanduser().resolve()
            if any(resolved == root or resolved.is_relative_to(root) for root in protected_roots):
                raise RuntimeError(
                    f"FATAL: Test attempted to connect to production data: {database}! "
                    "All tests must use isolated temporary storage."
                )
        return orig_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    yield
