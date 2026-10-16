#!/usr/bin/env python3
"""Reality Verification Test Suite (Anti-Fake & Evidence Integrity).

Verifies the system's commitment to authentic external evidence:
1. test_no_fake_expert_assignment: Crowd consensus never fabricates an expert pick.
2. test_model_does_not_use_taiwan_odds: Models compute win expectations strictly from team stats, not odds.
3. test_no_fake_market_fallback_in_production: Scraper never invents fake matches when offline/empty.
4. test_event_identity_alignment: Canonical identity resolves multi-lingual aliases and matches events.
5. test_moonshot_ranking_prefers_evidence: High odds combinations rank evidence quality ahead of raw multiplier.
6. test_market_odds_does_not_self_vote: Market baseline odds never count as a supporting confirmation vote.
"""

import tempfile
from datetime import datetime, timedelta, timezone
import pytest

from core.identity import GLOBAL_TEAM_REGISTRY, GLOBAL_EVENT_MATCHER
from core.parlay_engine import ParlayEngine
from core.scraper import PlaysportScraper
from core.signal_hub import SignalHub
from integrations.common.models import TaiwanLeg, PredictionSignal
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.models.pybaseball_mlb_model import PybaseballMLBAdapter
from integrations.models.penaltyblog_soccer_model import PenaltyblogSoccerAdapter


def _fresh_fixture_clock():
    now = datetime.now(timezone.utc)
    return {
        "start_time_utc": (now + timedelta(hours=2)).isoformat(),
        "odds_scraped_at": (now - timedelta(minutes=1)).isoformat(),
        "odds_status": "FRESH",
        "odds_age_minutes": 1.0,
    }


def test_no_fake_expert_assignment():
    """Verify that an option with high crowd and favorite odds does NOT get assigned a fake expert."""
    adapter = PlaysportExpertAdapter()

    # Match that is NOT picked by any expert on the leaderboard
    leg = TaiwanLeg(
        event_id="unpicked_event",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="運動家 客勝",
        taiwan_odds=1.40,
        start_time="10:00",
        away_team="運動家",
        home_team="守護者",
        side="客",
        signal_evidence={"consensus_ratio": 0.88, "vote_count": 500},
    )

    # In reality, the top expert picked 主 -1.5 (Guardians), NOT Athletics away ML!
    sig = adapter.get_expert_signal(leg)
    assert sig is None, "Fake expert signal was erroneously generated from crowd/odds!"


def test_model_does_not_use_taiwan_odds():
    """Verify that PybaseballMLBAdapter calculates probabilities purely from team stats, not odds."""
    adapter = PybaseballMLBAdapter()

    leg_fav = TaiwanLeg(
        event_id="116",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="釀酒人 客勝",
        taiwan_odds=1.20,  # Extreme favorite odds
        start_time="AM 12:35",
        away_team="釀酒人",
        home_team="海盜",
        side="客",
    )

    leg_dog = TaiwanLeg(
        event_id="116",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="釀酒人 客勝",
        taiwan_odds=5.50,  # Extreme underdog odds
        start_time="AM 12:35",
        away_team="釀酒人",
        home_team="海盜",
        side="客",
    )

    sig_fav = adapter.evaluate_leg(leg_fav)
    sig_dog = adapter.evaluate_leg(leg_dog)

    if sig_fav is not None and sig_dog is not None:
        # Probability MUST be independent of Taiwan Lottery odds!
        assert sig_fav.probability == sig_dog.probability
        assert sig_fav.metadata["projected_away_runs"] == sig_dog.metadata["projected_away_runs"]
        assert sig_fav.metadata["projected_home_runs"] == sig_dog.metadata["projected_home_runs"]


