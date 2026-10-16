#!/usr/bin/env python3
"""Standard data models for the Taiwan Betting Adapter Layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelQualityLabel:
    """Standardized model reliability classification."""
    MODEL_HIGH_QUALITY = "MODEL_HIGH_QUALITY"
    MODEL_EXPERIMENTAL = "MODEL_EXPERIMENTAL"
    MODEL_STALE = "MODEL_STALE"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    NO_MODEL = "NO_MODEL"


@dataclass
class PredictionSignal:
    """Standard signal emitted by any prediction, expert, crowd, or market source."""
    source_id: str
    source_name: str
    source_type: str                     # 'BETTING_MARKET', 'EXPERT', 'CROWD', 'MODEL', 'SCHEDULE'
    event_id: str
    market: str                          # '讓分', '不讓分', '大小', '和局'
    selection: str                       # e.g. '道奇 客勝 (1.52)'
    probability: Optional[float] = None  # e.g. 0.64
    score: Optional[float] = None        # e.g. +3.2 or xG 1.85
    confidence: Optional[str] = None     # 'HIGH', 'MED', 'LOW', 'REFERENCE_ONLY'
    pick: Optional[str] = None           # e.g. '客' or '大'
    rank: Optional[int] = None           # e.g. Expert leaderboard rank #1
    source_category: str = ""            # 'OPEN_SOURCE_ENGINE', 'PUBLIC_MODEL', 'LOCAL_FALLBACK_MODEL', 'VERIFIED_EXPERT', 'CROWD_CONSENSUS', 'BETTING_MARKET', 'MODEL_STALE'
    independence_group: str = ""         # 'DIXON_COLES_MATCHES', 'ESPN_SEASON_STATS', 'FIVETHIRTYEIGHT_ELO', 'PLAYSPORT_EXPERT', 'PLAYSPORT_CROWD', 'TAIWAN_MARKET'
    timestamp: str = field(default_factory=get_now_iso)
    data_as_of: Optional[str] = None
    data_age_hours: Optional[float] = None
    freshness_status: str = "UNKNOWN"    # 'LIVE', 'FRESH', 'AGING', 'STALE', 'UNKNOWN'
    market_implied_probability: Optional[float] = None
    model_probability: Optional[float] = None
    model_market_delta_pp: Optional[float] = None
    quality_label: str = "MODEL_EXPERIMENTAL"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "event_id": self.event_id,
            "market": self.market,
            "selection": self.selection,
            "probability": self.probability,
            "score": self.score,
            "confidence": self.confidence,
            "pick": self.pick,
            "rank": self.rank,
            "source_category": self.source_category,
            "independence_group": self.independence_group,
            "timestamp": self.timestamp,
            "data_as_of": self.data_as_of,
            "data_age_hours": self.data_age_hours,
            "freshness_status": self.freshness_status,
            "market_implied_probability": self.market_implied_probability,
            "model_probability": self.model_probability,
            "model_market_delta_pp": self.model_market_delta_pp,
            "quality_label": self.quality_label,
            "metadata": self.metadata,
        }


@dataclass
class VerifiedExpertPick:
    """Authentic pick verified on an expert's personal prediction page."""
    expert_userid: str
    expert_nickname: str
    rank: int
    win_percentage: float
    wins: int
    losses: int
    sport: str
    league: str
    event_id: str
    away_team: str
    home_team: str
    market: str                          # '不讓分', '讓分', '大小'
    side: str                            # '主', '客', '和', '大', '小'
    line: Optional[str] = None           # e.g. '-1.5', '8.5'
    raw_pick: str = ""
    pick_date: Optional[str] = None      # e.g. '2026-09-18'
    pick_timestamp: str = "TIMESTAMP_UNKNOWN"
    is_before_event: Optional[bool] = None
    verified_via: str = "playsport_member_prediction_page"

    @property
    def away_raw(self) -> str:
        return self.away_team

    @property
    def home_raw(self) -> str:
        return self.home_team

    def __getitem__(self, item: str) -> Any:
        if item == "away_raw":
            return self.away_team
        if item == "home_raw":
            return self.home_team
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expert_userid": self.expert_userid,
            "expert_nickname": self.expert_nickname,
            "rank": self.rank,
            "win_percentage": self.win_percentage,
            "wins": self.wins,
            "losses": self.losses,
            "sample_size": self.wins + self.losses,
            "sport": self.sport,
            "league": self.league,
            "event_id": self.event_id,
            "away_team": self.away_team,
            "home_team": self.home_team,
            "away_raw": self.away_team,
            "home_raw": self.home_team,
            "market": self.market,
            "side": self.side,
            "line": self.line,
            "raw_pick": self.raw_pick,
            "pick_date": self.pick_date,
            "pick_timestamp": self.pick_timestamp,
            "is_before_event": self.is_before_event,
            "verified_via": self.verified_via,
        }


