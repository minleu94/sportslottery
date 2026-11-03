#!/usr/bin/env python3
"""Experimental model fusion and estimated EV.

Only complete outcome markets can be de-vigged. Logit shrinkage is a heuristic,
not empirical calibration. Recommendation intervals remain unavailable until
forward observations support a validated uncertainty model.
"""

from __future__ import annotations

import logging
import math
from statistics import NormalDist
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.contracts.probability import ProbabilityEdgeEvaluation

from core.contracts.common import PredictionSignal, TaiwanLeg
from core.contracts.market import MarketBenchmarkEvidence
from probability.calibration import calculate_conservative_lower_bound, inv_logit, logit

logger = logging.getLogger(__name__)

# Default shrinkage parameters
DEFAULT_BETA_MODEL = 0.65       # Weight placed on statistical model logit vs market fair logit
DEFAULT_BETA_EXPERT = 0.0       # Deprecated; expert history is not event probability.
DEFAULT_BETA_CROWD = 0.0        # Deprecated; vote share is not event probability.
DEFAULT_TAIWAN_OVERROUND = 0.0  # Deprecated; an incomplete market has no known margin.


@dataclass
class ConfidenceInterval:
    lower_bound: float
    upper_bound: float
    uncertainty_level: str


@dataclass
class DirectEdgeResult:
    probability: float
    odds: float
    expected_value: float
    edge_pct: float
    is_negative_ev: bool
    is_value_bet: bool
    trap_warning: str = ""


class EdgeEngine:
    """Computes experimental model estimates, market baselines and estimated EV."""

    def __init__(
        self,
        beta_model: float = DEFAULT_BETA_MODEL,
        beta_expert: float = DEFAULT_BETA_EXPERT,
        beta_crowd: float = DEFAULT_BETA_CROWD,
        assumed_overround: float = DEFAULT_TAIWAN_OVERROUND,
        source_weights: Optional[Dict[str, Any]] = None,
    ):
        self.beta_model = beta_model
        self.beta_expert = beta_expert
        self.beta_crowd = beta_crowd
        self.assumed_overround = assumed_overround
        self.source_weights = source_weights or {}

    def evaluate_leg(
        self,
        leg: TaiwanLeg,
        signals: Optional[List[PredictionSignal]] = None,
        reference_opposing_odds: Optional[float] = None,
        *,
        research_candidate: bool = False,
        direct_accepted_model: bool = False,
        market_benchmark: Optional[MarketBenchmarkEvidence] = None,
    ) -> ProbabilityEdgeEvaluation:
        """Perform full quantitative evaluation for a TaiwanLeg."""
        from core.probability_evidence import evaluate_evidence
        return evaluate_evidence(self, leg, signals, reference_opposing_odds,
                                 research_candidate=research_candidate,
                                 direct_accepted_model=direct_accepted_model,
                                 market_benchmark=market_benchmark)

    @staticmethod
    def devig_proportional(odds_list: List[float]) -> List[float]:
        """Normalize market odds to remove margin proportionally."""
        inv_sum = sum(1.0 / o for o in odds_list if o > 0)
        if inv_sum <= 0:
            return [1.0 / len(odds_list)] * len(odds_list)
        return [(1.0 / o) / inv_sum for o in odds_list]

    @staticmethod
    def calibrate_probability_logit(raw_prob: float, shrinkage_factor: float = 0.80) -> float:
        """Calibrate raw probability towards 0.50 via logit shrinkage."""
        raw_prob = max(0.001, min(0.999, raw_prob))
        l = logit(raw_prob)
        shrunk_logit = l * shrinkage_factor
        return inv_logit(shrunk_logit)

    @staticmethod
    def calculate_confidence_interval(prob: float, sample_size: int = 20, confidence_level: float = 0.90) -> ConfidenceInterval:
        """Wilson interval for an observed hit proportion and actual sample count.

        This standalone statistical helper is never fed model or signal counts
        by the recommendation pipeline.
        """
        if (not math.isfinite(prob) or not 0 <= prob <= 1
                or not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size <= 0
                or not 0 < confidence_level < 1):
            raise ValueError("需要有效的觀測比例、正整數樣本數與 0～1 信心水準。")
        z = NormalDist().inv_cdf((1 + confidence_level) / 2)
        denominator = 1 + z * z / sample_size
        center = (prob + z * z / (2 * sample_size)) / denominator
        margin = z * math.sqrt(prob * (1 - prob) / sample_size + z * z / (4 * sample_size ** 2)) / denominator
        lower, upper = max(0.0, center - margin), min(1.0, center + margin)
        if margin < 0.04 and sample_size >= 40:
            lvl = "LOW"
        elif margin < 0.08:
            lvl = "MEDIUM"
        else:
            lvl = "HIGH"
        return ConfidenceInterval(lower_bound=lower, upper_bound=upper, uncertainty_level=lvl)

    @staticmethod
    def evaluate_edge(
        raw_prob: float,
        odds: float,
        sample_size: int = 20,
        apply_calibration: bool = True,
    ) -> DirectEdgeResult:
        """Direct mathematical edge and trap evaluation for a single probability & odds."""
        prob = EdgeEngine.calibrate_probability_logit(raw_prob) if apply_calibration else raw_prob
        ev = (prob * odds) - 1.0
        edge_pct = ev * 100.0
        is_neg = ev < 0.0
        is_val = ev >= 0.05
        trap_warning = "【負期望值陷阱】該熱門賠率過低，即便高勝率仍呈數學虧損！" if is_neg else ""
        return DirectEdgeResult(
            probability=prob,
            odds=odds,
            expected_value=ev,
            edge_pct=edge_pct,
            is_negative_ev=is_neg,
            is_value_bet=is_val,
            trap_warning=trap_warning,
        )

