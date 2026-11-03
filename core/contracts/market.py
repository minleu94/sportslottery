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


TAIWAN_MARKET_TO_ODDS_API = {
    "不讓分": "h2h", "和局": "h2h", "獨贏": "h2h", "勝負": "h2h",
    "moneyline": "h2h", "h2h": "h2h",
    "讓分": "spreads", "讓球": "spreads", "spread": "spreads", "spreads": "spreads",
    "大小": "totals", "大小分": "totals", "總分": "totals", "total": "totals", "totals": "totals",
}
MARKET_LINE_TOLERANCE = 0.01


def market_lines_equal(first: Optional[float], second: Optional[float], tolerance: float = MARKET_LINE_TOLERANCE) -> bool:
    """Compare two optional market lines with one shared tolerance."""
    if first is None or second is None:
        return first is None and second is None
    try:
        import math

        return math.isfinite(float(first)) and math.isfinite(float(second)) and math.isclose(
            float(first), float(second), abs_tol=tolerance
        )
    except (TypeError, ValueError, OverflowError):
        return False


def opposite_market_selection(market_type: str, selection: str) -> Optional[str]:
    """Return the complementary selection for a two-sided market."""
    opposites = {
        "SPREAD": {"home": "away", "away": "home"},
        "TOTAL": {"over": "under", "under": "over"},
        "MONEYLINE": {"home": "away", "away": "home"},
    }
    return opposites.get(str(market_type or "").upper(), {}).get(str(selection or "").casefold())


def opposing_market_line(market_type: str, line: Optional[float]) -> Optional[float]:
    """Return the opposite side's required line for a spread or total."""
    if line is None:
        return None
    market = str(market_type or "").upper()
    if market == "SPREAD":
        return -float(line)
    if market == "TOTAL":
        return float(line)
    return None


def canonical_market_event_id(sport: str, league: str, provider_event_id: str, kickoff_iso: Optional[str]) -> str:
    """Build the stable market event key used in benchmark lineage."""
    return ":".join((
        str(sport or "").casefold(),
        str(league or "").casefold(),
        str(provider_event_id or ""),
        str(kickoff_iso or "UNKNOWN_KICKOFF"),
    ))


@dataclass(frozen=True)
class MarketSelectionIdentity:
    """Comparable market/selection/line tuple shared by alignment and pricing."""

    market_type: str
    selection: str
    line: Optional[float]

    def same_outcome(self, other: "MarketSelectionIdentity") -> bool:
        return (
            str(self.market_type).upper() == str(other.market_type).upper()
            and str(self.selection).casefold() == str(other.selection).casefold()
            and market_lines_equal(self.line, other.line)
        )

    def opposite_outcome(self, other: "MarketSelectionIdentity") -> bool:
        market = str(self.market_type or "").upper()
        if market != str(other.market_type or "").upper():
            return False
        expected_selection = opposite_market_selection(market, self.selection)
        if expected_selection is None or expected_selection != str(other.selection or "").casefold():
            return False
        expected_line = opposing_market_line(market, self.line)
        return market_lines_equal(expected_line, other.line)


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
    observed_at_utc: Optional[str]                # Market-level quote time; null when provider omitted it
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
class MarketBenchmarkEvidence:
    """Validated international market evidence consumed by research decisions."""

    taiwan_event_id: str
    taiwan_selection: str
    canonical_event_id: str
    sport: str
    league: str
    market_type: str
    selection: str
    line: Optional[float]
    source_id: str
    bookmaker_ids: List[str]
    raw_outcome_odds: Dict[str, Dict[str, float]]
    market_observation_times: Dict[str, Dict[str, Optional[str]]]
    retrieved_at_utc: str
    is_synthetic: bool
    devig_method: Optional[str]
    fair_probability: Optional[float]
    sharp_fair_probability: Optional[float]
    source_qualification: str
    complete: bool
    freshness_status: str
    eligible: bool
    eligibility_reason: Optional[str] = None
    sharp_qualified_source_ids: List[str] = field(default_factory=list)
    bookmaker_evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
