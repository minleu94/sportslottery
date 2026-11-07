import { ApiRequestError, BASE_URL, authHeaders, setAuthToken } from "./shared"
import type { Profile } from "@/types"

export const profilesApi = {
  async getLineSettings(): Promise<{
    bound: boolean
    preferences: Record<"steam_drop" | "ticket_settlement" | "hedging_alert" | "morning_radar", boolean>
  }> {
    const res = await fetch(`${BASE_URL}/line/preferences`, { headers: authHeaders() })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "取得 LINE 設定失敗")
    }
    return res.json()
  },

  async saveLineSettings(payload: Record<string, boolean>) {
    const res = await fetch(`${BASE_URL}/line/preferences`, {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "儲存 LINE 設定失敗")
    }
    return res.json()
  },

  async getLineBindingRequests(): Promise<{ requests: Array<{ request_id: string; display_name: string; confirmation_code: string; created_at: string; expires_at: string }> }> {
    const res = await fetch(`${BASE_URL}/line/binding-requests`, { headers: authHeaders() })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "取得 LINE 綁定申請失敗")
    }
    return res.json()
  },

  async approveLineBindingRequest(requestId: string) {
    const res = await fetch(`${BASE_URL}/line/binding-requests/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
      headers: authHeaders(),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "核准 LINE 綁定失敗")
    }
    return res.json()
  },

  async rejectLineBindingRequest(requestId: string) {
    const res = await fetch(`${BASE_URL}/line/binding-requests/${encodeURIComponent(requestId)}/reject`, {
      method: "POST",
      headers: authHeaders(),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "拒絕 LINE 綁定失敗")
    }
    return res.json()
  },

  async unbindLineProfile() {
    const res = await fetch(`${BASE_URL}/line/binding`, { method: "DELETE", headers: authHeaders() })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || "解除 LINE 綁定失敗")
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
}
