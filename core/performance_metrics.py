#!/usr/bin/env python3
"""Multi-Bucket Performance Analytics Engine for Shadow Evaluation.

Computes forward performance metrics across:
1. Source Types (Crowd, Verified Experts, Probability Models)
2. Agreement Buckets (HIGH, MED, LOW, INSUFFICIENT)
3. Model-Market Delta Buckets (< -5pp, -5~0, 0~+3, +3~+5, +5~+10, > +10pp)
4. Expert Consensus Buckets (by count: 0, 1, 2-3, >=4; by ratio: <60%, 60-75%, >75%)
5. Crowd Consensus Buckets (50-60%, 60-70%, 70-80%, 80%+)
6. Calibration Bins (50-55%, 55-60%, 60-65%, 65-70%, 70%+)
7. Parlay Tier Metrics (10-25x, 25-75x, 75-200x, 200-500x)

Strictly enforces Small Sample Protection (N < 30 tagged as INSUFFICIENT_SAMPLE).
"""

from __future__ import annotations

import math
import json
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.strategy_version import GOVERNANCE_RULES, STRATEGY_VERSION, get_strategy_metadata
from core.experiment_identity import get_current_experiment_identity, validate_experiment_identity

INSUFFICIENT_THRESHOLD = GOVERNANCE_RULES["insufficient_sample_threshold"]  # 30


def _is_forward_binary(snapshot: Dict[str, Any], target_experiment_id: Optional[str] = None) -> bool:
    """Legacy, excluded and unresolved observations cannot certify forward results."""
    if (snapshot.get("forward_validation_eligible") is not True
            or snapshot.get("is_settled") is not True
            or snapshot.get("settlement_status") not in {"WON", "LOST"}
            or type(snapshot.get("actual_outcome")) is not bool
            or not isinstance(snapshot.get("strategy_version"), str)):
        return False
    identity = snapshot.get("experiment_identity")
    if not validate_experiment_identity(identity):
        return False
    if identity.get("strategy_version") != snapshot.get("strategy_version"):
        return False
    strategy_metadata = snapshot.get("strategy_metadata")
    if not isinstance(strategy_metadata, dict) or strategy_metadata.get("experiment_identity") != identity:
        return False
    if snapshot.get("strategy_config_hashes") != identity.get("config_hashes"):
        return False
    if target_experiment_id is None:
        target_experiment_id = get_current_experiment_identity()["experiment_id"]
    if identity.get("experiment_id") != target_experiment_id:
        return False
    if (snapshot["settlement_status"] == "WON") != snapshot["actual_outcome"]:
        return False
    from core.bet_validation import parse_aware_time
    start = parse_aware_time(snapshot.get("event_start"))
    settled = parse_aware_time(snapshot.get("settled_at"))
    source = snapshot.get("result_source")
    if (start is None or settled is None or not start <= settled <= datetime.now(timezone.utc)
            or not isinstance(source, str) or not source.strip()
            or source.strip().upper() in {"MANUAL", "UNKNOWN", "TEST", "FIXTURE"}):
        return False
    try:
        odds = float(snapshot.get("taiwan_odds"))
        if not math.isfinite(odds) or odds <= 1:
            return False
        payload_hash = snapshot.get("prediction_payload_hash")
        if not isinstance(payload_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
            return False
        from core.snapshot_logger import compute_prediction_payload_hash
        return compute_prediction_payload_hash(snapshot) == payload_hash
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def _normalize_line(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value).strip().casefold()


def _observation_identity(snapshot: Dict[str, Any]) -> tuple[Optional[str], Optional[tuple]]:
    event_id = str(snapshot.get("canonical_event_id") or snapshot.get("event_id") or "").strip().casefold()
    start = str(snapshot.get("event_start") or "").strip()
    if event_id:
        event_key = (event_id, start)
    else:
        teams = "|".join(str(snapshot.get(key) or "").strip().casefold()
                         for key in ("sport", "league", "away_team", "home_team"))
        if not start or not any(snapshot.get(key) for key in ("away_team", "home_team")):
            return None, None
        event_key = (teams, start)
    market = str(snapshot.get("market") or "").strip().casefold()
    side = str(snapshot.get("side") or "").strip().casefold()
    selection = str(snapshot.get("selection") or "").strip().casefold()
    if not market or (not side and not selection):
        return None, None
    choice = ("side", side) if side else ("selection", selection)
    return json.dumps(event_key, ensure_ascii=False, separators=(",", ":")), (
        event_key, market, choice, _normalize_line(snapshot.get("line")))


def _scope_forward_snapshots(
    snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], str, Dict[str, int]]:
    if target_experiment_id is None:
        target_experiment_id = get_current_experiment_identity()["experiment_id"]
    candidates = [s for s in snapshots if _is_forward_binary(s, target_experiment_id)]
    valid_identities = [s for s in snapshots if validate_experiment_identity(s.get("experiment_identity"))]
    keyed: Dict[tuple, List[Dict[str, Any]]] = {}
    missing_key = 0
    for snapshot in candidates:
        event_key, observation_key = _observation_identity(snapshot)
        if event_key is None or observation_key is None:
            missing_key += 1
            continue
        keyed.setdefault(observation_key, []).append(snapshot)

    unique: List[Dict[str, Any]] = []
    conflicts = 0
    duplicate_retries = 0
    for rows in keyed.values():
        results = {(row.get("settlement_status"), row.get("actual_outcome")) for row in rows}
        if len(results) != 1:
            conflicts += 1
            continue
        duplicate_retries += max(0, len(rows) - 1)
        rows.sort(key=lambda row: (str(row.get("snapshot_created_at") or row.get("timestamp") or ""),
                                   str(row.get("snapshot_id") or ""),
                                   str(row.get("prediction_payload_hash") or "")))
        unique.append(rows[0])
    event_count = len({_observation_identity(row)[0] for row in unique})
    return unique, target_experiment_id, {
        "input_count": len(snapshots),
        "eligible_count": len(candidates),
        "unique_event_count": event_count,
        "observation_count": len(unique),
        "duplicate_retries_removed": duplicate_retries,
        "conflicting_observations_excluded": conflicts,
        "missing_observation_key_excluded": missing_key,
        "legacy_or_invalid_identity_excluded": sum(
            1 for s in snapshots if not validate_experiment_identity(s.get("experiment_identity"))),
        "different_target_identity_excluded": sum(
            1 for s in valid_identities
            if s.get("experiment_identity", {}).get("experiment_id") != target_experiment_id),
    }


