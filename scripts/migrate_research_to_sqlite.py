"""Migrate prediction and parlay JSONL ledgers to a normalized SQLite database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research_paths import research_paths
from core.research_sqlite import migrate_jsonl_ledgers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="run without an interactive confirmation")
    args = parser.parse_args()

    paths = research_paths()
    directory = paths["snapshots"].parent
    destination = paths["database"]
    sources = [paths["snapshots"], paths["parlays"]]
    print("SQLite migration source ledgers:")
    for source in sources:
        size = source.stat().st_size if source.exists() else 0
        print(f"  {source}: {size / (1024**3):.2f} GiB")
    print(f"SQLite destination: {destination}")
    print("Original JSONL files will remain untouched as backups.")
    runs_dir = paths["root"] / "runs"
    recent_runs = sorted(runs_dir.glob("*/run.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if recent_runs:
        try:
            latest = json.loads(recent_runs[0].read_text(encoding="utf-8"))
            if latest.get("status") == "RUNNING":
                print(
                    f"Migration paused: background run {latest.get('run_id')} is still running. "
                    "Wait for it to finish, then rerun this command."
                )
                return 2
        except (OSError, ValueError):
            pass
    if not args.yes:
        answer = input("Stop the app before migration, then continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Migration cancelled.")
            return 1

    result = migrate_jsonl_ledgers(directory, destination)
    print(f"Migration complete: {result}")
    print("Restart the app; research reads and writes will then use SQLite automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
