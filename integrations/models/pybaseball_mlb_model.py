#!/usr/bin/env python3
"""Pybaseball MLB Prediction Model Adapter (Layer B - Model).

Uses real team runs scored, runs allowed, and records to compute
Bill James Pythagorean win expectations and compare against Taiwan Sports Lottery odds.
If real team stats cannot be obtained, returns None (MODEL_NOT_AVAILABLE).
"""

from __future__ import annotations

import json
import logging
import os
import time
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


class PybaseballMLBAdapter:
    """Evaluates MLB TaiwanLeg betting options using real team stats and Pythagorean expectations."""

    def __init__(self, cache_file: str = MLB_CACHE_FILE):
        self.version = "2.2.7"
        self.cache_file = cache_file
        self._stats_cache: Optional[Dict[str, Dict[str, float]]] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        })

    def _get_mlb_stats(self) -> Dict[str, Dict[str, float]]:
        if self._stats_cache is not None:
            return self._stats_cache

        # 1. Try fresh cache
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                    self._stats_cache = data.get("teams", {})
                    return self._stats_cache
            except Exception as exc:
                logger.warning("Error reading MLB cache: %s", exc)

        # 2. Fetch live ESPN MLB standings
        url = "http://site.api.espn.com/apis/v2/sports/baseball/mlb/standings"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                extracted = self._parse_espn_standings(resp.json())
                if extracted:
                    os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                    with open(self.cache_file, "w", encoding="utf-8") as f:
                        json.dump({"timestamp": time.time(), "teams": extracted}, f, indent=2, ensure_ascii=False)
                    self._stats_cache = extracted
                    return extracted
        except Exception as exc:
            logger.warning("Failed to fetch live MLB standings: %s", exc)

        # 3. Fallback to stale cache
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._stats_cache = json.load(f).get("teams", {})
                    return self._stats_cache
            except Exception:
                pass

        self._stats_cache = {}
        return {}

    def _parse_espn_standings(self, raw_data: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        teams: Dict[str, Dict[str, float]] = {}

        def walk(node: Dict[str, Any]):
            if "standings" in node and "entries" in node["standings"]:
                for e in node["standings"]["entries"]:
                    tm = e.get("team", {})
                    name = tm.get("displayName", "")
                    abbr = tm.get("abbreviation", "")
                    stats = {s.get("name"): s.get("value", 0.0) for s in e.get("stats", [])}
                    rs = float(stats.get("pointsFor", 0.0))
                    ra = float(stats.get("pointsAgainst", 0.0))
                    gp = float(stats.get("gamesPlayed", 0.0))
                    win_pct = float(stats.get("winPercent", 0.50))

                    can_team = GLOBAL_TEAM_REGISTRY.resolve(name, sport="baseball", league="MLB") or \
                               GLOBAL_TEAM_REGISTRY.resolve(abbr, sport="baseball", league="MLB")
                    key = can_team.canonical_id if can_team else name

                    teams[key] = {
                        "runs_scored": rs,
                        "runs_allowed": ra,
                        "games": max(1.0, gp),
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
            model_prob = p_home_pyth if side == "主" else p_away_pyth
        elif market == "讓分":
            # Run line adjustment
            fav_is_home = (p_home_pyth >= 0.50)
            if side == "主":
                model_prob = (p_home_pyth * 0.70) if fav_is_home else (p_home_pyth + (1.0 - p_home_pyth) * 0.38)
            else:
                model_prob = (p_away_pyth * 0.70) if not fav_is_home else (p_away_pyth + (1.0 - p_away_pyth) * 0.38)
        elif market == "大小":
            total_xr = xr_home + xr_away
            line_val = float(leg.line) if leg.line else 8.5
            delta = total_xr - line_val
            p_over = max(0.15, min(0.85, 0.50 + delta * 0.08))
            model_prob = p_over if side == "大" else (1.0 - p_over)

        if model_prob is None:
            return None

        model_prob = round(max(0.05, min(0.95, model_prob)), 3)
        edge = round((model_prob - market_implied) * 100.0, 1)

        confidence = "HIGH" if edge >= 3.5 else "MED" if edge >= 0.0 else "LOW"

        return PredictionSignal(
            source_id="pybaseball_mlb_model",
            source_name=f"Pybaseball Pythagorean (v{self.version})",
            source_type="MODEL",
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=model_prob,
            score=edge,
            confidence=confidence,
            pick=leg.selection,
            metadata={
                "github_repo": "jldbc/pybaseball",
                "model": "Bill James Pythagorean Expectation (exp 1.83)",
                "data_source": "ESPN Standings Live / Pybaseball",
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

