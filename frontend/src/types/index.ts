export interface Leg {
  event_id: string
  match_id?: string
  canonical_event_id?: string
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
  start_time_utc?: string
  away_team: string
  home_team: string
  away_pitcher?: string | null
  home_pitcher?: string | null
  side?: string
  line?: string | null
  evidence_quality?: string
  signal_evidence?: any
  signals?: any[]
  expected_value?: number | null
  edge?: number | null
  market_probability?: number | null
  model_probability_calibrated?: number | null
}

export interface ParlayRecommendation {
  parlay_id: string
  parlay_name: string
  total_odds: number
  tier: "high_consensus" | "aggressive" | "moonshot"
  legs: Leg[]
  combined_model_prob?: number
  expected_value?: number
  confidence_score?: number
  is_valid: boolean
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
  legs: any[]
}

export interface Profile {
  id: string
  name: string
  weekly_play_cap: number
  created_at?: string
  updated_at?: string
}

export interface RadarLeague {
  code: string
  name: string
  icon: string
  status: "GREEN" | "YELLOW" | "RED"
  status_text: string
  light_emoji: string
  game_count: number
  taiwan_market_count: number
  espn_event_count?: number
  in_season_calendar?: boolean
  opportunity_badge?: string
  positive_ev_count?: number
  banker_count?: number
  high_agreement_count?: number
  // Fallbacks
  league_id?: string
  league_name?: string
  sport?: string
  reason?: string
  active_legs_count?: number
}
