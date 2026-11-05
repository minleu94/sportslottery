export type JsonRecord = Record<string, unknown>
export type RadarStatus = "GREEN" | "YELLOW" | "RED" | "UNKNOWN"
export type ParlayTier = "high_consensus" | "aggressive" | "moonshot"

export interface PredictionSignal {
  source_id?: string
  source_name?: string
  source_type?: string
  type?: string
  event_id?: string
  market?: string
  selection?: string
  probability?: number | null
  score?: number | null
  confidence?: string | null
  pick?: string | null
  timestamp?: string
  freshness_status?: string
  metadata?: JsonRecord
}

export interface LineMovementEvidence extends JsonRecord {
  text_label?: string
  is_steam?: boolean
  is_trap_warning?: boolean
}

export interface LegSignalEvidence extends JsonRecord {
  consensus_ratio?: number | null
  expected_value_pct?: number | null
  sharp_expected_value_pct?: number | null
  sharp_fair_probability?: number | null
  market_fair_probability?: number | null
  market_fair_method?: string
  market_implied_probability?: number | null
  market_benchmark_fair_probability?: number | null
  market_benchmark_ev_pct?: number | null
  market_benchmark_status?: string
  probability_status?: string
  calibration_status?: string
  model_probability_calibrated?: number | null
  model_candidate_probability_fused?: number | null
  model_candidate_provenances?: JsonRecord[]
  model_accepted_ids?: string[]
  market_source_qualification?: string
  vote_count?: number | null
  bet_percentage?: number | null
  money_percentage?: number | null
  is_market_synthetic?: boolean
  is_splits_synthetic?: boolean
  is_sharp_money_divergence?: boolean
  line_movement?: LineMovementEvidence
}

export interface Leg {
  event_id: string
  match_id?: string
  canonical_event_id?: string | null
  sport: string
  league: string
  display_league?: string
  market: string
  market_type?: string
  selection: string
  odds: number
  taiwan_odds: number
  start_time?: string
  game_time?: string
  start_time_utc?: string | null
  away_team: string
  home_team: string
  away_pitcher?: string | null
  home_pitcher?: string | null
  side?: string
  line?: string | null
  evidence_quality?: string
  signal_evidence?: LegSignalEvidence
  signals?: PredictionSignal[]
  odds_scraped_at?: string | null
  odds_age_minutes?: number | null
  odds_status?: string
  eligible_for_parlay?: boolean
  expected_value?: number | null
  expected_value_pct?: number | null
  consensus_probability?: number | null
  market_implied_pct?: number | null
  agreement_badge?: string
  is_positive_ev?: boolean
  is_sharp_value_bet?: boolean
  crowd_desc?: string
  line_movement_label?: string
  edge?: number | null
  market_probability?: number | null
  model_probability_raw?: number | null
  model_probability_calibrated?: number | null
  is_market_synthetic?: boolean
  is_splits_synthetic?: boolean
}

export interface RadarGame extends JsonRecord {
  event_id?: string
  home_team?: string
  away_team?: string
  start_time?: string
  start_time_utc?: string
}

export interface RadarLeague {
  code: string
  name: string
  icon: string
  status: RadarStatus
  status_text: string
  light_emoji: string
  game_count: number
  taiwan_market_count: number
  espn_event_count?: number
  schedule_source_status?: string
  schedule_source_error?: string | null
  in_season_calendar?: boolean
  opportunity_badge?: string
  positive_ev_count?: number
  banker_count?: number
  high_agreement_count?: number
  games?: RadarGame[]
  // Compatibility aliases used by a few older display helpers.
  league_id?: string
  league_name?: string
  sport?: string
  reason?: string
  active_legs_count?: number
}

export interface RadarResponse {
  radar: RadarLeague[]
  status_counts: { GREEN: number; YELLOW: number; RED: number }
  total_legs: number
  source_status: Record<string, JsonRecord>
  as_of: string
}

export interface LegsResponse {
  total: number
  returned: number
  alliances: string[]
  legs: Leg[]
}

export interface ParlayRecommendation {
  candidate_id: string
  parlay_id: string
  parlay_name: string
  total_odds: number
  total_odds_exact?: number | null
  legs_count: number
  tier: ParlayTier
  legs: Leg[]
  expected_value?: number | null
  parlay_expected_value?: number | null
  parlay_ev_pct?: number | null
  sharp_parlay_ev?: number | null
  sharp_parlay_ev_pct?: number | null
  joint_probability?: number | null
  sharp_joint_probability?: number | null
  has_sharp_benchmark?: boolean
  joint_probability_validation_status?: string
  joint_probability_sources?: string[]
  parlay_expected_value_source?: string
  credible_value_basis?: boolean
  credible_value_status?: string
  sharp_badge?: string
  is_positive_ev?: boolean
  is_valid?: boolean
  confidence_score?: number
  signal_summary?: string
  correlation_risk_grade?: string
}

export interface ParlaySearchPerformance {
  service_setup_ms: number
  taiwan_fetch_ms: number
  signal_enrichment_ms: number
  parlay_search_ms: number
  response_format_ms: number
  total_ms: number
  raw_legs_count: number
  prepared_legs_cache_hit: boolean
}

export interface ParlaySearchResponse {
  target_odds: number
  min_odds: number
  max_odds: number
  tolerance: number
  tiers: Record<ParlayTier, ParlayRecommendation[]>
  diagnostics: JsonRecord
  search_complete: boolean
  total_combinations_searched: number
  enriched_legs_count: number
  performance?: ParlaySearchPerformance
}