def _has_model_probability(snapshot: Dict[str, Any]) -> bool:
    probability = snapshot.get("model_probability")
    return (snapshot.get("probability_status") in {"UNVALIDATED_MODEL_ESTIMATE", "MODEL_ESTIMATE", "CALIBRATED_MODEL_ESTIMATE"}
            and isinstance(probability, (int, float)) and not isinstance(probability, bool)
            and math.isfinite(probability) and 0 <= probability <= 1)


def _safe_roi(wins_odds_sum: float, sample_size: int) -> Optional[float]:
    """Calculate ROI percentage: ((sum of winning odds) - N) / N * 100."""
    if sample_size <= 0:
        return None
    return round(((wins_odds_sum - sample_size) / sample_size) * 100.0, 2)


def _metric_metadata(target_experiment_id: str) -> Dict[str, str]:
    return {"target_experiment_id": target_experiment_id,
            "sample_unit": "unique settled event/market/side/line; selection label fallback when side is absent"}


def _calc_brier(probs: List[float], outcomes: List[bool]) -> Optional[float]:
    if not probs or len(probs) != len(outcomes):
        return None
    scores = [(p - (1.0 if o else 0.0)) ** 2 for p, o in zip(probs, outcomes)]
    return round(sum(scores) / len(scores), 4)


