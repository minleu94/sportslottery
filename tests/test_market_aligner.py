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


def test_shared_team_registry_resolves_current_nba_fixture_aliases():
    """The aligner must support aliases already present in the project registry."""
    assert resolve_canonical_team("底特律活塞", "NBA") == "nba_det"
    assert resolve_canonical_team("Detroit Pistons", "NBA") == "nba_det"
    assert resolve_canonical_team("夏洛特黃蜂", "NBA") == "nba_cha"
    assert resolve_canonical_team("Charlotte Hornets", "NBA") == "nba_cha"


def test_nba_alias_alignment_and_offset_aware_kickoff():
    aligner = MarketAligner()
    leg = TaiwanLeg(
        event_id="playsport_det_cha",
        sport="basketball",
        league="NBA",
        home_team="夏洛特黃蜂",
        away_team="底特律活塞",
        market="不讓分",
        selection="黃蜂主勝",
        side="主",
        taiwan_odds=1.85,
        start_time_utc="2026-11-02T16:00:00-08:00",
    )
    candidate = MarketOddsSnapshot(
        source_id="the_odds_api:draftkings",
        source_type="BOOKMAKER",
        event_id="api_det_cha",
        league="NBA",
        home_team="Charlotte Hornets",
        away_team="Detroit Pistons",
        start_time_utc="2026-11-03T00:10:00Z",
        market_type="MONEYLINE",
        selection="home",
        decimal_odds=1.9,
        observed_at_utc="2026-11-02T07:40:00Z",
        retrieved_at_utc="2026-11-02T07:40:00Z",
        freshness_status="LIVE",
    )

    matched, record = aligner.align_leg_with_candidates(
        leg,
        [candidate],
        now_utc=datetime(2026, 11, 2, 8, 16, tzinfo=timezone.utc),
    )

    assert matched is candidate
    assert record.status == MarketAlignmentStatus.MATCHED
    assert record.time_delta_seconds == 600.0


def test_soccer_draw_market_aligns_to_odds_api_three_way_h2h():
    aligner = MarketAligner()
    now_iso = datetime.now(timezone.utc).isoformat()
    leg = TaiwanLeg(
        event_id="playsport_eve_new_draw",
        sport="soccer",
        league="PREMIER",
        home_team="紐卡索聯",
        away_team="艾佛頓",
        market="和局",
        selection="和局",
        side="和",
        taiwan_odds=3.2,
        start_time_utc=now_iso,
    )
    draw_quote = MarketOddsSnapshot(
        source_id="the_odds_api:book",
        source_type="BOOKMAKER",
        event_id="api_eve_new",
        league="SOCCER",
        home_team="Newcastle United",
        away_team="Everton",
        start_time_utc=now_iso,
        market_type="MONEYLINE",
        selection="draw",
        decimal_odds=3.4,
        observed_at_utc=now_iso,
        retrieved_at_utc=now_iso,
        freshness_status="LIVE",
    )

    matched, record = aligner.align_leg_with_candidates(leg, [draw_quote])

    assert matched is draw_quote
    assert record.status == MarketAlignmentStatus.MATCHED


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
        start_time_utc=now_iso,
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
        start_time_utc=now_iso,
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
        start_time_utc=now_iso,
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


def test_alignment_rejection_distinguishes_missing_quotes_and_league_mismatch():
    aligner = MarketAligner()
    now_iso = datetime.now(timezone.utc).isoformat()
    leg = TaiwanLeg(
        event_id="diagnostic_nba",
        sport="basketball",
        league="NBA",
        home_team="丹佛金塊",
        away_team="洛杉磯湖人",
        market="不讓分",
        selection="金塊主勝",
        side="主",
        taiwan_odds=1.8,
        start_time_utc=now_iso,
    )

    _, no_quotes = aligner.align_leg_with_candidates(leg, [])
    assert no_quotes.rejection_code == "ERR_NO_INTERNATIONAL_QUOTES"

    leg.home_team = "Unregistered Home"
    leg.away_team = "Unregistered Away"
    _, no_quotes_with_unresolved_teams = aligner.align_leg_with_candidates(leg, [])
    assert no_quotes_with_unresolved_teams.rejection_code == "ERR_NO_INTERNATIONAL_QUOTES"
    leg.home_team = "丹佛金塊"
    leg.away_team = "洛杉磯湖人"

    nfl_quote = MarketOddsSnapshot(
        source_id="the_odds_api:book",
        source_type="BOOKMAKER",
        event_id="nfl_fixture",
        league="NFL",
        home_team="Denver Nuggets",
        away_team="Los Angeles Lakers",
        start_time_utc=now_iso,
        market_type="MONEYLINE",
        selection="home",
        decimal_odds=1.9,
        observed_at_utc=now_iso,
        retrieved_at_utc=now_iso,
        freshness_status="LIVE",
    )
    _, wrong_league = aligner.align_leg_with_candidates(leg, [nfl_quote])
    assert wrong_league.rejection_code == "ERR_LEAGUE_MISMATCH"


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
        start_time_utc=now_iso,
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
        start_time_utc=old_time,
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


def test_odds_api_parser_uses_market_timestamp_and_preserves_unknown_freshness(tmp_path):
    client = TheOddsApiClient(api_key="", cache_path=tmp_path / "odds_cache.json")
    now = datetime.now(timezone.utc)
    bookmaker_update = now.isoformat()
    h2h_update = (now - timedelta(minutes=8)).isoformat()
    totals_update = (now - timedelta(seconds=15)).isoformat()
    payload = [{
        "id": "event-1",
        "home_team": "Los Angeles Dodgers",
        "away_team": "San Diego Padres",
        "commence_time": (now + timedelta(hours=2)).isoformat(),
        "bookmakers": [{
            "key": "pinnacle",
            "last_update": bookmaker_update,
            "markets": [
                {"key": "h2h", "last_update": h2h_update, "outcomes": [
                    {"name": "Los Angeles Dodgers", "price": 1.9},
                    {"name": "San Diego Padres", "price": 2.0},
                ]},
                {"key": "totals", "last_update": totals_update, "outcomes": [
                    {"name": "Over", "price": 1.9, "point": 8.5},
                    {"name": "Under", "price": 1.9, "point": 8.5},
                ]},
                {"key": "spreads", "last_update": "2026-11-02T21:00:00", "outcomes": [
                    {"name": "Los Angeles Dodgers", "price": 1.9, "point": -1.5},
                    {"name": "San Diego Padres", "price": 1.9, "point": 1.5},
                ]},
            ],
        }],
    }]

    parsed = client._parse_api_payload(payload, "MLB")
    by_market = {quote.market_type: quote for quote in parsed if quote.selection == "home" or quote.selection == "over"}
    assert by_market["MONEYLINE"].observed_at_utc == datetime.fromisoformat(h2h_update).isoformat()
    assert by_market["MONEYLINE"].freshness_status == "AGING"
    assert by_market["TOTAL"].observed_at_utc == datetime.fromisoformat(totals_update).isoformat()
    assert by_market["TOTAL"].freshness_status in {"LIVE", "FRESH"}
    assert by_market["SPREAD"].observed_at_utc is None
    assert by_market["SPREAD"].freshness_status == "UNKNOWN"


def test_the_odds_api_client_synthetic_fallback(tmp_path):
    client = TheOddsApiClient(api_key="", cache_path=tmp_path / "odds_cache.json")
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
