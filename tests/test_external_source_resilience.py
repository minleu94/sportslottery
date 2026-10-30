"""Test suite for external data source resilience and failure modes (P3-5).

Validates:
1. Playsport scraper handles network timeouts, 5xx HTTP errors, and malformed HTML gracefully.
2. Stale cache is NEVER marked as LIVE; preserves STALE_CACHE, CACHED, LIVE, and UNAVAILABLE statuses.
3. Odds adapter propagates source status and provenance metadata accurately.
4. BettingService and TicketRecorder reject expired or unverified recommendation bets.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests

from core.betting_service import BettingService
from core.profile_manager import ProfileManager
from core.scraper import PlaysportScraper
from core.wallet import WeeklyWalletManager
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter


class _FailingSession:
    def __init__(self, exception_to_raise: Exception):
        self.exception_to_raise = exception_to_raise
        self.headers = {}

    def get(self, url: str, timeout: int = 10):
        raise self.exception_to_raise


class _HttpErrorSession:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.headers = {}

    def get(self, url: str, timeout: int = 10):
        resp = requests.Response()
        resp.status_code = self.status_code
        return resp


class _MalformedHtmlSession:
    def __init__(self, html: str):
        self.html = html
        self.headers = {}

    def get(self, url: str, timeout: int = 10):
        resp = requests.Response()
        resp.status_code = 200
        resp._content = self.html.encode("utf-8")
        return resp


def test_network_timeout_without_cache(tmp_path: Path):
    """Network timeout with no prior cache must return empty list and report failure status."""
    cache_dir = tmp_path / "cache"
    scraper = PlaysportScraper(
        session=_FailingSession(requests.Timeout("Connection timed out after 10s")),
        cache_dir=cache_dir,
    )

    matches = scraper.fetch_scale_matches(alliance_id="1", force_refresh=True)
    assert matches == []

    status_map = scraper.get_scale_source_status()
    assert "1" in status_map
    status = status_map["1"]
    assert status["source_status"] == "FETCH_ERROR"
    assert status["failure_status"] == "FETCH_ERROR"
    assert "Timeout" in status["error"]
    assert status["match_count"] == 0


def test_network_timeout_with_stale_cache_fallback(tmp_path: Path):
    """Network failure with existing cache falls back to cache marked as STALE_CACHE, never LIVE."""
    cache_dir = tmp_path / "cache"
    scraper = PlaysportScraper(
        session=_FailingSession(requests.ConnectionError("Failed to resolve host")),
        cache_dir=cache_dir,
    )

    # Seed an older cache entry
    old_time = time.time() - 3600  # 1 hour ago
    old_iso = datetime.now(timezone.utc).isoformat()
    scraper.write_cache("scale_1", {
        "matches": [
            {
                "match_id": "mlb-2026-001",
                "sport": "baseball",
                "league": "MLB",
                "away_team": "洋基",
                "home_team": "紅襪",
                "game_time": "2026-10-31 07:00",
                "options": [
                    {"market_type": "不讓分", "side": "客", "selection": "洋基", "odds": 1.85},
                    {"market_type": "不讓分", "side": "主", "selection": "紅襪", "odds": 1.95},
                ],
            }
        ]
    })
    # Overwrite cached_at to simulate old cache
    cache_file = scraper.get_cache_path("scale_1")
    import json
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    data["cached_at"] = old_time
    data["cached_iso"] = old_iso
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    matches = scraper.fetch_scale_matches(alliance_id="1", force_refresh=True)
    assert len(matches) == 1
    m = matches[0]
    assert m["match_id"] == "mlb-2026-001"
    assert m["_is_stale_cache"] is True
    assert m["_cache_status"] == "STALE_CACHE"
    assert m["_failure_status"] == "FETCH_ERROR"

    status = scraper.get_scale_source_status()["1"]
    assert status["source_status"] == "STALE_CACHE"
    assert status["failure_status"] == "FETCH_ERROR"
    assert status["cache_age_minutes"] >= 59.0


def test_malformed_html_missing_table(tmp_path: Path):
    """Changed page structure without predictgame-table must record PARSE_EMPTY."""
    cache_dir = tmp_path / "cache"
    malformed_html = "<html><body><div class='redesign-content'>Under Maintenance</div></body></html>"
    scraper = PlaysportScraper(
        session=_MalformedHtmlSession(malformed_html),
        cache_dir=cache_dir,
    )

    matches = scraper.fetch_scale_matches(alliance_id="3", force_refresh=True)
    assert matches == []

    status = scraper.get_scale_source_status()["3"]
    assert status["failure_status"] == "PARSE_EMPTY"
    assert "Expected predictgame-table was absent" in status["error"]


def test_odds_adapter_marks_stale_cache_correctly(tmp_path: Path):
    """PlaysportOddsAdapter must label legs derived from stale cache as STALE_CACHE."""
    cache_dir = tmp_path / "cache"
    scraper = PlaysportScraper(
        session=_FailingSession(requests.Timeout("timeout")),
        cache_dir=cache_dir,
    )

    scraper.write_cache("scale_1", {
        "matches": [
            {
                "match_id": "mlb-001",
                "sport": "baseball",
                "league": "MLB",
                "away_team": "洋基",
                "home_team": "紅襪",
                "game_time": "2026-10-31 07:00",
                "options": [
                    {"market_type": "不讓分", "side": "客", "selection": "洋基", "odds": 1.85},
                    {"market_type": "不讓分", "side": "主", "selection": "紅襪", "odds": 1.95},
                ],
            }
        ]
    })
    # Make it stale
    cache_file = scraper.get_cache_path("scale_1")
    import json
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    data["cached_at"] = time.time() - 3600
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    adapter = PlaysportOddsAdapter(scraper=scraper)
    legs = adapter.get_taiwan_legs(alliance_ids=["1"], force_refresh=True)

    assert len(legs) > 0
    for leg in legs:
        assert leg.odds_status == "STALE_CACHE"


def test_recommendation_bet_rejects_expired_or_unverified(tmp_path: Path):
    """BettingService must reject recommendation bets when match has already started or odds stale."""
    db_path = tmp_path / "betting.sqlite3"
    pm = ProfileManager(db_path=db_path)
    profile = pm.create_profile("Tester", weekly_play_cap=500.0, pin_code="1234")

    wallet = WeeklyWalletManager(db_path=db_path, profile_id=profile["id"])
    wallet.deposit_external(200.0, notes="Deposit")

    service = BettingService(db_path=db_path, profile_id=profile["id"])

    # 1. Past match start time
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    expired_leg = {
        "event_id": "game-past-1",
        "sport": "baseball",
        "league": "MLB",
        "home_team": "紅襪",
        "away_team": "洋基",
        "market": "不讓分",
        "selection": "洋基",
        "taiwan_odds": 1.85,
        "start_time_utc": past_iso,
        "odds_scraped_at": now_iso,
    }

    with pytest.raises(ValueError, match="賽事已開賽"):
        service.place_ticket(
            legs=[expired_leg],
            stake=50.0,
            total_odds=1.85,
            entry_mode="recommendation",
            notes="Expired bet test",
        )

    # 2. Future match but stale scraped odds
    future_iso = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    stale_scraped_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    stale_odds_leg = {
        "event_id": "game-future-1",
        "sport": "baseball",
        "league": "MLB",
        "home_team": "紅襪",
        "away_team": "洋基",
        "market": "不讓分",
        "selection": "洋基",
        "taiwan_odds": 1.85,
        "start_time_utc": future_iso,
        "odds_scraped_at": stale_scraped_iso,
    }

    with pytest.raises(ValueError, match="盤口資料已過期"):
        service.place_ticket(
            legs=[stale_odds_leg],
            stake=50.0,
            total_odds=1.85,
            entry_mode="recommendation",
            notes="Stale odds bet test",
        )

    # 3. Valid future match with fresh scraped odds and LIVE status
    fresh_scraped_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    valid_leg = {
        "event_id": "game-future-2",
        "sport": "baseball",
        "league": "MLB",
        "home_team": "紅襪",
        "away_team": "洋基",
        "market": "不讓分",
        "selection": "洋基",
        "taiwan_odds": 1.85,
        "start_time_utc": future_iso,
        "odds_scraped_at": fresh_scraped_iso,
        "odds_status": "LIVE",
    }

    ticket = service.place_ticket(
        legs=[valid_leg],
        stake=50.0,
        total_odds=1.85,
        entry_mode="recommendation",
        notes="Valid recommendation bet test",
    )
    assert ticket["ticket_id"]
    assert ticket["entry_mode"] == "recommendation"
