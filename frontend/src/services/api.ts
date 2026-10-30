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

export const api = {
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
    const res = await fetch(`${BASE_URL}/wallet/status?profile_id=${encodeURIComponent(profileId)}`)
    if (!res.ok) throw new Error("取得錢包狀態失敗")
    return res.json()
  },

  async depositWallet(profileId: string, amount: number, notes = "") {
    const res = await fetch(`${BASE_URL}/wallet/deposit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, amount }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "提領失敗")
    }
    return res.json()
  },

  async getWalletLedger(profileId: string) {
    const res = await fetch(`${BASE_URL}/wallet/ledger?profile_id=${encodeURIComponent(profileId)}`)
    if (!res.ok) throw new Error("取得資金流水帳失敗")
    return res.json()
  },

  async getTickets(profileId: string, status?: string): Promise<{ tickets: Ticket[] }> {
    const qs = new URLSearchParams({ profile_id: profileId })
    if (status) qs.set("status", status)
    const res = await fetch(`${BASE_URL}/tickets?${qs.toString()}`)
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
  }) {
    const res = await fetch(`${BASE_URL}/tickets/place`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
      headers: { "Content-Type": "application/json" },
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

  async verifyPin(profileId: string, pinCode: string): Promise<{ success: boolean; profile: Profile }> {
    const res = await fetch(`${BASE_URL}/profiles/verify_pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, pin_code: pinCode }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "PIN 碼錯誤")
    }
    return res.json()
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
      headers: { "Content-Type": "application/json" },
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
}
