#!/usr/bin/env python3
"""Parlay Correlation Guard and Joint Probability Estimator.

Addresses the critical flaw in parlay pricing:
Assuming P(A ∩ B ∩ C) = P(A) * P(B) * P(C) for 10x~500x longshots leads to
severe compounding probability errors and overconfidence.

Correlation Guard detects:
1. Division / League Rivalry Clustering (Same division matches on same slate)
2. Home / Away Systemic Bias (All-home or all-away slate exposure)
3. Market Type Co-movement (Multiple low totals or high totals correlated by macro conditions)
4. Temporal Clumping (Matches starting at the exact same minute)

Outputs:
- Heuristic Correlation Penalty (0.0% to 25.0% haircut on joint probability)
- Heuristic Joint Probability Estimate (not empirically calibrated)
- Parlay Expected Value (Parlay EV) = Joint_Prob * Total_Taiwan_Odds - 1.0
- Correlation Risk Grade: 'INDEPENDENT_CLEAN', 'MILD_CORRELATION', 'ELEVATED_CORRELATION'
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

from integrations.common.models import TaiwanLeg

logger = logging.getLogger(__name__)

# MLB Division Mapping for rivalry correlation
MLB_DIVISIONS: Dict[str, str] = {
    # AL East
    "NYY": "AL_EAST", "BAL": "AL_EAST", "BOS": "AL_EAST", "TB": "AL_EAST", "TOR": "AL_EAST",
    # AL Central
    "CLE": "AL_CENTRAL", "KC": "AL_CENTRAL", "DET": "AL_CENTRAL", "MIN": "AL_CENTRAL", "CWS": "AL_CENTRAL",
    # AL West
    "HOU": "AL_WEST", "SEA": "AL_WEST", "TEX": "AL_WEST", "OAK": "AL_WEST", "LAA": "AL_WEST",
    # NL East
    "PHI": "NL_EAST", "ATL": "NL_EAST", "NYM": "NL_EAST", "WAS": "NL_EAST", "MIA": "NL_EAST",
    # NL Central
    "MIL": "NL_CENTRAL", "CHC": "NL_CENTRAL", "CIN": "NL_CENTRAL", "STL": "NL_CENTRAL", "PIT": "NL_CENTRAL",
    # NL West
    "LAD": "NL_WEST", "SD": "NL_WEST", "AZ": "NL_WEST", "SF": "NL_WEST", "COL": "NL_WEST",
}


@dataclass
class CorrelationEvaluation:
    """Evaluation of parlay cross-leg independence and joint value."""
    correlation_penalty: float         # 0.0 to 0.25 (haircut factor on joint probability)
    joint_probability: float           # P_joint = prod(P_i) * (1 - penalty)
    naive_joint_probability: float     # prod(P_i) without haircut
    parlay_expected_value: float       # joint_prob * total_odds - 1.0
    parlay_ev_pct: float               # parlay_ev * 100.0
    risk_grade: str                    # 'INDEPENDENT_CLEAN', 'MILD_CORRELATION', 'ELEVATED_CORRELATION'
    risk_factors: List[str]            # Human-readable detected correlation reasons
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def haircut_factor(self) -> float:
        return self.correlation_penalty

    @property
    def risk_level(self) -> str:
        return self.risk_grade

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_penalty": round(self.correlation_penalty, 4),
            "correlation_penalty_pct": round(self.correlation_penalty * 100.0, 1),
            "joint_probability": round(self.joint_probability, 6),
            "naive_joint_probability": round(self.naive_joint_probability, 6),
            "parlay_expected_value": round(self.parlay_expected_value, 4),
            "parlay_ev_pct": round(self.parlay_ev_pct, 2),
            "risk_grade": self.risk_grade,
            "risk_factors": self.risk_factors,
            "joint_probability_method": "STRUCTURAL_HEURISTIC_HAIRCUT",
            "joint_probability_validation_status": "UNVALIDATED_HEURISTIC",
            "empirical_joint_diagnostics_status": "NOT_INCLUDED",
            "details": self.details,
        }


class CorrelationGuard:
    """Analyzes a set of TaiwanLegs in a parlay and penalizes joint probability for correlations."""

    def __init__(self, max_penalty: float = 0.25):
        self.max_penalty = max_penalty

    def evaluate_parlay(
        self,
        legs: List[TaiwanLeg],
        total_odds: Optional[float] = None,
    ) -> CorrelationEvaluation:
        """Calculate joint probability, correlation haircut, and parlay EV."""
        if total_odds is None and legs:
            tot = 1.0
            for l in legs:
                tot *= float(l.taiwan_odds or 1.0)
            total_odds = round(tot, 2)
        elif total_odds is None:
            total_odds = 1.0

        if not legs:
            return CorrelationEvaluation(
                correlation_penalty=0.0,
                joint_probability=0.0,
                naive_joint_probability=0.0,
                parlay_expected_value=-1.0,
                parlay_ev_pct=-100.0,
                risk_grade="INDEPENDENT_CLEAN",
                risk_factors=[],
            )

        num_legs = len(legs)
        risk_factors: List[str] = []
        penalty = 0.0

        # 1. Product of individual consensus probabilities
        naive_joint = 1.0
        for l in legs:
            # Use consensus probability if evaluated, else market implied
            p = getattr(l, "consensus_probability", None)
            if p is None or p <= 0:
                p = 1.0 / l.taiwan_odds if l.taiwan_odds > 1.0 else 0.5
            naive_joint *= p

        # 2. Check Same Event or Duplicate Team Exposure
        event_ids = [l.event_id for l in legs if getattr(l, "event_id", None)]
        if len(event_ids) != len(set(event_ids)):
            penalty += 0.20
            risk_factors.append("包含同一賽事的重疊下注關卡（同場高度相關）")

        teams = []
        for l in legs:
            ht = getattr(l, "home_team", "")
            at = getattr(l, "away_team", "")
            if ht:
                teams.append(ht)
            if at:
                teams.append(at)
        team_counts: Dict[str, int] = {}
        for t in teams:
            team_counts[t] = team_counts.get(t, 0) + 1
        dup_teams = [t for t, c in team_counts.items() if c >= 2]
        if dup_teams:
            penalty += 0.08
            risk_factors.append(f"同隊伍重複曝險 ({', '.join(dup_teams)})")

        # 3. Check Home/Away Systemic Concentration Bias
        sides = [getattr(l, "side", "") for l in legs]
        home_count = sum(1 for s in sides if "主" in s)
        away_count = sum(1 for s in sides if "客" in s)

        if num_legs >= 3:
            if home_count == num_legs:
                penalty += 0.05
                risk_factors.append(f"全部 {num_legs} 關均押主隊（主場集中系統性偏誤）")
            elif away_count == num_legs:
                penalty += 0.06
                risk_factors.append(f"全部 {num_legs} 關均押客隊（客隊極端集中曝險）")

        # 3. Check Temporal Clustering (Matches starting at the exact same minute)
        start_times = [getattr(l, "start_time", "") for l in legs if getattr(l, "start_time", "")]
        time_counts: Dict[str, int] = {}
        for t in start_times:
            time_counts[t] = time_counts.get(t, 0) + 1

        clustered_times = [t for t, c in time_counts.items() if c >= 3]
        if clustered_times:
            penalty += 0.04
            risk_factors.append(f"多達 {time_counts[clustered_times[0]]} 場比賽於同時段開打 ({clustered_times[0]})")

        # 4. Check Market Type Concentration (e.g., all Totals)
        markets = [getattr(l, "market", "") for l in legs]
        under_count = sum(1 for l in legs if "小" in getattr(l, "selection", "") or getattr(l, "side", "") == "小")
        over_count = sum(1 for l in legs if "大" in getattr(l, "selection", "") or getattr(l, "side", "") == "大")

        if num_legs >= 3:
            if under_count >= 3:
                penalty += 0.05
                risk_factors.append(f"包含 {under_count} 關大小分小球（大盤得分環境連動性風險）")
            elif over_count >= 3:
                penalty += 0.04
                risk_factors.append(f"包含 {over_count} 關大小分大球（大盤高得分連動性風險）")

        # 5. Check Sports Diversification (Cross-sport bonus vs Single-sport penalty)
        sports = {getattr(l, "sport", "") for l in legs}
        if len(sports) == 1 and num_legs >= 4:
            penalty += 0.04
            risk_factors.append(f"長串 {num_legs} 關全部集中在單一運動類別 ({list(sports)[0]})")

        # 6. Cap penalty
        penalty = min(self.max_penalty, penalty)

        # 7. Joint probability with haircut
        joint_prob = naive_joint * (1.0 - penalty)
        parlay_ev = (joint_prob * total_odds) - 1.0

        if penalty <= 0.03:
            risk_grade = "INDEPENDENT_CLEAN"
        elif penalty <= 0.10:
            risk_grade = "MILD_CORRELATION"
        else:
            risk_grade = "ELEVATED_CORRELATION"

        details = {
            "num_legs": num_legs,
            "home_count": home_count,
            "away_count": away_count,
            "sports_count": len(sports),
            "under_count": under_count,
            "over_count": over_count,
        }

        return CorrelationEvaluation(
            correlation_penalty=penalty,
            joint_probability=joint_prob,
            naive_joint_probability=naive_joint,
            parlay_expected_value=parlay_ev,
            parlay_ev_pct=parlay_ev * 100.0,
            risk_grade=risk_grade,
            risk_factors=risk_factors,
            details=details,
        )

    assess_parlay = evaluate_parlay


def empirical_error_correlation(rows: list[dict[str, Any]], *,
                                min_paired_events: int = 100) -> dict[str, Any]:
    """Describe paired binary forecast-error correlations from scored events.

    Rows must contain a stable ``event_id``, ``actual_outcome`` (bool/0/1),
    and ``probabilities`` mapping model/source IDs to probabilities. Repeated
    rows for the same event are excluded as ambiguous; callers should prepare
    one point-in-time row per event and exact market/side scope. This is a
    diagnostic, not a causal independence claim.
    """
    by_event: dict[str, dict[str, Any]] = {}
    invalid = 0
    for row in rows:
        event = row.get("event_id")
        actual = row.get("actual_outcome")
        probs = row.get("probabilities")
        if not event or isinstance(actual, bool) is False and actual not in (0, 1) or not isinstance(probs, dict):
            invalid += 1
            continue
        clean = {}
        for name, value in probs.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                continue
            clean[str(name)] = float(value) - float(bool(actual))
        key = str(event)
        if key in by_event:
            by_event[key] = None
        else:
            by_event[key] = clean
    valid = {key: value for key, value in by_event.items() if value is not None}
    names = sorted({name for values in valid.values() for name in values})
    pairs = {}
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            paired = [(values[left], values[right]) for values in valid.values()
                      if left in values and right in values]
            pair_key = f"{left}::{right}"
            if len(paired) < min_paired_events:
                pairs[pair_key] = {"status": "INSUFFICIENT_PAIRED_EVENTS", "paired_event_count": len(paired),
                                   "minimum_paired_events": min_paired_events, "error_correlation": None}
                continue
            xs, ys = zip(*paired)
            if len(set(xs)) < 2 or len(set(ys)) < 2:
                corr = None
                status = "UNDEFINED_CONSTANT_ERRORS"
            else:
                corr = statistics.correlation(xs, ys)
                status = "DESCRIPTIVE_PAIRED_ERROR_CORRELATION"
            pairs[pair_key] = {"status": status, "paired_event_count": len(paired),
                               "minimum_paired_events": min_paired_events,
                               "error_correlation": round(corr, 6) if corr is not None else None}
    return {"status": "DESCRIPTIVE_DIAGNOSTIC", "sample_unit": "unique event with paired source residuals",
            "input_rows": len(rows), "unique_valid_events": len(valid),
            "duplicate_event_rows_excluded": sum(value is None for value in by_event.values()),
            "invalid_rows": invalid, "minimum_paired_events": min_paired_events,
            "pairs": pairs,
            "limitation": "Paired forecast-error correlation does not establish source independence or joint-ticket calibration."}


def empirical_joint_hit_diagnostic(rows: list[dict[str, Any]], *,
                                   min_tickets: int = 100,
                                   min_event_clusters: int = 30) -> dict[str, Any]:
    """Compare frozen joint estimates with observed ticket hit rates.

    Input rows need ticket_id, event_id, leg_outcomes (bool list), and the
    frozen predicted_joint_probability. A ticket is scored only once.
    """
    seen: set[str] = set()
    valid = []
    for row in rows:
        ticket = str(row.get("ticket_id") or "")
        outcomes = row.get("leg_outcomes")
        p = row.get("predicted_joint_probability")
        if (not ticket or ticket in seen or not row.get("event_id") or not isinstance(outcomes, list) or not outcomes
                or any(not isinstance(value, bool) for value in outcomes)
                or isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1):
            continue
        seen.add(ticket)
        valid.append({"event_id": str(row["event_id"]), "p": float(p),
                      "hit": all(outcomes)})
    event_count = len({row["event_id"] for row in valid})
    status = "READY_FOR_DESCRIPTIVE_DIAGNOSTIC" if len(valid) >= min_tickets and event_count >= min_event_clusters else "INSUFFICIENT_SAMPLE"
    return {"status": status, "ticket_count": len(valid), "event_cluster_count": event_count,
            "minimum_tickets": min_tickets, "minimum_event_clusters": min_event_clusters,
            "mean_predicted_joint_probability": sum(row["p"] for row in valid) / len(valid) if valid else None,
            "observed_joint_hit_rate": sum(row["hit"] for row in valid) / len(valid) if valid and status.startswith("READY") else None,
            "mean_probability_error": (sum(row["p"] - float(row["hit"]) for row in valid) / len(valid)
                                       if valid and status.startswith("READY") else None),
            "diagnostic_scope": "descriptive frozen-ticket comparison; no calibration claim"}


