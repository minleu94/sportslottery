"""Typed response contracts for the React-facing market and research APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtensibleResponse(BaseModel):
    """Document stable fields while preserving additive legacy response data."""

    model_config = ConfigDict(extra="allow")


class RadarLeagueResponse(ExtensibleResponse):
    code: str
    name: str
    icon: str
    status: str
    status_text: str
    light_emoji: str
    game_count: int
    taiwan_market_count: int
    espn_event_count: Optional[int] = None
    in_season_calendar: Optional[bool] = None
    opportunity_badge: Optional[str] = None
    positive_ev_count: Optional[int] = None
    banker_count: Optional[int] = None
    high_agreement_count: Optional[int] = None
    games: List[Dict[str, Any]] = Field(default_factory=list)


class RadarStatusCounts(ExtensibleResponse):
    GREEN: int
    YELLOW: int
    RED: int


class RadarResponse(ExtensibleResponse):
    radar: List[RadarLeagueResponse]
    status_counts: RadarStatusCounts
    total_legs: int
    source_status: Dict[str, Any]
    as_of: str


class SignalResponse(ExtensibleResponse):
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    type: Optional[str] = None
    pick: Optional[str] = None
    confidence: Optional[str] = None


class TaiwanLegResponse(ExtensibleResponse):
    event_id: str
    sport: str
    league: str
    market: str
    selection: str
    odds: float
    taiwan_odds: float
    away_team: str
    home_team: str
    match_id: Optional[str] = None
    canonical_event_id: Optional[str] = None
    market_type: Optional[str] = None
    display_league: Optional[str] = None
    start_time: Optional[str] = None
    game_time: Optional[str] = None
    start_time_utc: Optional[str] = None
    away_pitcher: Optional[str] = None
    home_pitcher: Optional[str] = None
    side: Optional[str] = None
    line: Optional[str] = None
    evidence_quality: Optional[str] = None
    signal_evidence: Dict[str, Any] = Field(default_factory=dict)
    signals: List[SignalResponse] = Field(default_factory=list)
    expected_value: Optional[float] = None
    expected_value_pct: Optional[float] = None
    consensus_probability: Optional[float] = None
    market_implied_pct: Optional[float] = None
    agreement_badge: Optional[str] = None
    is_positive_ev: Optional[bool] = None
    is_sharp_value_bet: Optional[bool] = None
    crowd_desc: Optional[str] = None
    line_movement_label: Optional[str] = None
    edge: Optional[float] = None
    market_probability: Optional[float] = None
    model_probability_calibrated: Optional[float] = None
    is_market_synthetic: Optional[bool] = None
    is_splits_synthetic: Optional[bool] = None


class LegsResponse(ExtensibleResponse):
    total: int
    returned: int
    alliances: List[str]
    legs: List[TaiwanLegResponse]


class ResearchAnalyticsResponse(ExtensibleResponse):
    total_snapshots: int
    cohort: Dict[str, Any]
    agreement: Dict[str, Any]
    ev_data: Dict[str, Any]
    crowd_data: Dict[str, Any]
    expert_data: Dict[str, Any]
    shadow_portfolio: Dict[str, Any]


class MarketResearchSummaryResponse(ExtensibleResponse):
    live_status: str
    live_status_scope: str
    the_odds_api: Dict[str, Any]
    alignment: Dict[str, Any]
    scheduler: Optional[Dict[str, Any]] = None
    snapshots: Dict[str, Any]
    forward_evaluation: Dict[str, Any]
    as_of_utc: str


class QuantitativeMetricsResponse(ExtensibleResponse):
    sample_size: int
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    clv_mean_pct: Optional[float] = None
    settled_roi_pct: Optional[float] = None
    roi_ci_95: Optional[tuple[float, float]] = None
    brier_ci_95: Optional[tuple[float, float]] = None
    pnl_drawdown_amount: Optional[float] = None
    win_rate_pct: Optional[float] = None
    status: str
    bet_count: int = 0
    simulated_roi_pct: Optional[float] = None
    simulated_roi_ci_95: Optional[tuple[float, float]] = None
    simulated_bet_count: int = 0


class ForwardEvaluationResponse(ExtensibleResponse):
    evaluation_scope: str
    as_of_utc: str
    sample_size: int
    paired_sample_size: int
    taiwan_market_baseline: QuantitativeMetricsResponse
    international_sharp_benchmark: QuantitativeMetricsResponse
    active_model_strategy: QuantitativeMetricsResponse
    delta_roi_vs_taiwan_base_pp: Optional[float] = None
    delta_roi_vs_sharp_benchmark_pp: Optional[float] = None
    delta_brier_vs_sharp_benchmark: Optional[float] = None
    delta_brier_ci_95: Optional[tuple[float, float]] = None
    champion_source: str
    acceptance_gate_qualified: bool
    status: str
    shadow_mode_recommendation: str
    international_market_benchmark: Optional[QuantitativeMetricsResponse] = None
    market_paired_sample_size: int = 0
    sharp_paired_sample_size: int = 0
    delta_brier_vs_market_benchmark: Optional[float] = None
    delta_brier_market_ci_95: Optional[tuple[float, float]] = None
    data_quality_status: str = "UNKNOWN"
    evaluation_protocol_status: str = "UNKNOWN"
    statistical_evidence_status: str = "UNKNOWN"


class ParlaySearchPerformanceResponse(ExtensibleResponse):
    service_setup_ms: float
    taiwan_fetch_ms: float
    signal_enrichment_ms: float
    parlay_search_ms: float
    response_format_ms: float
    total_ms: float
    raw_legs_count: int
    prepared_legs_cache_hit: bool


class ParlayRecommendationResponse(ExtensibleResponse):
    candidate_id: str
    parlay_id: str
    parlay_name: str
    total_odds: float
    total_odds_exact: Optional[float] = None
    legs_count: int
    tier: str
    legs: List[TaiwanLegResponse]
    expected_value: Optional[float] = None
    parlay_expected_value: Optional[float] = None
    parlay_ev_pct: Optional[float] = None
    sharp_parlay_ev: Optional[float] = None
    sharp_parlay_ev_pct: Optional[float] = None
    joint_probability: Optional[float] = None
    sharp_joint_probability: Optional[float] = None
    has_sharp_benchmark: Optional[bool] = None
    joint_probability_validation_status: Optional[str] = None
    joint_probability_sources: List[str] = Field(default_factory=list)
    parlay_expected_value_source: Optional[str] = None
    credible_value_basis: Optional[bool] = None
    credible_value_status: Optional[str] = None
    sharp_badge: Optional[str] = None
    is_positive_ev: Optional[bool] = None
    is_valid: Optional[bool] = None


class ParlayTiersResponse(ExtensibleResponse):
    high_consensus: List[ParlayRecommendationResponse]
    aggressive: List[ParlayRecommendationResponse]
    moonshot: List[ParlayRecommendationResponse]


class ParlaySearchResponse(ExtensibleResponse):
    target_odds: float
    min_odds: float
    max_odds: float
    tolerance: float
    tiers: ParlayTiersResponse
    diagnostics: Dict[str, Any]
    search_complete: bool
    total_combinations_searched: int
    enriched_legs_count: int
    performance: Optional[ParlaySearchPerformanceResponse] = None


__all__ = [
    "LegsResponse",
    "ForwardEvaluationResponse",
    "MarketResearchSummaryResponse",
    "ParlayRecommendationResponse",
    "ParlaySearchPerformanceResponse",
    "ParlaySearchResponse",
    "ParlayTiersResponse",
    "RadarLeagueResponse",
    "RadarResponse",
    "RadarStatusCounts",
    "QuantitativeMetricsResponse",
    "ResearchAnalyticsResponse",
    "SignalResponse",
    "TaiwanLegResponse",
]
