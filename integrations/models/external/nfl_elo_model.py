#!/usr/bin/env python3
"""NFL Football Elo & Quantitative Valuation Engine.

Features:
1. Dynamic Elo Rating System calibrated for the National Football League (NFL).
2. Home Field Advantage (+55.0 Elo points, approx +2.5 to +3.0 points spread).
3. Evaluates Moneyline (不讓分), Point Spread (讓分), and Totals (大小分).
4. Normal distribution margin and totals mapping using NFL empirical variance.
5. Strict provenance: Source category OPEN_SOURCE_ENGINE, independence group NFL_ELO_ENGINE.
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
from integrations.common.models import PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
STATE_FILE = DATA_DIR / "model_state" / "nfl_elo_model.json"
HOME_FIELD_ADVANTAGE = 55.0   # Approx +2.5 to +3.0 points in NFL spread
SPREAD_ELO_RATIO = 24.5       # ~24.5 Elo points equal 1 point in NFL spread
LEAGUE_AVG_TOTAL = 44.5       # Typical NFL game average total score
SPREAD_STD_DEV = 13.8         # Standard deviation for NFL final point margin
TOTAL_STD_DEV = 14.0          # Standard deviation for NFL combined game totals

# 32 NFL Teams with canonical ratings (centered around 1500)
BASE_NFL_ELO: Dict[str, float] = {
    "KC": 1660.0, "SF": 1620.0, "BAL": 1615.0, "DET": 1605.0,
    "PHI": 1585.0, "BUF": 1580.0, "GB": 1545.0, "HOU": 1535.0,
    "DAL": 1525.0, "CIN": 1520.0, "MIA": 1515.0, "LAR": 1510.0,
    "PIT": 1505.0, "TB": 1495.0, "CHI": 1485.0, "ATL": 1475.0,
    "SEA": 1470.0, "IND": 1465.0, "JAX": 1460.0, "MIN": 1460.0,
    "CLE": 1450.0, "NYJ": 1450.0, "ARI": 1440.0, "LAC": 1440.0,
    "WAS": 1435.0, "DEN": 1425.0, "TEN": 1415.0, "NO": 1410.0,
    "LV": 1400.0, "NYG": 1380.0, "NE": 1360.0, "CAR": 1340.0,
}

# Mapping common Chinese / English aliases to NFL canonical codes
NFL_TEAM_ALIASES: Dict[str, str] = {
    "酋長": "KC", "堪薩斯城酋長": "KC", "堪薩斯酋長": "KC", "CHIEFS": "KC", "KANSAS CITY": "KC",
    "49人": "SF", "四九人": "SF", "舊金山49人": "SF", "49ERS": "SF", "SAN FRANCISCO": "SF",
    "烏鴉": "BAL", "巴爾的摩烏鴉": "BAL", "RAVENS": "BAL", "BALTIMORE": "BAL",
    "雄獅": "DET", "底特律雄獅": "DET", "LIONS": "DET", "DETROIT": "DET",
    "老鷹": "PHI", "費城老鷹": "PHI", "EAGLES": "PHI", "PHILADELPHIA": "PHI",
    "比爾": "BUF", "水牛城比爾": "BUF", "BILLS": "BUF", "BUFFALO": "BUF",
    "包裝工": "GB", "綠灣包裝工": "GB", "PACKERS": "GB", "GREEN BAY": "GB",
    "德州人": "HOU", "休士頓德州人": "HOU", "TEXANS": "HOU", "HOUSTON": "HOU",
    "牛仔": "DAL", "達拉斯牛仔": "DAL", "COWBOYS": "DAL", "DALLAS": "DAL",
    "孟加拉虎": "CIN", "辛辛那提孟加拉虎": "CIN", "BENGALS": "CIN", "CINCINNATI": "CIN",
    "海豚": "MIA", "邁阿密海豚": "MIA", "DOLPHINS": "MIA", "MIAMI": "MIA",
    "公羊": "LAR", "洛杉磯公羊": "LAR", "RAMS": "LAR", "LA RAMS": "LAR",
    "鋼人": "PIT", "匹茲堡鋼人": "PIT", "STEELERS": "PIT", "PITTSBURGH": "PIT",
    "海盜": "TB", "坦帕灣海盜": "TB", "BUCCANEERS": "TB", "TAMPA BAY": "TB",
    "熊": "CHI", "芝加哥熊": "CHI", "BEARS": "CHI", "CHICAGO": "CHI",
    "獵鷹": "ATL", "亞特蘭大獵鷹": "ATL", "FALCONS": "ATL", "ATLANTA": "ATL",
    "海鷹": "SEA", "西雅圖海鷹": "SEA", "SEAHAWKS": "SEA", "SEATTLE": "SEA",
    "小馬": "IND", "印第安納波利斯小馬": "IND", "COLTS": "IND", "INDIANAPOLIS": "IND",
    "美洲虎": "JAX", "美洲豹": "JAX", "傑克遜維爾美洲豹": "JAX", "JAGUARS": "JAX", "JACKSONVILLE": "JAX",
    "維京人": "MIN", "明尼蘇達維京人": "MIN", "VIKINGS": "MIN", "MINNESOTA": "MIN",
    "布朗": "CLE", "克里夫蘭布朗": "CLE", "BROWNS": "CLE", "CLEVELAND": "CLE",
    "噴射機": "NYJ", "紐約噴射機": "NYJ", "JETS": "NYJ", "NY JETS": "NYJ",
    "紅雀": "ARI", "亞利桑那紅雀": "ARI", "CARDINALS": "ARI", "ARIZONA": "ARI",
    "電光": "LAC", "閃電": "LAC", "洛杉磯電光": "LAC", "洛杉磯閃電": "LAC", "CHARGERS": "LAC", "LA CHARGERS": "LAC",
    "指揮官": "WAS", "華盛頓指揮官": "WAS", "COMMANDERS": "WAS", "WASHINGTON": "WAS",
    "野馬": "DEN", "丹佛野馬": "DEN", "BRONCOS": "DEN", "DENVER": "DEN",
    "泰坦": "TEN", "田納西泰坦": "TEN", "TITANS": "TEN", "TENNESSEE": "TEN",
    "聖徒": "NO", "紐奧良聖徒": "NO", "SAINTS": "NO", "NEW ORLEANS": "NO",
    "突擊者": "LV", "拉斯維加斯突擊者": "LV", "RAIDERS": "LV", "LAS VEGAS": "LV",
    "巨人": "NYG", "紐約巨人": "NYG", "GIANTS": "NYG", "NY GIANTS": "NYG",
    "愛國者": "NE", "新英格蘭愛國者": "NE", "PATRIOTS": "NE", "NEW ENGLAND": "NE",
    "黑豹": "CAR", "卡羅萊納黑豹": "CAR", "PANTHERS": "CAR", "CAROLINA": "CAR",
}


def _resolve_nfl_team_code(name: str) -> str:
    """Resolve raw team string to 2-3 letter canonical NFL code."""
    cleaned = str(name).strip().upper()
    for alias, code in NFL_TEAM_ALIASES.items():
        if alias.upper() in cleaned:
            return code
    return cleaned[:3]


class NFLEloModel:
    """Quantitative Elo rating model for NFL American Football games."""

    SOURCE_CATEGORY = "OPEN_SOURCE_ENGINE"
    INDEPENDENCE_GROUP = "NFL_ELO_ENGINE"
    ENGINE_NAME = "NFL Elo Quantitative Valuation Engine"

    def __init__(self, state_file: Optional[Path] = None):
        self.version = "1.0.0"
        self.state_file = state_file or STATE_FILE
        self.elo_ratings: Dict[str, float] = dict(BASE_NFL_ELO)
        self.processed_games_count = 0
        self.last_updated_at: Optional[str] = None
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
        except Exception as exc:
            logger.warning("Error reading NFL Elo state: %s", exc)

    def save_state(self) -> None:
        """Persist updated ratings to disk atomically."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ratings": self.elo_ratings,
            "processed_games": self.processed_games_count,
            "last_updated_at": self.last_updated_at or datetime.now(timezone.utc).isoformat(),
            "version": self.version,
        }
        atomic_write_bytes(self.state_file, json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))

    def get_team_elo(self, team_key: str) -> float:
        """Get current Elo rating for team."""
        return self.elo_ratings.get(team_key, 1500.0)

    def predict_match(
        self,
        home_team: str,
        away_team: str,
    ) -> Dict[str, Any]:
        """Predict match win probabilities, spread, and totals."""
        home_code = _resolve_nfl_team_code(home_team)
        away_code = _resolve_nfl_team_code(away_team)

        elo_home = self.get_team_elo(home_code)
        elo_away = self.get_team_elo(away_code)

        # Elo difference with Home Field Advantage
        diff = elo_home - elo_away + HOME_FIELD_ADVANTAGE

        # Win probability (Standard logistic)
        prob_home = 1.0 / (1.0 + math.pow(10.0, -diff / 400.0))
        prob_away = 1.0 - prob_home

        # Projected margin (positive means home wins by margin)
        projected_margin = diff / SPREAD_ELO_RATIO

        # Projected total score
        elo_sum_diff = (elo_home + elo_away - 3000.0) / 100.0
        projected_total = LEAGUE_AVG_TOTAL + (elo_sum_diff * 0.8)

        return {
            "home_code": home_code,
            "away_code": away_code,
            "elo_home": elo_home,
            "elo_away": elo_away,
            "elo_diff_with_hfa": round(diff, 1),
            "prob_home": round(prob_home, 4),
            "prob_away": round(prob_away, 4),
            "projected_margin": round(projected_margin, 1),
            "projected_total": round(projected_total, 1),
        }

    def evaluate_spread_probability(self, projected_margin: float, line: float, side: str) -> float:
        """Calculate probability of covering an NFL point spread."""
        diff = projected_margin - line
        z = diff / SPREAD_STD_DEV
        p_home_cover = NormalDist().cdf(z)

        if side in {"主", "HOME", "home"}:
            return max(0.01, min(0.99, p_home_cover))
        return max(0.01, min(0.99, 1.0 - p_home_cover))

    def evaluate_totals_probability(self, projected_total: float, total_line: float, side: str) -> float:
        """Calculate probability of Over or Under for NFL total points."""
        diff = projected_total - total_line
        z = diff / TOTAL_STD_DEV
        p_over = NormalDist().cdf(z)

        if side in {"大", "OVER", "over"}:
            return max(0.01, min(0.99, p_over))
        return max(0.01, min(0.99, 1.0 - p_over))

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate an NFL TaiwanLeg option."""
        league_str = str(leg.league or "").upper()
        sport_str = str(leg.sport or "").lower()
        if "NFL" not in league_str and sport_str not in ("football", "american_football"):
            return None

        pred = self.predict_match(leg.home_team, leg.away_team)
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

        metadata = {
            "model_id": "nfl_elo_model",
            "model_version": self.version,
            "elo_home": pred["elo_home"],
            "elo_away": pred["elo_away"],
            "projected_margin": pred["projected_margin"],
            "projected_total": pred["projected_total"],
            "edge_pp": round(edge_pp, 2),
            "expected_value_pct": round((est_prob * odds - 1.0) * 100.0, 2),
            "initialized": True,
        }

        confidence = "HIGH" if edge_pp >= 4.0 else ("MED" if edge_pp >= 0.0 else "LOW")

        return PredictionSignal(
            source_id="nfl_elo_model",
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
            data_as_of=self.last_updated_at or datetime.now(timezone.utc).isoformat(),
            freshness_status="LIVE",
            metadata=metadata,
        )
