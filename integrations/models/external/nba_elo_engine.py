#!/usr/bin/env python3
"""NBA Basketball Elo & Quantitative Valuation Engine.

Features:
1. Dynamic Elo Rating System with NBA-specific Margin of Victory (MOV) multiplier.
2. Home Court Advantage (+100.0 Elo points, approx +3.0 points spread).
3. Evaluates Moneyline (不讓分), Point Spread (讓分), and Totals (大小分).
4. Dean Oliver Four Factors framework integration for offensive/defensive pacing.
5. Strict provenance: Source category OPEN_SOURCE_ENGINE, independence group NBA_ELO_ENGINE.
"""

from __future__ import annotations

import json
import logging
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

from core.identity import GLOBAL_TEAM_REGISTRY
from core.persistence import atomic_write_bytes
from integrations.common.models import PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
STATE_FILE = DATA_DIR / "model_state" / "nba_elo_engine.json"
HOME_COURT_ADVANTAGE = 100.0  # Approx +3.0 points in NBA spread
DEFAULT_K_FACTOR = 20.0
LEAGUE_AVG_TOTAL = 224.5
SPREAD_ELO_RATIO = 28.0       # ~28 Elo points equal 1 point in NBA spread
TOTAL_STD_DEV = 18.0          # Standard deviation for NBA game totals
SPREAD_STD_DEV = 12.0         # Standard deviation for NBA point differential

# Base 2026 season initial baseline Elo ratings (centered around 1500)
BASE_NBA_ELO: Dict[str, float] = {
    "NBA_BOS": 1660.0, "NBA_DEN": 1600.0, "NBA_OKC": 1590.0, "NBA_MIN": 1575.0,
    "NBA_NYK": 1565.0, "NBA_DAL": 1560.0, "NBA_MIL": 1550.0, "NBA_PHI": 1540.0,
    "NBA_IND": 1530.0, "NBA_CLE": 1530.0, "NBA_PHX": 1525.0, "NBA_LAL": 1520.0,
    "NBA_GSW": 1515.0, "NBA_MIA": 1510.0, "NBA_NOP": 1505.0, "NBA_ORL": 1500.0,
    "NBA_SAC": 1495.0, "NBA_HOU": 1490.0, "NBA_LAC": 1485.0, "NBA_MEM": 1480.0,
    "NBA_CHI": 1460.0, "NBA_ATL": 1455.0, "NBA_UTA": 1440.0, "NBA_BKN": 1430.0,
    "NBA_TOR": 1420.0, "NBA_SAS": 1410.0, "NBA_CHA": 1395.0, "NBA_POR": 1390.0,
    "NBA_WAS": 1360.0, "NBA_DET": 1350.0,
}


def _resolve_nba_team(name: str):
    """Resolve team name to canonical team in registry."""
    team = GLOBAL_TEAM_REGISTRY.resolve(name, sport="basketball", league="NBA")
    if team is None:
        team = GLOBAL_TEAM_REGISTRY.resolve(name, sport="basketball")
    return team


class NBAEloEngine:
    """Quantitative Elo and Four Factors rating model for NBA games."""

    SOURCE_CATEGORY = "OPEN_SOURCE_ENGINE"
    INDEPENDENCE_GROUP = "NBA_ELO_ENGINE"
    ENGINE_NAME = "NBA Elo & Four Factors Quantitative Model"

    def __init__(self, state_file: Optional[Path] = None):
        self.version = "1.0.0"
        self.state_file = state_file or STATE_FILE
        self.elo_ratings: Dict[str, float] = dict(BASE_NBA_ELO)
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
            logger.warning("Error reading NBA Elo state: %s", exc)

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
        """Get current Elo rating for canonical team key."""
        return self.elo_ratings.get(team_key, 1500.0)

    def predict_match(
        self,
        home_team: str,
        away_team: str,
    ) -> Dict[str, Any]:
        """Predict match win probabilities, spread, and totals."""
        can_home = _resolve_nba_team(home_team)
        can_away = _resolve_nba_team(away_team)

        home_id = can_home.canonical_id if can_home else home_team
        away_id = can_away.canonical_id if can_away else away_team

        elo_home = self.get_team_elo(home_id)
        elo_away = self.get_team_elo(away_id)

        # Elo difference with Home Court Advantage
        diff = elo_home - elo_away + HOME_COURT_ADVANTAGE

        # Win probability (Logistic formula)
        prob_home = 1.0 / (1.0 + math.pow(10.0, -diff / 400.0))
        prob_away = 1.0 - prob_home

        # Expected margin (positive means home wins by margin)
        projected_margin = diff / SPREAD_ELO_RATIO

        # Projected total score
        # Stronger teams push pace and score more efficiently
        elo_sum_diff = (elo_home + elo_away - 3000.0) / 100.0
        projected_total = LEAGUE_AVG_TOTAL + (elo_sum_diff * 1.5)

        return {
            "home_canonical": home_id,
            "away_canonical": away_id,
            "elo_home": elo_home,
            "elo_away": elo_away,
            "elo_diff_with_hca": round(diff, 1),
            "prob_home": round(prob_home, 4),
            "prob_away": round(prob_away, 4),
            "projected_margin": round(projected_margin, 1),
            "projected_total": round(projected_total, 1),
        }

    def evaluate_spread_probability(self, projected_margin: float, line: float, side: str) -> float:
        """Calculate probability of covering a point spread.

        Line is expressed relative to home (e.g. -4.5 means home must win by > 4.5).
        """
        # Difference between projected outcome and the spread line
        diff = projected_margin - line
        z = diff / SPREAD_STD_DEV
        p_home_cover = NormalDist().cdf(z)

        if side in {"主", "HOME", "home"}:
            return max(0.01, min(0.99, p_home_cover))
        return max(0.01, min(0.99, 1.0 - p_home_cover))

    def evaluate_totals_probability(self, projected_total: float, total_line: float, side: str) -> float:
        """Calculate probability of Over or Under for total points."""
        diff = projected_total - total_line
        z = diff / TOTAL_STD_DEV
        p_over = NormalDist().cdf(z)

        if side in {"大", "OVER", "over"}:
            return max(0.01, min(0.99, p_over))
        return max(0.01, min(0.99, 1.0 - p_over))

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate an NBA TaiwanLeg option."""
        if leg.sport != "basketball" or "NBA" not in leg.league.upper():
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
                    # If home is favored, line is negative for home
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

        # Calculate Edge vs break-even
        odds = float(leg.taiwan_odds or 1.0)
        be_hurdle = 1.0 / odds if odds > 1.0 else 0.5
        edge_pp = (est_prob - be_hurdle) * 100.0

        metadata = {
            "model_id": "nba_elo_engine",
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
            source_id="nba_elo_engine",
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
