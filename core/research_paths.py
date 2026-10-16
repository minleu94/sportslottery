"""One configured research ledger shared by the UI, gate and background runner.

Historical v1 logs stay untouched in data/historical. Newly sealed forecasts use
the configured ledger so unattended collection is immediately visible in the UI.
Reading these paths never creates folders or modifies wallet/model state.
"""
from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/research_pipeline.yaml"
PROTECTED_DIRS = ("cache", "historical", "wallet", "models", "model_state", "snapshots", "source_health")


def resolve_research_data_root(data_root=None, config_path=None) -> Path:
    config = Path(config_path or DEFAULT_CONFIG)
    if not config.is_absolute():
        config = PROJECT_ROOT / config
    if data_root is None:
        payload = yaml.safe_load(config.read_text(encoding="utf-8")) if config.exists() else {}
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Research configuration must be a mapping.")
        data_root = (payload or {}).get("data_root", "data/research_pipeline")
    raw_root = Path(data_root)
    root = raw_root if raw_root.is_absolute() else (PROJECT_ROOT / raw_root)
    resolved_root = root.resolve()
    production = (PROJECT_ROOT / "data").resolve()
    resolved_project = PROJECT_ROOT.resolve()
    if resolved_root == production or resolved_root == resolved_project or resolved_project.is_relative_to(resolved_root):
        raise ValueError("Research root cannot contain production data or the project checkout.")
    for name in PROTECTED_DIRS:
        protected = (production / name).resolve()
        if resolved_root == protected or resolved_root.is_relative_to(protected) or protected.is_relative_to(resolved_root):
            raise ValueError(f"Research root overlaps protected data: {protected}")
    return root


def research_paths(data_root=None, config_path=None) -> dict[str, Path]:
    root = resolve_research_data_root(data_root, config_path)
    return {"root": root,
            "snapshots": root / "historical/prediction_snapshots.jsonl",
            "parlays": root / "historical/parlay_snapshots.jsonl",
            "odds": root / "historical/odds_history.jsonl",
            "source_health": root / "source_health/playsport.jsonl",
            "reports": root / "reports"}
