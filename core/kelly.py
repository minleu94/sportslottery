#!/usr/bin/env python3
"""Fractional Kelly Staking Engine (分數型凱利注碼建議引擎).

Calculates mathematically grounded, variance-controlled betting allocations:
1. Full Kelly: f* = (b*p - q) / b
2. Quarter Kelly (1/4 凱利): Recommended standard for +EV parlays (75% variance reduction).
3. Eighth Kelly (1/8 凱利): Recommended for high-odds / longshot parlays (87.5% variance reduction).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


def calculate_kelly_stake(
    win_probability: float,
    decimal_odds: float,
    bankroll: float,
    min_stake: float = 10.0,
    max_stake: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate fractional Kelly betting stakes.

    Args:
        win_probability: Estimated win probability (0.0 to 1.0).
        decimal_odds: Taiwan lottery payout odds (e.g. 2.10, 15.0).
        bankroll: Current available bankroll / weekly wallet balance.
        min_stake: Minimum bet size allowed by Taiwan lottery (default NT$ 10).
        max_stake: Maximum single bet cap (defaults to current bankroll).

    Returns:
        Dict with edge, full Kelly fraction, quarter-Kelly stake, eighth-Kelly stake,
        and human-readable advice.
    """
    if win_probability <= 0.0 or win_probability >= 1.0:
        return {
            "has_edge": False,
            "edge_pct": 0.0,
            "full_kelly_fraction": 0.0,
            "quarter_kelly_stake": 0.0,
            "eighth_kelly_stake": 0.0,
            "advice": "無有效預估勝率",
        }

    if decimal_odds <= 1.0:
        return {
            "has_edge": False,
            "edge_pct": 0.0,
            "full_kelly_fraction": 0.0,
            "quarter_kelly_stake": 0.0,
            "eighth_kelly_stake": 0.0,
            "advice": "賠率過低無投注價值",
        }

    bankroll = max(0.0, float(bankroll))
    eff_max_stake = max_stake if max_stake is not None else bankroll

    b = decimal_odds - 1.0
    p = win_probability
    q = 1.0 - p

    # Expected Value (Edge %) = (p * decimal_odds - 1.0)
    expected_value = (p * decimal_odds) - 1.0
    edge_pct = round(expected_value * 100.0, 2)

    if expected_value <= 0:
        return {
            "has_edge": False,
            "edge_pct": edge_pct,
            "full_kelly_fraction": 0.0,
            "quarter_kelly_stake": 0.0,
            "eighth_kelly_stake": 0.0,
            "advice": f"期望值為負 ({edge_pct:+.1f}%)，凱利公式建議觀望或下注基本最低注 NT$ {min_stake:.0f}。",
        }

    # Full Kelly fraction f*
    full_fraction = (b * p - q) / b
    quarter_fraction = full_fraction * 0.25
    eighth_fraction = full_fraction * 0.125

    # Helper to round stake to multiples of 10 NTD within bounds
    def _to_stake(frac: float) -> float:
        if bankroll <= 0:
            return 0.0
        raw_val = frac * bankroll
        if raw_val < min_stake:
            return min(min_stake, eff_max_stake)
        rounded = math.ceil(raw_val / 10.0) * 10.0
        return min(rounded, eff_max_stake)

    quarter_stake = _to_stake(quarter_fraction)
    eighth_stake = _to_stake(eighth_fraction)

    advice = (
        f"🔥 具備正期望值 (+{edge_pct:.1f}%)！"
        f"建議注碼：1/4 凱利 NT$ {quarter_stake:,.0f} (標準進攻) / "
        f"1/8 凱利 NT$ {eighth_stake:,.0f} (防禦抗震)"
    )

    return {
        "has_edge": True,
        "edge_pct": edge_pct,
        "full_kelly_fraction": round(full_fraction, 4),
        "quarter_kelly_fraction": round(quarter_fraction, 4),
        "eighth_kelly_fraction": round(eighth_fraction, 4),
        "quarter_kelly_stake": quarter_stake,
        "eighth_kelly_stake": eighth_stake,
        "advice": advice,
    }
