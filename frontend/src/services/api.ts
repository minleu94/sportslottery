import type { Profile, RadarLeague, Ticket, WalletStatus, ParlayRecommendation } from "@/types"



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



let cachedAuthToken: string | null = typeof window !== "undefined" ? localStorage.getItem("auth_session_token") : null



export function setAuthToken(token: string | null) {

  cachedAuthToken = token

  if (typeof window !== "undefined") {

    if (token) {

      localStorage.setItem("auth_session_token", token)

    } else {

      localStorage.removeItem("auth_session_token")

    }

  }

}



export function getAuthToken(): string | null {

  if (!cachedAuthToken && typeof window !== "undefined") {

    cachedAuthToken = localStorage.getItem("auth_session_token")

  }

  return cachedAuthToken

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



  async getRadar(forceRefresh = false): Promise<{

    radar: RadarLeague[]

    status_counts: { GREEN: number; YELLOW: number; RED: number }

    total_legs: number

    source_status: any

    as_of: string

  }> {

    const res = await fetch(`${BASE_URL}/radar?force_refresh=${forceRefresh}`)

    if (!res.ok) throw new Error("取得賽季雷達失敗")

    return res.json()

  },



  async getLegs(alliances?: string[], forceRefresh = false) {

    const qs = new URLSearchParams()

    if (alliances && alliances.length > 0) qs.set("alliances", alliances.join(","))

    if (forceRefresh) qs.set("force_refresh", "true")

    const res = await fetch(`${BASE_URL}/legs?${qs.toString()}`)

    if (!res.ok) throw new Error("取得盤口失敗")

    return res.json()

  },



  async searchParlays(params: SearchParlaysParams): Promise<{

    target_odds: number

    min_odds: number

    max_odds: number

    tiers: {

      high_consensus: ParlayRecommendation[]

      aggressive: ParlayRecommendation[]

      moonshot: ParlayRecommendation[]

    }

    diagnostics: any

    search_complete: boolean

    total_combinations_searched: number

    enriched_legs_count: number

  }> {

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

    legs: any[]

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



  async verifyPin(profileId: string, pinCode: string): Promise<{ success: boolean; token: string; profile: Profile }> {

    const res = await fetch(`${BASE_URL}/profiles/verify_pin`, {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify({ profile_id: profileId, pin_code: pinCode }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "PIN 碼錯誤")

    }

    const data = await res.json()

    if (data.token) {

      setAuthToken(data.token)

    }

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

      headers: authHeaders({ "Content-Type": "application/json" }),

      body: JSON.stringify(payload),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "更新設定失敗")

    }

    return res.json()

  },



  async getResearchAnalytics() {

    const res = await fetch(`${BASE_URL}/research/analytics`)

    if (!res.ok) throw new Error("取得前瞻研究數據失敗")

    return res.json()

  },



  async loginProfile(identifier: string, pinCode: string): Promise<{ success: boolean; token: string; profile: Profile; message: string }> {

    const res = await fetch(`${BASE_URL}/profiles/login`, {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify({ identifier, pin_code: pinCode }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "登入失敗，PIN 碼或帳號錯誤")

    }

    const data = await res.json()

    if (data.token) {

      setAuthToken(data.token)

    }

    return data

  },



  async registerProfile(name: string, weeklyPlayCap: number = 200, pinCode: string = "0000"): Promise<{ success: boolean; token: string; profile: Profile }> {

    const res = await fetch(`${BASE_URL}/profiles/register`, {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify({ name, weekly_play_cap: weeklyPlayCap, pin_code: pinCode }),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "註冊失敗")

    }

    const data = await res.json()

    if (data.token) {

      setAuthToken(data.token)

    }

    return data

  },



  async getAuthMe(): Promise<{ success: boolean; profile: Profile; session: any }> {

    const res = await fetch(`${BASE_URL}/auth/me`, {

      headers: authHeaders(),

    })

    if (!res.ok) {

      const err = await res.json().catch(() => ({}))

      throw new Error(err.detail || "取得目前登入狀態失敗")

    }

    return res.json()

  },



  async logout(): Promise<void> {

    try {

      await fetch(`${BASE_URL}/profiles/logout`, {

        method: "POST",

        headers: authHeaders(),

      })

    } catch (e) {

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



  async adminDeletePlayer(profileId: string, adminPin?: string): Promise<{ success: boolean; message: string }> {

    const res = await fetch(`${BASE_URL}/admin/players/${encodeURIComponent(profileId)}`, {

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

}

