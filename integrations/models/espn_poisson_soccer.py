#!/usr/bin/env python3
"""ESPN Poisson Soccer Fallback Model (Local Fallback Model).

IMPORTANT PROVENANCE DISCLOSURE:
This is a LOCAL STATISTICAL FALLBACK MODEL using ESPN soccer standings
and basic univariate Poisson distributions to estimate match outcome probabilities.
It is NOT an official external multi-variate ML engine.
Data Source: ESPN Live Standings / Cached Season Aggregates.
Independence Group: ESPN_SEASON_STATS
Source Category: LOCAL_FALLBACK_MODEL
"""

from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from scipy.stats import poisson

from core.identity import GLOBAL_TEAM_REGISTRY
from core.persistence import atomic_write_bytes
from integrations.common.models import PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "cache")
CACHE_TTL = 43200  # 12 hours

LEAGUE_CODE_MAP = {
    "PREMIER": "eng.1",
    "CHAMPIONS": "uefa.champions",
    "MLS": "usa.1",
    "usa.1": "usa.1",
    "MAJOR LEAGUE SOCCER": "usa.1",
    "LALIGA": "esp.1",
    "esp.1": "esp.1",
    "英超": "eng.1",
    "西甲": "esp.1",
    "義甲": "ita.1",
    "德甲": "ger.1",
    "法甲": "fra.1",
    "歐冠": "uefa.champions",
    "英格蘭超級聯賽": "eng.1",
    "西班牙甲級聯賽": "esp.1",
}


