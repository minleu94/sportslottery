"""Replay and compare immutable recommendation snapshots without rerunning models."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.bet_validation import parse_aware_time
from core.experiment_identity import get_current_experiment_identity, validate_experiment_identity
from core.parlay_validation import _qualify as _qualify_parlay, prediction_hash as _parlay_prediction_hash
from core.research_paths import research_paths
from core.snapshot_logger import compute_prediction_payload_hash


def _identity_valid(row: dict[str, Any]) -> bool:
    identity = row.get("experiment_identity")
    metadata = row.get("strategy_metadata")
    return (validate_experiment_identity(identity) and isinstance(metadata, dict)
            and metadata.get("experiment_identity") == identity
            and row.get("strategy_version") == identity.get("strategy_version")
            and row.get("strategy_config_hashes") == identity.get("config_hashes"))


def _integrity_valid(row: dict[str, Any]) -> bool:
    try:
        return (_identity_valid(row) and isinstance(row.get("prediction_payload_hash"), str)
                and row["prediction_payload_hash"] == compute_prediction_payload_hash(row))
    except (TypeError, ValueError, OverflowError):
        return False


def _finite_probability(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _event_key(row: dict[str, Any]) -> tuple | None:
    start = parse_aware_time(row.get("event_start"))
    event = row.get("canonical_event_id") or row.get("event_id")
    market, side, selection = row.get("market"), row.get("side"), row.get("selection")
    if not event or not start or not market or not side or not selection:
        return None
    try:
        line_value = None if row.get("line") is None else float(row["line"])
        if line_value is not None and not math.isfinite(line_value):
            return None
        line = None if line_value is None else format(line_value, ".12g")
    except (TypeError, ValueError, OverflowError):
        return None
    return (str(event), str(row.get("sport") or ""), str(row.get("league") or ""),
            start.isoformat(), str(market), str(side), str(selection), line)


def replay_recommendation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Recalculate displayed EV from sealed inputs; never invokes a model."""
    integrity = _integrity_valid(snapshot)
    price = None
    try:
        candidate = float(snapshot.get("taiwan_odds"))
        if math.isfinite(candidate) and candidate > 1:
            price = candidate
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        hash_schema = int(snapshot.get("prediction_hash_schema", 1) or 1)
    except (TypeError, ValueError):
        hash_schema = 1
    probability = _finite_probability(snapshot.get("recommendation_probability")) if hash_schema >= 4 else None
    if probability is None and hash_schema >= 3:
        probability = _finite_probability(snapshot.get("consensus_probability"))
    if probability is None and hash_schema < 3:
        probability = _finite_probability(snapshot.get("model_probability"))
    breakeven = 1 / price if price is not None else None
    ev = probability * price - 1 if probability is not None and price is not None else None
    saved_ev = snapshot.get("expected_value") if hash_schema >= 3 else None
    try:
        saved_ev = float(saved_ev) if saved_ev is not None and math.isfinite(float(saved_ev)) else None
    except (TypeError, ValueError, OverflowError):
        saved_ev = None
    evidence = snapshot.get("signal_evidence") if hash_schema >= 3 and isinstance(snapshot.get("signal_evidence"), dict) else {}
    reasons = []
    if not integrity:
        reasons.append("INVALID_OR_TAMPERED_SNAPSHOT")
    if snapshot.get("forward_validation_eligible") is not True:
        reasons.append(snapshot.get("exclusion_reason") or "NOT_FORWARD_VALIDATION_ELIGIBLE")
    if probability is None:
        reasons.append("PROBABILITY_UNAVAILABLE")
    if price is None:
        reasons.append("ODDS_UNAVAILABLE")
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_refs": {"snapshot_id": snapshot.get("snapshot_id"),
                          "observation_window_id": snapshot.get("observation_window_id"),
                          "prediction_payload_hash": snapshot.get("prediction_payload_hash")},
        "integrity_valid": integrity,
        "experiment_id": (snapshot.get("experiment_identity") or {}).get("experiment_id"),
        "strategy_version": snapshot.get("strategy_version"),
        "strategy_config_hashes": snapshot.get("strategy_config_hashes"),
        "current_model_set": (snapshot.get("experiment_identity") or {}).get("current_model_set"),
        "event_key": _event_key(snapshot), "event_id": snapshot.get("event_id"),
        "canonical_event_id": snapshot.get("canonical_event_id"), "market": snapshot.get("market"),
        "side": snapshot.get("side"), "line": snapshot.get("line"),
        "selection": snapshot.get("selection"),
        "snapshot_timestamp": snapshot.get("snapshot_timestamp") or snapshot.get("timestamp"),
        "event_start": snapshot.get("event_start"), "odds": price,
        "probability": probability, "probability_status": snapshot.get("probability_status"),
        "breakeven_probability": breakeven, "replayed_expected_value": ev,
        "sealed_expected_value": saved_ev,
        "expected_value_difference": ev - saved_ev if ev is not None and saved_ev is not None else None,
        "independent_support_count": evidence.get("independent_support_count"),
        "supporting_groups": evidence.get("supporting_groups", []),
        "model_candidate_predictions": snapshot.get("model_candidate_predictions", []),
        "model_candidate_provenances": snapshot.get("model_candidate_provenances", []),
        "excluded_model_ids": snapshot.get("excluded_model_ids", []),
        "forward_validation_eligible": snapshot.get("forward_validation_eligible"),
        "exclusion_reasons": list(dict.fromkeys(reasons)),
        "settlement_status": snapshot.get("settlement_status", "PENDING"),
        "settled_at": snapshot.get("settled_at"), "actual_outcome": snapshot.get("actual_outcome"),
    }


