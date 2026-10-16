"""Estimate probabilities without treating popularity or model count as samples."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from probability.calibration import inv_logit, logit
from core.model_acceptance import acceptance_matches_signal


def evaluate_evidence(engine: Any, leg: Any, signals: Any = None, opposing_odds: Any = None,
                      *, research_candidate: bool = False, direct_accepted_model: bool = False):
    from core.edge_engine import ProbabilityEdgeEvaluation

    odds = float(leg.taiwan_odds)
    if not math.isfinite(odds) or odds <= 1:
        raise ValueError("機率評估需要大於1的有限賠率。")
    market_prob = 1 / odds
    evidence = leg.signal_evidence or {}
    outcomes = evidence.get("market_outcome_odds") or {}
    if not isinstance(outcomes, Mapping):
        outcomes = {}
    fair_method = "BREAKEVEN_BASELINE_NOT_DEVIGGED"
    fair = market_prob
    expected_sides = {"主", "客", "和"} if leg.sport == "soccer" and leg.market in {"不讓分", "和局", "獨贏"} else (
        {"大", "小"} if leg.market == "大小" else {"主", "客"}
    )
    if evidence.get("market_complete") and set(outcomes) == expected_sides and leg.side in outcomes:
        try:
            values = {side: float(value) for side, value in outcomes.items()}
            if all(math.isfinite(value) and value > 1 for value in values.values()) and abs(values[leg.side] - odds) < 1e-8:
                fair = (1 / odds) / sum(1 / value for value in values.values())
                fair_method = "COMPLETE_MARKET_PROPORTIONAL"
        except (ValueError, TypeError):
            pass
    elif opposing_odds is not None and len(expected_sides) == 2:
        opposing = float(opposing_odds)
        if math.isfinite(opposing) and opposing > 1:
            fair = market_prob / (market_prob + 1 / opposing)
            fair_method = "TWO_WAY_PROPORTIONAL"

    # One vote per data lineage, irrespective of adapters or repeat signals.
    groups = {}
    excluded = []
    accepted_ids = []
    model_categories = {"OPEN_SOURCE_ENGINE", "EXTERNAL_OPEN_SOURCE_ENGINE", "LOCAL_REIMPLEMENTATION", "LOCAL_FALLBACK_MODEL", "MODEL"}
    for signal in (signals if signals is not None else leg.signals):
        category = signal.source_category or signal.source_type
        if category not in model_categories:
            continue
        metadata = signal.metadata or {}
        probability = metadata.get("model_candidate_probability", signal.probability) if research_candidate else signal.probability
        acceptance = metadata.get("model_acceptance") or {}
        if not research_candidate and not acceptance_matches_signal(signal, leg):
            excluded.append(signal.source_id)
            continue
        if acceptance_matches_signal(signal, leg):
            accepted_ids.append(str(metadata.get("model_id", signal.source_id)))
        if signal.freshness_status not in {"LIVE", "FRESH", "AGING"} or metadata.get("initialized") is False:
            excluded.append(signal.source_id)
            continue
        if not isinstance(probability, (int, float)) or not math.isfinite(probability) or not 0 < probability < 1:
            excluded.append(signal.source_id)
            continue
        lineage = signal.independence_group or signal.source_id
        weight = metadata.get("configured_weight", engine.source_weights.get(category, {}).get("base_weight", 1.0))
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(weight) or weight <= 0:
            continue
        if signal.freshness_status == "AGING":
            weight *= 0.5
        # Choosing deterministically makes permutation and duplication irrelevant.
        candidate = (str(signal.source_id), float(probability), weight)
        if lineage not in groups or candidate[0] < groups[lineage][0]:
            groups[lineage] = candidate

    model_prob = None
    if groups:
        total_weight = sum(row[2] for row in groups.values())
        model_prob = sum(row[1] * row[2] for row in groups.values()) / total_weight
    # Historical leaderboard accuracy and crowd vote share describe a source,
    # not the probability of this selection. Neither changes the probability.
    if model_prob is None:
        calibrated = fair
    elif direct_accepted_model:
        # The acceptance certificate evaluates this calibrated model output
        # directly. Do not apply a second, uncertified market shrinkage step.
        calibrated = model_prob
    else:
        calibrated = inv_logit(logit(fair) + engine.beta_model * (logit(model_prob) - logit(fair)))
    consensus = calibrated if direct_accepted_model else max(0.001, min(0.999, calibrated))
    ev = consensus * odds - 1
    details = {
        "effective_sample_n": 0,
        "independent_model_count": len(groups), "model_count": len(groups),
        "excluded_models": excluded,
        "market_fair_method": fair_method,
        "probability_status": ("UNVALIDATED_MODEL_ESTIMATE" if research_candidate else
                               ("CALIBRATED_MODEL_ESTIMATE" if direct_accepted_model else
                                "UNVALIDATED_MODEL_FUSION_ESTIMATE")) if model_prob is not None else "MARKET_BASELINE_ONLY",
        "calibration_status": ("NOT_EMPIRICALLY_CALIBRATED" if research_candidate else
                               ("EMPIRICALLY_CALIBRATED_POINT_IN_TIME" if direct_accepted_model else
                                "FUSION_PROTOCOL_NOT_EMPIRICALLY_VALIDATED")) if model_prob is not None else "NOT_APPLICABLE_MARKET_BASELINE",
        "interval_status": "NOT_AVAILABLE",
        "has_expert": False, "has_crowd": False,
        "expert_probability_adjustment": False, "crowd_probability_adjustment": False,
        "model_groups": sorted(groups),
        "accepted_model_ids": sorted(set(accepted_ids)),
    }
    return ProbabilityEdgeEvaluation(
        market_probability=market_prob, market_fair_probability=fair,
        model_probability_raw=model_prob, model_probability_calibrated=calibrated,
        consensus_probability=consensus, conservative_prob_lower=None,
        conservative_prob_upper=None, confidence_interval=None, uncertainty_level="UNVALIDATED",
        edge_vs_breakeven_pp=(consensus - market_prob) * 100,
        edge_vs_fair_pp=(consensus - fair) * 100, expected_value=ev,
        conservative_ev=None, is_positive_ev=ev > 0,
        ev_grade="UNVALIDATED_ESTIMATE" if model_prob is not None else "MARKET_BASELINE", details=details,
    )
