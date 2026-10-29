#!/usr/bin/env python3
"""Unit tests for Fractional Kelly Staking Engine."""

import pytest
from core.kelly import calculate_kelly_stake


def test_kelly_positive_edge():
    # Win prob 0.60 on odds 2.0 (EV = +20%) with 200 NTD bankroll
    res = calculate_kelly_stake(
        win_probability=0.60,
        decimal_odds=2.0,
        bankroll=200.0,
        min_stake=10.0,
    )
    assert res["has_edge"] is True
    assert res["edge_pct"] == 20.0
    # Full Kelly: (1 * 0.6 - 0.4) / 1 = 0.20
    assert res["full_kelly_fraction"] == 0.20
    # 1/4 Kelly: 0.05 * 200 = 10 NTD
    assert res["quarter_kelly_stake"] == 10.0
    # 1/8 Kelly: 0.025 * 200 = 5 NTD -> min stake is 10 NTD
    assert res["eighth_kelly_stake"] == 10.0
    assert "正期望值" in res["advice"]


def test_kelly_large_bankroll_scaled():
    # Win prob 0.30 on 5.0 odds (EV = 0.3*5 - 1 = +50%) with 1000 NTD bankroll
    res = calculate_kelly_stake(
        win_probability=0.30,
        decimal_odds=5.0,
        bankroll=1000.0,
    )
    assert res["has_edge"] is True
    # b = 4, p = 0.3, q = 0.7 => (4*0.3 - 0.7) / 4 = 0.5 / 4 = 0.125
    assert res["full_kelly_fraction"] == 0.125
    # 1/4 Kelly: 0.03125 * 1000 = 31.25 -> rounded up to 40 NTD
    assert res["quarter_kelly_stake"] == 40.0
    # 1/8 Kelly: 0.015625 * 1000 = 15.625 -> rounded up to 20 NTD
    assert res["eighth_kelly_stake"] == 20.0


def test_kelly_negative_or_zero_edge():
    res = calculate_kelly_stake(
        win_probability=0.40,
        decimal_odds=2.0,  # EV = -20%
        bankroll=200.0,
    )
    assert res["has_edge"] is False
    assert res["full_kelly_fraction"] == 0.0
    assert res["quarter_kelly_stake"] == 0.0


def test_kelly_boundary_odds():
    res1 = calculate_kelly_stake(0.5, 1.0, 200.0)
    assert not res1["has_edge"]
    res2 = calculate_kelly_stake(0.0, 2.0, 200.0)
    assert not res2["has_edge"]
