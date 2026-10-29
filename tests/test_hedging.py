#!/usr/bin/env python3
"""Unit tests for Hedging & Arbitrage Lock-in Engine."""

import pytest
from core.hedging import calculate_hedge


def test_calculate_hedge_basic():
    # Ticket: stake 50 NTD, potential payout 2500 NTD (50x parlay)
    # Opposing odds: 1.75
    res = calculate_hedge(
        ticket_stake=50.0,
        potential_payout=2500.0,
        opposing_odds=1.75,
        opposing_selection="客受讓 +3.5",
    )

    assert res["opposing_selection"] == "客受讓 +3.5"
    assert res["hedge_odds"] == 1.75

    # Breakeven:
    # 50 / (1.75 - 1) = 66.67 => rounded up to 70
    assert res["breakeven"]["stake"] == 70.0
    assert res["breakeven"]["total_spent"] == 120.0
    assert res["breakeven"]["profit_if_hedge_wins"] >= 0.0  # 70 * 1.75 - 120 = 2.5
    assert res["breakeven"]["profit_if_parlay_wins"] > 2300.0

    # Guaranteed lock-in:
    # 2500 / 1.75 = 1428.57 => rounded up to 1430
    assert res["guaranteed"]["stake"] == 1430.0
    assert res["guaranteed"]["total_spent"] == 1480.0
    assert res["guaranteed"]["profit_if_parlay_wins"] > 1000.0
    assert res["guaranteed"]["profit_if_hedge_wins"] > 1000.0
    assert res["guaranteed"]["guaranteed_profit"] > 1000.0


def test_calculate_hedge_validation_errors():
    with pytest.raises(ValueError, match="注單本金必須大於 0"):
        calculate_hedge(0, 100, 1.8)

    with pytest.raises(ValueError, match="預期派彩必須大於注單本金"):
        calculate_hedge(100, 50, 1.8)

    with pytest.raises(ValueError, match="反向盤口賠率必須大於 1.0"):
        calculate_hedge(50, 200, 0.9)
