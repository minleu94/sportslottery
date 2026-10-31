#!/usr/bin/env python3
"""The Odds API Adapter with Quota Protection, Caching, and Synthetic Fixtures.

Supports:
- MLB, NBA, NFL, EPL, LaLiga, etc.
- Multi-market retrieval (h2h/moneyline, spreads, totals)
- Quota tracking and cache TTL enforcement
- Fallback to standardized synthetic fixtures when ODDS_API_KEY is unconfigured or exhausted
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from integrations.odds.market_models import (
    MarketFreshnessStatus,
    MarketOddsSnapshot,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "odds_api.yaml"
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "the_odds_api_cache.json"

SPORT_KEY_MAP = {
    "MLB": "baseball_mlb",
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "EPL": "soccer_epl",
    "英超": "soccer_epl",
    "西甲": "soccer_spain_la_liga",
    "LALIGA": "soccer_spain_la_liga",
    "SOCCER": "soccer_epl",
}


class TheOddsApiClient:
    """Client for The Odds API with robust quota tracking and caching."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        cache_path: Optional[Path] = None,
        api_key: Optional[str] = None,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.cache_path = cache_path or CACHE_PATH
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()

        # Key preference: Explicit argument > Environment variable > Config file
        self.api_key = (
            api_key
            or os.environ.get("ODDS_API_KEY")
            or self.config.get("api_key")
            or ""
        ).strip()

        self.base_url = self.config.get("base_url", "https://api.the-odds-api.com/v4")
        self.monthly_quota = int(self.config.get("monthly_quota", 500))
        self.cache_ttl = int(self.config.get("cache_ttl_seconds", 900))
        self.regions = self.config.get("regions", "us,eu")
        self.markets = self.config.get("markets", "h2h,spreads,totals")
        self.preferred_books = self.config.get("preferred_books", ["pinnacle", "draftkings", "fanduel"])

        self._cache_data: Dict[str, Any] = self._load_cache()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Failed to load odds_api.yaml: %s", exc)
            return {}

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {"usage": {}, "entries": {}}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {"usage": {}, "entries": {}}

    def _save_cache(self) -> None:
        try:
            self.cache_path.write_text(json.dumps(self._cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save odds api cache: %s", exc)

    def get_source_status(self) -> Dict[str, Any]:
        """Return operational capabilities and quota metrics."""
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        month_usage = self._cache_data.get("usage", {}).get(month_key, 0)
        has_key = bool(self.api_key)

        return {
            "source_id": "the_odds_api",
            "is_configured": has_key,
            "has_api_key": has_key,
            "monthly_quota": self.monthly_quota,
            "requests_used_this_month": month_usage,
            "requests_remaining_est": max(0, self.monthly_quota - month_usage),
            "cache_ttl_seconds": self.cache_ttl,
            "operating_mode": "LIVE_API" if has_key and month_usage < self.monthly_quota else "SYNTHETIC_FIXTURE",
            "supported_sports": list(SPORT_KEY_MAP.keys()),
        }

    def fetch_market_odds(
        self,
        sport_league: str,
        force_refresh: bool = False,
    ) -> List[MarketOddsSnapshot]:
        """Fetch market odds for a given sport league, or return synthetic fixtures if unconfigured."""
        league_norm = sport_league.upper().strip()
        sport_key = SPORT_KEY_MAP.get(league_norm, SPORT_KEY_MAP.get(sport_league.lower()))

        if not sport_key:
            logger.info("Unsupported sport/league for The Odds API: %s", sport_league)
            return []

        # Check API key presence
        if not self.api_key:
            logger.info("No ODDS_API_KEY configured; serving standardized synthetic fixtures for %s", league_norm)
            return self._generate_synthetic_fixtures(league_norm)

        # Check Cache TTL
        now_ts = time.time()
        cached_entry = self._cache_data.get("entries", {}).get(sport_key)
        if cached_entry and not force_refresh:
            fetched_at = cached_entry.get("fetched_at", 0)
            if (now_ts - fetched_at) < self.cache_ttl:
                logger.debug("Returning cached odds for %s (age %.1fs)", sport_key, now_ts - fetched_at)
                return [MarketOddsSnapshot(**item) for item in cached_entry.get("snapshots", [])]

        # Check Quota
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        used = self._cache_data.setdefault("usage", {}).get(month_key, 0)
        if used >= self.monthly_quota:
            logger.warning("Monthly quota exhausted for The Odds API (%d/%d); falling back to synthetic", used, self.monthly_quota)
            return self._generate_synthetic_fixtures(league_norm)

        # Call live API
        try:
            params = {
                "apiKey": self.api_key,
                "regions": self.regions,
                "markets": self.markets,
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            url = f"{self.base_url}/sports/{sport_key}/odds/?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Sportslottery-Intelligence/4.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode("utf-8"))

                # Increment usage
                self._cache_data["usage"][month_key] = used + 1

                snapshots = self._parse_api_payload(data, league_norm)

                # Update cache
                self._cache_data.setdefault("entries", {})[sport_key] = {
                    "fetched_at": now_ts,
                    "snapshots": [s.to_dict() for s in snapshots],
                }
                self._save_cache()
                return snapshots

        except Exception as exc:
            logger.warning("Error fetching live odds from The Odds API for %s: %s; using synthetic fixtures", sport_key, exc)
            return self._generate_synthetic_fixtures(league_norm)

    def _parse_api_payload(self, events: List[Dict[str, Any]], league: str) -> List[MarketOddsSnapshot]:
        snapshots: List[MarketOddsSnapshot] = []
        retrieved_at = datetime.now(timezone.utc).isoformat()

        for event in events:
            event_id = str(event.get("id"))
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence_time = event.get("commence_time", retrieved_at)

            bookmakers = event.get("bookmakers", [])
            for bm in bookmakers:
                book_key = bm.get("key", "").lower()
                source_id = f"the_odds_api:{book_key}"
                last_update = bm.get("last_update", retrieved_at)

                for mkt in bm.get("markets", []):
                    mkt_key = mkt.get("key")
                    outcomes = mkt.get("outcomes", [])

                    if mkt_key == "h2h":
                        market_type = "MONEYLINE"
                        for out in outcomes:
                            name = out.get("name")
                            price = float(out.get("price", 1.0))
                            selection = "home" if name == home_team else ("away" if name == away_team else "draw")
                            snapshots.append(
                                MarketOddsSnapshot(
                                    source_id=source_id,
                                    source_type="BOOKMAKER",
                                    event_id=event_id,
                                    league=league,
                                    home_team=home_team,
                                    away_team=away_team,
                                    start_time_utc=commence_time,
                                    market_type=market_type,
                                    selection=selection,
                                    line=None,
                                    decimal_odds=price,
                                    observed_at_utc=last_update,
                                    retrieved_at_utc=retrieved_at,
                                    freshness_status=MarketFreshnessStatus.LIVE.value,
                                    evidence_url="https://the-odds-api.com",
                                    source_license="COMMERCIAL_OR_FREE_TIER",
                                    is_synthetic=False,
                                )
                            )
                    elif mkt_key == "spreads":
                        market_type = "SPREAD"
                        for out in outcomes:
                            name = out.get("name")
                            price = float(out.get("price", 1.0))
                            point = float(out.get("point", 0.0))
                            selection = "home" if name == home_team else "away"
                            snapshots.append(
                                MarketOddsSnapshot(
                                    source_id=source_id,
                                    source_type="BOOKMAKER",
                                    event_id=event_id,
                                    league=league,
                                    home_team=home_team,
                                    away_team=away_team,
                                    start_time_utc=commence_time,
                                    market_type=market_type,
                                    selection=selection,
                                    line=point,
                                    decimal_odds=price,
                                    observed_at_utc=last_update,
                                    retrieved_at_utc=retrieved_at,
                                    freshness_status=MarketFreshnessStatus.LIVE.value,
                                    evidence_url="https://the-odds-api.com",
                                    source_license="COMMERCIAL_OR_FREE_TIER",
                                    is_synthetic=False,
                                )
                            )
                    elif mkt_key == "totals":
                        market_type = "TOTAL"
                        for out in outcomes:
                            name = out.get("name", "").lower()
                            price = float(out.get("price", 1.0))
                            point = float(out.get("point", 0.0))
                            selection = "over" if "over" in name else "under"
                            snapshots.append(
                                MarketOddsSnapshot(
                                    source_id=source_id,
                                    source_type="BOOKMAKER",
                                    event_id=event_id,
                                    league=league,
                                    home_team=home_team,
                                    away_team=away_team,
                                    start_time_utc=commence_time,
                                    market_type=market_type,
                                    selection=selection,
                                    line=point,
                                    decimal_odds=price,
                                    observed_at_utc=last_update,
                                    retrieved_at_utc=retrieved_at,
                                    freshness_status=MarketFreshnessStatus.LIVE.value,
                                    evidence_url="https://the-odds-api.com",
                                    source_license="COMMERCIAL_OR_FREE_TIER",
                                    is_synthetic=False,
                                )
                            )
        return snapshots

    def _generate_synthetic_fixtures(self, league: str) -> List[MarketOddsSnapshot]:
        """Generate high-fidelity, deterministic synthetic snapshots clearly tagged as synthetic."""
        now_utc = datetime.now(timezone.utc).isoformat()
        fixtures = []

        if league in {"MLB", "BASEBALL"}:
            matchups = [
                ("Los Angeles Dodgers", "San Diego Padres", -1.5, 2.10, 1.75, 8.5, 1.95, 1.87),
                ("New York Yankees", "Boston Red Sox", -1.5, 2.25, 1.68, 9.0, 1.90, 1.92),
            ]
        elif league in {"NBA", "BASKETBALL"}:
            matchups = [
                ("Boston Celtics", "Milwaukee Bucks", -4.5, 1.91, 1.91, 224.5, 1.90, 1.90),
                ("Denver Nuggets", "Los Angeles Lakers", -6.5, 1.90, 1.92, 220.5, 1.92, 1.88),
            ]
        elif league in {"NFL", "FOOTBALL"}:
            matchups = [
                ("Kansas City Chiefs", "Buffalo Bills", -2.5, 1.91, 1.91, 47.5, 1.90, 1.90),
            ]
        else:  # Soccer (EPL / LaLiga)
            matchups = [
                ("Arsenal", "Chelsea", -0.5, 1.85, 2.05, 2.5, 1.80, 2.05),
                ("Real Madrid", "Barcelona", -0.5, 2.10, 1.80, 3.0, 1.88, 1.95),
            ]

        for idx, (home, away, spread, home_spread_odds, away_spread_odds, total, over_odds, under_odds) in enumerate(matchups):
            ev_id = f"syn_{league.lower()}_{idx+1}"

            # Moneyline
            fixtures.append(
                MarketOddsSnapshot(
                    source_id="the_odds_api:pinnacle_synthetic",
                    source_type="SYNTHETIC_FIXTURE",
                    event_id=ev_id,
                    league=league,
                    home_team=home,
                    away_team=away,
                    start_time_utc=now_utc,
                    market_type="MONEYLINE",
                    selection="home",
                    decimal_odds=round(1.0 / (0.55 * 1.02), 2),
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )
            fixtures.append(
                MarketOddsSnapshot(
                    source_id="the_odds_api:pinnacle_synthetic",
                    source_type="SYNTHETIC_FIXTURE",
                    event_id=ev_id,
                    league=league,
                    home_team=home,
                    away_team=away,
                    start_time_utc=now_utc,
                    market_type="MONEYLINE",
                    selection="away",
                    decimal_odds=round(1.0 / (0.45 * 1.02), 2),
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )

            # Spreads
            fixtures.append(
                MarketOddsSnapshot(
                    source_id="the_odds_api:pinnacle_synthetic",
                    source_type="SYNTHETIC_FIXTURE",
                    event_id=ev_id,
                    league=league,
                    home_team=home,
                    away_team=away,
                    start_time_utc=now_utc,
                    market_type="SPREAD",
                    selection="home",
                    line=spread,
                    decimal_odds=home_spread_odds,
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )
            fixtures.append(
                MarketOddsSnapshot(
                    source_id="the_odds_api:pinnacle_synthetic",
                    source_type="SYNTHETIC_FIXTURE",
                    event_id=ev_id,
                    league=league,
                    home_team=home,
                    away_team=away,
                    start_time_utc=now_utc,
                    market_type="SPREAD",
                    selection="away",
                    line=-spread,
                    decimal_odds=away_spread_odds,
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )

            # Totals
            fixtures.append(
                MarketOddsSnapshot(
                    source_id="the_odds_api:pinnacle_synthetic",
                    source_type="SYNTHETIC_FIXTURE",
                    event_id=ev_id,
                    league=league,
                    home_team=home,
                    away_team=away,
                    start_time_utc=now_utc,
                    market_type="TOTAL",
                    selection="over",
                    line=total,
                    decimal_odds=over_odds,
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )
            fixtures.append(
                MarketOddsSnapshot(
                    source_id="the_odds_api:pinnacle_synthetic",
                    source_type="SYNTHETIC_FIXTURE",
                    event_id=ev_id,
                    league=league,
                    home_team=home,
                    away_team=away,
                    start_time_utc=now_utc,
                    market_type="TOTAL",
                    selection="under",
                    line=total,
                    decimal_odds=under_odds,
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )

        return fixtures
