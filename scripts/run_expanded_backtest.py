#!/usr/bin/env python3
"""Backward-compatible name for the audited, cutoff-aware model validator.

The previous backtest silently skipped fit/prediction errors and used decay
weights without a prediction-date base. All work now delegates to the strict
frozen-season validation engine.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model_validation import run_validation


def run_expanded_backtest(target_test_count: int | None = None,
                          source_dir: Path | None = None,
                          output_dir: Path | None = None,
                          league: str = "eng.1"):
    # target_test_count is accepted only to keep old imports from breaking; the
    # locked season split, not an arbitrary tail count, defines evaluation now.
    return run_validation(
        source_dir or PROJECT_ROOT / "artifacts" / "validation_sources_20261012",
        output_dir or PROJECT_ROOT / "artifacts" / "model_validation_20261012" / league.replace(".", "_"),
        league,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "artifacts" / "validation_sources_20261012")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "artifacts" / "model_validation_20261012" / "eng_1")
    parser.add_argument("--league", choices=("eng.1", "esp.1"), default="eng.1")
    args = parser.parse_args(argv)
    run_validation(args.data_dir, args.output_dir, args.league)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
