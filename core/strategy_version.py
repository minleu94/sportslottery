#!/usr/bin/env python3
"""Reproducible strategy and source/configuration provenance."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v2.0-research"
EVIDENCE_WEIGHTS_VERSION = "v2.0-configured"
SETTLEMENT_RULES_VERSION = "v1.1-status-aware"
FROZEN_DATE = "2026-10-12"

HASHED_SOURCE_DIRS = ("core", "integrations", "probability", "scripts", "ui", "pages")
HASHED_CONFIG_DIRS = ("config",)
HASHED_ROOT_FILES = ("app.py", "main.py", "pyproject.toml", "requirements-lock.txt")

# This manifest is intentionally broader than a narrow predictor allowlist: all
# runtime, ingestion, validation, settlement, and configuration modules are
# covered. Only presentation/reporting surfaces are omitted. Add new prediction
# dependencies here when introducing code outside these paths.
PREDICTION_CORE_EXCLUDES = {
    "core/research_alerts.py",          # local operational incident reporting
    "core/research_operations.py",     # read-only scheduler observation; no prediction dependencies
    "core/research_health.py",          # reads operational files only; no forecast inputs
    "core/clv_reporting.py",            # report-only price comparisons
    "core/recommendation_replay.py",    # reads sealed snapshots; no new predictions
    "core/research_reporting.py",       # report-only scores/output; no prediction or eligibility changes
    "core/performance_metrics.py",       # reads immutable outcomes; does not qualify predictions
    "core/research_dataset_exporter.py", # export formatting only
}
PREDICTION_SCRIPT_EXCLUDES = {
    "scripts/workspace_backup.py",     # backup/restore tools do not create forecasts
    "scripts/export_research_datasets.py",
    "scripts/generate_weekly_report.py",
    "scripts/manual_live_diagnostic.py",
    "scripts/build_model_acceptance_calibration_audit.py",
    "scripts/validate_parlay_forward.py",
}

GOVERNANCE_RULES = {
    "immutable_strategy": True,
    "no_mid_test_weight_changes": True,
    "min_sample_size_for_tuning": 100,
    "insufficient_sample_threshold": 30,
    "virtual_shadow_stake_ntd": 10.0,
    "real_wallet_frozen": True,
    "pre_game_cutoff_strict": True,
    "parlay_void_odds_one": True,
    "model_probabilities_calibrated": False,
    "unknown_prediction_time_is_point_in_time_verified": False,
}


def _hash_file_set(repo_dir: Path) -> Dict[str, str]:
    files = set()
    for dirname in HASHED_SOURCE_DIRS:
        root = repo_dir / dirname
        if root.exists():
            files.update(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    for dirname in HASHED_CONFIG_DIRS:
        root = repo_dir / dirname
        if root.exists():
            files.update(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".yaml", ".yml"})
    for name in HASHED_ROOT_FILES:
        path = repo_dir / name
        if path.is_file():
            files.add(path)
    return {path.relative_to(repo_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files, key=lambda item: item.relative_to(repo_dir).as_posix())}


def _prediction_manifest(repo_dir: Path) -> Dict[str, str]:
    """Content hashes for code/configuration that can change predictions or eligibility."""
    repo_dir = Path(repo_dir)
    files = set()
    for dirname in ("core", "integrations", "probability"):
        root = repo_dir / dirname
        if root.exists():
            files.update(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    config_root = repo_dir / "config"
    if config_root.exists():
        files.update(path for path in config_root.rglob("*")
                     if path.is_file() and path.suffix.lower() in {".yaml", ".yml"})
    scripts_root = repo_dir / "scripts"
    if scripts_root.exists():
        files.update(path for path in scripts_root.rglob("*.py") if "__pycache__" not in path.parts)
    for name in ("main.py", "pyproject.toml", "requirements-lock.txt"):
        path = repo_dir / name
        if path.is_file():
            files.add(path)
    result = {}
    for path in sorted(files, key=lambda item: item.relative_to(repo_dir).as_posix()):
        relative = path.relative_to(repo_dir).as_posix()
        if relative in PREDICTION_CORE_EXCLUDES or relative in PREDICTION_SCRIPT_EXCLUDES:
            continue
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def get_prediction_manifest_hash(repo_dir: Path) -> str:
    """Hash the auditable prediction dependency manifest, excluding UI/report code."""
    manifest = _prediction_manifest(Path(repo_dir))
    return hash_prediction_manifest(manifest)


def hash_prediction_manifest(manifest: Dict[str, str]) -> str:
    """Return the stable digest for a saved prediction manifest."""
    hasher = hashlib.sha256()
    for relative_path, file_hash in sorted(manifest.items()):
        path_bytes = relative_path.encode("utf-8")
        hasher.update(len(path_bytes).to_bytes(4, "big"))
        hasher.update(path_bytes)
        hasher.update(bytes.fromhex(file_hash))
    return hasher.hexdigest()


def get_core_code_hash(repo_dir: Path) -> str:
    """Hash relevant source and configuration bytes in stable relative-path order."""
    file_hashes = _hash_file_set(Path(repo_dir))
    hasher = hashlib.sha256()
    for relative_path, file_hash in file_hashes.items():
        content = (Path(repo_dir) / relative_path).read_bytes()
        path_bytes = relative_path.encode("utf-8")
        hasher.update(len(path_bytes).to_bytes(4, "big"))
        hasher.update(path_bytes)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


def get_evidence_weights_hash(repo_dir: Path) -> str:
    weights_path = Path(repo_dir) / "config" / "evidence_weights.yaml"
    return hashlib.sha256(weights_path.read_bytes()).hexdigest() if weights_path.exists() else "missing"


def _load_active_models(repo_dir: Path) -> Dict[str, Dict[str, Any]]:
    model_path = Path(repo_dir) / "config" / "models.yaml"
    if not model_path.exists():
        return {}
    try:
        loaded = yaml.safe_load(model_path.read_text(encoding="utf-8")) or {}
        models = loaded.get("models", {}) if isinstance(loaded, dict) else {}
        return {
            str(model_id): {
                "version": str(config.get("version", "unspecified")),
                "adapter": config.get("adapter"),
                "sport": config.get("sport"),
                "source_category": config.get("source_category"),
                "independence_group": config.get("independence_group"),
                "configured_weight": config.get("weight"),
            }
            for model_id, config in sorted(models.items())
            if isinstance(config, dict) and config.get("enabled", True)
        }
    except Exception as exc:
        logger.warning("Unable to read active model configuration: %s", exc)
        return {}


def get_git_status_and_reproducibility(repo_dir: Path) -> Dict[str, Any]:
    repo_dir = Path(repo_dir)
    code_hash = get_core_code_hash(repo_dir)
    git_commit = None
    git_dirty: Optional[bool] = None
    git_available = False
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=creationflags,
        )
        if result.returncode == 0 and result.stdout.strip():
            git_available = True
            git_commit = result.stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=creationflags,
            )
            if status.returncode == 0:
                git_dirty = bool(status.stdout.strip())
    except Exception:
        pass
    # Always bind the displayed version to actual relevant bytes, even when Git
    # reports clean (ignored/untracked source files may still affect execution).
    code_version = f"{git_commit}+content_{code_hash}" if git_commit else f"content_{code_hash}"
    return {"git_commit": git_commit, "git_available": git_available, "git_dirty": git_dirty,
            "working_tree_hash": code_hash, "code_hash": code_hash, "code_version": code_version}


def get_strategy_metadata(repo_dir: Path | None = None) -> Dict[str, Any]:
    repo_dir = Path(repo_dir or Path(__file__).resolve().parents[1])
    repro = get_git_status_and_reproducibility(repo_dir)
    file_hashes = _hash_file_set(repo_dir)
    prediction_manifest = _prediction_manifest(repo_dir)
    config_hashes = {name: digest for name, digest in file_hashes.items()
                     if name.startswith("config/")}
    active_models = _load_active_models(repo_dir)
    return {
        "strategy_version": STRATEGY_VERSION,
        "code_version": repro["code_version"],
        "git_commit": repro["git_commit"],
        "git_available": repro["git_available"],
        "git_dirty": repro["git_dirty"],
        "working_tree_hash": repro["working_tree_hash"],
        "code_hash": repro["code_hash"],
        "content_hash": repro["code_hash"],
        "hashed_file_count": len(file_hashes),
        "hashed_files": sorted(file_hashes),
        "prediction_manifest": prediction_manifest,
        "prediction_manifest_hash": get_prediction_manifest_hash(repo_dir),
        "config_hashes": config_hashes,
        "frozen_date": FROZEN_DATE,
        "current_model_set": active_models,
        "model_versions": {key: value["version"] for key, value in active_models.items()},
        "evidence_weights_version": EVIDENCE_WEIGHTS_VERSION,
        "evidence_weights_hash": get_evidence_weights_hash(repo_dir),
        "settlement_rules_version": SETTLEMENT_RULES_VERSION,
        "governance_rules": GOVERNANCE_RULES,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
