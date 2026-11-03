import type {
  ForwardEvaluationReport,
  Leg,
  LegsResponse,
  MarketCycleSummary,
  MarketResearchSummary,
  MarketSchedulerStatus,
  ParlaySearchResponse,
  Profile,
  RadarResponse,
  ResearchAnalyticsResponse,
  Ticket,
  WalletStatus,
} from "@/types"



const BASE_URL = "/api"



export interface SearchParlaysParams {

  target_odds: number

  tolerance?: number

  min_legs?: number

  max_legs?: number

  alliances?: string[]

  signal_filter?: string

  exclude_traps?: boolean

  prefer_steam?: boolean

  search_budget?: number

  force_refresh?: boolean

}



const LEGACY_AUTH_TOKEN_KEY = "auth_session_token"

function readLegacyAuthToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    return localStorage.getItem(LEGACY_AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

function removeLegacyAuthToken(): void {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY)
  } catch {
    // The in-memory token and HttpOnly cookie remain available when storage is disabled.
  }
}

let cachedAuthToken: string | null = readLegacyAuthToken()



export function setAuthToken(token: string | null) {

  cachedAuthToken = token

  // Keep legacy tokens in memory only; the server's HttpOnly cookie persists the session.
  removeLegacyAuthToken()

}



export function getAuthToken(): string | null {
  return cachedAuthToken

}

export class ApiRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "ApiRequestError"
  }
}



function authHeaders(existingHeaders: Record<string, string> = {}): Record<string, string> {

  const token = getAuthToken()

  const headers: Record<string, string> = { ...existingHeaders }

  if (token) {

    headers["Authorization"] = `Bearer ${token}`

  }

  return headers

}