def replay_recommendations(
    snapshots: list[dict[str, Any]], *, experiment_id: str | None = None,
) -> dict[str, Any]:
    """Replay one identity cohort and retain invalid/pending rows as diagnostics."""
    target = experiment_id or get_current_experiment_identity()["experiment_id"]
    rows = []
    invalid_identity = different_identity = 0
    for snapshot in snapshots:
        if not _identity_valid(snapshot):
            invalid_identity += 1
            continue
        if snapshot["experiment_identity"]["experiment_id"] != target:
            different_identity += 1
            continue
        rows.append(replay_recommendation(snapshot))
    rows.sort(key=lambda row: (str(row.get("snapshot_timestamp") or ""), str(row.get("snapshot_id") or "")))
    return {"schema": "sealed-recommendation-replay-v1", "experiment_id": target,
            "snapshot_count": len(rows), "invalid_identity_excluded": invalid_identity,
            "different_experiment_excluded": different_identity, "recommendations": rows}


def _is_settled_known(snapshot: dict[str, Any], as_of: datetime) -> bool:
    try:
        if int(snapshot.get("prediction_hash_schema", 1) or 1) < 3:
            return False
    except (TypeError, ValueError):
        return False
    if (snapshot.get("forward_validation_eligible") is not True
            or snapshot.get("is_settled") is not True
            or snapshot.get("settlement_status") not in {"WON", "LOST"}
            or type(snapshot.get("actual_outcome")) is not bool
            or ((snapshot.get("settlement_status") == "WON") != snapshot.get("actual_outcome"))):
        return False
    start, settled = parse_aware_time(snapshot.get("event_start")), parse_aware_time(snapshot.get("settled_at"))
    predicted = parse_aware_time(snapshot.get("snapshot_timestamp") or snapshot.get("timestamp"))
    source = snapshot.get("result_source")
    if (not isinstance(source, str) or not source.strip()
            or source.strip().upper() in {"MANUAL", "UNKNOWN", "TEST", "FIXTURE"}):
        return False
    try:
        odds = float(snapshot.get("taiwan_odds"))
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(start and settled and predicted and predicted < start <= settled <= as_of
                and math.isfinite(odds) and odds > 1)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "brier": None, "log_loss": None, "classification_accuracy": None,
                "selection_hit_rate": None, "roi_pct": None}
    briers, losses, returns, classification_hits, selection_hits = [], [], [], [], []
    for row in rows:
        p, y, odds = row["probability"], float(row["actual_outcome"]), row["odds"]
        p = max(1e-12, min(1 - 1e-12, p))
        briers.append((p-y)**2)
        losses.append(-(y*math.log(p) + (1-y)*math.log(1-p)))
        classification_hits.append((p >= 0.5) == bool(y))
        selection_hits.append(bool(y))
        returns.append(odds - 1 if y else -1)
    return {"n": n, "brier": sum(briers)/n, "log_loss": sum(losses)/n,
            "classification_accuracy": sum(classification_hits)/n,
            "selection_hit_rate": sum(selection_hits)/n, "roi_pct": 100*sum(returns)/n}


