from pathlib import Path
import os
import importlib.metadata as metadata
import tomllib

from packaging.requirements import Requirement

import yaml

from core.strategy_version import (get_core_code_hash, get_git_status_and_reproducibility,
                                   get_prediction_manifest_hash, get_strategy_metadata)


def make_repo(root: Path):
    (root / "core").mkdir(parents=True)
    (root / "integrations" / "models").mkdir(parents=True)
    (root / "probability").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "ui").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "core" / "edge_engine.py").write_text("EDGE = 1\n", encoding="utf-8")
    (root / "integrations" / "models" / "active.py").write_text("MODEL = 1\n", encoding="utf-8")
    (root / "probability" / "calibration.py").write_text("CALIBRATION = 1\n", encoding="utf-8")
    (root / "scripts" / "submit.py").write_text("SUBMIT = 1\n", encoding="utf-8")
    (root / "ui" / "tickets.py").write_text("UI = 1\n", encoding="utf-8")
    (root / "main.py").write_text("MAIN = 1\n", encoding="utf-8")
    (root / "config" / "models.yaml").write_text(
        "models:\n  active_model:\n    enabled: true\n    version: '1.0'\n    adapter: package.Adapter\n    sport: soccer\n    weight: 0.4\n", encoding="utf-8")
    (root / "config" / "evidence_weights.yaml").write_text("source_weights: {}\n", encoding="utf-8")
    (root / "config" / "expert_sources.yaml").write_text("sources: []\n", encoding="utf-8")


def test_hash_covers_active_code_and_model_configuration_not_mtime(tmp_path):
    root = tmp_path / "repo"
    make_repo(root)
    target = root / "core" / "edge_engine.py"
    original_hash = get_core_code_hash(root)
    original_mtime = target.stat().st_mtime_ns

    os.utime(target, ns=(original_mtime + 50_000_000, original_mtime + 50_000_000))
    assert get_core_code_hash(root) == original_hash

    target.write_text("EDGE = 2\n", encoding="utf-8")
    os.utime(target, ns=(original_mtime, original_mtime))
    changed_code_hash = get_core_code_hash(root)
    assert changed_code_hash != original_hash

    models_path = root / "config" / "models.yaml"
    models = yaml.safe_load(models_path.read_text(encoding="utf-8"))
    models["models"]["active_model"]["weight"] = 0.9
    models_path.write_text(yaml.safe_dump(models, sort_keys=True), encoding="utf-8")
    assert get_core_code_hash(root) != changed_code_hash
    metadata = get_strategy_metadata(root)
    assert metadata["current_model_set"]["active_model"]["configured_weight"] == 0.9
    assert len(metadata["content_hash"]) == 64


def test_hash_covers_evidence_and_probability_sources_in_stable_order(tmp_path):
    root = tmp_path / "repo"
    make_repo(root)
    first = get_core_code_hash(root)
    probability = root / "probability" / "calibration.py"
    probability.write_text("CALIBRATION = 2\n", encoding="utf-8")
    second = get_core_code_hash(root)
    assert second != first
    weights = root / "config" / "evidence_weights.yaml"
    weights.write_text("source_weights:\n  expert: 2\n", encoding="utf-8")
    third = get_core_code_hash(root)
    assert third != second

    # Traversal order and mtimes do not affect the digest.
    os.utime(probability, None)
    assert get_core_code_hash(root) == third


def test_hash_covers_application_entrypoints(tmp_path):
    root = tmp_path / "repo"
    make_repo(root)
    original = get_core_code_hash(root)
    for relative_path, replacement in (
        ("scripts/submit.py", "SUBMIT = 2\n"),
        ("ui/tickets.py", "UI = 2\n"),
        ("main.py", "MAIN = 2\n"),
    ):
        target = root / relative_path
        previous = target.read_text(encoding="utf-8")
        target.write_text(replacement, encoding="utf-8")
        assert get_core_code_hash(root) != original
        target.write_text(previous, encoding="utf-8")
        original = get_core_code_hash(root)


