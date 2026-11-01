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
LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "odds_api.local.yaml"
ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "the_odds_api_cache.json"
QUOTA_SAFETY_MARGIN = 5

SPORT_KEY_MAP = {
    "MLB": "baseball_mlb",
    "BASEBALL": "baseball_mlb",
    "NBA": "basketball_nba",
    "BASKETBALL": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "FOOTBALL": "americanfootball_nfl",
    "EPL": "soccer_epl",
    "英超": "soccer_epl",
    "西甲": "soccer_spain_la_liga",
    "LALIGA": "soccer_spain_la_liga",
    "SOCCER": "soccer_epl",
    "歐冠": "soccer_uefa_champs_league",
    "CHAMPIONS_LEAGUE": "soccer_uefa_champs_league",
    "德甲": "soccer_germany_bundesliga",
    "BUNDESLIGA": "soccer_germany_bundesliga",
    "義甲": "soccer_italy_serie_a",
    "SERIE_A": "soccer_italy_serie_a",
}


def _parse_env_file(path: Path) -> Dict[str, str]:
    """Parse key=value pairs from a local .env file without external dependencies."""
    if not path.is_file():
        return {}
    res = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                raw_v = v.strip()
                if (raw_v.startswith('"') and raw_v.endswith('"')) or (raw_v.startswith("'") and raw_v.endswith("'")):
                    raw_v = raw_v[1:-1].strip()
                res[k.strip()] = raw_v
    except Exception:
        pass
    return res


