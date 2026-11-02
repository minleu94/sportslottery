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
from integrations.odds.market_models import MarketBenchmarkEvidence

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
    """Adapter for validated Sharp evidence supplied by the market pipeline."""

    SOURCE_CATEGORY = "SHARP_MARKET_BENCHMARK"
    INDEPENDENCE_GROUP = "SHARP_CONSENSUS"

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR

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
        """Deprecated cache-only entry point; Taiwan odds cannot qualify as Sharp.

        Use ``evaluate_leg(leg, market_evidence)`` with typed evidence from the
        validated international market pipeline.
        """
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

    def evaluate_leg(
        self,
        leg: TaiwanLeg,
        market_evidence: Optional[MarketBenchmarkEvidence] = None,
    ) -> Optional[PredictionSignal]:
        """Adapt explicitly validated Sharp evidence; never discover or infer it locally."""
        comp = self.compare_leg(leg, market_evidence)
        if comp is None:
            return None
        sharp_source_id = str(comp.details.get("source_id") or "")
        metadata = {
            "sharp_fair_probability": round(comp.sharp_fair_prob, 4),
            "edge_pp": comp.edge_pp,
            "expected_value_pct": comp.expected_value_pct,
            "is_value_bet": comp.is_value_bet,
            "value_grade": comp.value_grade,
            "sharp_book": comp.sharp_book,
            "source_id": sharp_source_id,
            "canonical_event_id": market_evidence.canonical_event_id,
            "market_source_qualification": market_evidence.source_qualification,
            "market_freshness": market_evidence.freshness_status,
            "market_devig_method": market_evidence.devig_method,
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

    def compare_leg(
        self,
        leg: TaiwanLeg,
        market_evidence: Optional[MarketBenchmarkEvidence] = None,
    ) -> Optional[SharpComparisonResult]:
        """Return a comparison only for complete, fresh, typed Sharp evidence."""
        try:
            odds = float(leg.taiwan_odds or 0.0)
            sharp_probability = float(market_evidence.sharp_fair_probability) if isinstance(market_evidence, MarketBenchmarkEvidence) else 0.0
        except (TypeError, ValueError, OverflowError):
            return None
        if odds <= 1.0 or not isinstance(market_evidence, MarketBenchmarkEvidence):
            return None
        if (
            market_evidence.eligible is not True
            or market_evidence.complete is not True
            or market_evidence.is_synthetic is not False
            or market_evidence.source_qualification != "SHARP_QUALIFIED"
            or not isinstance(market_evidence.source_id, str)
            or not market_evidence.source_id.startswith("the_odds_api:")
            or not market_evidence.sharp_qualified_source_ids
            or market_evidence.taiwan_event_id != str(leg.event_id)
            or market_evidence.taiwan_selection != str(leg.selection)
            or market_evidence.market_type != ("SPREAD" if leg.market in {"讓分", "讓球"} else
                                                "TOTAL" if leg.market in {"大小", "大小分", "總分"} else "MONEYLINE")
            or not math.isfinite(odds)
            or not math.isfinite(sharp_probability)
            or not 0.0 < sharp_probability < 1.0
        ):
            return None
        raw_quotes = market_evidence.raw_outcome_odds
        raw_times = market_evidence.market_observation_times
        qualified_sources = market_evidence.sharp_qualified_source_ids
        if not isinstance(raw_quotes, dict) or not isinstance(raw_times, dict):
            return None
        if not isinstance(qualified_sources, (list, tuple, set)):
            return None
        sharp_source_id = next((str(item) for item in qualified_sources
                                if isinstance(item, str) and item.startswith("the_odds_api:")
                                and item in raw_quotes and item in raw_times), None)
        if sharp_source_id is None:
            return None
        sharp_book_name = sharp_source_id.split(":", 1)[-1].casefold()
        if not any(str(book).casefold() == sharp_book_name
                   for book in market_evidence.bookmaker_ids if isinstance(book, str)):
            return None
        outcome_odds = raw_quotes.get(sharp_source_id, {})
        outcome_times = raw_times.get(sharp_source_id, {})
        if not isinstance(outcome_odds, dict) or len(outcome_odds) < 2 or not isinstance(outcome_times, dict):
            return None
        if (str(leg.sport or "").casefold() == "soccer" and market_evidence.market_type == "MONEYLINE"
                and not {"home", "away", "draw"}.issubset(outcome_odds)):
            return None
        if any(not isinstance(key, str) or key not in outcome_times for key in outcome_odds):
            return None
        parsed_outcome_odds: Dict[str, float] = {}
        for key, value in outcome_odds.items():
            try:
                parsed_value = float(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(parsed_value) or parsed_value <= 1.0:
                return None
            parsed_outcome_odds[key] = parsed_value
        quote_times = [parse_aware_time(outcome_times.get(key)) for key in outcome_odds]
        retrieved_at = parse_aware_time(market_evidence.retrieved_at_utc)
        now = datetime.now(timezone.utc)
        if retrieved_at is None or not quote_times or any(item is None for item in quote_times):
            return None
        if any((now - item).total_seconds() > 900 or (retrieved_at - item).total_seconds() < -60
               for item in quote_times if item is not None):
            return None
        if (now - retrieved_at).total_seconds() < -60 or (now - retrieved_at).total_seconds() > 900:
            return None
        sharp_odds = parsed_outcome_odds.get(market_evidence.selection)
        if sharp_odds is None:
            return None
        observed_dt = parse_aware_time(outcome_times.get(market_evidence.selection))
        if observed_dt is None or (now - observed_dt).total_seconds() > 300:
            return None
        return self._build_comparison(
            event_id=leg.event_id, sport=leg.sport, league=leg.league, market=leg.market,
            selection=leg.selection, taiwan_odds=odds, sharp_odds=sharp_odds,
            sharp_fair_prob=sharp_probability,
            sharp_book=sharp_source_id.split(":", 1)[-1],
            observed_at_utc=observed_dt.isoformat(), source_id=sharp_source_id,
        )
