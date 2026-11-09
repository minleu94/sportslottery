"""Build resumable side indexes for bounded research settlement and reports."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research_paths import research_paths
from core.research_pipeline import ResearchPipeline
from core.research_sqlite import build_research_indexes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="run without an interactive confirmation")
    parser.add_argument("--batch-size", type=int, default=250, help="rows held in memory per backfill batch")
    parser.add_argument("--data-root", help="override the configured research data root")
    parser.add_argument("--config", default="config/research_pipeline.yaml", help="pipeline YAML path")
    args = parser.parse_args()

    pipeline = ResearchPipeline(config_path=args.config, data_root=args.data_root)
    paths = research_paths(pipeline.data_root, pipeline.config_path)
    database = paths["database"]
    if not database.exists():
        print(f"Research database not found: {database}")
        print("Migrate the JSONL ledgers to SQLite first with scripts/migrate_research_to_sqlite.py.")
        return 2
    size_gib = database.stat().st_size / (1024 ** 3)
    print(f"Research database: {database} ({size_gib:.2f} GiB)")
    print("This adds small indexed metadata tables; prediction rows and JSONL archives are preserved.")
    print("The first backfill reads each existing prediction/parlay row once. Later 15-minute runs use indexed batches.")
    if not args.yes:
        answer = input("Close the app and pause any scheduled pipeline before continuing? [y/N] ").strip().lower()
        if answer != "y":
            print("Index build cancelled.")
            return 1

    def report_progress(kind: str, rowid: int) -> None:
        if rowid % 5000 < max(1, args.batch_size):
            print(f"  {kind}: scanned through row {rowid:,}")

    try:
        with pipeline._Lock(paths["root"] / "locks" / "pipeline.lock"):
            result = build_research_indexes(database, batch_size=args.batch_size, progress=report_progress)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Index build paused: {type(exc).__name__}: {exc}")
        print("The persisted row cursors allow a later invocation to resume without rebuilding completed batches.")
        return 2
    print("Index build complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("Restart the app or allow the next cadence to use the indexed settlement queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
