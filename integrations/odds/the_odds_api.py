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
from typing import Any, Dict, List, Optional, Tuple

import yaml
from core.persistence import file_lock

from core.contracts.market import (
    MarketFreshnessStatus,
    MarketOddsSnapshot,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
CONFIG_PATH = CONFIG_DIR / "odds_api.yaml"  # User-owned runtime config; gitignored.
EXAMPLE_CONFIG_PATH = CONFIG_DIR / "odds_api.example.yaml"
LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "odds_api.local.yaml"
ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "the_odds_api_cache.json"
MONTHLY_BUDGET_TOTAL = 500
MANUAL_RESERVE_CREDITS = 50
MAX_AUTOMATED_BUDGET_CREDITS = 450
QUOTA_SAFETY_MARGIN = 50  # Enforce 50-credit reserve for manual research

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
        self._explicit_api_key_override = api_key is not None

        # Key preference:
        # 1. Explicit argument
        # 2. THE_ODDS_API_KEY environment variable (Primary)
        # 3. ODDS_API_KEY environment variable (Backward Compatibility)
        # 4. .env file in project root (THE_ODDS_API_KEY then ODDS_API_KEY)
        # 5. config/odds_api.local.yaml (Gitignored key storage managed by the UI)
        # 6. config/odds_api.yaml (Gitignored user-owned runtime config)
        # 7. config/odds_api.example.yaml (Tracked defaults without secrets)
        self.api_key, self.key_source = self._resolve_api_key(api_key)

        self.base_url = self.config.get("base_url", "https://api.the-odds-api.com/v4")
        self.monthly_quota = int(self.config.get("monthly_quota", 500))
        self.cache_ttl = int(self.config.get("cache_ttl_seconds", 900))
        self.regions = self.config.get("regions", "us,eu")
        self.markets = self.config.get("markets", "h2h,spreads,totals")
        self.scheduled_markets = self.config.get("scheduled_markets", "auto")
        self.preferred_books = self.config.get("preferred_books", ["pinnacle", "draftkings", "fanduel"])
        self.sharp_qualified_books = self.config.get("sharp_qualified_books", ["pinnacle"])
        if not isinstance(self.sharp_qualified_books, list):
            self.sharp_qualified_books = ["pinnacle"]
        self.sharp_qualified_books = [str(book).strip().casefold() for book in self.sharp_qualified_books if str(book).strip()]

        self._cache_data: Dict[str, Any] = self._load_cache()

    def _resolve_api_key(self, explicit_arg: Optional[str] = None) -> Tuple[str, str]:
        if explicit_arg is not None:
            clean = explicit_arg.strip()
            return clean, ("EXPLICIT_ARG" if clean else "UNCONFIGURED")
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
        user_cfg = self._load_yaml(self.config_path)
        if user_cfg.get("api_key"):
            return str(user_cfg["api_key"]).strip(), "BASE_CONFIG"
        example_cfg = self._load_yaml(EXAMPLE_CONFIG_PATH)
        if example_cfg.get("api_key"):
            return str(example_cfg["api_key"]).strip(), "EXAMPLE_CONFIG"
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
        merged = self._load_yaml(EXAMPLE_CONFIG_PATH)
        merged.update(self._load_yaml(self.config_path))
        local_override = self._load_yaml(self.local_config_path)
        if local_override:
            merged.update(local_override)
        return merged

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {"usage": {}, "entries": {}, "metrics": {}}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {"usage": {}, "entries": {}, "metrics": {}}

    def _save_cache(self) -> None:
        try:
            # All writers hold file_lock(cache_path), which prevents cross-client
            # lost updates; direct write avoids Windows replace restrictions on
            # protected temporary directories used by local installs/tests.
            self.cache_path.write_text(json.dumps(self._cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save odds api cache: %s", exc)

    def _refresh_cache_locked(self) -> None:
        """Reload the shared state while the cache lock is held."""
        self._cache_data = self._load_cache()
        self._cache_data.setdefault("usage", {})
        self._cache_data.setdefault("entries", {})
        self._cache_data.setdefault("metrics", {})

    def _metric(self, name: str, amount: int = 1) -> None:
        metrics = self._cache_data.setdefault("metrics", {})
        metrics[name] = int(metrics.get(name, 0)) + amount

    def save_api_key(self, api_key: str) -> bool:
        """Save API key locally to config/odds_api.local.yaml."""
        ok = save_local_api_key(api_key, self.local_config_path)
        if ok:
            self.api_key = api_key.strip()
            self.key_source = "LOCAL_CONFIG"
        return ok

    def reload_api_key(self) -> None:
        """Reload credentials after a local key update without restarting the service."""
        self._explicit_api_key_override = False
        self.api_key, self.key_source = self._resolve_api_key()

    def get_masked_api_key(self) -> str:
        """Return safely masked API key for UI display (e.g. ***1a2b). Never exposes full key."""
        if not self.api_key:
            return ""
        if len(self.api_key) >= 4:
            return f"***{self.api_key[-4:]}"
        return "***"

    def _api_key_fingerprint(self) -> str:
        """Identify which credential last verified successfully without storing the key."""
        import hashlib
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest() if self.api_key else ""

    def get_official_remaining(self) -> int:
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        with file_lock(self.cache_path):
            self._refresh_cache_locked()
            month_usage = self._cache_data.get("usage", {}).get(month_key, 0)
            official_rem = self._official_remaining_for_month(month_key)
            return official_rem if official_rem is not None else max(0, min(self.monthly_quota, MONTHLY_BUDGET_TOTAL) - month_usage)

    def _official_remaining_for_month(self, month_key: str) -> Optional[int]:
        recorded_month = self._cache_data.get("requests_remaining_month_key")
        if not recorded_month:
            # Legacy cache files predate the explicit month tag. Infer only when
            # the timestamp is available; otherwise ignore the possibly stale header.
            last_success = self._cache_data.get("last_successful_fetch_utc")
            try:
                recorded_month = datetime.fromisoformat(last_success.replace("Z", "+00:00")).strftime("%Y-%m")
            except (AttributeError, ValueError):
                return None
        if recorded_month != month_key:
            return None
        value = self._cache_data.get("requests_remaining_official")
        return int(value) if value is not None else None

    def test_connection(self, fetch_sample: bool = False, sport_league: str = "NBA") -> Dict[str, Any]:
        """Verify API key and live connectivity.

        Default (fetch_sample=False) calls /v4/sports which costs ZERO (0) credits.
        If fetch_sample=True, queries 1 league with 'h2h' (costs 1 credit).
        Never exposes the API key.
        """
        with file_lock(self.cache_path):
            self._refresh_cache_locked()
            return self._test_connection_locked(fetch_sample, sport_league)

    def _test_connection_locked(self, fetch_sample: bool, sport_league: str) -> Dict[str, Any]:
        if not self.api_key and not self._explicit_api_key_override:
            self.reload_api_key()
        if not self.api_key:
            return {
                "success": False,
                "status": "UNCONFIGURED",
                "message": "尚未設定 The Odds API 金鑰。",
                "credits_consumed": 0,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }

        t0 = time.time()
        now_utc = datetime.now(timezone.utc)
        month_key = now_utc.strftime("%Y-%m")

        if not fetch_sample:
            # Zero-credit validation endpoint: /v4/sports
            url = f"{self.base_url}/sports/?apiKey={urllib.parse.quote(self.api_key)}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Sportslottery-Intelligence/4.5"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw_bytes = resp.read()
                    data = json.loads(raw_bytes.decode("utf-8"))
                    self._metric("successful_requests")
                    h_used = resp.headers.get("x-requests-used")
                    h_remaining = resp.headers.get("x-requests-remaining")

                    if h_used is not None:
                        try:
                            self._cache_data.setdefault("usage", {})[month_key] = int(h_used)
                        except ValueError:
                            pass
                    if h_remaining is not None:
                        try:
                            self._cache_data["requests_remaining_official"] = int(h_remaining)
                            self._cache_data["requests_remaining_month_key"] = month_key
                        except ValueError:
                            pass

                    self._cache_data["last_successful_fetch_utc"] = now_utc.isoformat()
                    self._cache_data["last_successful_key_fingerprint"] = self._api_key_fingerprint()
                    self._cache_data["last_error"] = None
                    self._cache_data["failure_streak"] = 0
                    self._cache_data.pop("retry_after_epoch", None)
                    self._cache_data.pop("retry_after_utc", None)
                    self._save_cache()

                    return {
                        "success": True,
                        "status": "LIVE_VERIFIED",
                        "message": f"API 金鑰驗證成功！可存取 {len(data)} 項國際運動賽事 (本次健康診斷消耗 0 credits)。",
                        "credits_consumed": 0,
                        "official_remaining": self._cache_data.get("requests_remaining_official"),
                        "official_used": self._cache_data.get("usage", {}).get(month_key, 0),
                        "latency_ms": int((time.time() - t0) * 1000),
                        "timestamp_utc": now_utc.isoformat(),
                    }
            except urllib.error.HTTPError as exc:
                err_text = f"HTTP {exc.code} {exc.reason}"
                try:
                    err_body = exc.read().decode("utf-8")
                    err_json = json.loads(err_body)
                    if "message" in err_json:
                        err_text = f"HTTP {exc.code}: {err_json['message']}"
                except Exception:
                    pass
                self._cache_data["last_error"] = err_text
                self._cache_data["last_error_key_fingerprint"] = self._api_key_fingerprint()
                self._cache_data["last_error_utc"] = now_utc.isoformat()
                self._save_cache()
                return {
                    "success": False,
                    "status": "LIVE_ERROR",
                    "error": err_text,
                    "credits_consumed": 0,
                    "timestamp_utc": now_utc.isoformat(),
                }
            except Exception as exc:
                err_text = str(exc)
                self._cache_data["last_error"] = err_text
                self._cache_data["last_error_key_fingerprint"] = self._api_key_fingerprint()
                self._cache_data["last_error_utc"] = now_utc.isoformat()
                self._save_cache()
                return {
                    "success": False,
                    "status": "LIVE_ERROR",
                    "error": err_text,
                    "credits_consumed": 0,
                    "timestamp_utc": now_utc.isoformat(),
                }
        else:
            # 1-credit sample fetch test
            self._refresh_cache_locked()
            month_usage = int(self._cache_data.get("usage", {}).get(month_key, 0))
            remaining = self._official_remaining_for_month(month_key)
            if remaining is None:
                remaining = max(0, min(self.monthly_quota, MONTHLY_BUDGET_TOTAL) - month_usage)
            if month_usage + 1 > min(self.monthly_quota, MONTHLY_BUDGET_TOTAL) or remaining < 1:
                return {
                    "success": False,
                    "status": "QUOTA_EXHAUSTED",
                    "message": "本月 The Odds API 額度不足，未執行付費測試。",
                    "credits_consumed": 0,
                    "timestamp_utc": now_utc.isoformat(),
                }
            league_norm = sport_league.upper().strip()
            sport_key = SPORT_KEY_MAP.get(league_norm, "basketball_nba")
            params = {
                "apiKey": self.api_key,
                "regions": "us",
                "markets": "h2h",
                "oddsFormat": "decimal",
            }
            url = f"{self.base_url}/sports/{sport_key}/odds/?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Sportslottery-Intelligence/4.5"})
                self._metric("api_requests")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw_bytes = resp.read()
                    data = json.loads(raw_bytes.decode("utf-8"))
                    self._metric("successful_requests")
                    h_used = resp.headers.get("x-requests-used")
                    h_remaining = resp.headers.get("x-requests-remaining")
                    h_last = resp.headers.get("x-requests-last")

                    credits_last = int(h_last) if h_last is not None else 1
                    self._cache_data["requests_last_official"] = credits_last
                    self._cache_data["requests_last_accounting_source"] = (
                        "OFFICIAL_HEADERS" if h_last is not None or h_used is not None else "ESTIMATED"
                    )
                    if h_used is not None:
                        try:
                            self._cache_data.setdefault("usage", {})[month_key] = int(h_used)
                        except ValueError:
                            pass
                    if h_remaining is not None:
                        try:
                            self._cache_data["requests_remaining_official"] = int(h_remaining)
                            self._cache_data["requests_remaining_month_key"] = month_key
                        except ValueError:
                            pass

                    self._cache_data["last_successful_fetch_utc"] = now_utc.isoformat()
                    self._cache_data["last_successful_key_fingerprint"] = self._api_key_fingerprint()
                    self._cache_data["last_error"] = None
                    self._cache_data["failure_streak"] = 0
                    self._cache_data.pop("retry_after_epoch", None)
                    self._cache_data.pop("retry_after_utc", None)
                    self._save_cache()

                    return {
                        "success": True,
                        "status": "LIVE_VERIFIED",
                        "message": f"成功獲取 {league_norm} 真實盤口 {len(data)} 場 (消耗 {credits_last} credit)。",
                        "credits_consumed": credits_last,
                        "official_remaining": self._cache_data.get("requests_remaining_official"),
                        "official_used": self._cache_data.get("usage", {}).get(month_key, 0),
                        "latency_ms": int((time.time() - t0) * 1000),
                        "timestamp_utc": now_utc.isoformat(),
                    }
            except Exception as exc:
                err_text = str(exc)
                self._record_request_failure(err_text, exc)
                self._cache_data["last_error"] = err_text
                self._cache_data["last_error_key_fingerprint"] = self._api_key_fingerprint()
                self._cache_data["last_error_utc"] = now_utc.isoformat()
                return {
                    "success": False,
                    "status": "LIVE_ERROR",
                    "error": err_text,
                    "credits_consumed": 0,
                    "timestamp_utc": now_utc.isoformat(),
                }

    def get_source_status(self) -> Dict[str, Any]:
        """Return operational capabilities and quota metrics with strict mode distinctions."""
        if not self.api_key and not self._explicit_api_key_override:
            self.reload_api_key()
        with file_lock(self.cache_path):
            self._refresh_cache_locked()
            return self._get_source_status_locked()

    def _get_source_status_locked(self) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        month_key = now_utc.strftime("%Y-%m")
        month_usage = self._cache_data.get("usage", {}).get(month_key, 0)
        has_key = bool(self.api_key)
        official_rem = self._official_remaining_for_month(month_key)
        remaining_est = official_rem if official_rem is not None else max(0, min(self.monthly_quota, MONTHLY_BUDGET_TOTAL) - month_usage)
        has_successful_fetch = bool(
            has_key
            and self._cache_data.get("last_successful_fetch_utc")
            and self._cache_data.get("last_successful_key_fingerprint") == self._api_key_fingerprint()
        )
        last_error = self._cache_data.get("last_error")
        if not has_key or self._cache_data.get("last_error_key_fingerprint") != self._api_key_fingerprint():
            last_error = None

        if not has_key:
            mode = "UNCONFIGURED"
        elif remaining_est <= 0 or month_usage >= self.monthly_quota:
            mode = "QUOTA_EXHAUSTED"
        elif remaining_est <= MANUAL_RESERVE_CREDITS:
            mode = "QUOTA_SAFETY_PAUSE"
        elif has_successful_fetch:
            mode = "LIVE_VERIFIED"
        elif last_error:
            mode = "LIVE_ERROR"
        else:
            mode = "KEY_CONFIGURED_UNVERIFIED"

        # Days remaining in current month
        year = now_utc.year
        month = now_utc.month
        if month == 12:
            next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        days_remaining = max(1, (next_month.date() - now_utc.date()).days)

        schedulable_credits = max(0, remaining_est - MANUAL_RESERVE_CREDITS)
        daily_schedulable_budget = round(schedulable_credits / days_remaining, 1)

        return {
            "source_id": "the_odds_api",
            "is_configured": has_key,
            "has_api_key": has_key,
            "key_masked": self.get_masked_api_key(),
            "key_source": self.key_source,
            "monthly_quota": self.monthly_quota,
            "monthly_budget": MONTHLY_BUDGET_TOTAL,
            "manual_reserve_credits": MANUAL_RESERVE_CREDITS,
            "automated_budget_credits": MAX_AUTOMATED_BUDGET_CREDITS,
            "requests_used_this_month": month_usage,
            "requests_remaining_est": remaining_est,
            "official_remaining": official_rem,
            "requests_last_consumed": self._cache_data.get("requests_last_official", 0),
            "requests_last_accounting_source": self._cache_data.get("requests_last_accounting_source", "UNKNOWN"),
            "days_remaining_in_month": days_remaining,
            "daily_schedulable_budget": daily_schedulable_budget,
            "cache_ttl_seconds": self.cache_ttl,
            "operating_mode": mode,
            "is_live_verified": has_successful_fetch,
            "last_successful_fetch_utc": self._cache_data.get("last_successful_fetch_utc") if has_successful_fetch else None,
            "last_live_fetch_utc": self._cache_data.get("last_live_fetch_utc"),
            "last_error": last_error,
            "last_error_utc": self._cache_data.get("last_error_utc"),
            "last_query_summary": self._cache_data.get("last_query_summary"),
            "request_metrics": dict(self._cache_data.get("metrics", {})),
            "retry_after_utc": self._cache_data.get("retry_after_utc"),
            "supported_sports": list(SPORT_KEY_MAP.keys()),
        }

    def fetch_market_odds(
        self,
        sport_league: str,
        markets: Optional[str] = None,
        force_refresh: bool = False,
        automated: bool = False,
    ) -> List[MarketOddsSnapshot]:
        """Fetch market odds for a given sport league, or return synthetic fixtures if unconfigured."""
        # Hold one cross-process lock through lookup, network fetch, and persistence.
        # A waiter reloads the cache after the winner completes, so concurrent clients
        # share one request and cannot overwrite newer quota headers with stale state.
        started_at = time.time()
        with file_lock(self.cache_path):
            self._refresh_cache_locked()
            return self._fetch_market_odds_locked(sport_league, markets, force_refresh, automated, started_at)

    def _fetch_market_odds_locked(
        self,
        sport_league: str,
        markets: Optional[str],
        force_refresh: bool,
        automated: bool,
        started_at: float,
    ) -> List[MarketOddsSnapshot]:
        league_norm = sport_league.upper().strip()
        sport_key = SPORT_KEY_MAP.get(league_norm, SPORT_KEY_MAP.get(sport_league.lower()))

        if not sport_key:
            logger.info("Unsupported sport/league for The Odds API: %s", sport_league)
            return []

        # Check API key presence
        if not self.api_key and not self._explicit_api_key_override:
            self.reload_api_key()
        if not self.api_key:
            logger.info("No ODDS_API_KEY configured; serving standardized synthetic fixtures for %s", league_norm)
            return self._generate_synthetic_fixtures(league_norm)

        scheduled_markets = str(self.scheduled_markets or "auto").strip()
        default_markets = self.markets if scheduled_markets.casefold() in {"auto", "candidate", "candidate_driven"} else scheduled_markets
        target_markets = markets or default_markets or "h2h"
        regions = str(self.regions or "us")
        query_key = f"{sport_key}|{regions}|{target_markets}"
        # Check shared cache TTL. A force-refresh caller that waited behind a
        # request started after it arrived joins that in-flight result.
        now_ts = time.time()
        cached_entry = self._cache_data.get("entries", {}).get(query_key)
        if cached_entry:
            fetched_at = cached_entry.get("fetched_at", 0)
            is_fresh = (now_ts - fetched_at) < self.cache_ttl
            coalesced = fetched_at >= started_at
            if is_fresh and (not force_refresh or coalesced):
                self._metric("coalesced_requests" if coalesced else "cache_hits")
                self._save_cache()
                logger.debug("Returning cached odds for %s (age %.1fs)", sport_key, now_ts - fetched_at)
                return [MarketOddsSnapshot(**item) for item in cached_entry.get("snapshots", [])]

        # Check Quota & Safety Pause
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        used = int(self._cache_data.setdefault("usage", {}).get(month_key, 0))
        official_rem = self._official_remaining_for_month(month_key)
        remaining = official_rem if official_rem is not None else max(0, min(self.monthly_quota, MONTHLY_BUDGET_TOTAL) - used)
        estimated_cost = len([m for m in target_markets.split(",") if m.strip()]) * len([r for r in regions.split(",") if r.strip()])
        if estimated_cost <= 0:
            estimated_cost = 1
        auto_ceiling = min(MAX_AUTOMATED_BUDGET_CREDITS, self.monthly_quota, MONTHLY_BUDGET_TOTAL)
        hard_ceiling = min(self.monthly_quota, MONTHLY_BUDGET_TOTAL)
        retry_after = self._cache_data.get("retry_after_epoch", 0)
        if retry_after and now_ts < retry_after:
            self._metric("backoff_skips")
            self._save_cache()
            return self._generate_synthetic_fixtures(league_norm)
        if (
            used + estimated_cost > hard_ceiling
            or remaining < estimated_cost
            or (automated and (used + estimated_cost > auto_ceiling or remaining - estimated_cost < MANUAL_RESERVE_CREDITS))
        ):
            logger.warning(
                "Monthly quota protection triggered for The Odds API (%d/%d used, %d remaining, estimated cost %d, automated=%s); falling back to synthetic",
                used, hard_ceiling, remaining, estimated_cost, automated
            )
            self._metric("quota_skips")
            self._save_cache()
            return self._generate_synthetic_fixtures(league_norm)

        # Call live API
        try:
            params = {
                "apiKey": self.api_key,
                "regions": regions,
                "markets": target_markets,
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            url = f"{self.base_url}/sports/{sport_key}/odds/?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Sportslottery-Intelligence/4.0"})
            self._metric("api_requests")
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                self._metric("successful_requests")

                # Track usage from official response headers when available
                h_used = resp.headers.get("x-requests-used")
                h_remaining = resp.headers.get("x-requests-remaining")
                h_last = resp.headers.get("x-requests-last")

                credits_last = int(h_last) if h_last is not None else estimated_cost
                self._cache_data["requests_last_official"] = credits_last
                credit_accounting_source = (
                    "OFFICIAL_HEADERS" if h_last is not None or h_used is not None else "ESTIMATED"
                )
                self._cache_data["requests_last_accounting_source"] = credit_accounting_source

                if h_used is not None:
                    try:
                        self._cache_data["usage"][month_key] = int(h_used)
                    except ValueError:
                        self._cache_data["usage"][month_key] = used + credits_last
                else:
                    self._cache_data["usage"][month_key] = used + credits_last

                if h_remaining is not None:
                    try:
                        self._cache_data["requests_remaining_official"] = int(h_remaining)
                        self._cache_data["requests_remaining_month_key"] = month_key
                    except ValueError:
                        pass

                now_iso = datetime.now(timezone.utc).isoformat()
                self._cache_data["last_live_fetch_utc"] = now_iso
                self._cache_data["last_successful_fetch_utc"] = now_iso
                self._cache_data["last_successful_key_fingerprint"] = self._api_key_fingerprint()
                self._cache_data["last_error"] = None
                self._cache_data["last_query_summary"] = {
                    "sport": sport_key,
                    "league": league_norm,
                    "regions": regions,
                    "markets": target_markets,
                    "events_count": len(data),
                    "snapshots_count": 0,
                    "credits_consumed": credits_last,
                    "credit_accounting_source": credit_accounting_source,
                    "is_synthetic": False,
                }

                snapshots = self._parse_api_payload(data, league_norm)

                # Update cache
                self._cache_data["entries"][query_key] = {
                    "fetched_at": now_ts,
                    "sport_key": sport_key,
                    "regions": regions,
                    "markets": target_markets,
                    "snapshots": [s.to_dict() for s in snapshots],
                }
                self._cache_data.pop("retry_after_epoch", None)
                self._cache_data.pop("retry_after_utc", None)
                self._cache_data["failure_streak"] = 0
                self._save_cache()
                return snapshots

        except urllib.error.HTTPError as exc:
            err_text = f"HTTP {exc.code} {exc.reason}"
            try:
                err_body = exc.read().decode("utf-8")
                err_json = json.loads(err_body)
                if "message" in err_json:
                    err_text = f"HTTP {exc.code}: {err_json['message']}"
            except Exception:
                pass
            self._record_request_failure(err_text, exc)
            self._cache_data["last_error"] = err_text
            self._cache_data["last_error_key_fingerprint"] = self._api_key_fingerprint()
            self._cache_data["last_error_utc"] = datetime.now(timezone.utc).isoformat()
            logger.warning("The Odds API HTTP error for %s: %s; using synthetic fixtures", sport_key, err_text)
            return self._generate_synthetic_fixtures(league_norm)
        except Exception as exc:
            err_text = str(exc)
            self._record_request_failure(err_text, exc)
            self._cache_data["last_error"] = err_text
            self._cache_data["last_error_key_fingerprint"] = self._api_key_fingerprint()
            self._cache_data["last_error_utc"] = datetime.now(timezone.utc).isoformat()
            logger.warning("Error fetching live odds from The Odds API for %s: %s; using synthetic fixtures", sport_key, err_text)
            return self._generate_synthetic_fixtures(league_norm)

    def _record_request_failure(self, message: str, exc: Exception) -> None:
        self._metric("request_failures")
        streak = min(8, int(self._cache_data.get("failure_streak", 0)) + 1)
        self._cache_data["failure_streak"] = streak
        delay = min(300, 15 * (2 ** (streak - 1)))
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = min(3600, max(delay, int(retry_after)))
            except (TypeError, ValueError):
                pass
        retry_at = time.time() + delay
        self._cache_data["retry_after_epoch"] = retry_at
        self._cache_data["retry_after_utc"] = datetime.fromtimestamp(retry_at, timezone.utc).isoformat()
        self._save_cache()

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

                for mkt in bm.get("markets", []):
                    mkt_key = mkt.get("key")
                    outcomes = mkt.get("outcomes", [])
                    # The bookmaker-level last_update field is deprecated and
                    # can be shared across markets with different quote ages.
                    # Preserve the market timestamp and fail closed when it is
                    # missing or timezone-free.
                    observed_at_utc = None
                    market_freshness = MarketFreshnessStatus.UNKNOWN.value
                    raw_market_update = mkt.get("last_update")
                    if raw_market_update:
                        try:
                            market_update_dt = datetime.fromisoformat(
                                str(raw_market_update).replace("Z", "+00:00")
                            )
                            if market_update_dt.tzinfo is not None:
                                market_update_dt = market_update_dt.astimezone(timezone.utc)
                                observed_at_utc = market_update_dt.isoformat()
                                age_seconds = (datetime.now(timezone.utc) - market_update_dt).total_seconds()
                                if age_seconds < -300 or age_seconds > 900:
                                    market_freshness = MarketFreshnessStatus.STALE.value
                                elif age_seconds > 300:
                                    market_freshness = MarketFreshnessStatus.AGING.value
                                elif age_seconds > 120:
                                    market_freshness = MarketFreshnessStatus.FRESH.value
                                else:
                                    market_freshness = MarketFreshnessStatus.LIVE.value
                        except (TypeError, ValueError, OverflowError):
                            pass

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
                                    observed_at_utc=observed_at_utc,
                                    retrieved_at_utc=retrieved_at,
                                    freshness_status=market_freshness,
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
                                    observed_at_utc=observed_at_utc,
                                    retrieved_at_utc=retrieved_at,
                                    freshness_status=market_freshness,
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
                                    observed_at_utc=observed_at_utc,
                                    retrieved_at_utc=retrieved_at,
                                    freshness_status=market_freshness,
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
