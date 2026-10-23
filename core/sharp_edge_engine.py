#!/usr/bin/env python3
"""Sharp Edge & Positive EV Quantitative Valuation Engine.

Calculates:
1. Sharp Market De-vigged Fair Probability
2. Positive Edge over Taiwan Sports Lottery Odds (Edge = P_sharp - 1/Odds)
3. Direct EV (%) = (P_sharp * Odds - 1.0) * 100
4. Value Classification: PRIME_VALUE (+5%+), SOLID_VALUE (+2%~+5%), FAIR, TRAP (<0%)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from integrations.common.models import TaiwanLeg
from integrations.odds.sharp_benchmark_odds import SharpBenchmarkOddsAdapter, SharpComparisonResult

logger = logging.getLogger(__name__)


class SharpEdgeEngine:
    """Quantitative valuation engine comparing Taiwan Lottery against Sharp Fair benchmarks."""

    def __init__(self, adapter: Optional[SharpBenchmarkOddsAdapter] = None):
        self.adapter = adapter or SharpBenchmarkOddsAdapter()

    def evaluate_leg_sharp_edge(self, leg: TaiwanLeg) -> Optional[SharpComparisonResult]:
        """Compute the sharp edge and true EV for a single TaiwanLeg."""
        odds = float(leg.taiwan_odds or 0.0)
        if odds <= 1.0:
            return None

        evidence = leg.signal_evidence or {}
        opposing_odds = None
        draw_odds = None
        outcomes = evidence.get("market_outcome_odds") or {}

        if outcomes and isinstance(outcomes, dict):
            if leg.side == "主" and "客" in outcomes:
                opposing_odds = float(outcomes["客"])
                if "和" in outcomes:
                    draw_odds = float(outcomes["和"])
            elif leg.side == "客" and "主" in outcomes:
                opposing_odds = float(outcomes["主"])
                if "和" in outcomes:
                    draw_odds = float(outcomes["和"])
            elif leg.side == "大" and "小" in outcomes:
                opposing_odds = float(outcomes["小"])
            elif leg.side == "小" and "大" in outcomes:
                opposing_odds = float(outcomes["大"])

        return self.adapter.get_sharp_fair_odds(
            sport=leg.sport,
            league=leg.league,
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            taiwan_odds=odds,
            opposing_odds=opposing_odds,
            draw_odds=draw_odds,
        )

    def evaluate_parlay_sharp_ev(
        self,
        legs: List[TaiwanLeg],
        total_odds: float,
        correlation_penalty: float = 0.0,
    ) -> Dict[str, Any]:
        """Evaluate a multi-leg parlay using Sharp de-vigged fair probabilities.

        Joint Sharp Probability = prod(P_sharp_i) * (1 - correlation_penalty)
        Sharp Parlay EV = (Joint_Sharp_Probability * Total_Odds) - 1.0
        """
        if not legs or total_odds <= 1.0:
            return {
                "has_sharp_benchmark": False,
                "sharp_joint_probability": 0.0,
                "sharp_parlay_ev": -1.0,
                "sharp_parlay_ev_pct": -100.0,
                "value_legs_count": 0,
                "total_legs": len(legs),
            }

        sharp_probs = []
        value_count = 0

        for leg in legs:
            res = self.evaluate_leg_sharp_edge(leg)
            if res is not None and res.sharp_fair_prob > 0:
                sharp_probs.append(res.sharp_fair_prob)
                if res.is_value_bet:
                    value_count += 1
            else:
                # Fallback to market implied
                p = 1.0 / leg.taiwan_odds if leg.taiwan_odds > 1.0 else 0.5
                sharp_probs.append(p)

        # Naive joint
        naive_sharp_joint = 1.0
        for p in sharp_probs:
            naive_sharp_joint *= p

        haircut = max(0.0, min(0.35, correlation_penalty))
        joint_sharp_prob = naive_sharp_joint * (1.0 - haircut)
        sharp_parlay_ev = (joint_sharp_prob * total_odds) - 1.0
        sharp_parlay_ev_pct = sharp_parlay_ev * 100.0

        is_prime_value = sharp_parlay_ev >= 0.10
        is_positive_ev = sharp_parlay_ev > 0.0

        return {
            "has_sharp_benchmark": True,
            "sharp_joint_probability": round(joint_sharp_prob, 6),
            "naive_sharp_joint": round(naive_sharp_joint, 6),
            "sharp_parlay_ev": round(sharp_parlay_ev, 4),
            "sharp_parlay_ev_pct": round(sharp_parlay_ev_pct, 2),
            "value_legs_count": value_count,
            "total_legs": len(legs),
            "is_positive_ev": is_positive_ev,
            "is_prime_value": is_prime_value,
            "summary_badge": "🟢 正期望值 (+EV)" if is_positive_ev else "⚪ 市場中性/負EV",
        }
