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
from dataclasses import fields
from typing import Any, Dict, List, Optional

from core.contracts.common import TaiwanLeg
from integrations.odds.sharp_benchmark_odds import SharpBenchmarkOddsAdapter, SharpComparisonResult
from core.contracts.market import MarketBenchmarkEvidence

logger = logging.getLogger(__name__)


class SharpEdgeEngine:
    """Quantitative valuation engine comparing Taiwan Lottery against Sharp Fair benchmarks."""

    def __init__(self, adapter: Optional[SharpBenchmarkOddsAdapter] = None):
        self.adapter = adapter or SharpBenchmarkOddsAdapter()

    def evaluate_leg_sharp_edge(self, leg: TaiwanLeg) -> Optional[SharpComparisonResult]:
        """Compute Sharp EV only from the validated benchmark sealed on the leg."""
        odds = float(leg.taiwan_odds or 0.0)
        raw_evidence = (leg.signal_evidence or {}).get("market_benchmark")
        if odds <= 1.0 or not isinstance(raw_evidence, dict):
            return None
        try:
            allowed = {item.name for item in fields(MarketBenchmarkEvidence)}
            benchmark = MarketBenchmarkEvidence(**{
                key: value for key, value in raw_evidence.items() if key in allowed
            })
        except (TypeError, ValueError):
            return None
        return self.adapter.compare_leg(leg, benchmark)

    def evaluate_parlay_sharp_ev(
        self,
        legs: List[TaiwanLeg],
        total_odds: float,
        correlation_penalty: float = 0.0,
        precomputed_leg_results: Optional[List[Optional[SharpComparisonResult]]] = None,
    ) -> Dict[str, Any]:
        """Evaluate a multi-leg parlay using Sharp de-vigged fair probabilities.

        Joint Sharp Probability = prod(P_sharp_i) * (1 - correlation_penalty)
        Sharp Parlay EV = (Joint_Sharp_Probability * Total_Odds) - 1.0
        """
        if not legs or total_odds <= 1.0:
            return {
                "has_sharp_benchmark": False,
                "sharp_joint_probability": None,
                "sharp_parlay_ev": None,
                "sharp_parlay_ev_pct": None,
                "value_legs_count": 0,
                "total_legs": len(legs),
                "benchmark_status": "NO_QUALIFIED_SHARP_BENCHMARK",
                "summary_badge": "Sharp 基準尚未取得",
            }

        results = (precomputed_leg_results if precomputed_leg_results is not None
                   and len(precomputed_leg_results) == len(legs)
                   else [self.evaluate_leg_sharp_edge(leg) for leg in legs])
        if any(result is None for result in results):
            return {
                "has_sharp_benchmark": False,
                "sharp_joint_probability": None,
                "sharp_parlay_ev": None,
                "sharp_parlay_ev_pct": None,
                "value_legs_count": 0,
                "total_legs": len(legs),
                "benchmark_status": "INCOMPLETE_QUALIFIED_SHARP_BENCHMARK",
                "summary_badge": "Sharp 基準不完整，無法計算",
            }

        sharp_probs = []
        value_count = 0

        for res in results:
            assert res is not None  # guarded above
            sharp_probs.append(res.sharp_fair_prob)
            if res.is_value_bet:
                value_count += 1

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
            "benchmark_status": "QUALIFIED_SHARP_BENCHMARK_AVAILABLE",
            "is_positive_ev": is_positive_ev,
            "is_prime_value": is_prime_value,
            "summary_badge": "🟢 正期望值 (+EV)" if is_positive_ev else "⚪ 市場中性/負EV",
        }
