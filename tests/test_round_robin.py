#!/usr/bin/env python3
"""Unit tests for Taiwan Sports Lottery Round Robin Engine (過關組合 / 輪串)."""

import pytest

from core.round_robin import ROUND_ROBIN_SPECS, RoundRobinEngine


def test_supported_combinations():
    combos_3 = RoundRobinEngine.get_supported_combinations(3)
    assert "3_3" in combos_3
    assert "3_4" in combos_3
    assert "3_7" in combos_3

    combos_4 = RoundRobinEngine.get_supported_combinations(4)
    assert "4_5" in combos_4
    assert "4_11" in combos_4
    assert "4_15" in combos_4

    combos_6 = RoundRobinEngine.get_supported_combinations(6)
    assert "6_7" in combos_6
    assert "6_57" in combos_6


def test_generate_sub_bets_4_legs_4_in_5():
    legs = [
        {"selection": "隊A", "odds": 1.80},
        {"selection": "隊B", "odds": 1.80},
        {"selection": "隊C", "odds": 1.80},
        {"selection": "隊D", "odds": 1.80},
    ]
    # 4串5: sub_sizes = [3, 4] -> C(4,3)=4, C(4,4)=1 -> 5 sub-bets total
    sub_bets = RoundRobinEngine.generate_sub_bets(legs, [3, 4])
    assert len(sub_bets) == 5

    combo_3_bets = [b for b in sub_bets if b["combo_k"] == 3]
    combo_4_bets = [b for b in sub_bets if b["combo_k"] == 4]
    assert len(combo_3_bets) == 4
    assert len(combo_4_bets) == 1
    assert round(combo_3_bets[0]["odds"], 3) == round(1.80**3, 3)
    assert round(combo_4_bets[0]["odds"], 3) == round(1.80**4, 3)


def test_simulate_resilience_4_in_5_guaranteed_profit():
    # 4 legs each with 1.85 odds
    legs = [
        {"selection": "LAD", "odds": 1.85},
        {"selection": "BOS", "odds": 1.85},
        {"selection": "NYY", "odds": 1.85},
        {"selection": "HOU", "odds": 1.85},
    ]

    res = RoundRobinEngine.simulate_resilience(legs, "4_5", unit_stake=10.0)
    assert res["total_combinations"] == 5
    assert res["total_stake"] == 50.0

    # If all win: 4 * (1.85^3 * 10) + (1.85^4 * 10) = 4 * 63.316 + 117.135 = 253.26 + 117.14 = 370.40
    assert res["all_win"]["payout"] > 350.0
    assert res["all_win"]["profit"] > 300.0

    # If any 1 leg misses: exactly one 3-leg parlay survives: 1.85^3 * 10 = 63.32
    # 63.32 > 50.0, so profit is +13.32 even with 1 loss!
    assert res["one_miss"]["is_guaranteed_breakeven"] is True
    assert res["one_miss"]["min_payout"] > 50.0
    assert res["one_miss"]["min_profit"] > 0.0
    assert res["grade"] == "SHIELD_PROFIT"
    assert "🟢 完美防倒" in res["grade_badge"]
    assert len(res["one_miss"]["scenarios"]) == 4


def test_simulate_resilience_invalid_combo():
    legs = [{"selection": "A", "odds": 1.80}, {"selection": "B", "odds": 1.80}]
    with pytest.raises(ValueError, match="不支援 2 場的過關組合代碼"):
        RoundRobinEngine.simulate_resilience(legs, "4_5")
