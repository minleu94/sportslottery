import { BASE_URL, authHeaders } from "./shared"
import type { Leg, Ticket, WalletStatus } from "@/types"

export const walletApi = {
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
}
