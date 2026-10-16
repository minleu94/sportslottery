#!/usr/bin/env python3
"""Run frozen Football-Data historical validation and write auditable outputs."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model_validation import (
    SUPPORTED_LEAGUES,
    SUPPORTED_SEASONS,
    run_validation,
)

DEFAULT_DATA_DIR = PROJECT_ROOT / "artifacts" / "validation_sources_20261012"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "model_validation_20261012"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--league", choices=["all", *SUPPORTED_LEAGUES], default="all")
    parser.add_argument("--warmup-season", choices=SUPPORTED_SEASONS, default="2324")
    parser.add_argument("--validation-season", choices=SUPPORTED_SEASONS, default="2425")
    parser.add_argument("--holdout-season", choices=SUPPORTED_SEASONS, default="2526")
    args = parser.parse_args(argv)
    leagues = tuple(SUPPORTED_LEAGUES) if args.league == "all" else (args.league,)
    for league in leagues:
        run_validation(
            args.data_dir,
            args.output_dir / league.replace(".", "_"),
            league,
            warmup_season=args.warmup_season,
            validation_season=args.validation_season,
            holdout_season=args.holdout_season,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