export const api = {

  getAuthToken,

  setAuthToken,



  async getHealth() {

    const res = await fetch(`${BASE_URL}/health`)

    return res.json()

  },



  async getRadar(forceRefresh = false): Promise<RadarResponse> {

    const res = await fetch(`${BASE_URL}/radar?force_refresh=${forceRefresh}`)

    if (!res.ok) throw new Error("取得賽季雷達失敗")

    return res.json()

  },



  async getLegs(alliances?: string[], forceRefresh = false): Promise<LegsResponse> {

    const qs = new URLSearchParams()

    if (alliances && alliances.length > 0) qs.set("alliances", alliances.join(","))

    if (forceRefresh) qs.set("force_refresh", "true")

    const res = await fetch(`${BASE_URL}/legs?${qs.toString()}`)

    if (!res.ok) throw new Error("取得盤口失敗")

    return res.json()

  },



  async searchParlays(params: SearchParlaysParams): Promise<ParlaySearchResponse> {

    const res = await fetch(`${BASE_URL}/parlays/search`, {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify(params),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "搜尋串關失敗")

    }

    return res.json()

  },



  async getWalletStatus(profileId: string): Promise<WalletStatus> {

    const res = await fetch(`${BASE_URL}/wallet/status?profile_id=${encodeURIComponent(profileId)}`, {

      headers: authHeaders(),

    })

    if (!res.ok) throw new Error("取得錢包狀態失敗")

    return res.json()

  },



  async depositWallet(profileId: string, amount: number, notes = "") {

    const res = await fetch(`${BASE_URL}/wallet/deposit`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify({ profile_id: profileId, amount, notes }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "補金失敗")

    }

    return res.json()

  },



  async withdrawWallet(profileId: string, amount: number) {

    const res = await fetch(`${BASE_URL}/wallet/withdraw`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify({ profile_id: profileId, amount }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "提領失敗")

    }

    return res.json()

  },



  async getWalletLedger(profileId: string) {

    const res = await fetch(`${BASE_URL}/wallet/ledger?profile_id=${encodeURIComponent(profileId)}`, {

      headers: authHeaders(),

    })

    if (!res.ok) throw new Error("取得資金流水帳失敗")

    return res.json()

  },



  async getTickets(profileId: string, status?: string): Promise<{ tickets: Ticket[] }> {

    const qs = new URLSearchParams({ profile_id: profileId })

    if (status) qs.set("status", status)

    const res = await fetch(`${BASE_URL}/tickets?${qs.toString()}`, {

      headers: authHeaders(),

    })

    if (!res.ok) throw new Error("取得注單失敗")

    return res.json()

  },



  async placeTicket(payload: {

    profile_id: string

    legs: Leg[]

    stake: number

    placed_odds: number

    recommendation_odds?: number

    parlay_name?: string

    notes?: string

    idempotency_key?: string

    client_request_id?: string

    entry_mode?: string

  }) {

    const res = await fetch(`${BASE_URL}/tickets/place`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify(payload),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "下注失敗")

    }

    return res.json()

  },



  async settleTicket(ticketId: string, result: "WON" | "LOST" | "VOID", customPayout?: number) {

    const res = await fetch(`${BASE_URL}/tickets/settle`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify({ ticket_id: ticketId, result, custom_payout: customPayout }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "結算注單失敗")

    }

    return res.json()

  },



  async getProfiles(): Promise<{ profiles: Profile[] }> {

    const res = await fetch(`${BASE_URL}/profiles`)

    if (!res.ok) throw new Error("取得身分清單失敗")

    return res.json()

  },



  async verifyPin(profileId: string, pinCode: string): Promise<{ success: boolean; token?: string; profile: Profile }> {

    const res = await fetch(`${BASE_URL}/profiles/verify_pin`, {

      method: "POST",

      headers: { "Content-Type": "application/json", "X-Session-Mode": "cookie" },

      body: JSON.stringify({ profile_id: profileId, pin_code: pinCode }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "PIN 碼錯誤")

    }

    const data = await res.json()

    setAuthToken(data.token ?? null)

    return data

  },



  async updateProfile(payload: {

    profile_id: string

    current_pin: string

    name?: string

    weekly_play_cap?: number

    new_pin?: string

  }) {

    const res = await fetch(`${BASE_URL}/profiles/update`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json", "X-Session-Mode": "cookie" }),

      body: JSON.stringify(payload),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "更新設定失敗")

    }

    const data = await res.json()
    if (payload.new_pin) setAuthToken(data.token ?? null)
    return data

  },



  async getResearchAnalytics(): Promise<ResearchAnalyticsResponse> {

    const res = await fetch(`${BASE_URL}/research/analytics`)

    if (!res.ok) throw new Error("取得前瞻研究數據失敗")

    return res.json()

  },



  async loginProfile(identifier: string, pinCode: string): Promise<{ success: boolean; token?: string; profile: Profile; message: string; requires_pin_change?: boolean; warning?: string }> {

    const res = await fetch(`${BASE_URL}/profiles/login`, {

      method: "POST",

      headers: { "Content-Type": "application/json", "X-Session-Mode": "cookie" },

      body: JSON.stringify({ identifier, pin_code: pinCode }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "登入失敗，PIN 碼或帳號錯誤")

    }

    const data = await res.json()

    setAuthToken(data.token ?? null)

    return data

  },



  async registerProfile(name: string, weeklyPlayCap: number = 200, pinCode: string = "0000"): Promise<{ success: boolean; token?: string; profile: Profile }> {

    const res = await fetch(`${BASE_URL}/profiles/register`, {

      method: "POST",

      headers: { "Content-Type": "application/json", "X-Session-Mode": "cookie" },

      body: JSON.stringify({ name, weekly_play_cap: weeklyPlayCap, pin_code: pinCode }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "註冊失敗")

    }

    const data = await res.json()

    setAuthToken(data.token ?? null)

    return data

  },



  async getAuthMe(): Promise<{ success: boolean; profile: Profile; session: Record<string, unknown> }> {

    const res = await fetch(`${BASE_URL}/auth/me`, {

      headers: authHeaders(),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new ApiRequestError(err.detail || "取得目前登入狀態失敗", res.status)

    }

    return res.json()

  },



  async logout(): Promise<void> {

    try {

      await fetch(`${BASE_URL}/profiles/logout`, {

        method: "POST",

        headers: authHeaders(),

      })

    } catch {
      // ignore

    } finally {

      setAuthToken(null)

      if (typeof window !== "undefined") {

        localStorage.removeItem("auth_profile_id")

      }

    }

  },



  async getSystemStorageStatus() {

    const res = await fetch(`${BASE_URL}/system/storage_status`)

    if (!res.ok) throw new Error("取得系統設定與資料存放狀態失敗")

    return res.json()

  },



  async getAdminPlayersOverview(adminProfileId: string = "default"): Promise<{

    players: {

      id: string

      name: string

      weekly_play_cap: number

      weekly_wallet_balance: number

      weekly_staked: number

      prize_pool: number

      lifetime_net_profit: number

      is_line_bound: boolean

      created_at: string

      active_tickets_count: number

      total_tickets_count: number

    }[]

    total_players: number

  }> {

    const res = await fetch(`${BASE_URL}/admin/players_overview?admin_profile_id=${encodeURIComponent(adminProfileId)}`, {

      headers: authHeaders(),

    })

    if (!res.ok) throw new Error("取得全體玩家監控資料失敗")

    return res.json()

  },



  async adminDeletePlayer(profileId: string, deleteHistory: boolean = true, adminPin?: string): Promise<{ success: boolean; message: string }> {

    const res = await fetch(`${BASE_URL}/admin/players/${encodeURIComponent(profileId)}?delete_history=${deleteHistory}`, {

      method: "DELETE",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: adminPin ? JSON.stringify({ profile_id: profileId, admin_pin: adminPin }) : undefined,

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "刪除玩家失敗")

    }

    return res.json()

  },



  async adminResetPin(profileId: string, newPin: string = "0000", adminPin?: string): Promise<{ success: boolean; profile: Profile; message: string }> {

    const res = await fetch(`${BASE_URL}/admin/players/reset_pin`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify({ profile_id: profileId, new_pin: newPin, admin_pin: adminPin }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "重設 PIN 碼失敗")

    }

    return res.json()

  },



  async adminUpdatePlayer(payload: {

    profile_id: string

    name?: string

    weekly_play_cap?: number

    new_pin?: string

    admin_pin?: string

  }): Promise<{ success: boolean; profile: Profile; message: string }> {

    const res = await fetch(`${BASE_URL}/admin/players/update`, {

      method: "POST",

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify(payload),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "更新玩家設定失敗")

    }

    return res.json()

  },

  async getMarketStatus() {
    const res = await fetch(`${BASE_URL}/market/status`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("取得國際市場情報狀態失敗")
    return res.json()
  },

  async getMarketBenchmarks(league = "MLB", forceRefresh = false) {
    const res = await fetch(`${BASE_URL}/market/benchmark?league=${encodeURIComponent(league)}&force_refresh=${forceRefresh}`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("取得國際市場賠率對齊失敗")
    return res.json()
  },

  async getMarketSplits(league = "MLB") {
    const res = await fetch(`${BASE_URL}/market/splits?league=${encodeURIComponent(league)}`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("取得國際投注傾向失敗")
    return res.json()
  },

  async getMarketEvaluation(scope = "GLOBAL"): Promise<ForwardEvaluationReport> {
    const res = await fetch(`${BASE_URL}/market/evaluation?scope=${encodeURIComponent(scope)}`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("取得前瞻模型評估報告失敗")
    return res.json()
  },

  async getMarketResearchSummary(): Promise<MarketResearchSummary> {
    const res = await fetch(`${BASE_URL}/market/research-summary`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("取得市場情報與前瞻驗證摘要失敗")
    return res.json()
  },

  async updateMarketApiKey(the_odds_api_key: string) {
    const res = await fetch(`${BASE_URL}/market/config`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ the_odds_api_key }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "儲存 The Odds API 金鑰失敗")
    }
    return res.json()
  },

  async triggerMarketPipelineCycle(leagues?: string, forceRefresh = false): Promise<{
    status: string
    cycle_status?: string
    operation_status?: string
    cycle_result?: {
      snapshot_cycle?: MarketCycleSummary
      durations_ms?: {
        snapshot_and_fetch: number
        settlement_scan: number
        forward_evaluation: number
        total: number
      }
    }
    snapshot_cycle?: MarketCycleSummary
    settlement_cycle?: Record<string, unknown>
    evaluation_summary?: Record<string, unknown>
  }> {
    const url = leagues
      ? `${BASE_URL}/market/pipeline/cycle?leagues=${encodeURIComponent(leagues)}&force_refresh=${forceRefresh}`
      : `${BASE_URL}/market/pipeline/cycle?force_refresh=${forceRefresh}`
    const res = await fetch(url, {
      method: "POST",
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("執行前瞻市場驗證週期失敗")
    return res.json()
  },

  async getMarketSchedulerStatus(): Promise<MarketSchedulerStatus> {
    const res = await fetch(`${BASE_URL}/market/scheduler/status`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("取得自動排程狀態失敗")
    return res.json()
  },

  async testTheOddsConnection(fetchSample = false, sportLeague?: string): Promise<{
    status: string
    official_remaining?: number | null
    requests_remaining?: number | null
    requests_used?: number | null
    credits_consumed?: number | null
    latency_ms?: number | null
    operating_mode?: string
    error?: string | null
  }> {
    const res = await fetch(`${BASE_URL}/market/the-odds/test-connection`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ fetch_sample: fetchSample, sport_league: sportLeague }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "測試 The Odds API 連線失敗")
    }
    return res.json()
  },

  async estimatePipelineCost(leagues?: string, markets?: string) {
    const params = new URLSearchParams()
    if (leagues) params.append("leagues", leagues)
    if (markets) params.append("markets", markets)
    const res = await fetch(`${BASE_URL}/market/pipeline/estimate-cost?${params.toString()}`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error("估算排程配額失敗")
    return res.json()
  },

  async updateMarketSchedulerConfig(params: { enabled?: boolean; interval_seconds?: number }) {
    const res = await fetch(`${BASE_URL}/market/scheduler/config`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(params),
    })
    if (!res.ok) throw new Error("更新自動排程設定失敗")
    return res.json()
  },
}

