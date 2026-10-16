"""Auditable whole-ticket evaluation and shared-event exposure.

Probabilities remain heuristic estimates. Bootstrap resamples connected event
and UTC-slate clusters, never treats overlapping candidate tickets as independent.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

from core.bet_validation import assess_leg, parse_aware_time
from core.experiment_identity import validate_experiment_identity

PAYLOAD_FIELDS = ("recorded_at", "multiplier_tier", "experiment_identity", "legs",
                  "validation_legs", "original_total_odds", "joint_probability",
                  "naive_joint_probability", "correlation_penalty", "probability_status",
                  "forward_validation_eligible", "forward_exclusion_reason")


def prediction_hash(candidate: dict) -> str:
    payload = {key: candidate.get(key) for key in PAYLOAD_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def event_identity(leg: dict) -> str:
    canonical = leg.get("canonical_event_id")
    if canonical:
        return str(canonical)
    return json.dumps([leg.get("sport"), leg.get("league"), leg.get("event_id"),
                       leg.get("start_time_utc") or leg.get("event_start")], separators=(",", ":"))


def evaluation_tier(odds: float) -> str | None:
    """Disjoint evaluation bins; generation may share inclusive endpoints."""
    for label, lower, upper in (("10-25x", 10, 25), ("25-75x", 25, 75),
                                ("75-200x", 75, 200), ("200-500x", 200, 500)):
        if lower <= odds < upper or (label == "200-500x" and odds == upper):
            return label
    return None


def _qualify(candidate: dict) -> str | None:
    from core.snapshot_logger import compute_prediction_payload_hash
    identity = candidate.get("experiment_identity")
    if not validate_experiment_identity(identity):
        return "INVALID_EXPERIMENT_IDENTITY"
    observed = parse_aware_time(candidate.get("recorded_at"))
    legs, evidence = candidate.get("legs") or [], candidate.get("validation_legs") or []
    if observed is None or len(legs) < 2 or len(legs) != len(evidence):
        return "MISSING_PRE_EVENT_LEG_SNAPSHOTS"
    if len({event_identity(leg) for leg in legs}) != len(legs):
        return "DUPLICATE_EVENT"
    adopted_probabilities = []
    for leg, snapshot in zip(legs, evidence):
        start = parse_aware_time(snapshot.get("event_start"))
        snap_time = parse_aware_time(snapshot.get("snapshot_timestamp") or snapshot.get("timestamp"))
        if (start is None or snap_time is None or not snap_time <= observed < start
                or snapshot.get("forward_validation_eligible") is not True):
            return "LEG_NOT_ELIGIBLE_PRE_EVENT"
        if snapshot.get("experiment_identity") != identity:
            return "LEG_EXPERIMENT_MISMATCH"
        if ((snapshot.get("strategy_metadata") or {}).get("experiment_identity") != identity or
                snapshot.get("strategy_config_hashes") != identity.get("config_hashes")):
            return "LEG_EXPERIMENT_MISMATCH"
        if snapshot.get("prediction_payload_hash") != compute_prediction_payload_hash(snapshot):
            return "LEG_PAYLOAD_MISMATCH"
        if not assess_leg(leg, observed)["is_ready"]:
            return "LEG_NOT_READY"
        for key in ("event_id", "sport", "league", "market", "selection", "side", "line", "taiwan_odds"):
            if leg.get(key) != snapshot.get(key):
                return "LEG_SNAPSHOT_IDENTITY_MISMATCH"
        if (leg.get("odds_scraped_at") != snapshot.get("odds_timestamp") or
                (leg.get("signals") or []) != (snapshot.get("signals") or [])):
            return "LEG_SOURCE_CHANGED_AFTER_SNAPSHOT"
        leg_p, saved_p = leg.get("consensus_probability"), snapshot.get("consensus_probability")
        if leg_p != saved_p:
            return "LEG_ESTIMATE_CHANGED_AFTER_SNAPSHOT"
        adopted_probabilities.append(float(leg_p) if leg_p is not None and float(leg_p) > 0
                                     else 1 / float(leg["taiwan_odds"]))
    try:
        odds = float(candidate["original_total_odds"])
        if not math.isfinite(odds) or odds <= 1 or not math.isclose(
                odds, math.prod(float(leg["taiwan_odds"]) for leg in legs), abs_tol=0.011):
            return "INVALID_TICKET_ODDS"
        bounds = {"10-25x": (10, 25), "25-75x": (25, 75), "75-200x": (75, 200), "200-500x": (200, 500)}
        limits = bounds.get(candidate.get("multiplier_tier"))
        if limits is None or not limits[0] <= odds <= limits[1]:
            return "TIER_ODDS_MISMATCH"
        p, naive, penalty = (float(candidate[key]) for key in
                             ("joint_probability", "naive_joint_probability", "correlation_penalty"))
        if not all(math.isfinite(value) for value in (p, naive, penalty)) or not (
                0 < p < 1 and 0 < naive < 1 and 0 <= penalty <= 1):
            return "INVALID_JOINT_ESTIMATE"
        if not math.isclose(p, naive * (1 - penalty), abs_tol=0.000002):
            return "INCONSISTENT_HEURISTIC_ESTIMATE"
        if not math.isclose(naive, math.prod(adopted_probabilities), abs_tol=0.000002):
            return "JOINT_ESTIMATE_LEG_MISMATCH"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "INVALID_JOINT_ESTIMATE"
    return None


def freeze_candidate(candidate: dict, item: dict, snapshots: dict, identity: dict,
                     recorded_at: str, tier: str) -> None:
    candidate.update(recorded_at=recorded_at, multiplier_tier=tier,
                     experiment_identity=identity,
                     joint_probability=item.get("joint_probability"),
                     naive_joint_probability=item.get("naive_joint_probability"),
                     correlation_penalty=item.get("correlation_penalty"),
                     probability_status="UNVALIDATED_HEURISTIC_JOINT_ESTIMATE")
    candidate["validation_legs"] = [deepcopy(snapshots.get(
        (leg.get("signal_evidence") or {}).get("snapshot_id"), {})) for leg in candidate["legs"]]
    reason = _qualify(candidate)
    candidate["forward_validation_eligible"] = reason is None
    candidate["forward_exclusion_reason"] = reason
    candidate["prediction_payload_hash"] = prediction_hash(candidate)


def shared_event_exposure(items: list[dict]) -> list[dict]:
    sets = [{event_identity(leg) for leg in item.get("legs", [])} for item in items]
    frequency = Counter(event for events in sets for event in events)
    rows = []
    for i, events in enumerate(sets):
        peers = [j + 1 for j, other in enumerate(sets) if j != i and events & other]
        overlap = max((len(events & other) / len(events | other)
                       for j, other in enumerate(sets) if j != i and events | other), default=0)
        rows.append({"shared_event_count": sum(frequency[event] > 1 for event in events),
                     "overlapping_ticket_numbers": peers, "maximum_event_overlap_ratio": overlap})
    return rows


def _clusters(rows: list[dict]) -> list[list[dict]]:
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    owners = {}
    for i, row in enumerate(rows):
        keys = {"event:" + event_identity(leg) for leg in row["legs"]}
        keys.update("slate:" + parse_aware_time(leg.get("start_time_utc") or
                    leg.get("event_start")).date().isoformat() for leg in row["legs"])
        for key in keys:
            if key in owners:
                parent[find(i)] = find(owners[key])
            owners[key] = i
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)
    return list(groups.values())


def _scores(rows: list[dict], probability_field: str = "joint_probability") -> dict:
    if not rows:
        return {"brier": None, "log_loss": None, "hit_rate": None, "roi_pct": None}
    probs = [max(1e-12, min(1 - 1e-12, row[probability_field])) for row in rows]
    outcomes = [float(row["settlement_status"] == "WON") for row in rows]
    return {"brier": sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / len(rows),
            "log_loss": -sum(y * math.log(p) + (1-y) * math.log1p(-p)
                             for p, y in zip(probs, outcomes)) / len(rows),
            "hit_rate": sum(outcomes) / len(rows),
            "roi_pct": 100 * sum(row["original_total_odds"] * y - 1
                                 for row, y in zip(rows, outcomes)) / len(rows)}


def evaluate_parlay_forward(records: list[dict], experiment_id: str, *, replicates: int = 1000,
                            seed: int = 20261013, as_of=None) -> dict[str, Any]:
    cutoff = parse_aware_time(as_of) if as_of is not None else datetime.now(timezone.utc)
    if cutoff is None:
        raise ValueError("Evaluation cutoff must be timezone aware.")
    excluded = Counter()
    unique, conflicts = {}, set()
    for record in records:
        for row in record.get("candidates", []):
            try:
                reason = _qualify(row)
                if reason is None and (row.get("forward_validation_eligible") is not True or
                                      row.get("prediction_payload_hash") != prediction_hash(row)):
                    reason = "TICKET_PAYLOAD_MISMATCH"
                if reason is None and row["experiment_identity"]["experiment_id"] != experiment_id:
                    reason = "OTHER_EXPERIMENT"
                statuses = [item[0] for item in row.get("leg_settlement_statuses", [])]
                if reason is None and (not row.get("settled") or row.get("settlement_status") not in {"WON", "LOST"}
                                      or len(statuses) != len(row["legs"]) or
                                      any(status not in {"WON", "LOST"} for status in statuses)):
                    reason = "NOT_BINARY_FULL_TICKET_RESULT"
                if reason is None and (row["settlement_status"] == "WON") != all(s == "WON" for s in statuses):
                    reason = "RESULT_CONFLICT"
                if reason is None and row.get("won") is not (row["settlement_status"] == "WON"):
                    reason = "RESULT_CONFLICT"
                settled_time = parse_aware_time(row.get("settled_at"))
                if reason is None and (settled_time is None or settled_time > cutoff or settled_time < max(
                        parse_aware_time(leg.get("start_time_utc")) for leg in row["legs"])):
                    reason = "INVALID_SETTLEMENT_TIME"
                if reason is None:
                    from core.snapshot_logger import compute_prediction_payload_hash
                    results = row.get("leg_result_snapshots") or []
                    if len(results) != len(row["validation_legs"]):
                        reason = "MISSING_RESULT_PROVENANCE"
                    else:
                        for frozen, result, status in zip(row["validation_legs"], results, statuses):
                            result_time = parse_aware_time(result.get("settled_at"))
                            start_time = parse_aware_time(frozen.get("event_start"))
                            if (result.get("snapshot_id") != frozen.get("snapshot_id") or
                                    result.get("prediction_payload_hash") != frozen.get("prediction_payload_hash") or
                                    compute_prediction_payload_hash(result) != result.get("prediction_payload_hash") or
                                    result.get("settlement_status") != status or
                                    result.get("actual_outcome") is not (status == "WON") or
                                    not str(result.get("result_source") or "").strip() or
                                    str(result.get("result_source") or "").strip().upper() in {
                                        "MANUAL", "UNKNOWN", "TEST", "FIXTURE"} or result_time is None or
                                    result_time < start_time or result_time > settled_time):
                                reason = "INVALID_RESULT_PROVENANCE"
                                break
                if reason:
                    excluded[reason] += 1
                    continue
                key = tuple(sorted(event_identity(leg) + json.dumps([
                    leg.get("market"), leg.get("side") or leg.get("selection"),
                    str(Decimal(str(leg["line"])).normalize()) if leg.get("line") is not None else None])
                    for leg in row["legs"]))
                previous = unique.get(key)
                if previous and previous["settlement_status"] != row["settlement_status"]:
                    conflicts.add(key)
                if previous is None or row["recorded_at"] < previous["recorded_at"]:
                    unique[key] = row
            except (TypeError, ValueError, KeyError, OverflowError):
                excluded["INVALID_RECORD"] += 1
    excluded["CONFLICTING_TICKETS"] += len(conflicts)
    rows = [row for key, row in unique.items() if key not in conflicts]
    output = {"experiment_id": experiment_id, "probability_status": "UNVALIDATED_HEURISTIC_JOINT_ESTIMATE",
              "sample_unit": "unique binary settled ticket; fixed unit stake; void/push excluded",
              "evaluation_tier_bounds": "[10,25), [25,75), [75,200), [200,500]; original generation tier retained",
              "excluded_counts": dict(excluded), "tiers": {}}
    for tier in ("10-25x", "25-75x", "75-200x", "200-500x"):
        scoped = [row for row in rows if evaluation_tier(float(row["original_total_odds"])) == tier]
        clusters = _clusters(scoped)
        metrics = _scores(scoped)
        naive = _scores(scoped, "naive_joint_probability")
        bins = []
        for lower, upper in ((0, .01), (.01, .02), (.02, .05), (.05, .1), (.1, 1)):
            selected = [row for row in scoped if lower <= row["joint_probability"] < upper]
            if selected:
                bins.append({"lower": lower, "upper": upper, "n": len(selected),
                             "mean_estimated_probability": sum(row["joint_probability"] for row in selected)/len(selected),
                             "observed_hit_rate": _scores(selected)["hit_rate"]})
        intervals = None
        if len(clusters) >= 5 and replicates >= 100:
            rng, samples = random.Random(seed), {name: [] for name in metrics}
            samples["discounted_minus_naive_brier"] = []
            for _ in range(replicates):
                picked = [row for _ in clusters for row in rng.choice(clusters)]
                values, raw = _scores(picked), _scores(picked, "naive_joint_probability")
                for name in metrics:
                    samples[name].append(values[name])
                samples["discounted_minus_naive_brier"].append(values["brier"] - raw["brier"])
            intervals = {}
            for name, values in samples.items():
                values.sort()
                intervals[name] = [values[int(.025 * (len(values)-1))], values[int(.975 * (len(values)-1))]]
        output["tiers"][tier] = {**metrics, "n": len(scoped), "event_slate_cluster_count": len(clusters),
                                  "mean_estimated_probability": sum(row["joint_probability"] for row in scoped)/len(scoped) if scoped else None,
                                  "naive_brier": naive["brier"], "calibration_bins": bins,
                                  "cluster_bootstrap_ci95": intervals,
                                  "bootstrap_status": "COMPLETED" if intervals else "INSUFFICIENT_CLUSTERS",
                                  "bootstrap_replicates": replicates if intervals else 0, "bootstrap_seed": seed,
                                  "cluster_unit": "connected shared events and UTC event-date slates",
                                  "is_insufficient_sample": len(scoped) < 30 or len(clusters) < 5}
    return output
