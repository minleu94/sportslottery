#!/usr/bin/env python3
"""Register a future model evaluation or score its frozen completion manifest.

Registration pins the known training/source identity, model artifact hash and
protocol; the future evaluation data hash is computed only after that window
ends. `evaluate` rejects unfinished windows, mutable/unfrozen holdouts,
incorrect identities, non-point-in-time rows and overwritten reports. A
completed report is eligible for independent review, never runtime acceptance.

Frozen manifest contract (JSON):
  schema=prospective-model-evaluation-manifest-v1, evaluation_id,
  training_source_identity_sha256, model_artifact_sha256, frozen=true,
  holdout_frozen=true, finalized_at_utc, source_hashes=[{source_url,
  retrieved_at_utc,sha256}], rows=[{event_id,source_as_of,prediction_timestamp,
  event_start,settled_at,result_source_sha256,model_artifact_sha256,
  prediction_source_sha256,training_source_identity_sha256,
  model_probabilities:[H,D,A],outcome,
  market_probabilities?:[H,D,A]}], manifest_sha256.
The manifest hash is SHA-256 over canonical sorted compact JSON with the
manifest_sha256 property omitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model_validation import finalize_preregistered_evaluation, preregister_model_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register", help="immutably register a future evaluation")
    register.add_argument("--path", type=Path, required=True)
    register.add_argument("--evaluation-id", required=True)
    register.add_argument("--league", required=True)
    register.add_argument("--training-source-sha256", required=True)
    register.add_argument("--model-artifact-sha256", required=True)
    register.add_argument("--protocol-json", type=Path, required=True)
    register.add_argument("--start", required=True, help="Evaluation window first UTC date, YYYY-MM-DD")
    register.add_argument("--end", required=True, help="Evaluation window last UTC date, YYYY-MM-DD")
    evaluate = sub.add_parser("evaluate", help="score a frozen manifest after its registered window ends")
    evaluate.add_argument("--registration", type=Path, required=True)
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "register":
        protocol = json.loads(args.protocol_json.read_text(encoding="utf-8"))
        record = preregister_model_evaluation(
            args.path, evaluation_id=args.evaluation_id, league=args.league,
            training_source_identity_sha256=args.training_source_sha256,
            model_artifact_sha256=args.model_artifact_sha256, protocol=protocol,
            evaluation_start=args.start, evaluation_end=args.end,
        )
        print(json.dumps({"evaluation_id": record["evaluation_id"],
                          "registration_sha256": record["preregistration_sha256"],
                          "path": str(args.path)}, ensure_ascii=False))
        return 0
    report = finalize_preregistered_evaluation(args.registration, args.manifest, args.output)
    print(json.dumps({"evaluation_id": report["evaluation_id"], "status": report["status"],
                      "prospective_review_status": report["prospective_review_status"],
                      "sample_size_unique_events": report["sample_size_unique_events"],
                      "evaluation_manifest_sha256": report["evaluation_manifest_sha256"],
                      "path": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
