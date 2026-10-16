"""Build an out-of-sample temperature-calibration audit from frozen forecasts.

This historical Football-Data/B365 research artifact is explicitly not a Taiwan
forward acceptance record. Validation-season rows fit the temperature; locked
2526 holdout rows are used only once for evaluation.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from core.model_calibration import fit_chronological_temperature, multiclass_metrics

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts" / "model_validation_review_20261013_luna"
OUTPUT = ROOT / "artifacts" / "model_acceptance_calibration_audit_20261013"
VARIANTS = {
    "raw_dixon_coles": "raw_dixon_coles_probs",
    "fusion_beta_0_65": "fusion_beta_0_65_probs",
    "empirical_training_base": "empirical_training_base_probs",
}


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_league(league_dir: Path, output_dir: Path) -> dict:
    rows = _read(league_dir / "predictions.jsonl")
    rows = [row for row in rows if row.get("outcome_idx") in (0, 1, 2)
            and row.get("split") in {"validation", "holdout"}
            and all(isinstance(row.get(key), list) and len(row[key]) == 3
                    and all(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 for value in row[key])
                    and sum(row[key]) > 0 for key in (*VARIANTS.values(), "market_normalized_hda_probs"))]
    train = sorted((r for r in rows if r["split"] == "validation"), key=lambda r: r["date"])
    holdout = sorted((r for r in rows if r["split"] == "holdout"), key=lambda r: r["date"])
    if not train or not holdout:
        raise ValueError(f"{league_dir.name} lacks the locked chronological split")
    model_reports = {}
    market_vector = [r["market_normalized_hda_probs"] for r in holdout]
    model_reports["market_baseline"] = {"metrics": multiclass_metrics(holdout, market_vector),
                                        "calibration": "not fitted; comparison baseline"}
    for label, key in VARIANTS.items():
        fit = fit_chronological_temperature(train, holdout, probability_key=key)
        raw_vectors = [r[key] for r in holdout]
        model_reports[label] = {
            "fit": {key: value for key, value in fit.items() if key != "evaluation_probabilities"},
            "raw_holdout_metrics": multiclass_metrics(holdout, raw_vectors),
            "calibrated_holdout_metrics": multiclass_metrics(holdout, fit["evaluation_probabilities"]),
            "paired_vs_market": {
                "calibrated_brier_delta": multiclass_metrics(holdout, fit["evaluation_probabilities"])["multiclass_brier"] - multiclass_metrics(holdout, market_vector)["multiclass_brier"],
                "calibrated_logloss_delta": multiclass_metrics(holdout, fit["evaluation_probabilities"])["log_loss"] - multiclass_metrics(holdout, market_vector)["log_loss"],
            },
        }
    summary = {
        "schema": "historical-calibration-audit-v1",
        "scope": "external_historical_research_not_taiwan_forward_acceptance",
        "league": league_dir.name,
        "source_predictions_sha256": _sha256(league_dir / "predictions.jsonl"),
        "source_summary_sha256": _sha256(league_dir / "summary.json"),
        "source_experiment_identity": json.loads((league_dir / "summary.json").read_text(encoding="utf-8"))["protocol"].get("strategy_experiment_identity"),
        "warning": "Source experiment identity describes the frozen historical pipeline only; it does not identify current production code.",
        "split": {"fit_split": "validation", "evaluation_split": "holdout", "training_rows": len(train),
                  "evaluation_rows": len(holdout), "training_max_date": max(r["date"] for r in train),
                  "evaluation_min_date": min(r["date"] for r in holdout), "holdout_used_for_fitting": False},
        "model_results": model_reports,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# Frozen historical calibration audit: {league_dir.name}", "",
             "This is an external Football-Data/B365 historical research audit. It does not grant Taiwan forward model acceptance.", "",
             f"- Training: validation split, {len(train)} matches through {max(r['date'] for r in train)}",
             f"- Evaluation: locked holdout split, {len(holdout)} matches from {min(r['date'] for r in holdout)} onward",
             "- Temperature was fitted only on the earlier validation rows; holdout rows were not used to choose or refit it.",
             "- The source experiment identity is retained as provenance and is not claimed as the current production identity.", "",
             "| Forecast | Temperature | Raw holdout Brier | Calibrated holdout Brier | Raw log loss | Calibrated log loss | Paired Brier Δ vs market | Paired log loss Δ vs market |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in model_reports.items():
        if name == "market_baseline":
            metric = result["metrics"]
            lines.append(f"| {name} | — | {metric['multiclass_brier']:.6f} | — | {metric['log_loss']:.6f} | — | — | — |")
        else:
            raw, cal, fit = result["raw_holdout_metrics"], result["calibrated_holdout_metrics"], result["fit"]
            paired = result["paired_vs_market"]
            lines.append(f"| {name} | {fit['temperature']:.2f} | {raw['multiclass_brier']:.6f} | {cal['multiclass_brier']:.6f} | {raw['log_loss']:.6f} | {cal['log_loss']:.6f} | {paired['calibrated_brier_delta']:+.6f} | {paired['calibrated_logloss_delta']:+.6f} |")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    index = {"schema": "historical-calibration-audit-index-v1", "source_directory": str(SOURCE.relative_to(ROOT)),
             "output_directory": str(OUTPUT.relative_to(ROOT)), "leagues": []}
    for league_dir in sorted(p for p in SOURCE.iterdir() if p.is_dir()):
        result = _write_league(league_dir, OUTPUT / league_dir.name)
        index["leagues"].append({"league": result["league"], "artifact": f"{league_dir.name}/audit.json"})
    (OUTPUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
