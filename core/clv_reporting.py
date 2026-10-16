"""Read-only CLV reporting from sealed recommendations and observed quotes.

The report calls its price input the last pre-start observation, never an
authoritative market close; a 15-minute polling cadence cannot establish the
actual final price accepted by an operator.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.bet_validation import parse_aware_time
from core.experiment_identity import get_current_experiment_identity, validate_experiment_identity
from core.odds_watcher import select_last_prestart_observation
from core.research_paths import research_paths
from core.snapshot_logger import compute_prediction_payload_hash

CLV_BOOTSTRAP_REPLICATES = 1000
CLV_BOOTSTRAP_SEED = 20261014
CLV_MIN_EVENT_CLUSTERS = 30


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read valid JSON object rows from an append-only JSONL artifact."""
    rows = []
    if not Path(path).exists():
        return rows
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _line_key(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
        return format(number, ".12g") if math.isfinite(number) else "INVALID"
    except (TypeError, ValueError, OverflowError):
        return "INVALID"


def _valid_snapshot(snapshot: dict[str, Any]) -> bool:
    identity = snapshot.get("experiment_identity")
    metadata = snapshot.get("strategy_metadata")
    try:
        return (validate_experiment_identity(identity)
                and int(snapshot.get("prediction_hash_schema", 1) or 1) >= 3
                and isinstance(metadata, dict) and metadata.get("experiment_identity") == identity
                and snapshot.get("strategy_version") == identity.get("strategy_version")
                and snapshot.get("strategy_config_hashes") == identity.get("config_hashes")
                and isinstance(snapshot.get("prediction_payload_hash"), str)
                and snapshot.get("prediction_payload_hash") == compute_prediction_payload_hash(snapshot))
    except (TypeError, ValueError, OverflowError):
        return False


def build_clv_report(
    snapshots: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    experiment_id: str | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    """Report per-prediction last-prestart movement for one experiment identity."""
    current_id = experiment_id or get_current_experiment_identity()["experiment_id"]
    cutoff = parse_aware_time(as_of) if as_of is not None else datetime.now(timezone.utc)
    if cutoff is None or cutoff > datetime.now(timezone.utc):
        raise ValueError("as_of must be timezone-aware and not in the future")
    output = []
    audit = {"input_snapshots": len(snapshots), "invalid_identity_or_payload": 0,
             "different_experiment_excluded": 0, "not_forward_eligible": 0,
             "non_pre_event_or_after_asof_prediction": 0}
    for snapshot in snapshots:
        if not _valid_snapshot(snapshot):
            audit["invalid_identity_or_payload"] += 1
            continue
        if snapshot["experiment_identity"]["experiment_id"] != current_id:
            audit["different_experiment_excluded"] += 1
            continue
        if snapshot.get("forward_validation_eligible") is not True:
            audit["not_forward_eligible"] += 1
            continue
        start = parse_aware_time(snapshot.get("event_start"))
        event_time = snapshot.get("snapshot_timestamp") or snapshot.get("timestamp")
        predicted_at = parse_aware_time(event_time)
        if start is None or predicted_at is None or predicted_at >= start or predicted_at > cutoff:
            audit["non_pre_event_or_after_asof_prediction"] += 1
            continue
        observation = select_last_prestart_observation(
            observations,
            event_id=str(snapshot.get("event_id") or ""),
            canonical_event_id=snapshot.get("canonical_event_id"), sport=str(snapshot.get("sport") or ""),
            league=str(snapshot.get("league") or ""), market=str(snapshot.get("market") or ""),
            side=str(snapshot.get("side") or ""), selection=str(snapshot.get("selection") or ""),
            line=snapshot.get("line"), event_start=snapshot.get("event_start"),
            as_of=cutoff, not_before=predicted_at,
        )
        if start > cutoff:
            status = "PENDING_EVENT"
        elif observation is None:
            status = "NO_PRESTART_QUOTE"
        else:
            status = "LAST_PRESTART_OBSERVED"
        pred_odds = snapshot.get("taiwan_odds")
        try:
            pred_odds = float(pred_odds)
            if not math.isfinite(pred_odds) or pred_odds <= 1:
                pred_odds = None
        except (TypeError, ValueError, OverflowError):
            pred_odds = None
        close_odds = observation.get("odds") if observation else None
        ratio = ((pred_odds / close_odds) - 1) if pred_odds and close_odds else None
        prob_delta = ((1 / close_odds) - (1 / pred_odds)) * 100 if pred_odds and close_odds else None
        observed_at = parse_aware_time(observation.get("observed_at")) if observation else None
        minutes_before = ((start - observed_at).total_seconds() / 60) if observed_at else None
        output.append({
            "snapshot_id": snapshot.get("snapshot_id"),
            "snapshot_ref": {"snapshot_id": snapshot.get("snapshot_id"),
                             "observation_window_id": snapshot.get("observation_window_id"),
                             "prediction_payload_hash": snapshot.get("prediction_payload_hash")},
            "experiment_id": current_id, "strategy_version": snapshot.get("strategy_version"),
            "strategy_config_hashes": snapshot.get("strategy_config_hashes"),
            "event_id": snapshot.get("event_id"), "canonical_event_id": snapshot.get("canonical_event_id"),
            "market": snapshot.get("market"), "side": snapshot.get("side"),
            "selection": snapshot.get("selection"), "line": snapshot.get("line"),
            "event_start": start.isoformat(), "prediction_timestamp": predicted_at.isoformat(),
            "prediction_odds": pred_odds, "status": status,
            "last_prestart_observation": observation,
            "minutes_before_start": round(minutes_before, 2) if minutes_before is not None else None,
            "within_15_minutes_of_start": bool(minutes_before is not None and 0 <= minutes_before <= 15),
            "odds_clv_ratio": round(ratio, 6) if ratio is not None and status == "LAST_PRESTART_OBSERVED" else None,
            "implied_probability_movement_pp": round(prob_delta, 4) if prob_delta is not None and status == "LAST_PRESTART_OBSERVED" else None,
            "price_label": "last pre-start observed price; not verified official closing price",
        })
    output.sort(key=lambda row: (row["prediction_timestamp"], str(row["snapshot_id"] or "")))
    # The reporting unit is the first eligible forecast for each exact option
    # inside an event. Keep all observation rows above for audit, but prevent
    # repeated polling from turning one recommendation into repeated samples.
    def event_key(row: dict[str, Any]) -> str:
        return json.dumps((row.get("canonical_event_id") or row.get("event_id"),
                           row.get("event_start")), ensure_ascii=False,
                          separators=(",", ":"), sort_keys=True)

    def option_key(row: dict[str, Any]) -> str:
        return json.dumps((event_key(row), row.get("market"), row.get("side"), row.get("selection"),
                           _line_key(row.get("line"))), ensure_ascii=False,
                          separators=(",", ":"), sort_keys=True)

    first_by_option: dict[str, dict[str, Any]] = {}
    for row in output:
        first_by_option.setdefault(option_key(row), row)
    for row in output:
        row["is_first_forecast_for_option"] = first_by_option.get(option_key(row)) is row
    available = [row for row in output if row["status"] == "LAST_PRESTART_OBSERVED"
                 and row["odds_clv_ratio"] is not None]
    recent = [row for row in available if row["within_15_minutes_of_start"]]
    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        first_rows = [row for row in rows if row.get("is_first_forecast_for_option")]
        clusters: dict[str, list[dict[str, Any]]] = {}
        for row in first_rows:
            clusters.setdefault(event_key(row), []).append(row)
        points = [row["odds_clv_ratio"] for row in first_rows]
        interval = _event_cluster_interval(clusters, "odds_clv_ratio")
        return {"observation_count": n,
                "unique_option_count": len({option_key(row) for row in rows}),
                "unique_event_count": len({event_key(row) for row in rows}),
                "first_forecast_option_count": len(first_rows),
                "sample_unit": "first eligible forecast per event/market/side/selection/line",
                "sample_size": len(first_rows),
                "mean_odds_clv_ratio": sum(points) / len(points) if points else None,
                "raw_observation_mean_odds_clv_ratio": sum(r["odds_clv_ratio"] for r in rows) / n if n else None,
                "first_forecast_mean_odds_clv_ratio": sum(points) / len(points) if points else None,
                "first_forecast_mean_implied_probability_movement_pp": (
                    sum(r["implied_probability_movement_pp"] for r in first_rows
                        if r["implied_probability_movement_pp"] is not None)
                    / sum(r["implied_probability_movement_pp"] is not None for r in first_rows)
                    if any(r["implied_probability_movement_pp"] is not None for r in first_rows) else None),
                "event_cluster_bootstrap_95_ci_mean_odds_clv_ratio": interval,
                "mean_implied_probability_movement_pp": sum(r["implied_probability_movement_pp"] for r in rows) / n if n else None,
                "prediction_odds_above_last_observed_count": sum(r["odds_clv_ratio"] > 0 for r in rows),
                "prediction_odds_equal_last_observed_count": sum(r["odds_clv_ratio"] == 0 for r in rows),
                "prediction_odds_below_last_observed_count": sum(r["odds_clv_ratio"] < 0 for r in rows)}
    return {"schema": "last-prestart-odds-clv-v2", "experiment_id": current_id,
            "as_of": cutoff.isoformat(),
            "interpretation": "Last eligible pre-start observation only; periodic polling does not identify an authoritative final accepted price.",
            "audit": audit, "status_counts": {status: sum(row["status"] == status for row in output)
                                                for status in ("PENDING_EVENT", "NO_PRESTART_QUOTE", "LAST_PRESTART_OBSERVED")},
            "all_last_prestart_observations": aggregate(available),
            "observations_within_15_minutes": aggregate(recent),
            "predictions": output}


def _event_cluster_interval(clusters: dict[str, list[dict[str, Any]]], field: str) -> dict[str, Any]:
    """Cluster bootstrap over events; repeated options stay within their event."""
    keys = sorted(clusters)
    if len(keys) < CLV_MIN_EVENT_CLUSTERS:
        return {"status": "INSUFFICIENT_EVENT_CLUSTERS", "minimum_event_clusters": CLV_MIN_EVENT_CLUSTERS,
                "event_cluster_count": len(keys), "ci_95_low": None, "ci_95_high": None}
    rng = random.Random(CLV_BOOTSTRAP_SEED)
    draws = []
    for _ in range(CLV_BOOTSTRAP_REPLICATES):
        sampled = [keys[rng.randrange(len(keys))] for _ in keys]
        values = [row[field] for key in sampled for row in clusters[key]
                  if isinstance(row.get(field), (int, float)) and math.isfinite(row[field])]
        if values:
            draws.append(sum(values) / len(values))
    draws.sort()
    return {"status": "ESTIMATED_EVENT_CLUSTER_BOOTSTRAP", "minimum_event_clusters": CLV_MIN_EVENT_CLUSTERS,
            "event_cluster_count": len(keys), "replicates": len(draws), "seed": CLV_BOOTSTRAP_SEED,
            "ci_95_low": draws[int(0.025 * (len(draws) - 1))] if draws else None,
            "ci_95_high": draws[int(0.975 * (len(draws) - 1))] if draws else None}


def load_current_clv_report(*, as_of: Any = None, root: Path | None = None) -> dict[str, Any]:
    """Convenience API over the shared research prediction and odds ledgers."""
    paths = research_paths(root)
    return build_clv_report(read_jsonl(paths["snapshots"]), read_jsonl(paths["odds"]), as_of=as_of)
