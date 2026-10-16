"""Read-only evaluation of saved whole-ticket forecasts into an explicit output file."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.experiment_identity import get_current_experiment_identity
from core.parlay_validation import evaluate_parlay_forward
from core.research_paths import research_paths


def run(source: Path, output: Path) -> dict:
    if source.resolve() == output.resolve():
        raise ValueError("Report output must differ from the immutable source log.")
    raw = source.read_bytes() if source.exists() else b""
    rows, malformed = [], 0
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Record must be an object")
            rows.append(row)
        except (ValueError, UnicodeDecodeError):
            malformed += 1
    identity = get_current_experiment_identity()
    report = evaluate_parlay_forward(rows, identity["experiment_id"])
    report.update(generated_at=datetime.now(timezone.utc).isoformat(), source_file=str(source.resolve()),
                  source_sha256=hashlib.sha256(raw).hexdigest(), malformed_lines=malformed,
                  source_exists=source.exists(), source_record_count=len(rows), experiment_identity=identity)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=research_paths()["parlays"])
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    report = run(options.source, options.output)
    print(json.dumps({"tiers": report["tiers"], "excluded_counts": report["excluded_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
