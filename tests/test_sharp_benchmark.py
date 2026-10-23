#!/usr/bin/env python3
"""Unit tests for Sharp Market Benchmark and Sharp Edge Engine."""

from datetime import datetime, timezone
import pytest

from integrations.common.models import TaiwanLeg, PredictionSignal
from integrations.odds.sharp_benchmark_odds import SharpBenchmarkOddsAdapter, SharpComparisonResult
from core.sharp_edge_engine import SharpEdgeEngine


def create_sample_leg(
    sport="baseball",
    league="MLB",
    event_id="MLB_2026_001",
    market="不讓分",
    selection="主",
    side="主",
    taiwan_odds=2.10,
    market_outcome_odds=None,
):
    now = datetime.now(timezone.utc).isoformat()
    evidence = {}
    if market_outcome_odds is not None:
        evidence["market_outcome_odds"] = market_outcome_odds

    return TaiwanLeg(
        event_id=event_id,
        sport=sport,
        league=league,
        home_team="紅襪",
        away_team="洋基",
        market=market,
        selection=selection,
        side=side,
        taiwan_odds=taiwan_odds,
        start_time_utc=now,
        odds_scraped_at=now,
        odds_status="LIVE",
        signal_evidence=evidence,
    )


def test_sharp_benchmark_devig_two_way():
    adapter = SharpBenchmarkOddsAdapter()
    # Taiwan odds: 2.10 vs 1.70. Sharp de-vig fair prob
    comp = adapter.get_sharp_fair_odds(
        sport="baseball",
        league="MLB",
        event_id="MLB_001",
        market="不讓分",
        selection="主",
        taiwan_odds=2.10,
        opposing_odds=1.70,
    )
    assert comp is not None
    assert isinstance(comp, SharpComparisonResult)
    assert 0.0 < comp.sharp_fair_prob < 1.0
    assert comp.taiwan_implied_prob == pytest.approx(1.0 / 2.10, rel=1e-3)
    # Expected value = (sharp_fair_prob * 2.10) - 1.0
    expected_ev = (comp.sharp_fair_prob * 2.10) - 1.0
    assert comp.expected_value == pytest.approx(expected_ev, rel=1e-3)
    assert comp.expected_value_pct == pytest.approx(expected_ev * 100.0, rel=1e-3)


def test_sharp_benchmark_devig_three_way():
    adapter = SharpBenchmarkOddsAdapter()
    # Soccer 3-way: Home 2.80, Draw 3.20, Away 2.30
    comp = adapter.get_sharp_fair_odds(
        sport="soccer",
        league="EPL",
        event_id="EPL_001",
        market="不讓分",
        selection="主",
        taiwan_odds=2.80,
        opposing_odds=2.30,
        draw_odds=3.20,
    )
    assert comp is not None
    assert 0.0 < comp.sharp_fair_prob < 1.0
    assert comp.value_grade in {"STRONG_VALUE", "MODERATE_VALUE", "FAIR_VALUE", "NEGATIVE_EV"}


def test_sharp_benchmark_evaluate_leg_generates_signal():
    adapter = SharpBenchmarkOddsAdapter()
    leg = create_sample_leg(
        taiwan_odds=2.10,
        market_outcome_odds={"主": "2.10", "客": "1.70"}
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert isinstance(sig, PredictionSignal)
    assert sig.source_category == "SHARP_MARKET_BENCHMARK"
    assert sig.independence_group == "SHARP_CONSENSUS"
    assert "sharp_fair_probability" in sig.metadata
    assert "expected_value_pct" in sig.metadata
    assert sig.freshness_status == "LIVE"


def test_sharp_edge_engine_single_leg():
    engine = SharpEdgeEngine()
    # Test leg with favorable odds
    leg = create_sample_leg(
        taiwan_odds=2.20,
        market_outcome_odds={"主": "2.20", "客": "1.65"}
    )
    res = engine.evaluate_leg_sharp_edge(leg)
    assert res is not None
    assert res.taiwan_odds == 2.20
    assert res.sharp_fair_prob > 0.0


def test_sharp_edge_engine_parlay_ev_and_badges():
    engine = SharpEdgeEngine()
    leg1 = create_sample_leg(
        event_id="E1",
        taiwan_odds=2.00,
        market_outcome_odds={"主": "2.00", "客": "1.75"}
    )
    leg2 = create_sample_leg(
        event_id="E2",
        taiwan_odds=2.10,
        market_outcome_odds={"主": "2.10", "客": "1.68"}
    )

    # Multi-leg combo evaluation
    parlay_res = engine.evaluate_parlay_sharp_ev(
        legs=[leg1, leg2],
        total_odds=4.20,
        correlation_penalty=0.05,
    )

    assert parlay_res["has_sharp_benchmark"] is True
    assert parlay_res["sharp_joint_probability"] > 0
    assert "sharp_parlay_ev" in parlay_res
    assert "sharp_parlay_ev_pct" in parlay_res
    assert "summary_badge" in parlay_res
    assert parlay_res["total_legs"] == 2


def test_sharp_edge_engine_empty_legs():
    engine = SharpEdgeEngine()
    empty_res = engine.evaluate_parlay_sharp_ev([], 1.0)
    assert empty_res["has_sharp_benchmark"] is False
    assert empty_res["sharp_parlay_ev"] == -1.0
