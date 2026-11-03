import sqlite3
import uuid

import pytest

from core.research_paths import PROJECT_ROOT, research_paths
from core.persistence import append_jsonl, read_jsonl
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import PredictionSnapshotLogger
import core.storage_config as storage_config


def test_storage_path_bundle_is_canonical_and_side_effect_free(tmp_path):
    target = tmp_path / "uncreated-storage"
    paths = storage_config.resolve_storage_path_bundle(target)

    assert paths.root == target.resolve()
    assert paths.wallet_db == paths.root / "war_chest.sqlite3"
    assert paths.research_root == paths.root / "research_pipeline"
    assert paths.shadow_db == paths.shadow_root / "shadow_portfolio.sqlite"
    assert not target.exists()


def test_storage_bundle_resolves_the_project_data_alias():
    data_alias = PROJECT_ROOT / "data"
    paths = storage_config.resolve_storage_path_bundle(data_alias)

    assert paths.root == data_alias.resolve()
    assert paths.wallet_db.parent == data_alias.resolve()


def test_default_writers_use_the_isolated_process_bundle():
    paths = storage_config.get_storage_path_bundle()
    research = research_paths()

    assert PredictionSnapshotLogger().log_path == research["snapshots"]
    assert ShadowPortfolioManager().db_path == paths.shadow_db
    assert ShadowPortfolioManager().snapshot_path == research["snapshots"]
    assert research["root"] == paths.research_root

    append_jsonl(research["odds"], {"event_id": "test-event", "odds": 1.91})
    assert read_jsonl(research["odds"]) == [{"event_id": "test-event", "odds": 1.91}]


def test_test_sqlite_guard_rejects_project_data_alias_before_opening():
    target = PROJECT_ROOT / "data" / f"codex-guard-{uuid.uuid4().hex}.sqlite3"

    with pytest.raises(RuntimeError, match="production data"):
        sqlite3.connect(str(target))
    with pytest.raises(RuntimeError, match="production data"):
        sqlite3.connect(f"file:{target.as_posix()}?mode=rwc", uri=True)

    assert not target.exists()