export interface WalletStatus {
  profile_id: string
  profile_name?: string
  weekly_wallet_balance: number
  weekly_staked: number
  weekly_won: number
  weekly_external_deposited: number
  prize_pool: number
  lifetime_staked: number
  lifetime_won: number
  lifetime_external_deposited: number
  lifetime_net_profit: number
  weekly_play_cap: number
  external_deposit_remaining: number
  can_deposit: boolean
  can_stake: boolean
  current_week: string
}

export interface TicketLeg extends JsonRecord {
  event_id?: string
  event_name?: string
  away_team?: string
  home_team?: string
  selection?: string
  odds?: number
}

export interface Ticket {
  ticket_id: string
  profile_id: string
  created_at: string
  stake: number
  total_odds: number
  placed_odds: number
  potential_payout: number
  status: "PENDING" | "WON" | "LOST" | "VOID"
  actual_payout?: number
  notes?: string
  legs: TicketLeg[]
}

export interface Profile {
  id: string
  name: string
  weekly_play_cap: number
  created_at?: string
  updated_at?: string
}

export interface RequestMetrics {
  api_requests?: number
  cache_hits?: number
  coalesced_requests?: number
  request_failures?: number
  quota_skips?: number
  backoff_skips?: number
}

export interface OddsApiStatus {
  operating_mode?: string
  has_api_key?: boolean
  key_masked?: string | null
  status?: string
  last_successful_fetch_utc?: string | null
  requests_used_this_month?: number
  monthly_budget?: number
  monthly_quota?: number
  official_remaining?: number | null
  requests_remaining_est?: number | null
  requests_last_consumed?: number
  daily_schedulable_budget?: number
  request_metrics?: RequestMetrics
  [key: string]: unknown
}

export interface SnapshotSummary {
  total_count: number
  settled_count: number
  pending_count?: number
  pre_match_verified_count?: number
  post_match_leak_count?: number
  legacy_unverified_count?: number
  forward_eligible_count?: number
  valid_prediction_hash_count?: number
  market_benchmark_count?: number
  sharp_qualified_benchmark_count?: number
  excluded_breakdown?: Record<string, number>
}

export interface ForwardEvaluationSummary {
  sample_size: number
  paired_sample_size: number
  market_paired_sample_size: number
  sharp_paired_sample_size: number
  minimum_sample_size: number
  status: string
  data_quality_status?: string
  evaluation_protocol_status?: string
  statistical_evidence_status?: string
  champion_source?: string
  acceptance_gate_qualified: boolean
  shadow_mode_recommendation?: string
  delta_brier_ci_95?: [number, number] | null
  delta_brier_market_ci_95?: [number, number] | null
}

export interface AlignmentSummary {
  status: string
  real_matched_count?: number
  valid_candidate_count?: number
  candidate_rejection_counts?: Record<string, number>
  rejection_counts?: Record<string, number>
  rejection_examples?: Record<string, JsonRecord[]>
  [key: string]: unknown
}

export interface MarketCycleSummary {
  taiwan_snapshots_logged?: number
  valid_candidate_count?: number
  real_market_quote_count?: number
  real_matched_count?: number
  complete_market_benchmark_count?: number
  sharp_qualified_count?: number
  synthetic_market_quote_count?: number
  qualified_pending_candidate_count?: number
  credits_consumed?: number
  official_credits_consumed?: number | null
  target_leagues?: string[]
  target_markets?: string
  target_regions?: string
  closure_status?: string
  [key: string]: unknown
}

export interface MarketSchedulerStatus {
  enabled?: boolean
  is_executing?: boolean
  interval_seconds?: number
  last_run_utc?: string | null
  next_run_utc?: string | null
  last_status?: string | null
  stats?: { successful_runs?: number; total_runs?: number; [key: string]: unknown }
  last_cycle_summary?: MarketCycleSummary | null
  [key: string]: unknown
}

export interface MarketResearchSummary {
  live_status: string
  live_status_scope: string
  the_odds_api: OddsApiStatus
  alignment: AlignmentSummary
  scheduler?: MarketSchedulerStatus | null
  snapshots: SnapshotSummary
  forward_evaluation: ForwardEvaluationSummary
  as_of_utc: string
}

export interface ShadowPortfolioSummary {
  win_rate?: number
  total_tickets?: number
  roi?: number
  [key: string]: unknown
}

export interface ResearchAnalyticsResponse {
  total_snapshots: number
  cohort: JsonRecord & { resolved_count?: number }
  agreement: JsonRecord
  ev_data: JsonRecord
  crowd_data: JsonRecord
  expert_data: JsonRecord
  shadow_portfolio: ShadowPortfolioSummary
}

export interface QuantitativeMetricsSummary {
  sample_size: number
  brier_score?: number | null
  log_loss?: number | null
  clv_mean_pct?: number | null
  settled_roi_pct?: number | null
  roi_ci_95?: [number, number] | null
  brier_ci_95?: [number, number] | null
  pnl_drawdown_amount?: number | null
  win_rate_pct?: number | null
  status: string
  bet_count?: number
  simulated_roi_pct?: number | null
  simulated_roi_ci_95?: [number, number] | null
  simulated_bet_count?: number
}

export interface ForwardEvaluationReport {
  evaluation_scope: string
  as_of_utc: string
  sample_size: number
  paired_sample_size: number
  taiwan_market_baseline: QuantitativeMetricsSummary
  international_sharp_benchmark: QuantitativeMetricsSummary
  international_market_benchmark?: QuantitativeMetricsSummary | null
  active_model_strategy: QuantitativeMetricsSummary
  champion_source: string
  acceptance_gate_qualified: boolean
  status: string
  data_quality_status?: string
  evaluation_protocol_status?: string
  statistical_evidence_status?: string
  shadow_mode_recommendation: string
}