def test_prediction_identity_manifest_separates_ui_and_reporting_from_runtime(tmp_path):
    root = tmp_path / "repo"
    make_repo(root)
    app = root / "app.py"
    app.write_text("# layout only\n", encoding="utf-8")
    report = root / "scripts" / "generate_weekly_report.py"
    report.write_text("# report layout\n", encoding="utf-8")
    background_report = root / "core/research_reporting.py"
    background_report.write_text("# background report\n", encoding="utf-8")
    (root / "requirements-lock.txt").write_text("PyYAML==6.0\n", encoding="utf-8")
    before_build = get_core_code_hash(root)
    before_prediction = get_prediction_manifest_hash(root)
    app.write_text("# changed layout\n", encoding="utf-8")
    report.write_text("# changed report\n", encoding="utf-8")
    background_report.write_text("# changed background report\n", encoding="utf-8")
    assert get_core_code_hash(root) != before_build
    assert get_prediction_manifest_hash(root) == before_prediction

    # Parser, eligibility, model, settlement, configuration, and dependency
    # changes all participate in the prediction manifest.
    for relative, replacement in (
        ("integrations/models/active.py", "MODEL = 2\n"),
        ("core/edge_engine.py", "EDGE = 2\n"),
        ("config/models.yaml", "models: {}\n"),
        ("requirements-lock.txt", "PyYAML==6.1\n"),
    ):
        target = root / relative
        original = target.read_text(encoding="utf-8")
        prediction_before = get_prediction_manifest_hash(root)
        target.write_text(replacement, encoding="utf-8")
        assert get_prediction_manifest_hash(root) != prediction_before, relative
        target.write_text(original, encoding="utf-8")


def test_dependency_lock_versions_match_installed_metadata():
    repo_root = Path(__file__).resolve().parents[1]
    lock_path = repo_root / "requirements-lock.txt"
    locked = [Requirement(line.strip()) for line in lock_path.read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert locked
    lock_versions = {requirement.name.lower().replace("_", "-"): str(requirement.specifier).removeprefix("==")
                     for requirement in locked}
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    direct = (project["project"]["dependencies"]
              + project["project"]["optional-dependencies"]["test"]
              + project["build-system"]["requires"])
    for raw in direct:
        requirement = Requirement(raw)
        key = requirement.name.lower().replace("_", "-")
        assert lock_versions.get(key) == str(requirement.specifier).removeprefix("=="), key
    for requirement in locked:
        installed = metadata.version(requirement.name)
        assert installed == str(requirement.specifier).removeprefix("=="), requirement.name


def test_dirty_git_tree_hash_tracks_content_not_only_status_text(tmp_path, monkeypatch):
    import core.strategy_version as strategy

    root = tmp_path / "repo"
    make_repo(root)
    responses = iter([
        type("Result", (), {"returncode": 0, "stdout": "abc123\n"})(),
        type("Result", (), {"returncode": 0, "stdout": " M core/edge_engine.py\n"})(),
        type("Result", (), {"returncode": 0, "stdout": "abc123\n"})(),
        type("Result", (), {"returncode": 0, "stdout": " M core/edge_engine.py\n"})(),
    ])
    monkeypatch.setattr(strategy.subprocess, "run", lambda *args, **kwargs: next(responses))
    first = get_git_status_and_reproducibility(root)
    (root / "core" / "edge_engine.py").write_text("EDGE = different bytes\n", encoding="utf-8")
    second = get_git_status_and_reproducibility(root)
    assert first["git_dirty"] is True and second["git_dirty"] is True
    assert first["working_tree_hash"] != second["working_tree_hash"]


def test_git_clean_code_version_still_binds_content_hash(tmp_path, monkeypatch):
    import core.strategy_version as strategy

    root = tmp_path / "repo"
    make_repo(root)
    responses = iter([
        type("Result", (), {"returncode": 0, "stdout": "abc123\n"})(),
        type("Result", (), {"returncode": 0, "stdout": ""})(),
        type("Result", (), {"returncode": 0, "stdout": "abc123\n"})(),
        type("Result", (), {"returncode": 0, "stdout": ""})(),
    ])
    monkeypatch.setattr(strategy.subprocess, "run", lambda *args, **kwargs: next(responses))
    first = get_git_status_and_reproducibility(root)
    (root / "core" / "edge_engine.py").write_text("EDGE = ignored-or-untracked bytes\n", encoding="utf-8")
    second = get_git_status_and_reproducibility(root)
    assert first["git_dirty"] is False and second["git_dirty"] is False
    assert first["code_version"] != second["code_version"]
    assert second["code_hash"] in second["code_version"]