class ESPNPoissonSoccerFallback:
    """Evaluates soccer TaiwanLeg betting options using real team stats and univariate Poisson distributions.

    Declared as a LOCAL_FALLBACK_MODEL. Belongs to the ESPN_SEASON_STATS independence group.
    """

    SOURCE_CATEGORY = "LOCAL_FALLBACK_MODEL"
    INDEPENDENCE_GROUP = "ESPN_SEASON_STATS"
    ENGINE_NAME = "ESPN Soccer Standings Poisson (Local Fallback)"

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.version = "1.0.0"
        self.cache_dir = cache_dir
        self._league_caches: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._cache_meta: Dict[str, Dict[str, Any]] = {}
        self._parse_audit: Dict[str, Any] = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        })

    def _resolve_league_code(self, league_name: str) -> Optional[str]:
        name = str(league_name or "").strip().casefold()
        for alias, code in LEAGUE_CODE_MAP.items():
            if name == alias.casefold() or name == code.casefold():
                return code
        return None

    def _get_soccer_stats(self, league_code: str) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        memory_meta = self._cache_meta.get(league_code, {})
        memory_epoch = self._parse_epoch(memory_meta.get("timestamp"))
        if league_code in self._league_caches and memory_epoch is not None and 0 <= now - memory_epoch < CACHE_TTL:
            return self._league_caches[league_code]

        cache_file = os.path.join(self.cache_dir, f"espn_soccer_{league_code}.json")
        stale_stats = self._league_caches.get(league_code)
        stale_meta = dict(memory_meta)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cached_stats = data.get("teams", {})
                cached_epoch = self._parse_epoch(data.get("timestamp"))
                cache_verified = (data.get("league_code") == league_code
                                  and isinstance(data.get("source_content_sha256"), str)
                                  and bool(re.fullmatch(r"[0-9a-f]{64}", data["source_content_sha256"]))
                                  and isinstance(data.get("parse_audit"), dict)
                                  and (league_code != "usa.1" or data.get("mls_scope_verified") is True)
                                  and isinstance(cached_stats, dict) and bool(cached_stats)
                                  and all(isinstance(row, dict) and row.get("provider_team_id")
                                          for row in cached_stats.values()))
                if cache_verified:
                    cached_observed = data.get("observed_at")
                    if not cached_observed and cached_epoch is not None:
                        cached_observed = datetime.fromtimestamp(cached_epoch, timezone.utc).isoformat()
                    cached_meta = {"timestamp": cached_epoch, "observed_at": cached_observed,
                                   "data_as_of": cached_observed, "season": data.get("season"),
                                   "source_url": data.get("source_url"),
                                   "source_content_sha256": data.get("source_content_sha256"),
                                   "parse_audit": data.get("parse_audit"),
                                   "source_status": "CACHED"}
                    if cached_epoch is not None and 0 <= now - cached_epoch < CACHE_TTL:
                        self._league_caches[league_code] = cached_stats
                        self._cache_meta[league_code] = cached_meta
                        return self._league_caches[league_code]
                    stale_stats, stale_meta = cached_stats, cached_meta
                elif cached_stats:
                    logger.info("Ignoring legacy or unverified ESPN cache for %s", league_code)
            except Exception as exc:
                logger.warning("Error reading soccer cache for %s: %s", league_code, exc)

        url = f"https://site.api.espn.com/apis/v2/sports/soccer/{league_code}/standings"
        failure_status = "UNKNOWN"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                failure_status = f"HTTP_{resp.status_code}"
                raise ValueError(failure_status)
            source_content_sha256 = hashlib.sha256(resp.content).hexdigest()
            payload = resp.json()
            if league_code == "usa.1" and (payload.get("uid") != "s:600~l:770" or payload.get("abbreviation") != "MLS"):
                raise ValueError("MLS source league identity mismatch")
            teams = self._parse_soccer_standings(payload, league_code=league_code)
            if teams:
                observed_at = datetime.now(timezone.utc).isoformat()
                timestamp = time.time()
                season = self._season_from_payload(payload)
                os.makedirs(self.cache_dir or ".", exist_ok=True)
                # Preserve the exact public response behind the forecast source hash.
                raw_path = os.path.join(self.cache_dir, "source_payloads", source_content_sha256 + ".json")
                atomic_write_bytes(raw_path, resp.content)
                cache_payload = {"league_code": league_code, "timestamp": timestamp, "observed_at": observed_at,
                                 "data_as_of": observed_at, "season": season, "source_url": url,
                                 "source_content_sha256": source_content_sha256,
                                 "source_payload_path": raw_path,
                                 "parse_audit": dict(self._parse_audit), "mls_scope_verified": league_code == "usa.1", "teams": teams}
                atomic_write_bytes(cache_file, json.dumps(cache_payload, indent=2, ensure_ascii=False).encode("utf-8"))
                self._league_caches[league_code] = teams
                self._cache_meta[league_code] = {"timestamp": timestamp, "observed_at": observed_at,
                                                 "data_as_of": observed_at, "season": season,
                                                 "source_url": url, "source_content_sha256": source_content_sha256,
                                                 "parse_audit": dict(self._parse_audit),
                                                 "source_status": "LIVE", "failure_status": None}
                return teams
            failure_status = "PARSE_EMPTY"
        except Exception as exc:
            if failure_status == "UNKNOWN":
                failure_status = "FETCH_ERROR"
            logger.warning("Failed to fetch live soccer standings for %s: %s", league_code, exc)

        if stale_stats:
            self._league_caches[league_code] = stale_stats
            self._cache_meta[league_code] = stale_meta
            self._cache_meta[league_code]["source_status"] = "STALE" if stale_meta.get("observed_at") else "UNKNOWN"
            self._cache_meta[league_code]["failure_status"] = failure_status
            return stale_stats

        self._league_caches[league_code] = {}
        self._cache_meta[league_code] = {"timestamp": None, "observed_at": None, "data_as_of": None,
                                         "season": None, "source_status": failure_status,
                                         "failure_status": failure_status}
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
        """Read a single consistent season from root or nested standings groups."""
        seasons: set[int] = set()
        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            for candidate in (node.get("season"), (node.get("standings") or {}).get("season")
                              if isinstance(node.get("standings"), dict) else None):
                if isinstance(candidate, dict):
                    candidate = candidate.get("year") or candidate.get("name") or candidate.get("displayName")
                match = re.search(r"\b(\d{4})(?:[-/](\d{4}))?\b", str(candidate or ""))
                if match:
                    seasons.add(int(match.group(1)))
            for child in node.get("children", []) if isinstance(node.get("children", []), list) else []:
                visit(child)
        visit(raw_data)
        return next(iter(seasons)) if len(seasons) == 1 else None

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

    def _parse_soccer_standings(self, raw_data: Dict[str, Any], *, league_code: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """Flatten ESPN conference/division standings without defaulting absent stats.

        ESPN's usa.1 response nests multiple conference tables under children;
        other competitions may nest group nodes further. Only registered ESPN
        team IDs are accepted, preventing a misspelled name or bad ID from
        silently becoming a model row.
        """
        grouped: Dict[str, list[dict[str, Any]]] = {}
        invalid_rows = missing_stats = 0
        lookup = getattr(GLOBAL_TEAM_REGISTRY, "_lookup", {})

        def visit(node: Any, path: tuple[str, ...] = ()) -> None:
            nonlocal invalid_rows, missing_stats
            if not isinstance(node, dict):
                return
            label = str(node.get("name") or node.get("displayName") or "").strip()
            group_path = path + ((label,) if label else ())
            standings = node.get("standings")
            if isinstance(standings, dict) and isinstance(standings.get("entries"), list):
                group_name = " / ".join(group_path)
                for entry in standings["entries"]:
                    team = entry.get("team") if isinstance(entry, dict) else None
                    if not isinstance(team, dict):
                        invalid_rows += 1
                        continue
                    name = str(team.get("displayName") or "").strip()
                    provider_id = str(team.get("id") or "").strip()
                    canonical = lookup.get(f"ESPN_TEAM_{provider_id}".casefold()) if provider_id else None
                    named = lookup.get(name.casefold()) if name else None
                    if canonical is None:
                        canonical = named
                    if (not name or canonical is None
                            or (league_code == "usa.1" and canonical.league != "MLS")
                            or (named is not None and named.canonical_id != canonical.canonical_id)):
                        invalid_rows += 1
                        continue
                    values = {str(stat.get("name")): stat.get("value")
                              for stat in entry.get("stats", []) if isinstance(stat, dict)}
                    try:
                        # ESPN labels soccer goals as pointsFor/pointsAgainst.
                        gf, ga, gp = (float(values[key]) for key in ("pointsFor", "pointsAgainst", "gamesPlayed"))
                    except (KeyError, TypeError, ValueError, OverflowError):
                        missing_stats += 1
                        continue
                    if not all(math.isfinite(value) for value in (gf, ga, gp)) or gp <= 0 or gf < 0 or ga < 0:
                        invalid_rows += 1
                        continue
                    row = {"goals_for": gf, "goals_against": ga, "games": gp,
                           "team_name": name, "provider_team_id": provider_id or canonical.canonical_id,
                           "standings_group": group_name}
                    grouped.setdefault(canonical.canonical_id, []).append(row)
            children = node.get("children", [])
            if isinstance(children, list):
                for child in children:
                    visit(child, group_path)

        visit(raw_data)
        teams = {}
        conflicting_groups = 0
        for team_id, records in grouped.items():
            unique_values = {(row["goals_for"], row["goals_against"], row["games"], row["provider_team_id"])
                             for row in records}
            if len(unique_values) != 1:
                conflicting_groups += 1
                continue
            teams[team_id] = records[0]
        self._parse_audit = {"accepted_team_count": len(teams), "invalid_team_or_stat_rows": invalid_rows,
                             "missing_required_stat_rows": missing_stats,
                             "conflicting_multi_group_teams": conflicting_groups}
        return teams

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate a soccer TaiwanLeg option using real team stats."""
        if leg.sport != "soccer":
            return None

        league_code = self._resolve_league_code(leg.league)
        if not league_code:
            logger.info("Soccer league %s not recognized; model returning None", leg.league)
            return None

        stats_map = self._get_soccer_stats(league_code)
        if not stats_map:
            logger.info("Soccer stats not available for %s; returning None", league_code)
            return None

        can_away = GLOBAL_TEAM_REGISTRY.resolve(leg.away_team, sport="soccer")
        can_home = GLOBAL_TEAM_REGISTRY.resolve(leg.home_team, sport="soccer")

        away_id = can_away.canonical_id if can_away else leg.away_team
        home_id = can_home.canonical_id if can_home else leg.home_team

        away_stats = stats_map.get(away_id)
        home_stats = stats_map.get(home_id)

        if not away_stats or not home_stats:
            logger.info("Missing stats for soccer teams %s or %s; returning None", away_id, home_id)
            return None

        event_dt = self._event_datetime(leg)
        meta = self._cache_meta.get(league_code, {})
        prediction_at = datetime.now(timezone.utc)
        observed_at = meta.get("observed_at")
        try:
            parsed_observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")) if observed_at else None
            observed_dt = parsed_observed.astimezone(timezone.utc) if parsed_observed and parsed_observed.tzinfo else None
        except ValueError:
            observed_dt = None
        if event_dt is None:
            event_season = None
        elif league_code == "usa.1":
            event_season = event_dt.year
        else:
            event_season = event_dt.year if event_dt.month >= 8 else event_dt.year - 1
        source_season = meta.get("season")
        season_matches = event_season is not None and source_season == event_season
        source_status = meta.get("source_status", "UNKNOWN")
        timestamp = self._parse_epoch(meta.get("timestamp"))
        age_seconds = time.time() - timestamp if timestamp is not None else None
        point_time_order = bool(event_dt and observed_dt and observed_dt <= prediction_at < event_dt)
        fusion_ready = bool(source_status in {"LIVE", "CACHED"} and age_seconds is not None
                            and 0 <= age_seconds < CACHE_TTL and point_time_order and season_matches)

        # Calculations from real stats
        avg_lg_goals = 1.35
        att_home = (home_stats["goals_for"] / home_stats["games"]) / avg_lg_goals
        def_home = (home_stats["goals_against"] / home_stats["games"]) / avg_lg_goals
        att_away = (away_stats["goals_for"] / away_stats["games"]) / avg_lg_goals
        def_away = (away_stats["goals_against"] / away_stats["games"]) / avg_lg_goals

        home_xg = max(0.25, round(att_home * def_away * avg_lg_goals * 1.15, 2))
        away_xg = max(0.25, round(att_away * def_home * avg_lg_goals * 0.88, 2))

        # Compute Poisson probabilities across 0..8 goals
        prob_home = 0.0
        prob_draw = 0.0
        prob_away = 0.0
        prob_over_25 = 0.0

        for h in range(8):
            for a in range(8):
                p = float(poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg))
                if h > a:
                    prob_home += p
                elif h == a:
                    prob_draw += p
                else:
                    prob_away += p
                if h + a > 2.5:
                    prob_over_25 += p

        taiwan_odds = leg.taiwan_odds
        market = leg.market
        side = leg.side
        market_implied = 1.0 / taiwan_odds if taiwan_odds > 1.0 else 0.50

        # Map to leg selection
        model_prob: Optional[float] = None
        if market == "不讓分":
            if side == "主":
                model_prob = prob_home
            elif side == "客":
                model_prob = prob_away
            elif side == "和":
                model_prob = prob_draw
        elif market == "大小":
            try:
                if leg.line is None or abs(float(leg.line) - 2.5) > 1e-8:
                    return None
            except (TypeError, ValueError):
                return None
            if side == "大":
                model_prob = prob_over_25
            elif side == "小":
                model_prob = 1.0 - prob_over_25

        if model_prob is None:
            return None

        model_prob = round(max(0.05, min(0.92, model_prob)), 3)
        edge = round((model_prob - market_implied) * 100.0, 1)

        confidence = ("MED" if edge >= 0.0 else "LOW") if fusion_ready else "REFERENCE_ONLY"

        return PredictionSignal(
            source_id="espn_poisson_soccer",
            source_name="ESPN 足球卜瓦松模型 (Local Fallback)",
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
            timestamp=prediction_at.isoformat(),
            data_as_of=meta.get("data_as_of"),
            data_age_hours=round(age_seconds / 3600, 2) if age_seconds is not None else None,
            freshness_status="FRESH" if fusion_ready else "STALE" if source_status == "STALE" else "UNKNOWN",
            quality_label="MODEL_EXPERIMENTAL" if fusion_ready else "MODEL_STALE",
            metadata={
                "model_category": self.SOURCE_CATEGORY,
                "independence_group": self.INDEPENDENCE_GROUP,
                "engine_name": self.ENGINE_NAME,
                "data_source": f"ESPN Soccer Standings ({league_code})",
                "source_url": f"https://site.api.espn.com/apis/v2/sports/soccer/{league_code}/standings",
                "source_status": source_status,
                "league_code": league_code,
                "source_content_sha256": meta.get("source_content_sha256"),
                "standings_parse_audit": meta.get("parse_audit"),
                "failure_status": meta.get("failure_status"),
                "observed_at": observed_at,
                "prediction_timestamp": prediction_at.isoformat(),
                "pre_event_source_order_valid": point_time_order,
                "data_as_of": meta.get("data_as_of"),
                "data_as_of_semantics": "ESPN season standings snapshot observation time; not a historical event cutoff",
                "aggregate_season_stats": True,
                "cache_age_hours": round(age_seconds / 3600, 2) if age_seconds is not None else None,
                "source_season": source_season,
                "event_season": event_season,
                "season_matches": season_matches,
                "point_in_time_status": "VALID" if fusion_ready else "REFERENCE_ONLY",
                "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
                "calibration_status": "NOT_EMPIRICALLY_CALIBRATED",
                "initialized": fusion_ready,
                "empirically_calibrated": False,
                "home_team": home_stats["team_name"],
                "away_team": away_stats["team_name"],
                "home_provider_team_id": home_stats["provider_team_id"],
                "away_provider_team_id": away_stats["provider_team_id"],
                "home_standings_group": home_stats.get("standings_group"),
                "away_standings_group": away_stats.get("standings_group"),
                "projected_home_xg": home_xg,
                "projected_away_xg": away_xg,
                "market_implied_prob": round(market_implied, 3),
                "edge_pp": edge,
            },
        )


# Backward-compatible alias
PenaltyblogSoccerAdapter = ESPNPoissonSoccerFallback
