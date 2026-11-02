#!/usr/bin/env python3
"""Sharp Market Benchmark & De-vigged Fair Odds Adapter.

In sports betting quantitative finance, sharp international bookmakers (e.g.,
Pinnacle, Betfair Exchange) operate on very low margins (1.5%~2.5%) and rapid
price discovery driven by market liquidity.

Taiwan Sports Lottery (台灣運彩) operates with high margins (10%~15%) and often
lags international market moves or shades lines toward popular public favorites.

This module provides:
1. Sharp odds retrieval (local cache or live API)
2. Accurate multi-way and two-way de-vigging
3. Calculation of true Market Edge and Positive Expected Value (+EV)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.bet_validation import parse_aware_time
from integrations.common.models import PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "sharp_odds"


@dataclass
class SharpComparisonResult:
    """Quantitative comparison between Taiwan Lottery and Sharp Reference Market."""
    event_id: str
    sport: str
    league: str
    market: str
    selection: str
    taiwan_odds: float
    sharp_odds: float
    sharp_fair_prob: float            # De-vigged sharp probability
    taiwan_implied_prob: float        # 1.0 / taiwan_odds
    edge_pp: float                    # (sharp_fair_prob - taiwan_implied_prob) * 100
    expected_value: float             # (sharp_fair_prob * taiwan_odds) - 1.0
    expected_value_pct: float         # expected_value * 100
    is_value_bet: bool                # expected_value >= 0.02 (+2%)
    value_grade: str                  # STRONG_VALUE, MODERATE_VALUE, FAIR, NEGATIVE_EV
    sharp_book: str = "Pinnacle/Consensus"
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sport": self.sport,
            "league": self.league,
            "market": self.market,
            "selection": self.selection,
            "taiwan_odds": self.taiwan_odds,
            "sharp_odds": self.sharp_odds,
            "sharp_fair_prob": round(self.sharp_fair_prob, 4),
            "taiwan_implied_prob": round(self.taiwan_implied_prob, 4),
            "edge_pp": round(self.edge_pp, 2),
            "expected_value": round(self.expected_value, 4),
            "expected_value_pct": round(self.expected_value_pct, 2),
            "is_value_bet": self.is_value_bet,
            "value_grade": self.value_grade,
            "sharp_book": self.sharp_book,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class SharpBenchmarkOddsAdapter:
    """Adapter for obtaining sharp reference market odds and de-vigged fair probabilities."""

    SOURCE_CATEGORY = "SHARP_MARKET_BENCHMARK"
    INDEPENDENCE_GROUP = "SHARP_CONSENSUS"

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}

    def get_sharp_fair_odds(
        self,
        sport: str,
        league: str,
        event_id: str,
        market: str,
        selection: str,
        taiwan_odds: float,
        opposing_odds: Optional[float] = None,
        draw_odds: Optional[float] = None,
    ) -> Optional[SharpComparisonResult]:
        """Calculate a benchmark only from an explicitly sourced external quote.

        Taiwan opposing prices are intentionally not accepted as Sharp evidence.
        """
        if taiwan_odds <= 1.0:
            return None

        # Check memory cache first
        cache_key = f"{sport}:{league}:{event_id}:{market}:{selection}"
        if cache_key in self._memory_cache:
            data = self._memory_cache[cache_key]
            source_type = str(data.get("source_type") or "").upper()
            if (
                source_type not in {"BOOKMAKER", "EXCHANGE"}
                or not data.get("source_id")
                or not data.get("observed_at_utc")
                or data.get("is_synthetic") is True
            ):
                return None
            try:
                sharp_probability = float(data.get("fair_prob"))
                sharp_odds = float(data.get("sharp_odds"))
                observed_at = parse_aware_time(data.get("observed_at_utc"))
                if not (math.isfinite(sharp_probability) and 0.0 < sharp_probability < 1.0
                        and math.isfinite(sharp_odds) and sharp_odds > 1.0):
                    return None
            except (TypeError, ValueError, OverflowError):
                return None
            if observed_at is None:
                return None
            now = datetime.now(timezone.utc)
            age_seconds = (now - observed_at).total_seconds()
            if age_seconds > 900 or age_seconds < -300:
                return None
            return self._build_comparison(
                event_id=event_id, sport=sport, league=league, market=market,
                selection=selection, taiwan_odds=taiwan_odds,
                sharp_odds=sharp_odds,
                sharp_fair_prob=sharp_probability,
                sharp_book=str(data.get("book") or data["source_id"]),
                observed_at_utc=observed_at.isoformat(),
                source_id=str(data["source_id"]),
            )

        # The previous Taiwan-price de-vig fallback was not independent market
        # evidence and must never be labeled as a Sharp benchmark.
        return None

    def _build_comparison(
        self,
        event_id: str,
        sport: str,
        league: str,
        market: str,
        selection: str,
        taiwan_odds: float,
        sharp_odds: float,
        sharp_fair_prob: float,
        sharp_book: str = "Pinnacle",
        observed_at_utc: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> SharpComparisonResult:
        taiwan_implied = 1.0 / taiwan_odds
        edge_pp = (sharp_fair_prob - taiwan_implied) * 100.0
        ev = (sharp_fair_prob * taiwan_odds) - 1.0
        ev_pct = ev * 100.0

        if ev >= 0.08:
            grade = "STRONG_VALUE"
        elif ev >= 0.02:
            grade = "MODERATE_VALUE"
        elif ev >= -0.02:
            grade = "FAIR_VALUE"
        else:
            grade = "NEGATIVE_EV"

        return SharpComparisonResult(
            event_id=event_id,
            sport=sport,
            league=league,
            market=market,
            selection=selection,
            taiwan_odds=taiwan_odds,
            sharp_odds=sharp_odds,
            sharp_fair_prob=sharp_fair_prob,
            taiwan_implied_prob=taiwan_implied,
            edge_pp=edge_pp,
            expected_value=ev,
            expected_value_pct=ev_pct,
            is_value_bet=ev >= 0.02,
            value_grade=grade,
            sharp_book=sharp_book,
            timestamp=observed_at_utc or datetime.now(timezone.utc).isoformat(),
            details={"source_id": source_id} if source_id else {},
        )

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Produce a PredictionSignal representing Sharp Market consensus."""
        odds = float(leg.taiwan_odds or 0.0)
        if odds <= 1.0:
            return None

        comp = self.get_sharp_fair_odds(
            sport=leg.sport,
            league=leg.league,
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            taiwan_odds=odds,
        )

        if not comp:
            return None

        # Build PredictionSignal
        metadata = {
            "sharp_fair_probability": round(comp.sharp_fair_prob, 4),
            "edge_pp": comp.edge_pp,
            "expected_value_pct": comp.expected_value_pct,
            "is_value_bet": comp.is_value_bet,
            "value_grade": comp.value_grade,
            "sharp_book": comp.sharp_book,
        }

        confidence = "HIGH" if comp.is_value_bet else ("MED" if comp.value_grade == "FAIR_VALUE" else "LOW")
        observed_at = parse_aware_time(comp.timestamp)
        freshness = (
            "AGING"
            if observed_at and (datetime.now(timezone.utc) - observed_at).total_seconds() > 300
            else "LIVE"
        )

        return PredictionSignal(
            source_id="sharp_benchmark",
            source_name=f"Sharp Market Benchmark ({comp.sharp_book})",
            source_type="SHARP_BENCHMARK",
            source_category=self.SOURCE_CATEGORY,
            independence_group=self.INDEPENDENCE_GROUP,
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=comp.sharp_fair_prob,
            confidence=confidence,
            data_as_of=comp.timestamp,
            freshness_status=freshness,
            metadata=metadata,
        )
