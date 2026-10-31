#!/usr/bin/env python3
"""Tests for Market Fair Probability and Theoretical EV Engine.

Milestone 3 Verification:
- Tests multiplicative and Shin/Power devigging
- Tests EV formula: EV = P_fair * Taiwan_Odds - 1.0
- Tests multi-book consensus median and dispersion calculation
- Tests fail-closed behavior on missing or invalid odds
- Tests disclaimer and value grade classification
"""

import math
import pytest

from core.market_fair_odds import (
    BookmakerQuote,
    MarketFairOddsEngine,
    devig_two_way_power,
)


def test_devig_two_way_power():
    # Symmetric 50-50 market
    p1, p2, vig = devig_two_way_power(1.91, 1.91)
    assert math.isclose(p1, 0.5, abs_tol=0.01)
    assert math.isclose(p2, 0.5, abs_tol=0.01)
    assert vig > 0.04  # ~4.7% vig

    # Favorite vs Underdog market
    p_fav, p_dog, _ = devig_two_way_power(1.30, 3.60)
    assert p_fav > p_dog
    assert math.isclose(p_fav + p_dog, 1.0, abs_tol=0.01)


def test_market_fair_odds_positive_ev():
    engine = MarketFairOddsEngine()

    # Sharp benchmark: Fair probability ~ 55%
    quotes = [
        BookmakerQuote(book_name="Pinnacle", odds=1.82, opposing_odds=2.10),
        BookmakerQuote(book_name="DraftKings", odds=1.80, opposing_odds=2.05),
    ]

    # Taiwan Lottery offers high price 1.95 on this selection
    result = engine.calculate_fair_odds(taiwan_odds=1.95, benchmark_quotes=quotes)
    assert result is not None
    assert result.is_value_bet is True
    assert result.value_grade in {"MODERATE_VALUE", "STRONG_VALUE"}
    assert result.theoretical_ev > 0.02
    assert "Theoretical EV" in result.risk_disclaimer
    assert result.books_compared == 2


def test_market_fair_odds_negative_ev():
    engine = MarketFairOddsEngine()

    # Sharp benchmark: Fair probability ~ 45%
    quotes = [
        BookmakerQuote(book_name="Pinnacle", odds=2.15, opposing_odds=1.75),
    ]

    # Taiwan Lottery offers low price 1.70
    result = engine.calculate_fair_odds(taiwan_odds=1.70, benchmark_quotes=quotes)
    assert result is not None
    assert result.is_value_bet is False
    assert result.value_grade == "NEGATIVE_EV"
    assert result.theoretical_ev < 0.0


def test_market_fair_odds_fail_closed():
    engine = MarketFairOddsEngine()

    # Invalid taiwan odds <= 1.0
    res1 = engine.calculate_fair_odds(taiwan_odds=0.95, benchmark_quotes=[BookmakerQuote("Pin", 1.90, opposing_odds=1.90)])
    assert res1 is None

    # Empty quotes
    res2 = engine.calculate_fair_odds(taiwan_odds=1.80, benchmark_quotes=[])
    assert res2 is None

    # Missing counterpart/opposing odds MUST fail closed rather than use fixed 0.98 multiplier
    res3 = engine.calculate_fair_odds(taiwan_odds=1.80, benchmark_quotes=[BookmakerQuote("Pin", 1.90, opposing_odds=None)])
    assert res3 is None


def test_market_fair_odds_three_way_complete_and_incomplete():
    engine = MarketFairOddsEngine()

    # 1. Complete 3-way soccer market: Home 2.10, Draw 3.40, Away 3.50
    q_home = BookmakerQuote(
        book_name="Pinnacle",
        odds=2.10,
        opposing_odds=3.50,
        draw_odds=3.40,
        is_three_way=True,
    )
    res_complete = engine.calculate_fair_odds(taiwan_odds=2.25, benchmark_quotes=[q_home])
    assert res_complete is not None
    # 1/2.10 = 0.4762, 1/3.50 = 0.2857, 1/3.40 = 0.2941, sum = 1.0560
    # fair_p = 0.4762 / 1.0560 = ~0.4509
    assert 0.44 < res_complete.market_fair_prob < 0.46
    assert res_complete.theoretical_ev == pytest.approx((res_complete.market_fair_prob * 2.25) - 1.0, abs=1e-4)

    # 2. Incomplete 3-way market: Draw odds missing. MUST NOT fall back to 2-way devigging!
    q_missing_draw = BookmakerQuote(
        book_name="Pinnacle",
        odds=2.10,
        opposing_odds=3.50,
        draw_odds=None,
        is_three_way=True,
    )
    res_incomplete = engine.calculate_fair_odds(taiwan_odds=2.25, benchmark_quotes=[q_missing_draw])
    assert res_incomplete is None

    # 3. Incomplete 3-way market: Opposing odds missing.
    q_missing_away = BookmakerQuote(
        book_name="Pinnacle",
        odds=2.10,
        opposing_odds=None,
        draw_odds=3.40,
        is_three_way=True,
    )
    res_incomplete_away = engine.calculate_fair_odds(taiwan_odds=2.25, benchmark_quotes=[q_missing_away])
    assert res_incomplete_away is None