def _calc_logloss(probs: List[float], outcomes: List[bool]) -> Optional[float]:
    if not probs or len(probs) != len(outcomes):
        return None
    losses = []
    for p, o in zip(probs, outcomes):
        y = 1.0 if o else 0.0
        p_c = max(0.001, min(0.999, p))
        losses.append(-(y * math.log(p_c) + (1.0 - y) * math.log(1.0 - p_c)))
    return round(sum(losses) / len(losses), 4)


class PerformanceMetricsEngine:
    """Evaluates forward prediction snapshots and generates segmented performance metrics."""

    @staticmethod
    def forward_cohort(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Any]:
        """Public shared cohort for UI, reports and evidence audits."""
        observations, identity, audit = _scope_forward_snapshots(snapshots, target_experiment_id)
        return {"observations": observations, "target_experiment_id": identity, "audit": audit}

    @staticmethod
    def compare_experiments(snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare validated experiment groups over their shared observation basis.

        Legacy rows remain visible only in the reference counts; they are never
        merged into a current or historical experiment's forward metrics.
        """
        groups: Dict[str, List[Dict[str, Any]]] = {}
        identities: Dict[str, Dict[str, Any]] = {}
        legacy_reference_count = 0
        for snapshot in snapshots:
            identity = snapshot.get("experiment_identity")
            if not validate_experiment_identity(identity):
                legacy_reference_count += 1
                continue
            experiment_id = identity["experiment_id"]
            groups.setdefault(experiment_id, []).append(snapshot)
            identities[experiment_id] = dict(identity)

        comparisons: Dict[str, Any] = {}
        key_sets = []
        for experiment_id, records in groups.items():
            unique, _, audit = _scope_forward_snapshots(records, experiment_id)
            observation_keys = {_observation_identity(row)[1] for row in unique}
            key_sets.append(observation_keys)
            comparisons[experiment_id] = {
                "experiment_identity": identities[experiment_id],
                "agreement_buckets": PerformanceMetricsEngine.evaluate_agreement_buckets(
                    records, target_experiment_id=experiment_id),
                "model_metrics": PerformanceMetricsEngine.evaluate_model_overall_metrics(
                    records, target_experiment_id=experiment_id),
                "audit": audit,
            }
        shared_count = len(set.intersection(*key_sets)) if key_sets else 0
        return {
            "comparison_basis": "paired unique event/market/side/line observations; selection label fallback only",
            "paired_observation_count": shared_count,
            "experiments": comparisons,
            "legacy_reference": {"excluded_count": legacy_reference_count},
        }

    @staticmethod
    def evaluate_agreement_buckets(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Evaluate performance across HIGH, MED, LOW, INSUFFICIENT buckets."""
        snapshots, target_experiment_id, _ = _scope_forward_snapshots(snapshots, target_experiment_id)
        buckets = {
            "HIGH": {"n": 0, "wins": 0, "odds_sum": 0.0, "total_odds": 0.0},
            "MED": {"n": 0, "wins": 0, "odds_sum": 0.0, "total_odds": 0.0},
            "LOW": {"n": 0, "wins": 0, "odds_sum": 0.0, "total_odds": 0.0},
            "INSUFFICIENT": {"n": 0, "wins": 0, "odds_sum": 0.0, "total_odds": 0.0},
        }

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id):
                continue
            quality = s.get("evidence_quality", "INSUFFICIENT")
            if quality not in buckets:
                quality = "INSUFFICIENT"

            outcome = bool(s.get("actual_outcome"))
            odds = float(s.get("taiwan_odds", 1.0))

            b = buckets[quality]
            b["n"] += 1
            b["total_odds"] += odds
            if outcome:
                b["wins"] += 1
                b["odds_sum"] += odds

        res = {}
        for k, v in buckets.items():
            n = v["n"]
            res[k] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "hit_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "average_odds": round(v["total_odds"] / n, 2) if n > 0 else None,
                "roi_pct": _safe_roi(v["odds_sum"], n),
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }
        return res

    @staticmethod
    def evaluate_model_market_delta_buckets(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Evaluate performance across Model - Market Delta (percentage points) buckets."""
        snapshots, target_experiment_id, _ = _scope_forward_snapshots(snapshots, target_experiment_id)
        bins = {
            "< -5pp": {"min": -999.0, "max": -5.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "-5 ~ 0pp": {"min": -5.0, "max": 0.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "0 ~ +3pp": {"min": 0.0, "max": 3.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "+3 ~ +5pp": {"min": 3.0, "max": 5.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "+5 ~ +10pp": {"min": 5.0, "max": 10.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "> +10pp": {"min": 10.0, "max": 999.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
        }

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id) or not _has_model_probability(s):
                continue
            delta = s.get("model_market_delta_pp")
            if delta is None:
                delta = s.get("model_market_delta")
            if delta is None:
                continue

            delta_val = float(delta)
            outcome = bool(s.get("actual_outcome"))
            odds = float(s.get("taiwan_odds", 1.0))
            prob = s["model_probability"]

            for b_name, b_meta in bins.items():
                if b_meta["min"] <= delta_val < b_meta["max"] or (b_meta["max"] == 999.0 and delta_val >= b_meta["min"]):
                    b_meta["n"] += 1
                    if outcome:
                        b_meta["wins"] += 1
                        b_meta["odds_sum"] += odds
                    b_meta["probs"].append(prob)
                    b_meta["outcomes"].append(outcome)
                    break

        res = {}
        for k, v in bins.items():
            n = v["n"]
            res[k] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "hit_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "roi_pct": _safe_roi(v["odds_sum"], n),
                "brier_score": _calc_brier(v["probs"], v["outcomes"]),
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }
        return res

    @staticmethod
    def evaluate_expert_metrics(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Any]:
        """Evaluate individual expert performance and consensus buckets."""
        snapshots, target_experiment_id, _ = _scope_forward_snapshots(snapshots, target_experiment_id)
        expert_records: Dict[str, Dict[str, Any]] = {}
        consensus_counts = {
            "0 expert": {"n": 0, "wins": 0, "odds_sum": 0.0},
            "1 expert": {"n": 0, "wins": 0, "odds_sum": 0.0},
            "2-3 experts": {"n": 0, "wins": 0, "odds_sum": 0.0},
            ">=4 experts": {"n": 0, "wins": 0, "odds_sum": 0.0},
        }
        consensus_ratios = {
            "<60%": {"n": 0, "wins": 0, "odds_sum": 0.0},
            "60-75%": {"n": 0, "wins": 0, "odds_sum": 0.0},
            ">75%": {"n": 0, "wins": 0, "odds_sum": 0.0},
        }

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id):
                continue

            outcome = bool(s.get("actual_outcome"))
            odds = float(s.get("taiwan_odds", 1.0))
            experts = s.get("verified_experts", [])
            exp_count = len(experts)

            # Consensus by count
            if exp_count == 0:
                c_key = "0 expert"
            elif exp_count == 1:
                c_key = "1 expert"
            elif 2 <= exp_count <= 3:
                c_key = "2-3 experts"
            else:
                c_key = ">=4 experts"

            consensus_counts[c_key]["n"] += 1
            if outcome:
                consensus_counts[c_key]["wins"] += 1
                consensus_counts[c_key]["odds_sum"] += odds

            # Individual experts
            for exp in experts:
                name = exp if isinstance(exp, str) else exp.get("userid") or exp.get("expert_userid") or exp.get("nickname") or exp.get("expert_nickname") or exp.get("expert_name")
                if not name:
                    continue
                if name not in expert_records:
                    expert_records[name] = {"n": 0, "wins": 0, "odds_sum": 0.0, "total_odds": 0.0}
                expert_records[name]["n"] += 1
                expert_records[name]["total_odds"] += odds
                if outcome:
                    expert_records[name]["wins"] += 1
                    expert_records[name]["odds_sum"] += odds

        # Summarize experts
        leaderboard = {}
        for name, v in expert_records.items():
            n = v["n"]
            leaderboard[name] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "win_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "average_odds": round(v["total_odds"] / n, 2) if n > 0 else None,
                "roi_pct": _safe_roi(v["odds_sum"], n),
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }

        counts_res = {}
        for k, v in consensus_counts.items():
            n = v["n"]
            counts_res[k] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "hit_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "roi_pct": _safe_roi(v["odds_sum"], n),
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }

        return {
            "leaderboard": leaderboard,
            "consensus_count_buckets": counts_res,
        }

    @staticmethod
    def evaluate_crowd_buckets(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Evaluate Crowd consensus percentage bins (50-60%, 60-70%, 70-80%, 80%+)."""
        snapshots, target_experiment_id, _ = _scope_forward_snapshots(snapshots, target_experiment_id)
        bins = {
            "50-60%": {"min": 0.50, "max": 0.60, "n": 0, "wins": 0, "odds_sum": 0.0},
            "60-70%": {"min": 0.60, "max": 0.70, "n": 0, "wins": 0, "odds_sum": 0.0},
            "70-80%": {"min": 0.70, "max": 0.80, "n": 0, "wins": 0, "odds_sum": 0.0},
            "80%+":   {"min": 0.80, "max": 1.01, "n": 0, "wins": 0, "odds_sum": 0.0},
        }

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id):
                continue
            ratio = s.get("crowd_ratio")
            if ratio is None:
                continue
            ratio_val = float(ratio)
            # Normalize percentage if passed as 0~100
            if ratio_val > 1.0:
                ratio_val /= 100.0

            outcome = bool(s.get("actual_outcome"))
            odds = float(s.get("taiwan_odds", 1.0))

            for b_name, b_meta in bins.items():
                if b_meta["min"] <= ratio_val < b_meta["max"]:
                    b_meta["n"] += 1
                    if outcome:
                        b_meta["wins"] += 1
                        b_meta["odds_sum"] += odds
                    break

        res = {}
        for k, v in bins.items():
            n = v["n"]
            res[k] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "hit_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "roi_pct": _safe_roi(v["odds_sum"], n),
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }
        return res

    @staticmethod
    def evaluate_calibration_bins(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Evaluate probability calibration: predicted probability bins vs empirical hit rate."""
        snapshots, target_experiment_id, _ = _scope_forward_snapshots(snapshots, target_experiment_id)
        bins = {
            "0-10%": {"min": 0.0, "max": 0.10, "n": 0, "wins": 0, "pred_sum": 0.0},
            "10-25%": {"min": 0.10, "max": 0.25, "n": 0, "wins": 0, "pred_sum": 0.0},
            "25-50%": {"min": 0.25, "max": 0.50, "n": 0, "wins": 0, "pred_sum": 0.0},
            "50-55%": {"min": 0.50, "max": 0.55, "n": 0, "wins": 0, "pred_sum": 0.0},
            "55-60%": {"min": 0.55, "max": 0.60, "n": 0, "wins": 0, "pred_sum": 0.0},
            "60-65%": {"min": 0.60, "max": 0.65, "n": 0, "wins": 0, "pred_sum": 0.0},
            "65-70%": {"min": 0.65, "max": 0.70, "n": 0, "wins": 0, "pred_sum": 0.0},
            "70%+":   {"min": 0.70, "max": 1.01, "n": 0, "wins": 0, "pred_sum": 0.0},
        }

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id) or not _has_model_probability(s):
                continue
            prob = s.get("model_probability")
            if prob is None:
                continue
            prob_val = float(prob)
            outcome = bool(s.get("actual_outcome"))

            for b_name, b_meta in bins.items():
                if b_meta["min"] <= prob_val < b_meta["max"]:
                    b_meta["n"] += 1
                    b_meta["pred_sum"] += prob_val
                    if outcome:
                        b_meta["wins"] += 1
                    break

        res = {}
        for k, v in bins.items():
            n = v["n"]
            res[k] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "avg_predicted_prob": round(v["pred_sum"] / n, 4) if n > 0 else None,
                "empirical_hit_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "calibration_error": round(abs((v["wins"] / n) - (v["pred_sum"] / n)), 4) if n > 0 else None,
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }
        return res

    @staticmethod
    def evaluate_model_overall_metrics(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Any]:
        """Compute aggregate Brier, Log Loss, and ROI for models."""
        snapshots, target_experiment_id, audit = _scope_forward_snapshots(snapshots, target_experiment_id)
        probs = []
        outcomes = []
        odds_sum = 0.0
        wins = 0

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id) or not _has_model_probability(s):
                continue
            prob = s.get("model_probability")
            if prob is None:
                continue
            outcome = bool(s.get("actual_outcome"))
            odds = float(s.get("taiwan_odds", 1.0))

            probs.append(float(prob))
            outcomes.append(outcome)
            if outcome:
                wins += 1
                odds_sum += odds

        n = len(probs)
        return {
            "sample_size": n,
            **_metric_metadata(target_experiment_id),
            "wins": wins,
            "hit_rate": round(wins / n, 4) if n > 0 else None,
            "classification_accuracy": round(sum((p >= 0.5) == o for p, o in zip(probs, outcomes)) / n, 4) if n > 0 else None,
            "brier_score": _calc_brier(probs, outcomes),
            "log_loss": _calc_logloss(probs, outcomes),
            "roi_pct": _safe_roi(odds_sum, n),
            "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            "target_experiment_id": target_experiment_id,
            "observation_count": audit["observation_count"],
            "unique_event_count": audit["unique_event_count"],
            "audit": audit,
        }

    @staticmethod
    def evaluate_ev_buckets(snapshots: List[Dict[str, Any]], target_experiment_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Evaluate forward performance across Expected Value (EV) tiers.

        Tiers:
        - 優質價值 (EV >= +5%)
        - 溫和價值 (0% <= EV < +5%)
        - 負期望值陷阱 (EV < 0%)
        """
        snapshots, target_experiment_id, _ = _scope_forward_snapshots(snapshots, target_experiment_id)
        bins = {
            "優質價值 (EV ≥ +5%)": {"min": 0.05, "max": 999.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "溫和價值 (0% ≤ EV < +5%)": {"min": 0.0, "max": 0.05, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
            "負期望值陷阱 (EV < 0%)": {"min": -999.0, "max": 0.0, "n": 0, "wins": 0, "odds_sum": 0.0, "probs": [], "outcomes": []},
        }

        for s in snapshots:
            if not _is_forward_binary(s, target_experiment_id) or not _has_model_probability(s):
                continue

            ev = s.get("expected_value")
            odds = float(s.get("taiwan_odds", 1.0))
            prob = s.get("calibrated_probability") or s.get("model_probability") or s.get("consensus_probability")
            if ev is None:
                if prob is not None and odds > 1.0:
                    ev = prob * odds - 1.0
                else:
                    continue

            ev_val = float(ev)
            outcome = bool(s.get("actual_outcome"))
            p_val = prob if prob is not None else (1.0 / odds if odds > 0 else 0.5)

            for b_name, b_meta in bins.items():
                if b_meta["min"] <= ev_val < b_meta["max"] or (b_meta["max"] == 999.0 and ev_val >= b_meta["min"]):
                    b_meta["n"] += 1
                    if outcome:
                        b_meta["wins"] += 1
                        b_meta["odds_sum"] += odds
                    b_meta["probs"].append(p_val)
                    b_meta["outcomes"].append(outcome)
                    break

        res = {}
        for k, v in bins.items():
            n = v["n"]
            res[k] = {
                "sample_size": n,
                **_metric_metadata(target_experiment_id),
                "wins": v["wins"],
                "hit_rate": round(v["wins"] / n, 4) if n > 0 else None,
                "roi_pct": _safe_roi(v["odds_sum"], n),
                "brier_score": _calc_brier(v["probs"], v["outcomes"]),
                "is_insufficient_sample": n < INSUFFICIENT_THRESHOLD,
            }
        return res

