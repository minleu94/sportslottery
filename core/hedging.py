#!/usr/bin/env python3
"""Conditional hedge arithmetic for user-supplied opposing prices.

The results assume the entered price is available and accepted, with compatible
market definitions and settlement. This module does not obtain live opposing
odds, verify execution, or guarantee a break-even outcome or profit.
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
    """Calculate conditional scenario stakes for a user-supplied opposing price.

    Args:
        ticket_stake: Initial stake of the parlay ticket (e.g. NT$ 50).
        potential_payout: Total potential return if all legs win (e.g. NT$ 2,500).
        opposing_odds: Odds available for the opposing outcome of the pending leg (e.g. 1.75).
        opposing_selection: Description of the opposing selection (e.g. '客受讓 +3.5').

    Returns:
        Dict containing arithmetic scenarios. These are not execution guarantees.
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
            "desc": f"假設反向價格 {opposing_odds:.2f} 可成交，反買 NT$ {h_breakeven:,.0f}：最後一關反向命中試算 {breakeven_if_hedge_wins:+,.2f} 元，原串關全過試算 {breakeven_if_parlay_wins:+,.2f} 元。",
        },
        "guaranteed": {
            "stake": h_guaranteed,
            "total_spent": guaranteed_total_spent,
            "profit_if_parlay_wins": guaranteed_if_parlay_wins,
            "profit_if_hedge_wins": guaranteed_if_hedge_wins,
            "guaranteed_profit": guaranteed_profit,
            "desc": f"假設反向價格 {opposing_odds:.2f} 可成交，反買 NT$ {h_guaranteed:,.0f}：兩結果淨額相同的條件式試算約 NT$ {guaranteed_profit:,.2f}；不保證成交或獲利。",
        },
    }
