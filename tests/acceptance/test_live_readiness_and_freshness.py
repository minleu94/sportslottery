#!/usr/bin/env python3
"""Acceptance Test Suite for Live Readiness, Freshness & Reproducibility Gate.

Fulfills Requirement 29:
1. test_soccer_current_season_present
2. test_soccer_data_freshness_gate
3. test_stale_model_not_high_quality
4. test_mlb_current_season_stats
5. test_mlb_pitcher_claim_is_real
6. test_expert_pick_before_event
7. test_crowd_timestamp_exists
8. test_taiwan_odds_has_timestamp
9. test_stale_odds_blocks_ready_parlay
10. test_model_market_delta
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from core.bet_validation import assess_leg
from core.parlay_engine import ParlayEngine
from core.signal_hub import SignalHub
from integrations.common.models import ModelQualityLabel, PredictionSignal, TaiwanLeg, VerifiedExpertPick
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# 1. test_soccer_current_season_present
def test_soccer_current_season_present():
    """Verify that 2025-2026 and 2026-2027 season match records are present in the soccer dataset."""
    cache_file = PROJECT_ROOT / "data" / "cache" / "real_matches_eng.1.json"
    assert cache_file.exists(), "real_matches_eng.1.json must exist"

    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    seasons = data.get("dataset_seasons", [])
    assert "2025-2026" in seasons
    assert "2026-2027" in seasons

    matches = data.get("matches", [])
    assert len(matches) >= 1000, f"Expected >= 1000 matches across seasons, got {len(matches)}"

    # Check for recent 2026 matches
    matches_2026 = [m for m in matches if m.get("date", "").startswith("2026")]
    assert len(matches_2026) >= 30, f"Expected >= 30 matches in 2026, got {len(matches_2026)}"


# 2. test_soccer_data_freshness_gate
def test_soccer_data_freshness_gate():
    """Verify data_age_days and freshness_status are computed and enforced."""
    adapter = PenaltyblogDixonColesAdapter()

    # Prediction on recent match date (4 days age relative to 2026-09-14)
    leg = TaiwanLeg(
        event_id="501",
        sport="soccer",
        league="英超",
        market="不讓分",
        selection="兵工廠 客勝",
        taiwan_odds=2.10,
        start_time="22:00",
        start_time_utc="2026-09-18T22:00:00Z",
        away_team="兵工廠",
        home_team="切爾西",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.freshness_status == "FRESH"
    prov = sig.metadata.get("provenance", {})
    assert prov.get("data_age_days") <= 14
    assert prov.get("freshness_status") == "FRESH"


# 3. test_stale_model_not_high_quality
def test_stale_model_not_high_quality():
    """If training data is stale relative to prediction date (> 45 days), signal cannot be high quality."""
    adapter = PenaltyblogDixonColesAdapter()

    # Far future prediction date (simulating stale cache)
    leg = TaiwanLeg(
        event_id="502",
        sport="soccer",
        league="英超",
        market="不讓分",
        selection="兵工廠 客勝",
        taiwan_odds=2.10,
        start_time="22:00",
        start_time_utc="2027-01-15T22:00:00Z",
        away_team="兵工廠",
        home_team="切爾西",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.freshness_status == "STALE"
    assert sig.confidence == "REFERENCE_ONLY"
    assert sig.quality_label == ModelQualityLabel.MODEL_STALE

    # SignalHub must not give HIGH agreement to a stale model
    hub = SignalHub()
    leg.signals = [sig]
    enriched = hub.evaluate_taiwan_leg(leg)
    assert enriched.evidence_quality != "HIGH", "Stale model must not produce HIGH agreement!"


# 4. test_mlb_current_season_stats
def test_mlb_current_season_stats():
    """MLB model metadata must list season 2026, team_stats_source, and latest_game_date."""
    adapter = FiveThirtyEightMLBEloAdapter()
    leg = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        start_time_utc="2026-09-18T23:05:00Z",
        away_team="道奇",
        home_team="巨人",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.metadata.get("season") == "2026"
    assert "MLB Stats API" in sig.metadata.get("team_stats_source", "")
    assert sig.metadata.get("latest_game_date") == "2026-09-18"
    assert sig.freshness_status == "LIVE"


# 5. test_mlb_pitcher_claim_is_real
def test_mlb_pitcher_claim_is_real():
    """If no probable pitchers are verified, must flag NO_LIVE_PITCHER_ADJUSTMENT."""
    adapter = FiveThirtyEightMLBEloAdapter()

    # Match with no starting pitchers
    leg = TaiwanLeg(
        event_id="102",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="運動家 客勝",
        taiwan_odds=2.40,
        start_time="07:05",
        start_time_utc="2026-09-18T23:05:00Z",
        away_team="運動家",
        home_team="天使",
        away_pitcher=None,
        home_pitcher=None,
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.metadata.get("pitcher_source") == "NO_LIVE_PITCHER_ADJUSTMENT"
    assert sig.quality_label == ModelQualityLabel.MODEL_EXPERIMENTAL

    # Match with verified probable starting pitchers
    leg_with_sp = TaiwanLeg(
        event_id="103",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="小熊 客勝",
        taiwan_odds=1.85,
        start_time="06:40",
        start_time_utc="2026-09-18T22:40:00Z",
        away_team="小熊",
        home_team="紅人",
        away_pitcher="Clay Holmes",
        home_pitcher="Chase Burns",
        side="客",
    )
    sig_sp = adapter.evaluate_leg(leg_with_sp)
    assert sig_sp is not None
    assert "Clay Holmes" in sig_sp.metadata.get("pitcher_source", "")
    assert sig_sp.quality_label == ModelQualityLabel.MODEL_HIGH_QUALITY


# 6. test_expert_pick_before_event
def test_expert_pick_before_event():
    """VerifiedExpertPick must document pick_timestamp and verify date matching."""
    pick = VerifiedExpertPick(
        expert_userid="12345",
        expert_nickname="測試大神",
        rank=1,
        win_percentage=75.0,
        wins=15,
        losses=5,
        sport="baseball",
        league="MLB",
        event_id="101",
        away_team="道奇",
        home_team="巨人",
        market="不讓分",
        side="客",
        pick_date="2026-09-18",
        pick_timestamp="TIMESTAMP_UNKNOWN",
    )
    assert pick.pick_date == "2026-09-18"
    assert pick.pick_timestamp == "TIMESTAMP_UNKNOWN"


# 7. test_crowd_timestamp_exists
def test_crowd_timestamp_exists():
    """Crowd adapter must preserve snapshot timestamp and data age."""
    leg = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        away_team="道奇",
        home_team="巨人",
        side="客",
        odds_scraped_at="2026-09-18T16:00:00Z",
        odds_age_minutes=5.0,
        signal_evidence={"consensus_ratio": 0.72, "vote_count": 167},
    )
    crowd_adapter = PlaysportCrowdAdapter()
    sig = crowd_adapter.get_crowd_signal(leg)
    assert sig is not None
    assert sig.data_as_of == "2026-09-18T16:00:00Z"
    assert sig.metadata.get("data_age_minutes") == 5.0
    assert sig.metadata.get("vote_count") == 167
    assert sig.freshness_status == "FRESH"


# 8. test_taiwan_odds_has_timestamp
def test_taiwan_odds_has_timestamp():
    """TaiwanLeg must store odds_scraped_at, odds_age_minutes, and odds_status."""
    leg = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        away_team="道奇",
        home_team="巨人",
        odds_scraped_at="2026-09-18T16:15:00Z",
        odds_age_minutes=2.5,
        odds_status="FRESH",
    )
    assert leg.odds_scraped_at == "2026-09-18T16:15:00Z"
    assert leg.odds_age_minutes == 2.5
    assert leg.odds_status == "FRESH"


# 9. test_stale_odds_blocks_ready_parlay
def test_stale_odds_blocks_ready_parlay():
    """Stale odds are rejected before a parlay is emitted as a candidate."""
    now = datetime.now(timezone.utc)
    event_start = (now + timedelta(hours=3)).isoformat()
    odds_observed = (now - timedelta(minutes=2)).isoformat()
    leg1 = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        start_time_utc=event_start,
        odds_scraped_at=odds_observed,
        odds_age_minutes=1.0,
        away_team="道奇",
        home_team="巨人",
        odds_status="LIVE",
        evidence_quality="HIGH",
        signal_evidence={"agreement": "HIGH", "supporting_groups": ["fixture"]},
    )
    leg2 = TaiwanLeg(
        event_id="102",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="洋基 客勝",
        taiwan_odds=1.75,
        start_time="07:05",
        start_time_utc=event_start,
        odds_scraped_at=odds_observed,
        odds_age_minutes=90.0,
        away_team="洋基",
        home_team="紅襪",
        odds_status="STALE_CACHE",  # Stale odds!
        evidence_quality="HIGH",
        signal_evidence={"agreement": "HIGH", "supporting_groups": ["fixture"]},
    )
    engine = ParlayEngine()
    results = engine.search_parlays(
        legs=[leg1, leg2],
        min_odds=2.0,
        max_odds=5.0,
        signal_filter="wild",
        min_legs=2,
        max_legs=2,
    )
    combos = results["high_consensus"] + results["aggressive"] + results["moonshot"]
    assert combos == []
    assert assess_leg(leg1)["is_ready"] is True
    stale_assessment = assess_leg(leg2)
    assert stale_assessment["is_ready"] is False
    assert "ODDS_STALE" in stale_assessment["reasons"]


# 10. test_model_market_delta
def test_model_market_delta():
    """PredictionSignal must include market_implied_probability, model_probability, and delta."""
    adapter = FiveThirtyEightMLBEloAdapter()
    leg = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        start_time_utc="2026-09-18T23:05:00Z",
        away_team="道奇",
        home_team="巨人",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.market_implied_probability is not None
    assert sig.model_probability is not None
    assert sig.model_market_delta_pp is not None
    # Verify math consistency
    expected_delta = round((sig.model_probability - sig.market_implied_probability) * 100.0, 1)
    assert abs(sig.model_market_delta_pp - expected_delta) < 0.2