def test_no_fake_market_fallback_in_production():
    """Verify that scraper returns empty list and never generates fake matches when data is unavailable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        scraper = PlaysportScraper(cache_dir=tmpdir)
        # Simulate network failure on empty cache
        import requests
        class FailingSession:
            headers = {}
            def get(self, *args, **kwargs):
                raise requests.RequestException("Connection error")
        scraper.session = FailingSession()
        matches = scraper.fetch_scale_matches(alliance_id="1")
        assert matches == [], "Production scraper must return empty list, not fake matches!"


def test_event_identity_alignment():
    """Verify multi-lingual team alias resolution and canonical identity."""
    # MLB
    yankees_zh = GLOBAL_TEAM_REGISTRY.resolve("洋基", sport="baseball", league="MLB")
    yankees_en = GLOBAL_TEAM_REGISTRY.resolve("New York Yankees", sport="baseball", league="MLB")
    yankees_abbr = GLOBAL_TEAM_REGISTRY.resolve("NYY", sport="baseball", league="MLB")

    assert yankees_zh is not None
    assert yankees_en is not None
    assert yankees_abbr is not None
    assert yankees_zh.canonical_id == yankees_en.canonical_id == yankees_abbr.canonical_id == "MLB_NYY"

    # Soccer
    arsenal_zh = GLOBAL_TEAM_REGISTRY.resolve("兵工廠", sport="soccer")
    arsenal_en = GLOBAL_TEAM_REGISTRY.resolve("Arsenal", sport="soccer")
    assert arsenal_zh is not None
    assert arsenal_en is not None
    assert arsenal_zh.canonical_id == arsenal_en.canonical_id == "SOC_ARS"

    # Event matching
    ev1 = GLOBAL_EVENT_MATCHER.match_or_create(
        sport="baseball",
        league="MLB",
        away_name="小熊",
        home_name="紅人",
        start_time_utc="2026-09-19T00:00:00Z",
        taiwan_event_id="101",
    )
    ev2 = GLOBAL_EVENT_MATCHER.match_or_create(
        sport="baseball",
        league="MLB",
        away_name="Chicago Cubs",
        home_name="Cincinnati Reds",
        start_time_utc="2026-09-19T00:30:00Z",
    )
    assert ev1.canonical_event_id == ev2.canonical_event_id


def test_moonshot_ranking_prefers_evidence():
    """Verify that Moonshot parlays prioritize evidence quality over blind high multiplier."""
    engine = ParlayEngine()

    # Leg A: High evidence quality
    leg_a = TaiwanLeg(
        event_id="E1",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="A勝",
        taiwan_odds=5.0,
        **_fresh_fixture_clock(),
        start_time="10:00",
        away_team="隊伍A",
        home_team="隊伍B",
        side="客",
    )
    leg_a.evidence_quality = "HIGH"
    leg_a.signal_evidence = {"agreement": "HIGH", "evidence_quality": "HIGH", "non_market_supports": 2, "supporting_groups": ["fixed-model-A", "fixed-human-A"], "agreement_emoji": "🟢", "source_url": "https://fixture.invalid/a"}

    leg_b = TaiwanLeg(
        event_id="E2",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="B勝",
        taiwan_odds=8.0,
        **_fresh_fixture_clock(),
        start_time="10:00",
        away_team="隊伍C",
        home_team="隊伍D",
        side="客",
    )
    leg_b.evidence_quality = "HIGH"
    leg_b.signal_evidence = {"agreement": "HIGH", "evidence_quality": "HIGH", "non_market_supports": 2, "supporting_groups": ["fixed-model-B", "fixed-human-B"], "agreement_emoji": "🟢", "source_url": "https://fixture.invalid/b"}

    # Leg C: Insufficient signal (blind longshot)
    leg_c = TaiwanLeg(
        event_id="E3",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="C勝",
        taiwan_odds=15.0,
        **_fresh_fixture_clock(),
        start_time="10:00",
        away_team="隊伍E",
        home_team="隊伍F",
        side="客",
    )
    leg_c.evidence_quality = "INSUFFICIENT_SIGNAL"
    leg_c.signal_evidence = {"agreement": "INSUFFICIENT_SIGNAL", "evidence_quality": "INSUFFICIENT_SIGNAL", "non_market_supports": 0, "agreement_emoji": "⚪"}

    leg_d = TaiwanLeg(
        event_id="E4",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="D勝",
        taiwan_odds=18.0,
        **_fresh_fixture_clock(),
        start_time="10:00",
        away_team="隊伍G",
        home_team="隊伍H",
        side="客",
    )
    leg_d.evidence_quality = "INSUFFICIENT_SIGNAL"
    leg_d.signal_evidence = {"agreement": "INSUFFICIENT_SIGNAL", "evidence_quality": "INSUFFICIENT_SIGNAL", "non_market_supports": 0, "agreement_emoji": "⚪"}

    # Run parlay search with wild mode
    results = engine.search_parlays(
        legs=[leg_a, leg_b, leg_c, leg_d],
        min_odds=20.0,
        max_odds=500.0,
        signal_filter="wild",
    )

    moonshot_list = results["moonshot"]
    assert len(moonshot_list) >= 2

    # Combo (leg_a, leg_b) has odds 40.0 with min_score=3 (HIGH).
    # Combo (leg_c, leg_d) has odds 270.0 with min_score=0 (INSUFFICIENT).
    # The combo with higher evidence quality MUST be ranked first!
    first_combo = moonshot_list[0]
    assert first_combo["min_evidence_score"] >= 2, "Moonshot ranking must prioritize evidence quality over raw odds!"


def test_market_odds_does_not_self_vote():
    """Verify that market baseline odds NEVER cast a confirmation vote for itself."""
    hub = SignalHub()

    leg = TaiwanLeg(
        event_id="test_market_only",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="強隊勝",
        taiwan_odds=1.35,  # Strong market favorite
        start_time="10:00",
        away_team="強隊",
        home_team="弱隊",
        side="客",
        signal_evidence={},  # No crowd votes
    )

    evaluated = hub.evaluate_taiwan_leg(leg)
    # Market odds alone must result in INSUFFICIENT_SIGNAL with 0 non-market supports!
    assert evaluated.evidence_quality == "INSUFFICIENT_SIGNAL"
    assert evaluated.signal_evidence["support_count"] == 0
    assert evaluated.signal_evidence["has_verified_expert"] is False
    assert evaluated.signal_evidence["has_crowd_support"] is False
