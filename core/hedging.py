#!/usr/bin/env python3
"""Hedging and Arbitrage Lock-in Engine (聽牌對衝與保本鎖利計算引擎).

When a multi-leg parlay has won N-1 legs and only 1 final leg remains pending,
this engine calculates exact opposing hedge stakes to either:
1. BREAKEVEN (保本對衝): Spend minimal hedge stake so if the parlay busts on the last leg,
   net loss is NT$ 0 (zero risk).
2. GUARANTEED_LOCK_IN (100% 絕對對等鎖利): Equalize net profit across all outcomes,
   locking in guaranteed pure profit regardless of the final game result.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


def calculate_hedge(
    ticket_stake: float,
    potential_payout: float,
    opposing_odds: float,
    opposing_selection: str = "反向盤口",
) -> Dict[str, Any]:
    """Calculate breakeven and guaranteed lock-in hedge stakes.

    Args:
        ticket_stake: Initial stake of the parlay ticket (e.g. NT$ 50).
        potential_payout: Total potential return if all legs win (e.g. NT$ 2,500).
        opposing_odds: Odds available for the opposing outcome of the pending leg (e.g. 1.75).
        opposing_selection: Description of the opposing selection (e.g. '客受讓 +3.5').

    Returns:
        Dict containing breakeven and guaranteed lock-in staking recommendations.
    """
    if ticket_stake <= 0:
        raise ValueError("注單本金必須大於 0")
    if potential_payout <= ticket_stake:
        raise ValueError("預期派彩必須大於注單本金才有對衝價值")
    if opposing_odds <= 1.0:
        raise ValueError("反向盤口賠率必須大於 1.0")

    # 1. Breakeven Hedge (保本對衝)
    # Target: H * (opposing_odds - 1) - ticket_stake = 0
    # => H = ticket_stake / (opposing_odds - 1)
    net_odds = opposing_odds - 1.0
    h_breakeven_raw = ticket_stake / net_odds
    # Round to realistic lottery bet increments (multiples of 10 NTD)
    h_breakeven = math.ceil(h_breakeven_raw / 10.0) * 10.0

    # Outcomes for Breakeven
    breakeven_if_parlay_wins = round(potential_payout - (ticket_stake + h_breakeven), 2)
    breakeven_if_hedge_wins = round(h_breakeven * opposing_odds - (ticket_stake + h_breakeven), 2)

    # 2. Guaranteed Lock-in Profit Hedge (100% 絕對鎖利對衝)
    # Target: Net profit if Parlay wins == Net profit if Hedge wins
    # P - S - H = H * O - S - H => P = H * O => H = P / O
    h_guaranteed_raw = potential_payout / opposing_odds
    h_guaranteed = math.ceil(h_guaranteed_raw / 10.0) * 10.0

    guaranteed_total_spent = ticket_stake + h_guaranteed
    guaranteed_if_parlay_wins = round(potential_payout - guaranteed_total_spent, 2)
    guaranteed_if_hedge_wins = round(h_guaranteed * opposing_odds - guaranteed_total_spent, 2)
    guaranteed_profit = min(guaranteed_if_parlay_wins, guaranteed_if_hedge_wins)

    return {
        "opposing_selection": opposing_selection,
        "hedge_odds": opposing_odds,
        "ticket_stake": ticket_stake,
        "potential_payout": potential_payout,
        "breakeven": {
            "stake": h_breakeven,
            "total_spent": ticket_stake + h_breakeven,
            "profit_if_parlay_wins": breakeven_if_parlay_wins,
            "profit_if_hedge_wins": breakeven_if_hedge_wins,
            "desc": f"反買 NT$ {h_breakeven:,.0f}：若最後一關倒了完全不賠 (保本)，若過關仍淨賺 NT$ {breakeven_if_parlay_wins:,.2f}！",
        },
        "guaranteed": {
            "stake": h_guaranteed,
            "total_spent": guaranteed_total_spent,
            "profit_if_parlay_wins": guaranteed_if_parlay_wins,
            "profit_if_hedge_wins": guaranteed_if_hedge_wins,
            "guaranteed_profit": guaranteed_profit,
            "desc": f"反買 NT$ {h_guaranteed:,.0f}：無論最後一場誰贏，100% 絕對穩賺約 NT$ {guaranteed_profit:,.2f}！",
        },
    }
