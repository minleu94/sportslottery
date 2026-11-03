"""Probability evaluation result contract shared by the edge policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class ProbabilityEdgeEvaluation:
    """Estimated probability and value with explicit evidence limitations."""

    market_probability: float
    market_fair_probability: float
    model_probability_raw: Optional[float]
    model_probability_calibrated: float
    consensus_probability: float
    conservative_prob_lower: Optional[float]
    conservative_prob_upper: Optional[float]
    confidence_interval: Optional[Tuple[float, float]]
    uncertainty_level: str
    edge_vs_breakeven_pp: float
    edge_vs_fair_pp: float
    expected_value: float
    conservative_ev: Optional[float]
    is_positive_ev: bool
    ev_grade: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_probability": round(self.market_probability, 4),
            "market_fair_probability": round(self.market_fair_probability, 4),
            "model_probability_raw": round(self.model_probability_raw, 4) if self.model_probability_raw is not None else None,
            "model_probability_calibrated": round(self.model_probability_calibrated, 4),
            "consensus_probability": round(self.consensus_probability, 4),
            "conservative_prob_lower": round(self.conservative_prob_lower, 4) if self.conservative_prob_lower is not None else None,
            "conservative_prob_upper": round(self.conservative_prob_upper, 4) if self.conservative_prob_upper is not None else None,
            "confidence_interval": [round(value, 4) for value in self.confidence_interval] if self.confidence_interval is not None else None,
            "uncertainty_level": self.uncertainty_level,
            "edge_vs_breakeven_pp": round(self.edge_vs_breakeven_pp, 2),
            "edge_vs_fair_pp": round(self.edge_vs_fair_pp, 2),
            "expected_value": round(self.expected_value, 4),
            "expected_value_pct": round(self.expected_value * 100.0, 2),
            "conservative_ev": round(self.conservative_ev, 4) if self.conservative_ev is not None else None,
            "is_positive_ev": self.is_positive_ev,
            "ev_grade": self.ev_grade,
            "details": self.details,
        }