def save_local_api_key(api_key: str, dest_path: Optional[Path] = None) -> bool:
    """Save API key into gitignored config/odds_api.local.yaml without modifying Git."""
    dest = dest_path or LOCAL_CONFIG_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    current: Dict[str, Any] = {}
    if dest.is_file():
        try:
            current = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
        except Exception:
            current = {}
    current["api_key"] = api_key.strip()
    dest.write_text(yaml.safe_dump(current, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return True


class TheOddsApiClient:
    """Client for The Odds API with robust quota tracking, caching, and safe fallback."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        local_config_path: Optional[Path] = None,
        env_file_path: Optional[Path] = None,
        cache_path: Optional[Path] = None,
        api_key: Optional[str] = None,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.local_config_path = local_config_path or LOCAL_CONFIG_PATH
        self.env_file_path = env_file_path or ENV_FILE_PATH
        self.cache_path = cache_path or CACHE_PATH
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()

        # Key preference:
        # 1. Explicit argument
        # 2. THE_ODDS_API_KEY environment variable (Primary)
        # 3. ODDS_API_KEY environment variable (Backward Compatibility)
        # 4. .env file in project root (THE_ODDS_API_KEY then ODDS_API_KEY)
        # 5. config/odds_api.local.yaml (Gitignored local override)
        # 6. config/odds_api.yaml (Base config file)
        self.api_key, self.key_source = self._resolve_api_key(api_key)

        self.base_url = self.config.get("base_url", "https://api.the-odds-api.com/v4")
        self.monthly_quota = int(self.config.get("monthly_quota", 500))
        self.cache_ttl = int(self.config.get("cache_ttl_seconds", 900))
        self.regions = self.config.get("regions", "us,eu")
        self.markets = self.config.get("markets", "h2h,spreads,totals")
        self.preferred_books = self.config.get("preferred_books", ["pinnacle", "draftkings", "fanduel"])

        self._cache_data: Dict[str, Any] = self._load_cache()

    def _resolve_api_key(self, explicit_arg: Optional[str] = None) -> Tuple[str, str]:
        if explicit_arg and explicit_arg.strip():
            return explicit_arg.strip(), "EXPLICIT_ARG"
        if os.environ.get("THE_ODDS_API_KEY"):
            return os.environ["THE_ODDS_API_KEY"].strip(), "ENV_THE_ODDS_API_KEY"
        if os.environ.get("ODDS_API_KEY"):
            return os.environ["ODDS_API_KEY"].strip(), "ENV_ODDS_API_KEY"
        dotenv_vars = _parse_env_file(self.env_file_path)
        if dotenv_vars.get("THE_ODDS_API_KEY"):
            return dotenv_vars["THE_ODDS_API_KEY"].strip(), "DOTENV"
        if dotenv_vars.get("ODDS_API_KEY"):
            return dotenv_vars["ODDS_API_KEY"].strip(), "DOTENV"
        local_cfg = self._load_yaml(self.local_config_path)
        if local_cfg.get("api_key"):
            return str(local_cfg["api_key"]).strip(), "LOCAL_CONFIG"
        base_cfg = self._load_yaml(self.config_path)
        if base_cfg.get("api_key"):
            return str(base_cfg["api_key"]).strip(), "BASE_CONFIG"
        return "", "UNCONFIGURED"

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            return {}

    def _load_config(self) -> Dict[str, Any]:
        merged = self._load_yaml(self.config_path)
        local_override = self._load_yaml(self.local_config_path)
        if local_override:
            merged.update(local_override)
        return merged

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

    def save_api_key(self, api_key: str) -> bool:
        """Save API key locally to config/odds_api.local.yaml."""
        ok = save_local_api_key(api_key, self.local_config_path)
        if ok:
            self.api_key = api_key.strip()
            self.key_source = "LOCAL_CONFIG"
        return ok

    def get_source_status(self) -> Dict[str, Any]:
        """Return operational capabilities and quota metrics."""
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        month_usage = self._cache_data.get("usage", {}).get(month_key, 0)
        has_key = bool(self.api_key)
        official_rem = self._cache_data.get("requests_remaining_official")
        remaining_est = official_rem if official_rem is not None else max(0, self.monthly_quota - month_usage)

        if not has_key:
            mode = "SYNTHETIC_FIXTURE"
        elif remaining_est <= 0 or month_usage >= self.monthly_quota:
            mode = "QUOTA_EXHAUSTED"
        elif remaining_est <= QUOTA_SAFETY_MARGIN:
            mode = "QUOTA_SAFETY_PAUSE"
        else:
            mode = "LIVE_API"

        return {
            "source_id": "the_odds_api",
            "is_configured": has_key,
            "has_api_key": has_key,
            "key_source": self.key_source,
            "monthly_quota": self.monthly_quota,
            "requests_used_this_month": month_usage,
            "requests_remaining_est": remaining_est,
            "official_remaining": official_rem,
            "cache_ttl_seconds": self.cache_ttl,
            "operating_mode": mode,
            "last_live_fetch_utc": self._cache_data.get("last_live_fetch_utc"),
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

        # Check Quota & Safety Pause
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        used = self._cache_data.setdefault("usage", {}).get(month_key, 0)
        official_rem = self._cache_data.get("requests_remaining_official")
        remaining = official_rem if official_rem is not None else max(0, self.monthly_quota - used)
        if used >= self.monthly_quota or remaining <= QUOTA_SAFETY_MARGIN:
            logger.warning(
                "Monthly quota protection triggered for The Odds API (%d/%d used, %d remaining); falling back to synthetic",
                used, self.monthly_quota, remaining
            )
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

                # Track usage from official response headers when available
                h_used = resp.headers.get("x-requests-used")
                h_remaining = resp.headers.get("x-requests-remaining")
                if h_used is not None:
                    try:
                        self._cache_data["usage"][month_key] = int(h_used)
                    except ValueError:
                        self._cache_data["usage"][month_key] = used + 1
                else:
                    self._cache_data["usage"][month_key] = used + 1

                if h_remaining is not None:
                    try:
                        self._cache_data["requests_remaining_official"] = int(h_remaining)
                    except ValueError:
                        pass

                self._cache_data["last_live_fetch_utc"] = datetime.now(timezone.utc).isoformat()

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
            is_soccer = league in {"EPL", "SOCCER", "LALIGA", "西甲", "英超"}
            home_ml_odds = round(1.0 / (0.45 * 1.03), 2) if is_soccer else round(1.0 / (0.55 * 1.02), 2)
            away_ml_odds = round(1.0 / (0.27 * 1.03), 2) if is_soccer else round(1.0 / (0.45 * 1.02), 2)
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
                    decimal_odds=home_ml_odds,
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="synthetic://fixture/the_odds_api",
                    source_license="TEST_FIXTURE_NO_KEY",
                    is_synthetic=True,
                )
            )
            if is_soccer:
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
                        selection="draw",
                        decimal_odds=round(1.0 / (0.28 * 1.03), 2),
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
                    decimal_odds=away_ml_odds,
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