def compare_experiment_versions(
    snapshots: list[dict[str, Any]], *, experiment_ids: list[str] | None = None, as_of: Any = None,
) -> dict[str, Any]:
    """Compare sealed versions on exact common event/market/side/line cohorts."""
    cutoff = parse_aware_time(as_of) if as_of is not None else datetime.now(timezone.utc)
    if cutoff is None or cutoff > datetime.now(timezone.utc):
        raise ValueError("as_of must be timezone-aware and not in the future")
    replays = []
    identity_ids = set()
    audit = {"invalid_or_tampered_payload_excluded": 0, "not_forward_eligible_excluded": 0,
             "invalid_event_key_excluded": 0, "probability_or_odds_unavailable_excluded": 0}
    for snapshot in snapshots:
        if not _integrity_valid(snapshot):
            audit["invalid_or_tampered_payload_excluded"] += 1
            continue
        identity = snapshot["experiment_identity"]["experiment_id"]
        identity_ids.add(identity)
        replay = replay_recommendation(snapshot)
        if replay["forward_validation_eligible"] is not True:
            audit["not_forward_eligible_excluded"] += 1
            continue
        if replay["event_key"] is None:
            audit["invalid_event_key_excluded"] += 1
            continue
        if replay["probability"] is None or replay["odds"] is None:
            audit["probability_or_odds_unavailable_excluded"] += 1
            continue
        replays.append((snapshot, replay))
    selected = sorted(set(experiment_ids) if experiment_ids is not None else identity_ids)
    if len(selected) < 2:
        return {"schema": "matched-experiment-comparison-v1", "status": "INSUFFICIENT_VERSIONS",
                "experiment_ids": selected, "matched_event_count": 0, "settled_matched_count": 0,
                "version_metrics": {}, "pairwise_deltas": [], "audit": audit}
    by_version: dict[str, dict[tuple, tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(dict)
    conflicting_keys: dict[str, set[tuple]] = defaultdict(set)
    duplicates = 0
    for snapshot, replay in replays:
        version = replay["experiment_id"]
        if version not in selected or replay["probability"] is None or replay["odds"] is None:
            continue
        key = replay["event_key"]
        previous = by_version[version].get(key)
        if previous is None:
            by_version[version][key] = (snapshot, replay)
        else:
            duplicates += 1
            if (previous[0].get("actual_outcome") is not None
                    and snapshot.get("actual_outcome") is not None
                    and previous[0].get("actual_outcome") != snapshot.get("actual_outcome")):
                conflicting_keys[version].add(key)
            previous_time = parse_aware_time(previous[0].get("snapshot_timestamp") or previous[0].get("timestamp"))
            this_time = parse_aware_time(snapshot.get("snapshot_timestamp") or snapshot.get("timestamp"))
            if this_time and previous_time and this_time < previous_time:
                by_version[version][key] = (snapshot, replay)
    for version, keys in conflicting_keys.items():
        for key in keys:
            by_version[version].pop(key, None)
    if any(version not in by_version for version in selected):
        common_keys = set()
    else:
        common_keys = set.intersection(*(set(by_version[version]) for version in selected))
    common = []
    invalid_result_source_excluded = 0
    for key in sorted(common_keys, key=str):
        items = {version: by_version[version][key] for version in selected}
        if not all(_is_settled_known(snapshot, cutoff) for snapshot, _ in items.values()):
            invalid_result_source_excluded += sum(
                not isinstance(snapshot.get("result_source"), str)
                or not snapshot.get("result_source", "").strip()
                or snapshot.get("result_source", "").strip().upper() in {"MANUAL", "UNKNOWN", "TEST", "FIXTURE"}
                for snapshot, _ in items.values()
            )
            continue
        outcomes = {snapshot.get("actual_outcome") for snapshot, _ in items.values()}
        if len(outcomes) != 1:
            continue
        outcome = outcomes.pop()
        for version, (snapshot, replay) in items.items():
            common.append((version, {**replay, "actual_outcome": outcome}))
    metric_rows = {version: _metrics([row for v, row in common if v == version]) for version in selected}
    deltas = []
    for i, left in enumerate(selected):
        for right in selected[i+1:]:
            a, b = metric_rows[left], metric_rows[right]
            deltas.append({"left_experiment_id": left, "right_experiment_id": right,
                           "common_sample_size": min(a["n"], b["n"]),
                           "brier_left_minus_right": a["brier"]-b["brier"] if a["brier"] is not None and b["brier"] is not None else None,
                           "log_loss_left_minus_right": a["log_loss"]-b["log_loss"] if a["log_loss"] is not None and b["log_loss"] is not None else None,
                           "classification_accuracy_left_minus_right": a["classification_accuracy"]-b["classification_accuracy"] if a["classification_accuracy"] is not None and b["classification_accuracy"] is not None else None,
                           "selection_hit_rate_left_minus_right": a["selection_hit_rate"]-b["selection_hit_rate"] if a["selection_hit_rate"] is not None and b["selection_hit_rate"] is not None else None,
                           "roi_left_minus_right_pp": a["roi_pct"]-b["roi_pct"] if a["roi_pct"] is not None and b["roi_pct"] is not None else None})
    return {"schema": "matched-experiment-comparison-v1",
            "status": "COMPLETED" if common else "NO_SETTLED_MATCHED_COHORT",
            "experiment_ids": selected, "matched_event_count": len(common_keys),
            "settled_matched_count": len(common)//len(selected) if selected else 0,
            "audit": {**audit, "invalid_result_source_excluded": invalid_result_source_excluded},
            "duplicate_snapshots_removed": duplicates, "version_metrics": metric_rows,
            "pairwise_deltas": deltas,
            "interpretation": "Each identity is evaluated separately on the exact common settled event/market/side/line cohort; no probabilities or outcomes are regenerated."}


def load_current_recommendation_replay(*, root: Path | None = None) -> dict[str, Any]:
    """Convenience API reading only sealed snapshots from the configured research ledger."""
    from core.clv_reporting import read_jsonl
    return replay_recommendations(read_jsonl(research_paths(root)["snapshots"]))


def compare_current_experiment_versions(
    experiment_ids: list[str] | None = None, *, as_of: Any = None, root: Path | None = None,
) -> dict[str, Any]:
    """Compare identities using the configured shared snapshot ledger."""
    from core.clv_reporting import read_jsonl
    return compare_experiment_versions(
        read_jsonl(research_paths(root)["snapshots"]), experiment_ids=experiment_ids, as_of=as_of,
    )


def replay_parlay_recommendation(candidate: dict[str, Any]) -> dict[str, Any]:
    """Replay one frozen whole-ticket estimate and its exact sealed leg evidence."""
    if not isinstance(candidate, dict):
        return {"integrity_valid": False, "forward_validation_eligible": False,
                "exclusion_reasons": ["INVALID_CANDIDATE"]}
    identity = candidate.get("experiment_identity")
    try:
        candidate_hash_valid = (isinstance(candidate.get("prediction_payload_hash"), str)
                                and candidate.get("prediction_payload_hash") == _parlay_prediction_hash(candidate))
    except (TypeError, ValueError, OverflowError):
        candidate_hash_valid = False
    try:
        qualification_reason = _qualify_parlay(candidate)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        qualification_reason = "INVALID_FROZEN_CANDIDATE"
    reasons = []
    if not validate_experiment_identity(identity):
        reasons.append("INVALID_EXPERIMENT_IDENTITY")
    if not candidate_hash_valid:
        reasons.append("TICKET_PAYLOAD_HASH_MISMATCH")
    if candidate.get("forward_validation_eligible") is not True:
        reasons.append(candidate.get("forward_exclusion_reason") or "TICKET_NOT_QUALIFIED")
    if qualification_reason:
        reasons.append(qualification_reason)

    legs = candidate.get("legs") if isinstance(candidate.get("legs"), list) else []
    evidence = candidate.get("validation_legs") if isinstance(candidate.get("validation_legs"), list) else []
    sealed_probabilities = []
    leg_rows = []
    for index, leg in enumerate(legs):
        if not isinstance(leg, dict):
            reasons.append("INVALID_LEG")
            leg = {}
        snap = evidence[index] if index < len(evidence) and isinstance(evidence[index], dict) else {}
        p = snap.get("consensus_probability")
        try:
            p = float(p) if p is not None and float(p) > 0 else 1 / float(leg.get("taiwan_odds"))
            if not math.isfinite(p) or not 0 < p <= 1:
                p = None
        except (AttributeError, TypeError, ValueError, OverflowError):
            p = None
        if p is not None:
            sealed_probabilities.append(p)
        leg_rows.append({
            "event_id": leg.get("event_id") if isinstance(leg, dict) else None,
            "canonical_event_id": leg.get("canonical_event_id") if isinstance(leg, dict) else None,
            "sport": leg.get("sport") if isinstance(leg, dict) else None,
            "league": leg.get("league") if isinstance(leg, dict) else None,
            "market": leg.get("market") if isinstance(leg, dict) else None,
            "selection": leg.get("selection") if isinstance(leg, dict) else None,
            "side": leg.get("side") if isinstance(leg, dict) else None,
            "line": leg.get("line") if isinstance(leg, dict) else None,
            "odds": leg.get("taiwan_odds") if isinstance(leg, dict) else None,
            "snapshot_ref": {"snapshot_id": snap.get("snapshot_id"),
                             "prediction_payload_hash": snap.get("prediction_payload_hash")},
            "sealed_probability": p,
            "sealed_prediction_evidence": snap,
        })
    try:
        odds = float(candidate.get("original_total_odds"))
        joint = float(candidate.get("joint_probability"))
        naive = float(candidate.get("naive_joint_probability"))
        penalty = float(candidate.get("correlation_penalty"))
        calculated_odds = math.prod(float(leg["taiwan_odds"]) for leg in legs)
        calculated_naive = math.prod(sealed_probabilities) if len(sealed_probabilities) == len(legs) else None
        calculated_joint = calculated_naive * (1 - penalty) if calculated_naive is not None else None
        math_consistent = bool(
            all(math.isfinite(value) for value in (odds, joint, naive, penalty, calculated_odds))
            and calculated_naive is not None and calculated_joint is not None
            and math.isclose(odds, calculated_odds, abs_tol=0.011)
            and math.isclose(naive, calculated_naive, abs_tol=0.000002)
            and math.isclose(joint, naive * (1 - penalty), abs_tol=0.000002)
            and math.isclose(joint, calculated_joint, abs_tol=0.000002)
        )
    except (AttributeError, TypeError, ValueError, OverflowError, KeyError):
        odds = joint = naive = penalty = calculated_odds = calculated_naive = calculated_joint = None
        math_consistent = False
    if not math_consistent:
        reasons.append("INCONSISTENT_TICKET_MATH")
    reasons = list(dict.fromkeys(reasons))
    integrity_valid = candidate_hash_valid and validate_experiment_identity(identity)
    return {
        "schema": "sealed-parlay-replay-v1",
        "candidate_id": candidate.get("candidate_id"),
        "parlay_fingerprint": candidate.get("parlay_fingerprint"),
        "target_type": candidate.get("target_type"),
        "experiment_id": identity.get("experiment_id") if isinstance(identity, dict) else None,
        "strategy_version": identity.get("strategy_version") if isinstance(identity, dict) else None,
        "strategy_config_hashes": identity.get("config_hashes") if isinstance(identity, dict) else None,
        "experiment_protocol_settings": identity.get("protocol_settings") if isinstance(identity, dict) else None,
        "current_model_set": identity.get("current_model_set") if isinstance(identity, dict) else None,
        "recorded_at": candidate.get("recorded_at"),
        "multiplier_tier": candidate.get("multiplier_tier"),
        "snapshot_ref": {"candidate_id": candidate.get("candidate_id"),
                         "prediction_payload_hash": candidate.get("prediction_payload_hash"),
                         "recorded_at": candidate.get("recorded_at"),
                         "multiplier_tier": candidate.get("multiplier_tier")},
        "integrity_valid": integrity_valid,
        "forward_validation_eligible": integrity_valid and candidate.get("forward_validation_eligible") is True
            and qualification_reason is None and math_consistent,
        "exclusion_reasons": reasons,
        "probability_status": candidate.get("probability_status"),
        "original_total_odds": odds,
        "recomputed_total_odds_from_legs": calculated_odds,
        "breakeven_probability": 1 / odds if odds is not None and odds > 1 else None,
        "joint_probability": joint,
        "naive_joint_probability": naive,
        "recomputed_naive_joint_probability": calculated_naive,
        "correlation_penalty": penalty,
        "recomputed_joint_probability": calculated_joint,
        "expected_value": joint * odds - 1 if joint is not None and odds is not None else None,
        "naive_expected_value": naive * odds - 1 if naive is not None and odds is not None else None,
        "math_consistent": math_consistent,
        "legs": leg_rows,
        "settled": candidate.get("settled"),
        "settlement_status": candidate.get("settlement_status", "PENDING"),
        "leg_settlement_statuses": candidate.get("leg_settlement_statuses", []),
    }


def replay_parlay_recommendations(
    records: list[dict[str, Any]], *, experiment_id: str | None = None,
) -> dict[str, Any]:
    """Replay archived ticket candidates for one exact experiment identity."""
    target = experiment_id or get_current_experiment_identity()["experiment_id"]
    replayed, audit = [], {"invalid_or_unsealed_record": 0, "different_experiment_excluded": 0,
                          "candidate_count": 0}
    for record in records:
        identity = record.get("experiment_identity") if isinstance(record, dict) else None
        metadata = record.get("strategy_metadata") if isinstance(record, dict) else None
        if (not validate_experiment_identity(identity) or not isinstance(metadata, dict)
                or metadata.get("strategy_version") != identity.get("strategy_version")
                or metadata.get("config_hashes") != identity.get("config_hashes")
                or record.get("strategy_version") != identity.get("strategy_version")):
            audit["invalid_or_unsealed_record"] += 1
            continue
        if identity.get("experiment_id") != target:
            audit["different_experiment_excluded"] += 1
            continue
        candidates = record.get("candidates")
        if not isinstance(candidates, list):
            audit["invalid_or_unsealed_record"] += 1
            continue
        for candidate in candidates:
            audit["candidate_count"] += 1
            if not isinstance(candidate, dict) or candidate.get("experiment_identity") != identity:
                audit["invalid_or_unsealed_record"] += 1
                continue
            replayed.append(replay_parlay_recommendation(candidate))
    replayed.sort(key=lambda row: (str(row.get("snapshot_ref", {}).get("recorded_at") or ""),
                                   str(row.get("candidate_id") or "")))
    return {"schema": "sealed-parlay-recommendations-v1", "experiment_id": target,
            "candidate_count": len(replayed), "audit": audit, "recommendations": replayed}


def load_current_parlay_recommendations(*, root: Path | None = None) -> dict[str, Any]:
    """Load and replay immutable parlay records from the configured shared ledger."""
    from core.clv_reporting import read_jsonl
    paths = research_paths(root)
    return replay_parlay_recommendations(read_jsonl(paths["parlays"]))
