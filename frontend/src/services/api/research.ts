import { BASE_URL, authHeaders } from "./shared"
import type { ForwardEvaluationReport, MarketCycleSummary, MarketResearchSummary, MarketSchedulerStatus, ResearchAnalyticsResponse } from "@/types"

export const researchApi = {
  async getResearchAnalytics(): Promise<ResearchAnalyticsResponse> {

    const res = await fetch(`${BASE_URL}/research/analytics`)

    if (!res.ok) throw new Error("取得前瞻研究數據失敗")

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
