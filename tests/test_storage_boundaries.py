import sqlite3
import shutil
import subprocess
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


def test_default_test_storage_never_resolves_into_project_data():
    paths = storage_config.get_storage_path_bundle()
    project_data = (PROJECT_ROOT / "data").resolve()

    assert paths.root.resolve() != project_data
    assert not paths.root.resolve().is_relative_to(project_data)


def test_test_sqlite_guard_rejects_project_data_alias_before_opening():
    target = PROJECT_ROOT / "data" / f"codex-guard-{uuid.uuid4().hex}.sqlite3"

    with pytest.raises(RuntimeError, match="production data"):
        sqlite3.connect(str(target))
    with pytest.raises(RuntimeError, match="production data"):
        sqlite3.connect(f"file:{target.as_posix()}?mode=rwc", uri=True)

    assert not target.exists()


def test_storage_copy_accepts_robocopy_success_codes_and_verifies_contents(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "research").mkdir(parents=True)
    (source / "research" / "snapshot.jsonl").write_text("sealed-row\n", encoding="utf-8")
    target.mkdir()
    def successful_copy(*args, **kwargs):
        shutil.copytree(source, target, dirs_exist_ok=True)
        return subprocess.CompletedProcess(args[0], 3, "copied", "")
    monkeypatch.setattr(storage_config.os, "name", "nt")
    monkeypatch.setattr(storage_config.subprocess, "run", successful_copy)
    ok, message = storage_config._copy_and_verify_storage(source, target)
    assert ok and "SHA-256" in message


@pytest.mark.parametrize("return_code,copy_partial", [(1, True), (8, False)])
def test_storage_copy_rejects_partial_or_failed_robocopy(tmp_path, monkeypatch, return_code, copy_partial):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir(); target.mkdir()
    (source / "one.db").write_bytes(b"one")
    (source / "two.jsonl").write_bytes(b"two")
    def mock_robocopy(*args, **kwargs):
        if copy_partial:
            shutil.copy2(source / "one.db", target / "one.db")
        return subprocess.CompletedProcess(args[0], return_code, "partial", "copy failed")
    monkeypatch.setattr(storage_config.os, "name", "nt")
    monkeypatch.setattr(storage_config.subprocess, "run", mock_robocopy)
    ok, message = storage_config._copy_and_verify_storage(source, target)
    assert not ok
    assert "驗證失敗" in message or "robocopy 失敗" in message
    assert (source / "one.db").read_bytes() == b"one"
    assert (source / "two.jsonl").read_bytes() == b"two"


def test_storage_update_does_not_switch_on_copy_failure(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    (source / "research.sqlite3").write_bytes(b"original")
    target.mkdir()
    monkeypatch.setattr(storage_config, "get_storage_root", lambda: source)
    monkeypatch.setattr(storage_config, "save_storage_config", lambda _: pytest.fail("config switched"))
    monkeypatch.setattr(storage_config, "sync_junction", lambda _: pytest.fail("junction switched"))
    monkeypatch.setattr(storage_config, "_copy_and_verify_storage", lambda *_: (False, "verification failed"))
    ok, message = storage_config.update_storage_location(str(target), migrate=True)
    assert not ok and message == "verification failed"
    assert (source / "research.sqlite3").read_bytes() == b"original"


def test_storage_update_switches_only_after_verified_copy(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir(); target.mkdir()
    (source / "snapshot.jsonl").write_text("row\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(storage_config, "get_storage_root", lambda: source)
    monkeypatch.setattr(storage_config, "_copy_and_verify_storage",
                        lambda *_: (True, "verified"))
    monkeypatch.setattr(storage_config, "save_storage_config", lambda path: calls.append(("config", path)))
    monkeypatch.setattr(storage_config, "sync_scheduled_task_argument",
                        lambda path: (True, "scheduled"))
    monkeypatch.setattr(storage_config, "sync_junction",
                        lambda path: (calls.append(("junction", path)) or (True, "linked")))
    ok, message = storage_config.update_storage_location(str(target), migrate=True)
    assert ok and str(target) in message
    assert calls == [("config", target), ("junction", target)]


def test_junction_creation_failure_restores_original_data_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    local_data = project / "data"
    target = tmp_path / "new-storage"
    local_data.mkdir(parents=True)
    (local_data / "keep.sqlite3").write_bytes(b"keep")
    target.mkdir()
    monkeypatch.setattr(storage_config, "PROJECT_ROOT", project)
    monkeypatch.setattr(storage_config.os, "name", "nt")
    monkeypatch.setattr(storage_config, "_is_windows_junction", lambda _: False)
    monkeypatch.setattr(storage_config.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 1, "", "mklink denied"))
    ok, message = storage_config.sync_junction(target)
    assert not ok and "Junction 失敗" in message
    assert (local_data / "keep.sqlite3").read_bytes() == b"keep"
    assert not list(project.glob("data.storage-backup-*"))