@dataclass
class TaiwanLeg:
    """A genuine betting selection available in Taiwan Sports Lottery.

    All Parlay calculations MUST be based strictly on this object and its taiwan_odds!
    """
    event_id: str                        # 台灣運彩賽事編號 (e.g. '116')
    sport: str                           # 'baseball', 'soccer', 'football', 'basketball'
    league: str                          # e.g. 'MLB', '英超', 'NFL'
    market: str                          # '讓分', '不讓分', '大小', '和局'
    selection: str                       # e.g. '釀酒人 不讓分勝'
    taiwan_odds: float                   # 台灣運彩實際盤口賠率 (MUST be > 1.0)
    start_time: str = ""                      # Unknown is not a midnight kickoff.
    away_team: str = "客隊"                       # e.g. '釀酒人'
    home_team: str = "主隊"                       # e.g. '海盜'
    side: str = "客"                     # '客', '主', '和', '大', '小'
    line: Optional[str] = None           # e.g. '-1.5' or '8.5'
    canonical_event_id: Optional[str] = None
    start_time_utc: Optional[str] = None
    away_pitcher: Optional[str] = None
    home_pitcher: Optional[str] = None
    odds_scraped_at: Optional[str] = None
    odds_age_minutes: Optional[float] = None
    odds_status: str = "UNKNOWN"         # 'LIVE', 'FRESH', 'STALE_CACHE', 'UNAVAILABLE'
    reference_odds: Optional[float] = None
    price_difference_desc: Optional[str] = None
    evidence_quality: str = "INSUFFICIENT_SIGNAL"
    signal_evidence: Dict[str, Any] = field(default_factory=dict)
    signals: List[PredictionSignal] = field(default_factory=list)
    eligible_for_parlay: bool = True
    market_probability: Optional[float] = None
    model_probability_raw: Optional[float] = None
    model_probability_calibrated: Optional[float] = None
    consensus_probability: Optional[float] = None
    edge: Optional[float] = None
    expected_value: Optional[float] = None
    conservative_ev: Optional[float] = None
    confidence_interval: Optional[Tuple[float, float]] = None
    uncertainty_level: Optional[str] = None
    recommendation_odds: Optional[float] = None
    placed_odds: Optional[float] = None
    closing_odds: Optional[float] = None
    clv: Optional[float] = None
    source_families: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.taiwan_odds is None or self.taiwan_odds <= 1.0:
            self.eligible_for_parlay = False
        if self.recommendation_odds is None and self.taiwan_odds:
            self.recommendation_odds = self.taiwan_odds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "match_id": self.event_id,
            "canonical_event_id": self.canonical_event_id,
            "sport": self.sport,
            "league": self.league,
            "market": self.market,
            "market_type": self.market,
            "selection": self.selection,
            "odds": self.taiwan_odds,
            "taiwan_odds": self.taiwan_odds,
            "start_time": self.start_time,
            "game_time": self.start_time,
            "start_time_utc": self.start_time_utc,
            "away_team": self.away_team,
            "home_team": self.home_team,
            "away_pitcher": self.away_pitcher,
            "home_pitcher": self.home_pitcher,
            "odds_scraped_at": self.odds_scraped_at,
            "odds_age_minutes": self.odds_age_minutes,
            "odds_status": self.odds_status,
            "reference_odds": self.reference_odds,
            "price_difference_desc": self.price_difference_desc,
            "side": self.side,
            "line": self.line,
            "evidence_quality": self.evidence_quality,
            "signal_evidence": self.signal_evidence,
            "signals": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.signals],
            "eligible_for_parlay": self.eligible_for_parlay,
            "market_probability": self.market_probability,
            "model_probability_raw": self.model_probability_raw,
            "model_probability_calibrated": self.model_probability_calibrated,
            "consensus_probability": self.consensus_probability,
            "edge": self.edge,
            "expected_value": self.expected_value,
            "conservative_ev": self.conservative_ev,
            "confidence_interval": list(self.confidence_interval) if self.confidence_interval else None,
            "uncertainty_level": self.uncertainty_level,
            "recommendation_odds": self.recommendation_odds,
            "placed_odds": self.placed_odds,
            "closing_odds": self.closing_odds,
            "clv": self.clv,
            "source_families": self.source_families,
        }
