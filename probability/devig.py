#!/usr/bin/env python3
"""De-vigging models to extract Market Fair Probability from bookmaker odds.

De-vigging methods remove the bookmaker's overround (juice/vig) to calculate
the fair implied probability according to the market pricing.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple


def calculate_implied_prob(odds: float) -> float:
    """Calculate raw implied probability q = 1 / odds."""
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def devig_multiplicative(odds_list: List[float]) -> Tuple[List[float], float]:
    """Remove overround using standard proportional (multiplicative) normalization.

    Returns:
        (fair_probs, overround_percentage)
    """
    if not odds_list:
        return [], 0.0

    implied_probs = [calculate_implied_prob(o) for o in odds_list]
    total_implied = sum(implied_probs)

    if total_implied <= 0:
        equal_p = 1.0 / len(odds_list)
        return [equal_p] * len(odds_list), 0.0

    overround = total_implied - 1.0
    fair_probs = [q / total_implied for q in implied_probs]

    return fair_probs, overround


def devig_two_way(odds_a: float, odds_b: float) -> Tuple[float, float, float]:
    """De-vig a 2-way binary market (e.g. Spread, Over/Under, Tennis).

    Returns:
        (fair_prob_a, fair_prob_b, vig_margin)
    """
    probs, vig = devig_multiplicative([odds_a, odds_b])
    return probs[0], probs[1], vig


def devig_three_way(odds_home: float, odds_draw: float, odds_away: float) -> Tuple[float, float, float, float]:
    """De-vig a 3-way market (e.g. Soccer 1X2).

    Returns:
        (fair_home, fair_draw, fair_away, vig_margin)
    """
    probs, vig = devig_multiplicative([odds_home, odds_draw, odds_away])
    return probs[0], probs[1], probs[2], vig
