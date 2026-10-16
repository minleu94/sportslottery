#!/usr/bin/env python3
"""ESPN Pythagorean MLB Model (Local Fallback Model).

IMPORTANT PROVENANCE DISCLOSURE:
This is a LOCAL STATISTICAL FALLBACK MODEL using ESPN standings statistics
and Bill James' classic Pythagorean Expectation formula.
It is NOT an official ML prediction engine from `pybaseball`.
Data Source: ESPN Live Standings / Cached Season Aggregates.
Independence Group: ESPN_SEASON_STATS
Source Category: LOCAL_FALLBACK_MODEL
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from core.identity import GLOBAL_TEAM_REGISTRY
from integrations.common.models import PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "cache")
MLB_CACHE_FILE = os.path.join(CACHE_DIR, "espn_mlb_standings.json")
CACHE_TTL = 43200  # 12 hours
PYTH_EXPONENT = 1.83
LEAGUE_AVG_RUNS = 4.45


class ESPNPythagoreanMLBModel:
    """Evaluates MLB TaiwanLeg betting options using real team stats and Pythagorean expectations.

    Declared as a LOCAL_FALLBACK_MODEL. Belongs to the ESPN_SEASON_STATS independence group.
    """

    SOURCE_CATEGORY = "LOCAL_FALLBACK_MODEL"
    INDEPENDENCE_GROUP = "ESPN_SEASON_STATS"
    ENGINE_NAME = "ESPN Pythagorean Expectation (Local Fallback)"

    def __init__(self, cache_file: str = MLB_CACHE_FILE):
        self.version = "1.0.0"
        self.cache_file = cache_file
        self._stats_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._cache_meta: Dict[str, Any] = {"source_status": "UNKNOWN", "observed_at": None, "season": None}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        })

    def _get_mlb_stats(self) -> Dict[str, Dict[str, float]]:
        now = time.time()
        observed_epoch = self._parse_epoch(self._cache_meta.get("timestamp"))
        if self._stats_cache is not None and observed_epoch is not None and 0 <= now - observed_epoch < CACHE_TTL:
            return self._stats_cache

        stale_stats = self._stats_cache
        stale_meta = dict(self._cache_meta)
        # A process cache follows the same TTL as the on-disk snapshot.
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cached_stats = data.get("teams", {})
                cached_epoch = self._parse_epoch(data.get("timestamp"))
                if isinstance(cached_stats, dict) and cached_stats:
                    cached_observed = data.get("observed_at")
                    if not cached_observed and cached_epoch is not None:
                        cached_observed = datetime.fromtimestamp(cached_epoch, timezone.utc).isoformat()
                    cached_meta = {"timestamp": cached_epoch, "observed_at": cached_observed,
                                   "season": data.get("season"), "source_status": "CACHED",
                                   "data_as_of": cached_observed}
                    if cached_epoch is not None and 0 <= now - cached_epoch < CACHE_TTL:
                        self._stats_cache, self._cache_meta = cached_stats, cached_meta
                        return self._stats_cache
                    stale_stats, stale_meta = cached_stats, cached_meta
            except Exception as exc:
                logger.warning("Error reading MLB cache: %s", exc)

        url = "https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings"
        failure_status = "UNKNOWN"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                failure_status = f"HTTP_{resp.status_code}"
                raise ValueError(failure_status)
            payload = resp.json()
            extracted = self._parse_espn_standings(payload)
            if extracted:
                observed_at = datetime.now(timezone.utc).isoformat()
                timestamp = time.time()
                season = self._season_from_payload(payload)
                os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump({"timestamp": timestamp, "observed_at": observed_at, "data_as_of": observed_at,
                               "season": season, "source_url": url, "teams": extracted},
                              f, indent=2, ensure_ascii=False)
                self._stats_cache = extracted
                self._cache_meta = {"timestamp": timestamp, "observed_at": observed_at,
                                    "data_as_of": observed_at, "season": season, "source_status": "LIVE",
                                    "failure_status": None}
                return extracted
            failure_status = "PARSE_EMPTY"
        except Exception as exc:
            if failure_status == "UNKNOWN":
                failure_status = "FETCH_ERROR"
            logger.warning("Failed to fetch live MLB standings: %s", exc)

        # Preserve stale observations for reference, but never present them as fusion-ready.
        if stale_stats:
            self._stats_cache = stale_stats
            self._cache_meta = stale_meta
            self._cache_meta["source_status"] = "STALE" if self._cache_meta.get("observed_at") else "UNKNOWN"
            self._cache_meta["failure_status"] = failure_status
            return stale_stats

        self._stats_cache = {}
        self._cache_meta = {"source_status": failure_status, "failure_status": failure_status,
                            "observed_at": None, "data_as_of": None, "season": None}
        return {}

    @staticmethod
    def _parse_epoch(value: Any) -> Optional[float]:
        try:
            result = float(value)
            return result if math.isfinite(result) and result > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _season_from_payload(raw_data: Dict[str, Any]) -> Optional[int]:
        season = raw_data.get("season") if isinstance(raw_data, dict) else None
        if isinstance(season, dict):
            season = season.get("year") or season.get("name") or season.get("displayName")
        try:
            return int(str(season)[:4])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _event_datetime(leg: TaiwanLeg) -> Optional[datetime]:
        value = getattr(leg, "start_time_utc", None)
        if not value:
            return None
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return result.astimezone(timezone.utc) if result.tzinfo else None
        except ValueError:
            return None

    def _parse_espn_standings(self, raw_data: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        teams: Dict[str, Dict[str, float]] = {}

        def walk(node: Dict[str, Any]):
            if "standings" in node and "entries" in node["standings"]:
                for e in node["standings"]["entries"]:
                    tm = e.get("team", {})
                    name = tm.get("displayName", "")
                    abbr = tm.get("abbreviation", "")
                    stats = {s.get("name"): s.get("value") for s in e.get("stats", [])}
                    try:
                        rs, ra, gp = (float(stats[key]) for key in ("pointsFor", "pointsAgainst", "gamesPlayed"))
                        win_pct = float(stats["winPercent"]) if stats.get("winPercent") is not None else None
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not all(math.isfinite(value) for value in (rs, ra, gp)) or gp <= 0 or rs <= 0 or ra <= 0:
                        continue

                    can_team = GLOBAL_TEAM_REGISTRY.resolve(name, sport="baseball", league="MLB") or \
                               GLOBAL_TEAM_REGISTRY.resolve(abbr, sport="baseball", league="MLB")
                    key = can_team.canonical_id if can_team else name

                    teams[key] = {
                        "runs_scored": rs,
                        "runs_allowed": ra,
                        "games": gp,
                        "win_pct": win_pct,
                        "team_name": name,
                    }
            for child in node.get("children", []):
                walk(child)

        walk(raw_data)
        return teams

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate an MLB TaiwanLeg option using real team stats."""
        if leg.sport != "baseball" or "MLB" not in leg.league:
            return None

        stats_map = self._get_mlb_stats()
        if not stats_map:
            logger.info("No MLB stats available; model returning None")
            return None

        can_away = GLOBAL_TEAM_REGISTRY.resolve(leg.away_team, sport="baseball", league="MLB")
        can_home = GLOBAL_TEAM_REGISTRY.resolve(leg.home_team, sport="baseball", league="MLB")

        away_id = can_away.canonical_id if can_away else leg.away_team
        home_id = can_home.canonical_id if can_home else leg.home_team

        away_stats = stats_map.get(away_id)
        home_stats = stats_map.get(home_id)

        if not away_stats or not home_stats:
            logger.info("Missing stats for %s or %s; model returning None", away_id, home_id)
            return None

        event_dt = self._event_datetime(leg)
        observed_at = self._cache_meta.get("observed_at")
        observed_dt = None
        try:
            parsed_observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")) if observed_at else None
            observed_dt = parsed_observed.astimezone(timezone.utc) if parsed_observed and parsed_observed.tzinfo else None
        except ValueError:
            pass
        event_season = event_dt.year if event_dt else None
        source_season = self._cache_meta.get("season")
        season_matches = event_season is not None and source_season == event_season
        status = self._cache_meta.get("source_status", "UNKNOWN")
        age_seconds = time.time() - self._parse_epoch(self._cache_meta.get("timestamp")) if self._parse_epoch(self._cache_meta.get("timestamp")) is not None else None
        pre_event_observation = bool(event_dt and observed_dt and observed_dt < event_dt)
        fusion_ready = bool(status in {"LIVE", "CACHED"} and age_seconds is not None and 0 <= age_seconds < CACHE_TTL
                            and pre_event_observation and season_matches)

        # Genuine calculations from real data
        away_rs_pg = away_stats["runs_scored"] / away_stats["games"]
        away_ra_pg = away_stats["runs_allowed"] / away_stats["games"]
        home_rs_pg = home_stats["runs_scored"] / home_stats["games"]
        home_ra_pg = home_stats["runs_allowed"] / home_stats["games"]

        # Expected runs per team
        off_away = away_rs_pg / LEAGUE_AVG_RUNS
        def_away = away_ra_pg / LEAGUE_AVG_RUNS
        off_home = home_rs_pg / LEAGUE_AVG_RUNS
        def_home = home_ra_pg / LEAGUE_AVG_RUNS

        xr_home = round(off_home * def_away * LEAGUE_AVG_RUNS * 1.04, 2)
        xr_away = round(off_away * def_home * LEAGUE_AVG_RUNS * 0.96, 2)

        # Bill James Pythagorean win expectancy
        p_home_pyth = (xr_home ** PYTH_EXPONENT) / (xr_home ** PYTH_EXPONENT + xr_away ** PYTH_EXPONENT)
        p_away_pyth = 1.0 - p_home_pyth

        # Map to specific TaiwanLeg market & selection
        market = leg.market
        side = leg.side
        taiwan_odds = leg.taiwan_odds
        market_implied = 1.0 / taiwan_odds if taiwan_odds > 1.0 else 0.50

        model_prob: Optional[float] = None
        if market == "不讓分":
            if side == "主":
                model_prob = p_home_pyth
            elif side == "客":
                model_prob = p_away_pyth
        elif market == "大小":
            if side not in {"大", "小"} or leg.line is None:
                return None
            total_xr = xr_home + xr_away
            try:
                line_val = float(leg.line)
            except (TypeError, ValueError):
                return None
            delta = total_xr - line_val
            p_over = max(0.15, min(0.85, 0.50 + delta * 0.08))
            model_prob = p_over if side == "大" else 1.0 - p_over

        if model_prob is None:
            return None

        model_prob = round(max(0.05, min(0.95, model_prob)), 3)
        edge = round((model_prob - market_implied) * 100.0, 1)

        confidence = ("MED" if edge >= 0.0 else "LOW") if fusion_ready else "REFERENCE_ONLY"

        return PredictionSignal(
            source_id="espn_pythagorean_mlb",
            source_name="ESPN 畢氏定理模型 (Local Fallback)",
            source_type="MODEL",
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=model_prob,
            score=edge,
            confidence=confidence,
            pick=leg.selection,
            source_category=self.SOURCE_CATEGORY,
            independence_group=self.INDEPENDENCE_GROUP,
            data_as_of=self._cache_meta.get("data_as_of"),
            data_age_hours=round(age_seconds / 3600, 2) if age_seconds is not None else None,
            freshness_status="FRESH" if fusion_ready else "STALE" if status == "STALE" else "UNKNOWN",
            quality_label="MODEL_EXPERIMENTAL" if fusion_ready else "MODEL_STALE",
            metadata={
                "model_category": self.SOURCE_CATEGORY,
                "independence_group": self.INDEPENDENCE_GROUP,
                "engine_name": self.ENGINE_NAME,
                "data_source": "ESPN Standings Live / Season Stats",
                "source_url": "https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings",
                "source_status": status,
                "failure_status": self._cache_meta.get("failure_status"),
                "observed_at": observed_at,
                "data_as_of": self._cache_meta.get("data_as_of"),
                "data_as_of_semantics": "ESPN season standings snapshot observation time; not a historical event cutoff",
                "aggregate_season_stats": True,
                "cache_age_hours": round(age_seconds / 3600, 2) if age_seconds is not None else None,
                "source_season": source_season,
                "event_season": event_season,
                "season_matches": season_matches,
                "point_in_time_status": "VALID" if fusion_ready else "REFERENCE_ONLY",
                "initialized": fusion_ready,
                "empirically_calibrated": False,
                "away_team": away_stats["team_name"],
                "home_team": home_stats["team_name"],
                "projected_away_runs": xr_away,
                "projected_home_runs": xr_home,
                "pyth_win_prob_home": round(p_home_pyth, 3),
                "pyth_win_prob_away": round(p_away_pyth, 3),
                "market_implied_prob": round(market_implied, 3),
                "edge_pp": edge,
                "away_pitcher": leg.away_pitcher,
                "home_pitcher": leg.home_pitcher,
            },
        )


# Backward-compatible alias
PybaseballMLBAdapter = ESPNPythagoreanMLBModel
