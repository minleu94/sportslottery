#!/usr/bin/env python3
"""Unit tests for Banker Mode (穩健銀行家模式 - 低賠率高勝率串關)."""

from datetime import datetime, timedelta, timezone
import pytest

from core.parlay_engine import ParlayEngine
from integrations.common.models import TaiwanLeg


def create_leg(event_id, away, home, selection, odds, fair_prob=0.70):
    now = datetime.now(timezone.utc)
    return TaiwanLeg(
        event_id=event_id,
        canonical_event_id=f"canonical-{event_id}",
        sport="baseball",
        league="MLB",
        home_team=home,
        away_team=away,
        market="不讓分",
        selection=selection,
        side="主",
        taiwan_odds=odds,
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
        odds_scraped_at=now.isoformat(),
        odds_status="FRESH",
        evidence_quality="HIGH",
        signal_evidence={
            "agreement": "HIGH",
            "agreement_badge": "🟢 HIGH",
            "evidence_quality": "HIGH",
            "independent_support_count": 3,
            "market_implied_probability": 1.0 / odds,
            "market_fair_probability": fair_prob,
            "sharp_fair_probability": fair_prob,
            "sharp_expected_value_pct": round((fair_prob * odds - 1.0) * 100, 2),
            "is_sharp_value_bet": True,
            "consensus_probability": fair_prob,
            "non_market_supports": 2,
        },
    )


def test_banker_mode_2_leg_search():
    engine = ParlayEngine()
    leg1 = create_leg("E1", "洋基", "紅襪", "紅襪", 1.55, fair_prob=0.72)
    leg2 = create_leg("E2", "道奇", "巨人", "巨人", 1.60, fair_prob=0.70)
    leg3 = create_leg("E3", "勇士", "大都會", "大都會", 1.50, fair_prob=0.75)

    legs = [leg1, leg2, leg3]

    # Search in banker mode: 1.5x ~ 4.0x, min_legs=2, max_legs=3
    diagnostics = {}
    res = engine.search_parlays(
        legs=legs,
        min_odds=1.5,
        max_odds=4.0,
        min_legs=2,
        max_legs=3,
        diagnostics=diagnostics,
        search_budget=10000,
    )

    high_c = res["high_consensus"]
    assert len(high_c) > 0

    for combo in high_c:
        assert 2 <= len(combo["legs"]) <= 3
        assert 1.5 <= combo["total_odds"] <= 4.0
        # Joint probability should be high (> 20%)
        assert combo["joint_probability"] > 0.20
        # Total odds between 1.5 and 4.0
        assert combo["total_odds"] >= 1.5
        assert combo["total_odds"] <= 4.0


def test_banker_mode_bounds_enforcement():
    engine = ParlayEngine()
    leg1 = create_leg("E1", "A", "B", "B", 1.50, fair_prob=0.70)
    leg2 = create_leg("E2", "C", "D", "D", 1.50, fair_prob=0.70)
    leg3 = create_leg("E3", "E", "F", "F", 5.00, fair_prob=0.25)

    legs = [leg1, leg2, leg3]

    # Target 2.25x (1.5 * 1.5), max_odds 3.0
    res = engine.search_parlays(
        legs=legs,
        min_odds=1.5,
        max_odds=3.0,
        min_legs=2,
        max_legs=2,
        search_budget=5000,
    )

    high_c = res["high_consensus"]
    assert len(high_c) == 1
    combo = high_c[0]
    assert combo["total_odds"] == pytest.approx(2.25, rel=1e-3)
    assert len(combo["legs"]) == 2
