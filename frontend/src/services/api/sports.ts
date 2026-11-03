import { BASE_URL } from "./shared"
import type { LegsResponse, ParlaySearchResponse, RadarResponse } from "@/types"
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

export const sportsApi = {
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
}
