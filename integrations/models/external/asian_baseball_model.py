#!/usr/bin/env python3
"""Asian Professional Baseball (CPBL, NPB, KBO) Quantitative Valuation Engine.

Features:
1. Dynamic Elo & Pythagorean run expectancy calibrated for Asian Baseball Leagues:
   - CPBL (中華職棒 - Alliance 6)
   - NPB (日本職棒 - Alliance 2)
   - KBO (韓國職棒 - Alliance 9)
2. Home Field Advantage (+24.0 Elo points, approx +0.25 runs in baseball).
3. Evaluates Moneyline (不讓分), Run Line / Spread (讓分 ±1.5), and Totals (大小分).
4. Starting pitcher differential weighting when available.
5. Strict provenance: Source category OPEN_SOURCE_ENGINE, independence group ASIAN_BASEBALL_MODEL.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

from core.identity import GLOBAL_TEAM_REGISTRY
from core.persistence import atomic_write_bytes
from core.contracts.common import PredictionSignal, TaiwanLeg
from core.model_provenance import model_input_evidence

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
STATE_FILE = DATA_DIR / "model_state" / "asian_baseball_model.json"

HOME_FIELD_ADVANTAGE = 24.0   # Standard baseball home advantage (~54% home win rate)
RUN_LINE_STD_DEV = 3.2        # Standard deviation of run differential in Asian baseball
TOTAL_STD_DEV = 3.6           # Standard deviation of total runs in Asian baseball

LEAGUE_BASE_TOTALS: Dict[str, float] = {
    "CPBL": 8.5,
    "NPB": 6.8,   # NPB is historically more pitcher-dominated
    "KBO": 9.2,   # KBO is traditionally higher-scoring
}

# Baseline initial team Elo ratings for Asian Baseball
BASE_ASIAN_BASEBALL_ELO: Dict[str, float] = {
    # CPBL (中華職棒)
    "統一": 1540.0, "中信": 1535.0, "樂天桃猿": 1510.0, "味全": 1500.0,
    "富邦": 1450.0, "台鋼": 1465.0,
    # NPB (日本職棒 - 太平洋 / 中央聯盟)
    "軟銀": 1580.0, "讀賣巨人": 1550.0, "阪神": 1545.0, "橫濱": 1530.0,
    "歐力士": 1520.0, "火腿": 1515.0, "羅德": 1500.0, "廣島": 1495.0,
    "樂天金鷲": 1480.0, "養樂多": 1475.0, "中日": 1450.0, "西武": 1420.0,
    # KBO (韓國職棒)
    "起亞虎": 1555.0, "三星獅": 1540.0, "LG雙子": 1535.0, "斗山熊": 1510.0,
    "KT巫師": 1505.0, "SSG登陸者": 1495.0, "樂天巨人": 1480.0, "韓華鷹": 1475.0,
    "NC恐龍": 1465.0, "培證英雄": 1440.0,
}


ASIAN_LEAGUE_TEAMS = {
    "CPBL": {"統一", "中信", "樂天桃猿", "味全", "富邦", "台鋼"},
    "NPB": {"軟銀", "讀賣巨人", "阪神", "橫濱", "歐力士", "火腿", "羅德", "廣島", "樂天金鷲", "養樂多", "中日", "西武"},
    "KBO": {"起亞虎", "三星獅", "LG雙子", "斗山熊", "KT巫師", "SSG登陸者", "樂天巨人", "韓華鷹", "NC恐龍", "培證英雄"},
}

ASIAN_TEAM_ALIASES = {
    "統一": ("統一", "統一獅", "統一7-ELEVEn獅", "Uni-President 7-Eleven Lions", "Uni Lions"),
    "中信": ("中信", "中信兄弟", "CTBC Brothers", "Brothers"),
    "樂天桃猿": ("樂天桃猿", "Rakuten Monkeys", "Rakuten Monkeys Taoyuan"),
    "味全": ("味全", "味全龍", "Wei Chuan Dragons"),
    "富邦": ("富邦", "富邦悍將", "Fubon Guardians"),
    "台鋼": ("台鋼", "台鋼雄鷹", "TSG Hawks"),
    "軟銀": ("軟銀", "福岡軟銀鷹", "Fukuoka SoftBank Hawks", "SoftBank Hawks"),
    "讀賣巨人": ("讀賣巨人", "讀賣", "Yomiuri Giants"),
    "阪神": ("阪神", "阪神虎", "Hanshin Tigers"),
    "橫濱": ("橫濱", "橫濱DeNA海灣之星", "Yokohama DeNA BayStars", "Yokohama BayStars"),
    "歐力士": ("歐力士", "歐力士猛牛", "Orix Buffaloes"),
    "火腿": ("火腿", "北海道日本火腿鬥士", "Hokkaido Nippon-Ham Fighters", "Nippon-Ham Fighters"),
    "羅德": ("羅德", "千葉羅德海洋", "Chiba Lotte Marines"),
    "廣島": ("廣島", "廣島東洋鯉魚", "Hiroshima Toyo Carp", "Hiroshima Carp"),
    "樂天金鷲": ("樂天金鷲", "東北樂天金鷲", "Tohoku Rakuten Golden Eagles", "Rakuten Eagles"),
    "養樂多": ("養樂多", "東京養樂多燕子", "Tokyo Yakult Swallows", "Yakult Swallows"),
    "中日": ("中日", "中日龍", "Chunichi Dragons"),
    "西武": ("西武", "埼玉西武獅", "Saitama Seibu Lions"),
    "起亞虎": ("起亞虎", "KIA Tigers"),
    "三星獅": ("三星獅", "Samsung Lions"),
    "LG雙子": ("LG雙子", "LG Twins"),
    "斗山熊": ("斗山熊", "Doosan Bears"),
    "KT巫師": ("KT巫師", "KT Wiz", "KT WIZ"),
    "SSG登陸者": ("SSG登陸者", "SSG Landers"),
    "樂天巨人": ("樂天巨人", "Lotte Giants"),
    "韓華鷹": ("韓華鷹", "Hanwha Eagles"),
    "NC恐龍": ("NC恐龍", "NC Dinos"),
    "培證英雄": ("培證英雄", "Kiwoom Heroes"),
}


def _normalize_team_name(name: str) -> str:
    return "".join(char for char in str(name or "").casefold() if char.isalnum())


def _resolve_asian_team_key(name: str, league: str | None = None) -> str | None:
    """Resolve an exact supported league/team alias; never invent a 1500 team."""
    normalized = _normalize_team_name(name)
    leagues = [str(league).upper()] if league else list(ASIAN_LEAGUE_TEAMS)
    matches = set()
    for candidate_league in leagues:
        if candidate_league not in ASIAN_LEAGUE_TEAMS:
            continue
        for key in ASIAN_LEAGUE_TEAMS[candidate_league]:
            aliases = ASIAN_TEAM_ALIASES.get(key, (key,))
            if any(normalized == _normalize_team_name(alias) for alias in aliases):
                matches.add(key)
    return next(iter(matches)) if len(matches) == 1 else None


class AsianBaseballModel:
    """Quantitative valuation engine for CPBL, NPB, and KBO baseball."""

    SOURCE_CATEGORY = "OPEN_SOURCE_ENGINE"
    INDEPENDENCE_GROUP = "ASIAN_BASEBALL_MODEL"
    ENGINE_NAME = "Asian Baseball Quantitative Valuation Engine"

    def __init__(self, state_file: Optional[Path] = None):
        self.version = "1.1.0"
        self.state_file = state_file or STATE_FILE
        self.elo_ratings: Dict[str, float] = dict(BASE_ASIAN_BASEBALL_ELO)
        self.processed_games_count = 0
        self.last_updated_at: Optional[str] = None
        self.data_as_of_by_league: Dict[str, str] = {}
        self.source_by_league: Dict[str, str] = {}
        self.processed_events: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted team ratings if available."""
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                ratings = data.get("ratings")
                if isinstance(ratings, dict):
                    self.elo_ratings.update(ratings)
                self.processed_games_count = data.get("processed_games", 0)
                self.last_updated_at = data.get("last_updated_at")
                for attr, key in ((self.data_as_of_by_league, "data_as_of_by_league"),
                                  (self.source_by_league, "source_by_league"),
                                  (self.processed_events, "research_events")):
                    value = data.get(key, {})
                    if isinstance(value, dict):
                        attr.update(value)
        except Exception as exc:
            logger.warning("Error reading Asian baseball Elo state: %s", exc)

    def save_state(self) -> None:
        """Persist updated ratings to disk atomically."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ratings": self.elo_ratings,
            "processed_games": self.processed_games_count,
            "last_updated_at": self.last_updated_at or datetime.now(timezone.utc).isoformat(),
            "data_as_of_by_league": self.data_as_of_by_league,
            "source_by_league": self.source_by_league,
            "research_events": self.processed_events,
            "version": self.version,
        }
        atomic_write_bytes(self.state_file, json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))

    def get_team_elo(self, team_name: str, league: str | None = None) -> float | None:
        """Get current Elo rating for team."""
        key = _resolve_asian_team_key(team_name, league)
        return self.elo_ratings.get(key) if key else None

    def predict_match(
        self,
        league: str,
        home_team: str,
        away_team: str,
    ) -> Optional[Dict[str, Any]]:
        """Predict Asian baseball match win probabilities and run projections."""
        league_clean = str(league).upper()
        norm_league = "CPBL" if "CPBL" in league_clean or "中職" in league_clean or "中華職棒" in league_clean \
            else "NPB" if "NPB" in league_clean or "日棒" in league_clean \
            else "KBO" if "KBO" in league_clean or "韓棒" in league_clean or "韓國職棒" in league_clean \
            else None

        if norm_league is None:
            return None

        elo_home = self.get_team_elo(home_team, norm_league)
        elo_away = self.get_team_elo(away_team, norm_league)
        if elo_home is None or elo_away is None or _resolve_asian_team_key(home_team, norm_league) == _resolve_asian_team_key(away_team, norm_league):
            return None

        # Elo difference with Home Field Advantage
        diff = elo_home - elo_away + HOME_FIELD_ADVANTAGE

        # Win probability (Baseball logistic formula)
        prob_home = 1.0 / (1.0 + math.pow(10.0, -diff / 400.0))
        prob_away = 1.0 - prob_home

        # Projected run margin: ~100 Elo points approx 0.85 runs in Asian baseball
        projected_margin = diff * 0.0085

        # Projected total runs
        base_total = LEAGUE_BASE_TOTALS.get(norm_league, 8.0)
        elo_sum_diff = (elo_home + elo_away - 3000.0) / 100.0
        projected_total = base_total + (elo_sum_diff * 0.25)

        return {
            "norm_league": norm_league,
            "elo_home": elo_home,
            "elo_away": elo_away,
            "diff_with_hfa": round(diff, 1),
            "prob_home": round(prob_home, 4),
            "prob_away": round(prob_away, 4),
            "projected_margin": round(projected_margin, 2),
            "projected_total": round(projected_total, 2),
        }

    def evaluate_spread_probability(self, projected_margin: float, line: float, side: str) -> float:
        """Calculate probability of covering a baseball run line (e.g. -1.5 / +1.5)."""
        diff = projected_margin - line
        z = diff / RUN_LINE_STD_DEV
        p_home_cover = NormalDist().cdf(z)

        if side in {"主", "HOME", "home"}:
            return max(0.01, min(0.99, p_home_cover))
        return max(0.01, min(0.99, 1.0 - p_home_cover))

    def evaluate_totals_probability(self, projected_total: float, total_line: float, side: str) -> float:
        """Calculate probability of Over or Under for total runs."""
        diff = projected_total - total_line
        z = diff / TOTAL_STD_DEV
        p_over = NormalDist().cdf(z)

        if side in {"大", "OVER", "over"}:
            return max(0.01, min(0.99, p_over))
        return max(0.01, min(0.99, 1.0 - p_over))

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate an Asian baseball TaiwanLeg option (CPBL, NPB, KBO)."""
        league_str = str(leg.league or "").upper()
        sport_str = str(leg.sport or "").lower()

        is_asian_baseball = (
            sport_str == "baseball"
            and any(x in league_str for x in ("CPBL", "NPB", "KBO", "日棒", "中職", "韓棒", "中華職棒", "日本職棒", "韓國職棒"))
        )
        if not is_asian_baseball:
            return None

        pred = self.predict_match(leg.league, leg.home_team, leg.away_team)
        if pred is None:
            return None
        market = leg.market or ""
        side = getattr(leg, "side", "") or ""
        selection = leg.selection or ""
        line = getattr(leg, "line", None)

        est_prob: Optional[float] = None

        if market in {"不讓分", "獨贏", "MONEYLINE"}:
            if "主" in selection or side == "主":
                est_prob = pred["prob_home"]
            elif "客" in selection or side == "客":
                est_prob = pred["prob_away"]

        elif market in {"讓分", "SPREAD", "HANDICAP"}:
            if line is not None:
                try:
                    fline = float(line)
                    est_prob = self.evaluate_spread_probability(pred["projected_margin"], fline, side)
                except (ValueError, TypeError):
                    pass

        elif market in {"大小", "TOTAL", "OVER_UNDER"}:
            if line is not None:
                try:
                    fline = float(line)
                    est_prob = self.evaluate_totals_probability(pred["projected_total"], fline, side)
                except (ValueError, TypeError):
                    pass

        if est_prob is None or est_prob <= 0.0 or est_prob >= 1.0:
            return None

        odds = float(leg.taiwan_odds or 1.0)
        be_hurdle = 1.0 / odds if odds > 1.0 else 0.5
        edge_pp = (est_prob - be_hurdle) * 100.0

        data_as_of = self.data_as_of_by_league.get(pred["norm_league"])
        source = self.source_by_league.get(pred["norm_league"])
        evidence = model_input_evidence(data_as_of, leg.start_time_utc,
                                        fresh_hours=48, aging_days=7)
        has_updated_state = bool(data_as_of and source)
        metadata = {
            "model_id": "asian_baseball_model",
            "model_version": self.version,
            "league": pred["norm_league"],
            "elo_home": pred["elo_home"],
            "elo_away": pred["elo_away"],
            "projected_margin": pred["projected_margin"],
            "projected_total": pred["projected_total"],
            "edge_pp": round(edge_pp, 2),
            "expected_value_pct": round((est_prob * odds - 1.0) * 100.0, 2),
            "initialized": True,
            "data_source": source or "embedded_baseline_prior",
            "source_status": "UPDATED_STATE" if has_updated_state else "BASELINE_ONLY",
            "data_source_observed_at": data_as_of,
            "point_in_time_status": evidence["point_in_time_status"] if has_updated_state else "BASELINE_PRIOR",
            "point_in_time_verified": evidence["point_in_time_verified"] if has_updated_state else False,
            "pre_event_source_order_valid": evidence["pre_event_source_order_valid"] if has_updated_state else False,
            "processed_games_count": self.processed_games_count,
        }

        confidence = "HIGH" if edge_pp >= 4.0 else ("MED" if edge_pp >= 0.0 else "LOW")

        return PredictionSignal(
            source_id="asian_baseball_model",
            source_name=self.ENGINE_NAME,
            source_type="MODEL",
            source_category=self.SOURCE_CATEGORY,
            independence_group=self.INDEPENDENCE_GROUP,
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=round(est_prob, 4),
            score=round(edge_pp, 2),
            confidence=confidence,
            data_as_of=data_as_of,
            freshness_status=evidence["freshness_status"] if has_updated_state else "UNKNOWN",
            metadata={**metadata,
                      "data_source": source or "embedded_baseline_prior",
                      "source_status": "UPDATED_STATE" if has_updated_state else "BASELINE_ONLY",
                      "point_in_time_status": evidence["point_in_time_status"] if has_updated_state else "BASELINE_PRIOR",
                      "point_in_time_verified": evidence["point_in_time_verified"] if has_updated_state else False,
                      "pre_event_source_order_valid": evidence["pre_event_source_order_valid"] if has_updated_state else False,
                      "model_state_updated_at": self.last_updated_at,
                      "data_source_observed_at": data_as_of,
                      "processed_games_count": self.processed_games_count},
        )
