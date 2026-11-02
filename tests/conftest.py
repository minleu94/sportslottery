"""Default suite stays offline; live network checks require an explicit opt-in.
All tests run against isolated temporary databases to protect production war chest data.
"""
import os
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
    test_db = test_storage / "war_chest.sqlite3"

    # 1. Patch core.storage_config
    import core.storage_config as sc
    monkeypatch.setattr(sc, "get_storage_root", lambda: test_storage)
    monkeypatch.setattr(sc, "get_db_path", lambda: test_db)
    monkeypatch.setattr(sc, "get_research_root", lambda: test_storage / "research_pipeline")

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

    # 5. Set server.api singleton profile manager to use test DB
    try:
        import server.api as sa
        sa._profile_mgr = pm.ProfileManager(db_path=test_db)
        sa._shadow_portfolio = None
    except ImportError:
        pass

    # 6. Safety guard on sqlite3.connect to block any connection to live production DB
    orig_connect = sqlite3.connect
    prod_data_markers = ["sportslottery_data", "sports_lottery_data"]

    def guarded_connect(database, *args, **kwargs):
        db_str = str(database or "")
        norm = os.path.abspath(db_str).lower() if db_str else ""
        if "war_chest.sqlite3" in norm:
            for marker in prod_data_markers:
                if marker in norm:
                    raise RuntimeError(
                        f"FATAL: Test attempted to connect to production database: {database}! "
                        "All tests must use isolated test database."
                    )
        return orig_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    yield
