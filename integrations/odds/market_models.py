#!/usr/bin/env python3
"""Standardized International Market Intelligence & Betting Splits Data Models.

Part of Sportslottery Phase 4: Global Market Intelligence & Prediction Quality Upgrade.
Adheres strictly to the unified market contract:
- Full provenance and timestamp integrity
- Preserves explicit None/null when values are not observed (never fabricated)
- Defines explicit alignment and data freshness statuses
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class MarketFreshnessStatus(str, Enum):
    LIVE = "LIVE"
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class MarketAlignmentStatus(str, Enum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"
    STALE = "STALE"
    MARKET_NOT_EQUIVALENT = "MARKET_NOT_EQUIVALENT"


class SignalClassification(str, Enum):
    CROWD_SENTIMENT = "CROWD_SENTIMENT"           # 玩運彩彩迷選票
    EXPERT_PICKS = "EXPERT_PICKS"                 # 專家推薦/達人預測
    BET_COUNT_SPLITS = "BET_COUNT_SPLITS"         # 國際投注張數比例 (Bets %)
    MONEY_VOLUME_SPLITS = "MONEY_VOLUME_SPLITS"   # 國際投注金額比例 (Money %)
    MARKET_BENCHMARK = "MARKET_BENCHMARK"         # 國際盤口/Sharp 定價
    STATISTICAL_MODEL = "STATISTICAL_MODEL"       # 獨立統計模型預測


@dataclass
class MarketOddsSnapshot:
    """Standardized snapshot of bookmaker or consensus market odds."""
    source_id: str                                # e.g. "the_odds_api:pinnacle"
    source_type: str                              # "BOOKMAKER", "EXCHANGE", "CONSENSUS", "SYNTHETIC_FIXTURE"
    event_id: str                                 # Unique identifier in external provider
    league: str                                   # e.g. "MLB", "NBA", "EPL", "NFL"
    home_team: str                                # Standard English or canonical name
    away_team: str                                # Standard English or canonical name
    start_time_utc: str                           # ISO-8601 UTC string
    market_type: str                              # "MONEYLINE", "SPREAD", "TOTAL"
    selection: str                                # e.g. "home", "away", "over", "under", "draw"
    decimal_odds: float                           # Must be decimal odds >= 1.0
    observed_at_utc: str                          # When the bookmaker published or reported the odds
    retrieved_at_utc: str                         # When our system fetched the odds
    freshness_status: str                         # LIVE, FRESH, AGING, STALE, UNKNOWN
    line: Optional[float] = None                  # Spread handicap or total threshold (e.g. -1.5, 7.5)
    evidence_url: Optional[str] = None            # Provenance URL
    source_license: Optional[str] = None          # Terms of use or license identifier
    is_synthetic: bool = False                    # True if mock/testing fallback
    raw_payload: Optional[Dict[str, Any]] = None  # Preserved raw payload for audits

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not self.raw_payload:
            data.pop("raw_payload", None)
        return data


@dataclass
class BettingSplitsSnapshot:
    """Standardized snapshot of public betting splits (tickets vs money volume)."""
    source_id: str                                # e.g. "vsin_splits", "action_network"
    source_type: str                              # "BETTING_SPLITS"
    event_id: str
    league: str
    home_team: str
    away_team: str
    start_time_utc: str
    market_type: str                              # "SPREAD", "MONEYLINE", "TOTAL"
    selection: str                                # "home", "away", "over", "under"
    bet_percentage: Optional[float]               # Tickets percentage 0.0 - 100.0 (null if not available)
    money_percentage: Optional[float]             # Money handle percentage 0.0 - 100.0 (null if not available)
    sample_size: Optional[int]                    # Total bets or handle index if known (null if omitted)
    reporting_bookmaker: Optional[str]            # e.g. "DraftKings", "Circa", "Consensus"
    reporting_scope: Optional[str]                # e.g. "US_COMMERCIAL", "VEGAS_LOCAL"
    observed_at_utc: str
    retrieved_at_utc: str
    freshness_status: str
    line: Optional[float] = None
    evidence_url: Optional[str] = None
    source_license: Optional[str] = None
    is_synthetic: bool = False
    raw_payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not self.raw_payload:
            data.pop("raw_payload", None)
        return data


@dataclass
class MarketAlignmentRecord:
    """Audit record capturing the precision alignment between TaiwanLeg and International Market."""
    status: MarketAlignmentStatus
    taiwan_event_id: str
    taiwan_league: str
    taiwan_market: str
    taiwan_selection: str
    taiwan_side: str
    taiwan_line: Optional[str]
    international_event_id: Optional[str]
    international_source_id: Optional[str]
    international_market_type: Optional[str]
    international_selection: Optional[str]
    international_line: Optional[float]
    aligned_at_utc: str
    time_delta_seconds: Optional[float] = None
    team_name_similarity: Optional[float] = None
    reason: str = ""
    rejection_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data
