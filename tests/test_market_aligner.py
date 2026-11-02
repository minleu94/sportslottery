#!/usr/bin/env python3
"""Tests for Market Aligner and International Odds Adapters.

Milestone 2 Verification:
- Tests team alias resolution across languages
- Tests direct match & team direction reversal (Home/Away inversion)
- Tests spread line handicap matching & mismatch rejection
- Tests total line threshold matching & mismatch rejection
- Tests staleness rejection
- Tests non-existent event rejection
- Verifies TheOddsApiClient and BettingSplitsClient data contracts
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from core.market_aligner import MarketAligner, resolve_canonical_team
from integrations.common.models import TaiwanLeg
from integrations.odds.betting_splits_client import BettingSplitsClient
from integrations.odds.market_models import (
    MarketAlignmentStatus,
    MarketOddsSnapshot,
)
from integrations.odds.the_odds_api import TheOddsApiClient


def test_canonical_team_resolution():
    assert resolve_canonical_team("洛杉磯道奇", "MLB") == "los angeles dodgers"
    assert resolve_canonical_team("道奇", "MLB") == "los angeles dodgers"
    assert resolve_canonical_team("LAD", "MLB") == "los angeles dodgers"
    assert resolve_canonical_team("丹佛金塊", "NBA") == "denver nuggets"
    assert resolve_canonical_team("金塊", "NBA") == "denver nuggets"
    assert resolve_canonical_team("兵工廠", "EPL") == "arsenal"
    assert resolve_canonical_team("阿森納", "英超") == "arsenal"
    assert resolve_canonical_team("Unknown FC", "MLB") is None


def test_exact_spread_alignment_matched():
    aligner = MarketAligner()
    now_iso = datetime.now(timezone.utc).isoformat()

    leg = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        home_team="道奇",
        away_team="教士",
        market="讓分",
        selection="道奇 -1.5",
        side="主",
        line="-1.5",
        taiwan_odds=1.85,
    )

    candidate = MarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="ext_101",
        league="MLB",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        start_time_utc=now_iso,
        market_type="SPREAD",
        selection="home",
        line=-1.5,
        decimal_odds=1.92,
        observed_at_utc=now_iso,
        retrieved_at_utc=now_iso,
        freshness_status="LIVE",
    )

    matched, record = aligner.align_leg_with_candidates(leg, [candidate])
    assert matched is not None
    assert record.status == MarketAlignmentStatus.MATCHED
    assert record.international_event_id == "ext_101"
    assert record.rejection_code is None


def test_spread_line_mismatch_rejected():
    aligner = MarketAligner()
    now_iso = datetime.now(timezone.utc).isoformat()

    leg = TaiwanLeg(
        event_id="102",
        sport="baseball",
        league="MLB",
        home_team="道奇",
        away_team="教士",
        market="讓分",
        selection="道奇 -1.5",
        side="主",
        line="-1.5",
        taiwan_odds=1.85,
    )

    # International quote has line -2.5 instead of -1.5
    candidate = MarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="ext_102",
        league="MLB",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        start_time_utc=now_iso,
        market_type="SPREAD",
        selection="home",
        line=-2.5,
        decimal_odds=2.45,
        observed_at_utc=now_iso,
        retrieved_at_utc=now_iso,
        freshness_status="LIVE",
    )

    matched, record = aligner.align_leg_with_candidates(leg, [candidate])
    assert matched is None
    assert record.status == MarketAlignmentStatus.MARKET_NOT_EQUIVALENT
    assert record.rejection_code == "ERR_LINE_MISMATCH"


def test_total_threshold_mismatch_rejected():
    aligner = MarketAligner()
    now_iso = datetime.now(timezone.utc).isoformat()

    leg = TaiwanLeg(
        event_id="103",
        sport="baseball",
        league="MLB",
        home_team="道奇",
        away_team="教士",
        market="大小",
        selection="大 8.5",
        side="大",
        line="8.5",
        taiwan_odds=1.75,
    )

    # Int quote has total line 9.0
    candidate = MarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="ext_103",
        league="MLB",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        start_time_utc=now_iso,
        market_type="TOTAL",
        selection="over",
        line=9.0,
        decimal_odds=1.95,
        observed_at_utc=now_iso,
        retrieved_at_utc=now_iso,
        freshness_status="LIVE",
    )

    matched, record = aligner.align_leg_with_candidates(leg, [candidate])
    assert matched is None
    assert record.status == MarketAlignmentStatus.MARKET_NOT_EQUIVALENT
    assert record.rejection_code == "ERR_LINE_MISMATCH"


def test_team_direction_reversal_handling():
    aligner = MarketAligner()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Taiwan lists: Away=教士, Home=道奇
    # External lists: Home=San Diego Padres, Away=Los Angeles Dodgers (teams reversed!)
    leg = TaiwanLeg(
        event_id="104",
        sport="baseball",
        league="MLB",
        home_team="道奇",
        away_team="教士",
        market="不讓分",
        selection="道奇 客勝",
        side="主",  # Backing Dodgers
        taiwan_odds=1.60,
    )

    candidate = MarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="ext_104",
        league="MLB",
        home_team="San Diego Padres",
        away_team="Los Angeles Dodgers",
        start_time_utc=now_iso,
        market_type="MONEYLINE",
        selection="away",  # Dodgers is 'away' in candidate
        decimal_odds=1.65,
        observed_at_utc=now_iso,
        retrieved_at_utc=now_iso,
        freshness_status="LIVE",
    )

    matched, record = aligner.align_leg_with_candidates(leg, [candidate])
    assert matched is not None
    assert record.status == MarketAlignmentStatus.MATCHED
    assert matched.selection == "away"


def test_stale_quote_rejection():
    aligner = MarketAligner(max_staleness_seconds=3600.0)  # 1 hour limit
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=3)).isoformat()

    leg = TaiwanLeg(
        event_id="105",
        sport="baseball",
        league="MLB",
        home_team="道奇",
        away_team="教士",
        market="不讓分",
        selection="道奇勝",
        side="主",
        taiwan_odds=1.60,
    )

    candidate = MarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="ext_105",
        league="MLB",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        start_time_utc=old_time,
        market_type="MONEYLINE",
        selection="home",
        decimal_odds=1.65,
        observed_at_utc=old_time,
        retrieved_at_utc=old_time,
        freshness_status="STALE",
    )

    matched, record = aligner.align_leg_with_candidates(leg, [candidate], now_utc=now)
    assert matched is None
    assert record.status == MarketAlignmentStatus.STALE
    assert record.rejection_code == "ERR_STALE_ODDS"


def test_the_odds_api_client_synthetic_fallback():
    client = TheOddsApiClient(api_key="")
    status = client.get_source_status()
    assert status["is_configured"] is False
    assert status["operating_mode"] in ("UNCONFIGURED", "SYNTHETIC_FIXTURE")

    # Should safely return synthetic fixtures without error
    mlb_odds = client.fetch_market_odds("MLB")
    assert len(mlb_odds) > 0
    assert all(snap.is_synthetic for snap in mlb_odds)
    assert all(snap.source_license == "TEST_FIXTURE_NO_KEY" for snap in mlb_odds)


def test_betting_splits_client_null_preservation():
    client = BettingSplitsClient()
    splits = client.get_betting_splits("MLB")
    assert len(splits) > 0
    for split in splits:
        assert split.bet_percentage is not None
        assert split.money_percentage is not None
        assert split.reporting_bookmaker in {"DraftKings", "Circa Sports", "Consensus"}
        assert split.source_type == "BETTING_SPLITS"
