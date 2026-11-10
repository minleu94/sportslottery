import React, { useCallback, useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { api } from "@/services/api"
import type {
  AlignmentSummary,
  MarketCycleSummary,
  MarketResearchSummary,
  ResearchAnalyticsResponse,
  ShadowPortfolioSummary,
  JsonRecord,
} from "@/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import {
  BarChart2,
  Users,
  Brain,
  Globe,
  Key,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Database,
  Activity,
  ExternalLink,
  ShieldCheck,
  Clock,
  Play,
  Pause,
} from "lucide-react"

const ALIGNMENT_REASON_LABELS: Record<string, string> = {
  MISSING_EVENT_ID: "缺少賽事識別碼",
  TAIWAN_ODDS_NOT_FRESH: "台彩盤口不是新鮮報價",
  SYNTHETIC_TAIWAN_ODDS: "台彩盤口為合成資料",
  INVALID_OR_MISSING_START_TIME: "缺少有效開賽時間",
  UNSUPPORTED_OR_MISMATCHED_LEAGUE: "聯賽不支援或不一致",
  SPORT_LEAGUE_MISMATCH: "運動種類與聯賽不一致",
  MISSING_TEAMS: "主客隊資料不完整",
  MISSING_SELECTION: "缺少投注選項",
  UNSUPPORTED_MARKET: "玩法不支援",
  MARKET_NOT_ALLOWED: "玩法未列入目前查詢設定",
  INVALID_SELECTION_SIDE: "投注方向無效",
  MISSING_OR_INVALID_LINE: "缺少有效讓分／大小分線位",
  INVALID_TAIWAN_ODDS: "台彩賠率無效",
  DUPLICATE_CANDIDATE_LEG: "重複候選已略過",
  TAIWAN_SOURCE_ERROR: "台彩資料來源讀取失敗",
  ERR_INVALID_TAIWAN_LEG: "台彩候選欄位不完整",
  ERR_LEAGUE_UNKNOWN: "無法識別聯賽",
  ERR_EVENT_TIME_UNKNOWN: "賽事時間無法識別",
  ERR_NO_INTERNATIONAL_QUOTES: "沒有國際報價",
  ERR_TEAM_NOT_FOUND: "隊名無法配對",
  ERR_MARKET_TYPE_MISMATCH: "玩法不一致",
  ERR_LEAGUE_MISMATCH: "聯賽不一致",
  ERR_TEAM_NOT_MATCHED: "主客隊不一致",
  ERR_EVENT_TIME_MISMATCH: "開賽時間差距過大",
  ERR_EVENT_TIME_AMBIGUOUS: "賽事時間配對有歧義",
  ERR_MARKET_NOT_FOUND: "找不到相同玩法",
  ERR_LINE_MISMATCH: "盤線不同",
  ERR_ODDS_TIME_UNKNOWN: "國際報價時間未知",
  ERR_ODDS_TIME_FUTURE: "國際報價時間異常",
  ERR_STALE_ODDS: "國際報價已過期",
}

function alignmentReasonLabel(code: string) {
  return ALIGNMENT_REASON_LABELS[code] || code.replaceAll("_", " ").toLowerCase()
}

export const ResearchView: React.FC = () => {
  const [data, setData] = useState<ResearchAnalyticsResponse | null>(null)
  const [marketSummary, setMarketSummary] = useState<MarketResearchSummary | null>(null)
  const [loadingMarket, setLoadingMarket] = useState(true)
  const [loadingAnalytics, setLoadingAnalytics] = useState(true)
  const [marketLoadError, setMarketLoadError] = useState<string | null>(null)
  const [analyticsLoadError, setAnalyticsLoadError] = useState<string | null>(null)
  const [apiKeyInput, setApiKeyInput] = useState("")
  const [showKeyForm, setShowKeyForm] = useState(false)
  const [submittingKey, setSubmittingKey] = useState(false)
  const [runningCycle, setRunningCycle] = useState(false)
  const [togglingScheduler, setTogglingScheduler] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: "success" | "warning" | "error"; text: string } | null>(null)

  const loadAnalytics = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoadingMarket(true)
      setLoadingAnalytics(true)
      setMarketLoadError(null)
      setAnalyticsLoadError(null)
    }
    const [marketResult, analyticsResult] = await Promise.allSettled([
      api.getMarketResearchSummary(),
      api.getResearchAnalytics(),
    ])
    if (marketResult.status === "fulfilled") {
      setMarketSummary(marketResult.value)
    } else {
      setMarketLoadError(marketResult.reason instanceof Error ? marketResult.reason.message : "無法讀取市場狀態")
    }
    if (analyticsResult.status === "fulfilled") {
      setData(analyticsResult.value)
    } else {
      setAnalyticsLoadError(analyticsResult.reason instanceof Error ? analyticsResult.reason.message : "無法讀取研究指標")
    }
    setLoadingMarket(false)
    setLoadingAnalytics(false)
  }, [])

  useEffect(() => {
    // The callback only updates state after the API promises settle.
    // oxlint-disable-next-line react/set-state-in-effect -- async external data load
    void loadAnalytics(false)
  }, [loadAnalytics])

  async function handleSaveKey(e: React.FormEvent) {
    e.preventDefault()
    if (!apiKeyInput.trim()) return
    setSubmittingKey(true)
    setFeedbackMsg(null)
    try {
      await api.updateMarketApiKey(apiKeyInput.trim())
      setFeedbackMsg({
        type: "success",
        text: "✓ API Key 成功儲存至本機安全設定 (config/odds_api.local.yaml，嚴格隔離不進 Git)！",
      })
      setApiKeyInput("")
      setShowKeyForm(false)
      const updated = await api.getMarketResearchSummary()
      setMarketSummary(updated)
      setMarketLoadError(null)
    } catch (err: any) {
      setFeedbackMsg({ type: "error", text: err.message || "儲存金鑰失敗" })
    } finally {
      setSubmittingKey(false)
    }
  }

  async function handleTestConnection() {
    setTestingConnection(true)
    setFeedbackMsg(null)
    try {
      const res = await api.testTheOddsConnection(false)
      if (res.status === "SUCCESS") {
        setFeedbackMsg({
          type: "success",
          text: `✓ 連線測試成功 (0 額度消耗)！官方剩餘: ${res.official_remaining ?? res.requests_remaining ?? "未知"} Credits，已使用: ${res.requests_used ?? 0} Credits，延遲: ${res.latency_ms ? `${res.latency_ms}ms` : "正常"} (模式: ${res.operating_mode})`,
        })
      } else {
        setFeedbackMsg({
          type: "error",
          text: `✕ 連線測試未成功: ${res.error || "未知錯誤"} (狀態: ${res.status})`,
        })
      }
      const updated = await api.getMarketResearchSummary().catch(() => null)
      if (updated) {
        setMarketSummary(updated)
        setMarketLoadError(null)
      }
    } catch (err: any) {
      setFeedbackMsg({
        type: "error",
        text: `✕ 連線測試失敗: ${err.message || String(err)}`,
      })
    } finally {
      setTestingConnection(false)
    }
  }

  async function handleTriggerCycle() {
    setRunningCycle(true)
    setFeedbackMsg(null)
    try {
      const result = await api.triggerMarketPipelineCycle()
      const durations = result?.cycle_result?.durations_ms
      const cycle = result?.cycle_result?.snapshot_cycle || {}
      const timing = durations
        ? `（抓取/快照 ${(durations.snapshot_and_fetch / 1000).toFixed(1)} 秒、結算 ${(durations.settlement_scan / 1000).toFixed(1)} 秒、驗證 ${(durations.forward_evaluation / 1000).toFixed(1)} 秒；總計 ${(durations.total / 1000).toFixed(1)} 秒）`
        : ""
      const hasQualifiedCandidates = (cycle.qualified_pending_candidate_count || 0) > 0
      const cycleDetails = `台彩快照 ${cycle.taiwan_snapshots_logged || 0}、國際盤報價筆數 ${cycle.real_market_quote_count || 0}、配對選項數 ${cycle.real_matched_count || 0}、配對賽事 ${cycle.real_matched_event_count || 0}/${cycle.unique_candidate_event_count || 0}、Synthetic ${cycle.synthetic_market_quote_count || 0}、待結算合格候選 ${cycle.qualified_pending_candidate_count || 0}、本次扣點 ${cycle.credits_consumed || 0}。`
      setFeedbackMsg({
        type: hasQualifiedCandidates ? "success" : "warning",
        text: hasQualifiedCandidates
          ? `✓ 同步及評估作業完成，取得合格真實盤口候選。${cycleDetails}${timing}`
          : `⚠ 同步及評估作業已執行完畢，但本輪沒有合格真實盤口，前瞻閉環尚未完成。${cycleDetails}${timing}`,
      })
      await loadAnalytics()
    } catch (err: any) {
      setFeedbackMsg({ type: "error", text: err.message || "執行週期失敗" })
    } finally {
      setRunningCycle(false)
    }
  }

  async function handleToggleScheduler() {
    const sched = marketSummary?.scheduler
    const targetEnabled = !sched?.enabled
    setTogglingScheduler(true)
    setFeedbackMsg(null)
    try {
      await api.updateMarketSchedulerConfig({ enabled: targetEnabled })
      setFeedbackMsg({
        type: "success",
        text: targetEnabled
          ? "✓ 自動前瞻排程已啟動，將依照 API 配額動態調度背景更新！"
          : "✓ 自動前瞻排程已暫停，轉為僅手動觸發模式。",
      })
      const updated = await api.getMarketResearchSummary()
      setMarketSummary(updated)
      setMarketLoadError(null)
    } catch (err: any) {
      setFeedbackMsg({ type: "error", text: err.message || "更新排程設定失敗" })
    } finally {
      setTogglingScheduler(false)
    }
  }

  const portfolio: ShadowPortfolioSummary = data?.shadow_portfolio || {}
  const theOdds = marketSummary?.the_odds_api
  const snaps = marketSummary?.snapshots
  const fwd = marketSummary?.forward_evaluation
  const opMode = marketSummary?.live_status || theOdds?.operating_mode || "UNKNOWN"
  const sampleSize = fwd?.paired_sample_size || 0
  const eligibleEventCount = fwd?.sample_size || 0
  const sched = marketSummary?.scheduler
  const alignment: AlignmentSummary = marketSummary?.alignment ?? { status: "UNKNOWN" }
  const lastCycle: MarketCycleSummary = sched?.last_cycle_summary ?? {}
  const realQuoteCount = lastCycle.real_market_quote_count ?? 0
  const syntheticQuoteCount = lastCycle.synthetic_market_quote_count ?? 0
  const minSample = fwd?.minimum_sample_size || 30
  const rejectionSummary = [
    ...Object.entries(alignment?.candidate_rejection_counts || {})
      .map(([reason, count]) => `候選 ${alignmentReasonLabel(reason)} ${count}`),
    ...Object.entries(alignment?.rejection_counts || {})
      .map(([reason, count]) => `配對 ${alignmentReasonLabel(reason)} ${count}`),
  ]
    .join(" · ")
  const rejectionEntries = [
    ...Object.entries(alignment?.candidate_rejection_counts || {}).map(([code, count]) => ({ code, count, kind: "候選" })),
    ...Object.entries(alignment?.rejection_counts || {}).map(([code, count]) => ({ code, count, kind: "配對" })),
  ].filter((entry) => entry.count > 0)
  const marketUnavailableLabel = loadingMarket ? "載入中…" : marketLoadError ? "讀取失敗" : "未知"
  const analyticsUnavailableLabel = loadingAnalytics ? "載入中…" : analyticsLoadError ? "讀取失敗" : "未知"
  const snapshotCount = snaps?.total_count ?? data?.total_snapshots
  const settledCount = snaps?.settled_count ?? data?.cohort?.resolved_count
  const hasLastCycle = Boolean(sched?.last_cycle_summary)

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="space-y-5"
    >
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 tracking-tight">
          <BarChart2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          影子前瞻評估與模型指標
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          追蹤前瞻快照、真實賽果回測、大眾共識與專家主推的校準表現
        </p>
        <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
          離線 fixture／CI 通過只驗證固定資料下的程式行為；不代表目前已配對真實盤口，也不代表模型預測優勢已驗證。
        </p>
      </div>

      {(loadingMarket || loadingAnalytics) && (
        <div role="status" aria-live="polite" className="text-xs text-slate-500 dark:text-slate-400">
          正在讀取研究資料；載入完成前不會把未知狀態當成 0。
        </div>
      )}
      {(marketLoadError || analyticsLoadError) && (
        <div role="alert" aria-live="assertive" className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
          <span>
            {marketLoadError ? `市場狀態讀取失敗：${marketLoadError}` : null}
            {marketLoadError && analyticsLoadError ? " · " : null}
            {analyticsLoadError ? `研究指標讀取失敗：${analyticsLoadError}` : null}
            {marketSummary || data ? "；畫面保留上次成功取得的資料。" : null}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void loadAnalytics()}
            disabled={loadingMarket || loadingAnalytics}
            className="h-7 shrink-0 text-xs"
          >
            重新載入
          </Button>
        </div>
      )}

      {/* Global Market Intelligence & Continuous Forward Pipeline Banner */}
      <Card className="border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
        <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Globe className="w-4 h-4 text-slate-400" />
              <span>國際市場資料與前瞻驗證狀態</span>
            </CardTitle>
            <div className="flex items-center gap-2">
              {loadingMarket && !marketSummary ? (
                <Badge variant="secondary" className="py-0.5 text-slate-400">載入 API 狀態中</Badge>
              ) : marketLoadError && !marketSummary ? (
                <Badge variant="red" className="py-0.5">API 狀態讀取失敗</Badge>
              ) : opMode === "LIVE_VERIFIED" || opMode === "LIVE_API" ? (
                <Badge variant="green" className="gap-1.5 py-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                  API 曾成功連線；盤口配對另列
                </Badge>
              ) : opMode === "KEY_CONFIGURED_UNVERIFIED" ? (
                <Badge variant="blue" className="gap-1.5 py-0.5">
                  <Key className="w-3.5 h-3.5 text-slate-400" />
                  KEY CONFIGURED (已配置金鑰，待驗證)
                </Badge>
              ) : opMode === "QUOTA_SAFETY_PAUSE" ? (
                <Badge variant="amber" className="gap-1.5 py-0.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  配額防護暫停 (保留手動 50 Credits)
                </Badge>
              ) : opMode === "QUOTA_EXHAUSTED" ? (
                <Badge variant="red" className="gap-1.5 py-0.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  本月 API 配額已耗盡
                </Badge>
              ) : opMode === "LIVE_ERROR" ? (
                <Badge variant="red" className="gap-1.5 py-0.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  API 連線異常 (降級展示)
                </Badge>
              ) : opMode === "UNKNOWN" ? (
                <Badge variant="secondary" className="py-0.5 text-slate-400">API 狀態未知</Badge>
              ) : (
                <Badge variant="secondary" className="gap-1.5 py-0.5 text-slate-400">
                  SYNTHETIC (合成展示模式)
                </Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          {/* Unified Hairline Operational Matrix (De-boxed) */}
          <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/40 dark:bg-slate-950/40 overflow-hidden divide-y divide-slate-200/70 dark:divide-slate-800/80">
            <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-slate-200/70 dark:divide-slate-800/80">
              {/* 1. Market Live Status */}
              <div className="p-3.5 space-y-1">
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>The Odds API 連線</span>
                  <Activity className="w-3.5 h-3.5 text-slate-400" />
                </div>
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono">
                  The Odds API
                </div>
                <div className="text-xs text-slate-400 truncate">
                  {theOdds?.key_masked ? `金鑰: ${theOdds.key_masked}` : marketSummary ? "尚未配置 Key" : marketUnavailableLabel}
                </div>
                <div className="text-xs text-slate-400 truncate">
                  {!marketSummary
                    ? marketUnavailableLabel
                    : !theOdds?.has_api_key
                    ? "降級合成展示"
                    : theOdds?.last_successful_fetch_utc
                    ? `最近成功: ${new Date(theOdds.last_successful_fetch_utc).toLocaleTimeString()}`
                    : "等待連線測試或首次排程"}
                </div>
              </div>

              {/* 2. Quota Usage Tracker */}
              <div className="p-3.5 space-y-1">
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>本月配額 (500/月)</span>
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
                  {marketSummary
                    ? `${theOdds?.requests_used_this_month ?? "—"} / ${theOdds?.monthly_budget ?? theOdds?.monthly_quota ?? "—"}`
                    : marketUnavailableLabel}
                </div>
                <div className="text-xs text-slate-600 dark:text-slate-400 font-medium truncate tabular-nums">
                  官方剩餘: {marketSummary ? `${theOdds?.official_remaining ?? theOdds?.requests_remaining_est ?? "未知"} Credits` : marketUnavailableLabel}
                </div>
                <div className="text-xs text-slate-400 truncate">
                  日排程預算: {marketSummary ? `${theOdds?.daily_schedulable_budget ?? "未知"} (手動保留 50)` : marketUnavailableLabel}
                </div>
                <div className="text-xs text-slate-400 truncate tabular-nums">
                  最近扣點 {theOdds?.requests_last_consumed || 0} · 請求 {theOdds?.request_metrics?.api_requests || 0} · 快取命中 {theOdds?.request_metrics?.cache_hits || 0} · 合併 {theOdds?.request_metrics?.coalesced_requests || 0}
                </div>
                <div className="text-xs text-slate-400 truncate tabular-nums">
                  失敗 {theOdds?.request_metrics?.request_failures || 0} · 配額略過 {theOdds?.request_metrics?.quota_skips || 0} · 退避略過 {theOdds?.request_metrics?.backoff_skips || 0}
                </div>
              </div>

              {/* 3. Snapshots Accumulation */}
              <div className="p-3.5 space-y-1">
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>歷史快照 / 已結算</span>
                  <Database className="w-3.5 h-3.5 text-slate-400" />
                </div>
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
                  {snapshotCount != null ? `${snapshotCount} / ${settledCount ?? "—"}` : marketUnavailableLabel}
                </div>
                <div className="text-xs text-slate-600 dark:text-slate-400 font-medium truncate">
                  有效前瞻: {snaps?.forward_eligible_count ?? (marketSummary ? "未知" : marketUnavailableLabel)}
                </div>
                <div className="text-xs text-slate-400 truncate">
                  歷史基線封存: {snaps?.legacy_unverified_count ?? (marketSummary ? "未知" : marketUnavailableLabel)} 筆
                </div>
              </div>

              {/* 4. Forward Gate Status */}
              <div className="p-3.5 space-y-1">
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>模型 / Sharp 配對事件 (N)</span>
                  <span className="text-xs font-mono font-medium text-slate-400">門檻 {minSample}</span>
                </div>
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
                  {fwd ? `${sampleSize} / ${minSample}` : marketUnavailableLabel}
                </div>
                <div className="text-xs truncate">
                  <span className="text-slate-600 dark:text-slate-400 font-medium">
                    {fwd?.acceptance_gate_qualified
                      ? "Sharp 配對差異獲得統計支持，仍需人工審閱"
                      : fwd
                        ? `未宣告優勢：${fwd.statistical_evidence_status || fwd.status || "尚未評估"}`
                        : "前瞻評估狀態未知"}
                  </span>
                </div>
                <div className="text-xs text-slate-400 truncate">
                  {fwd
                    ? `Sharp 配對 ${sampleSize} · 國際市場配對 ${fwd.market_paired_sample_size ?? "未知"} · 合格事件 ${eligibleEventCount}`
                    : "配對樣本未知"}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-slate-200/70 dark:divide-slate-800/80 text-xs">
              <div className="p-3.5">
                <div className="text-slate-500 dark:text-slate-400">最近一輪國際盤口</div>
                <div className="mt-1 font-semibold text-slate-800 dark:text-slate-200">
                  {realQuoteCount > 0
                    ? `真實報價 ${realQuoteCount} · 完整市場 ${lastCycle.complete_market_benchmark_count ?? 0}`
                    : syntheticQuoteCount > 0 ? "只有合成報價" : "未知／尚未執行"}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {hasLastCycle
                    ? `符合指定 Sharp 來源規則 ${lastCycle.sharp_qualified_count ?? "未知"} · 最近扣點 ${lastCycle.official_credits_consumed ?? "未取得官方記帳"}`
                    : "尚無排程週期記錄"}
                </div>
              </div>
              <div className="p-3.5">
                <div className="text-slate-500 dark:text-slate-400">台彩賽事與國際盤配對</div>
                <div className="mt-1 font-semibold text-slate-800 dark:text-slate-200">
                  {alignment.status === "UNKNOWN" || alignment.status === "NO_RECORDED_CYCLE"
                    ? "尚無配對週期資料"
                    : `候選選項 ${alignment.valid_candidate_count ?? "未知"} · 配對選項 ${alignment.real_matched_count ?? "未知"} · 配對賽事 ${alignment.real_matched_event_count ?? "未知"}/${alignment.unique_candidate_event_count ?? "未知"}`}
                </div>
                {rejectionEntries.length > 0 ? (
                  <details className="mt-1 text-xs text-slate-500">
                    <summary className="cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
                      查看拒絕原因（{rejectionEntries.reduce((sum, entry) => sum + entry.count, 0)}）
                    </summary>
                    <ul className="mt-1 space-y-1 pl-3">
                      {rejectionEntries.map(({ code, count, kind }) => {
                        const example = alignment.rejection_examples?.[code]?.[0] as JsonRecord | undefined
                        return (
                          <li key={`${kind}-${code}`}>
                            <span className="font-medium">{kind}：{alignmentReasonLabel(code)} × {count}</span>
                            {example?.reason ? <span className="block pl-1">{String(example.reason)}</span> : null}
                            {example?.taiwan_league || example?.taiwan_market ? (
                              <span className="block pl-1">
                                {String(example.taiwan_league || "")}{example.taiwan_market ? ` · ${String(example.taiwan_market)}` : ""}
                                {example.taiwan_selection ? ` · ${String(example.taiwan_selection)}` : ""}
                              </span>
                            ) : null}
                          </li>
                        )
                      })}
                    </ul>
                  </details>
                ) : (
                  <div className="mt-1 text-xs text-slate-500">
                    {alignment.status === "UNKNOWN" || alignment.status === "NO_RECORDED_CYCLE"
                      ? "尚無拒絕原因資料"
                      : rejectionSummary || "最近週期沒有拒絕原因"}
                  </div>
                )}
              </div>
              <div className="p-3.5">
                <div className="text-slate-500 dark:text-slate-400">前瞻資料品質與模型協定</div>
                <div className="mt-1 font-semibold text-slate-800 dark:text-slate-200">
                  {fwd?.data_quality_status || (marketSummary ? "尚無資料品質狀態" : marketUnavailableLabel)}
                </div>
                <div className="mt-1 text-xs text-slate-500 truncate">
                  {fwd?.evaluation_protocol_status || (marketSummary ? "尚無模型協定狀態" : marketUnavailableLabel)} · Brier 95% CI {fwd?.delta_brier_ci_95?.map((value: number) => value.toFixed(4)).join(" 至 ") || "尚無"}
                </div>
              </div>
            </div>
          </div>

          {/* Automated In-Service Scheduler Bar */}
          <div className="p-3.5 rounded-xl border border-sky-500/20 bg-sky-50/40 dark:bg-sky-950/20 space-y-2">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center flex-wrap gap-2">
                <Clock className="w-4 h-4 text-sky-500" />
                <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                  背景定時前瞻排程 (In-Service Scheduler)
                </span>
                {sched?.enabled ? (
                  <Badge variant="green" className="text-[10px] py-0.5">
                    ● 運行中 ({sched?.interval_seconds ? `${Math.round(sched.interval_seconds / 3600)}h 動態間隔` : "4h"})
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="text-[10px] py-0.5 text-slate-400">
                    ○ 已手動暫停
                  </Badge>
                )}
                {sched?.is_executing && (
                  <Badge variant="amber" className="text-[10px] py-0.5 animate-pulse">
                    執行中...
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleToggleScheduler}
                  disabled={togglingScheduler}
                  className="h-7 text-xs px-2.5 gap-1"
                >
                  {sched?.enabled ? (
                    <>
                      <Pause className="w-3 h-3 text-amber-500" />
                      <span>暫停排程</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3 h-3 text-emerald-500" />
                      <span>啟用排程</span>
                    </>
                  )}
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs pt-1 border-t border-sky-500/10">
              <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
                <span className="text-slate-400">最近執行:</span>
                <span className="font-mono font-medium">
                  {sched?.last_run_utc ? new Date(sched.last_run_utc).toLocaleTimeString() : "尚未執行"}
                </span>
                {sched?.last_status === "SUCCESS" && (
                  <span className="text-slate-500 font-bold text-[10px]">(執行完成)</span>
                )}
                {sched?.last_status === "FAILED" && (
                  <span className="text-rose-500 font-bold text-[10px]">(失敗)</span>
                )}
                {sched?.last_status === "SKIPPED_CONCURRENT" && (
                  <span className="text-amber-500 font-bold text-[10px]">(防重疊跳過)</span>
                )}
              </div>

              <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
                <span className="text-slate-400">下次預計:</span>
                <span className="font-mono font-medium text-sky-600 dark:text-sky-400">
                  {sched?.enabled && sched?.next_run_utc
                    ? new Date(sched.next_run_utc).toLocaleString()
                    : "排程暫停中"}
                </span>
              </div>

              <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
                <span className="text-slate-400">累計循環:</span>
                <span className="font-mono">
                  {sched?.stats?.successful_runs || 0} 成功 / {sched?.stats?.total_runs || 0} 總次
                </span>
              </div>
            </div>
            {sched?.last_cycle_summary && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] pt-2 border-t border-sky-500/10">
                <div className="text-slate-600 dark:text-slate-300">台彩快照 <strong className="font-mono">{sched.last_cycle_summary.taiwan_snapshots_logged ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">有效候選 <strong className="font-mono">{sched.last_cycle_summary.valid_candidate_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">國際報價筆數 <strong className="font-mono">{sched.last_cycle_summary.real_market_quote_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">台彩候選賽事 <strong className="font-mono">{sched.last_cycle_summary.unique_candidate_event_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">配對選項數 <strong className="font-mono">{sched.last_cycle_summary.real_matched_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">配對賽事／候選 <strong className="font-mono">{sched.last_cycle_summary.real_matched_event_count ?? 0}/{sched.last_cycle_summary.unique_candidate_event_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">完整市場 <strong className="font-mono">{sched.last_cycle_summary.complete_market_benchmark_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">符合指定 Sharp 來源規則 <strong className="font-mono">{sched.last_cycle_summary.sharp_qualified_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">Synthetic <strong className="font-mono">{sched.last_cycle_summary.synthetic_market_quote_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">待結算合格候選 <strong className="font-mono">{sched.last_cycle_summary.qualified_pending_candidate_count ?? 0}</strong></div>
                <div className="text-slate-600 dark:text-slate-300">本次扣點 <strong className="font-mono">{sched.last_cycle_summary.credits_consumed ?? 0}</strong></div>
                <div className={`col-span-2 sm:col-span-5 font-medium ${sched.last_cycle_summary.closure_status === "QUALIFIED_REAL_MARKET_DATA" ? "text-emerald-500" : "text-amber-500"}`}>
                  {sched.last_cycle_summary.closure_status === "QUALIFIED_REAL_MARKET_DATA"
                    ? "最近一輪取得合格真實盤口候選"
                    : "最近一輪同步作業已結束，但沒有合格真實盤口候選；前瞻閉環未完成"}
                </div>
                <div className="col-span-2 sm:col-span-5 text-[10px] text-slate-500 dark:text-slate-400">
                  抓取範圍：{(sched.last_cycle_summary.target_leagues || []).join(", ") || "未知"} · 市場 {sched.last_cycle_summary.target_markets || "未知"} · 區域 {sched.last_cycle_summary.target_regions || "未知"}
                </div>
              </div>
            )}
          </div>

          {/* Feedback message banner */}
          <AnimatePresence>
            {feedbackMsg && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className={`p-3 rounded-lg text-xs flex items-center gap-2 ${
                  feedbackMsg.type === "success"
                    ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-400"
                    : feedbackMsg.type === "warning"
                    ? "bg-amber-500/10 border border-amber-500/30 text-amber-400"
                    : "bg-rose-500/10 border border-rose-500/30 text-rose-400"
                }`}
              >
                {feedbackMsg.type === "success" ? (
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                ) : feedbackMsg.type === "warning" ? (
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                ) : (
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                )}
                <span>{feedbackMsg.text}</span>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Action buttons & Collapsible API key form */}
          <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-200/60 dark:border-slate-800/60">
            <Button
              variant="outline"
              size="sm"
              onClick={handleTestConnection}
              disabled={testingConnection}
              className="gap-1.5 text-xs border-emerald-500/40 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"
            >
              <Activity className={`w-3.5 h-3.5 ${testingConnection ? "animate-spin" : ""}`} />
              {testingConnection ? "連線測試中..." : "測試連線 (0 Credits)"}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowKeyForm(!showKeyForm)}
              className="gap-1.5 text-xs"
            >
              <Key className="w-3.5 h-3.5 text-amber-500" />
              {theOdds?.has_api_key ? "更新 The Odds API 金鑰" : "設定 The Odds API 金鑰"}
            </Button>

            <Button
              variant="default"
              size="sm"
              onClick={handleTriggerCycle}
              disabled={runningCycle}
              className="gap-1.5 text-xs bg-sky-600 hover:bg-sky-500 text-white"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${runningCycle ? "animate-spin" : ""}`} />
              {runningCycle ? "前瞻週期執行中..." : "立即執行前瞻同步週期"}
            </Button>

            <a
              href="https://the-odds-api.com"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-sky-500 hover:text-sky-400 hover:underline ml-auto"
            >
              <span>免費取得 API Key (500次/月)</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {/* Collapsible Key Form */}
          <AnimatePresence>
            {showKeyForm && (
              <motion.form
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                onSubmit={handleSaveKey}
                className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/90 dark:bg-slate-950/70 p-4 space-y-3 overflow-hidden"
              >
                <div className="text-xs font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                  <Key className="w-4 h-4 text-amber-500" />
                  配置 The Odds API 金鑰 (本機安全儲存)
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
                  金鑰將儲存於本機 <code>config/odds_api.local.yaml</code>（已列入 <code>.gitignore</code>，絕不會提交至 Git），或您亦可直接於專案根目錄 <code>.env</code> 設定 <code>THE_ODDS_API_KEY</code>。
                </p>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    placeholder="貼上您的 The Odds API Key (例如: a1b2c3d4e5...)"
                    className="flex-1 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={submittingKey || !apiKeyInput.trim()}
                    className="text-xs bg-emerald-600 hover:bg-emerald-500"
                  >
                    {submittingKey ? "儲存中..." : "確認儲存"}
                  </Button>
                </div>
              </motion.form>
            )}
          </AnimatePresence>
        </CardContent>
      </Card>

      {/* Snapshot Stats Unified Hairline Matrix */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-xs">
        <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-slate-200/70 dark:divide-slate-800/80 tabular-nums">
          <div className="p-4">
            <div className="text-xs text-slate-500 dark:text-slate-400">歷史盤口快照總數</div>
            <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 font-mono mt-1">
              {snapshotCount != null ? snapshotCount.toLocaleString() : marketUnavailableLabel}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">獨立觀測樣本</div>
          </div>

          <div className="p-4">
            <div className="text-xs text-slate-500 dark:text-slate-400">影子投組勝率</div>
            <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 font-mono mt-1">
              {portfolio?.win_rate != null ? `${(portfolio.win_rate * 100).toFixed(1)}%` : analyticsUnavailableLabel}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">
              {portfolio?.total_tickets != null ? `${portfolio.total_tickets} 筆影子模擬單` : analyticsUnavailableLabel}
            </div>
          </div>

          <div className="p-4">
            <div className="text-xs text-slate-500 dark:text-slate-400">影子投組 ROI</div>
            <div
              className={`text-2xl font-semibold tabular-nums font-mono mt-1 ${
                portfolio?.roi != null && portfolio.roi > 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-slate-900 dark:text-slate-100"
              }`}
            >
              {portfolio?.roi != null ? `${(portfolio.roi * 100).toFixed(1)}%` : analyticsUnavailableLabel}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">虛擬回測收益率</div>
          </div>

          <div className="p-4">
            <div className="text-xs text-slate-500 dark:text-slate-400">前瞻族群追蹤</div>
            <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 font-mono mt-1">
              {settledCount != null ? settledCount : marketUnavailableLabel}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">已結算校準樣本</div>
          </div>
        </div>
      </div>

      {/* Research Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Consensus & Crowd breakdown */}
        <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="w-4 h-4 text-sky-500" />
              社群投票研究狀態
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <p className="text-xs text-slate-600 dark:text-slate-400">
              比較票數比例與賽果前，必須先累積同玩法、賽前取得且可追溯的樣本；目前的介面指標不能單獨證明投票有預測力。
            </p>
            <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 p-3 text-xs text-slate-700 dark:text-slate-300">
              <div className="font-semibold text-emerald-600 dark:text-emerald-400 mb-1">待驗證問題：</div>
              <ul className="list-disc list-inside space-y-1 text-slate-500 dark:text-slate-400">
                <li>熱門投票比例是否與同規格市場價格變化一致。</li>
                <li>逆向升水只作觀察訊號；沒有前瞻比較前，不稱為陷阱或優勢。</li>
              </ul>
            </div>
          </CardContent>
        </Card>

        {/* Model & Expert breakdown */}
        <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
              統計模型與專家主推評估
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <p className="text-xs text-slate-600 dark:text-slate-400">
              研究資料包括 Poisson／Elo 模型與專家訊號；各來源的賽前預測表現仍須分開評估。
            </p>
            <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 p-3 text-xs text-slate-700 dark:text-slate-300">
              <div className="font-semibold text-amber-600 dark:text-amber-400 mb-1">多來源獨立支持原則：</div>
              <p className="text-slate-500 dark:text-slate-400">
                多來源同向只表示支持訊號來源較多；目前尚無足夠前瞻樣本證明這會提高勝率或 EV。
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Global Market Intelligence & Forward Acceptance Gate */}
      <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
        <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
          <CardTitle className="text-base flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Globe className="w-5 h-5 text-sky-500" />
              <span>三向基準比較與影子前瞻閘門 (Three-Way Benchmark & Acceptance Gate)</span>
            </div>
            <span className="text-xs font-mono font-semibold bg-sky-500/10 text-sky-500 px-2.5 py-1 rounded-full">
              {fwd?.acceptance_gate_qualified ? "STATISTICAL EVIDENCE SUPPORTED" : "MODEL REMAINS UNVERIFIED"}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
            30 筆是最低配對樣本門檻，不代表模型通過。系統還會要求快照完整性、固定的已接受模型版本與協定，以及模型相對 Sharp 基準的 Brier 差異 95% 信賴區間低於 0；未同時滿足時，模型仍列為未驗證。
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50 space-y-1">
              <div className="text-xs font-bold text-slate-500">基準 1：台彩隱含基線</div>
              <div className="text-lg font-black text-slate-800 dark:text-slate-200 font-mono">
                Naive Market Baseline
              </div>
              <p className="text-[11px] text-slate-400">
                高抽水 (10~15%)，作為零假設基準 (Baseline Only)。
              </p>
            </div>

            <div className="p-3.5 rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-1">
              <div className="text-xs font-bold text-emerald-600 dark:text-emerald-400">基準 2：國際市場基準／Sharp 來源規則</div>
              <div className="text-lg font-black text-emerald-600 dark:text-emerald-400 font-mono">
                一般國際市場與指定來源分開統計
              </div>
              <p className="text-[11px] text-emerald-700/80 dark:text-emerald-400/80">
                Sharp 資格依設定的來源白名單與資料品質規則判定，並非已證明該來源在此聯賽／玩法具有市場領先性；只供比較，不代表真實勝率或正期望值。
              </p>
            </div>

            <div className="p-3.5 rounded-xl border border-sky-500/30 bg-sky-500/5 space-y-1">
              <div className="text-xs font-bold text-sky-600 dark:text-sky-400">策略 3：影子驗證模型族</div>
              <div className="text-lg font-black text-sky-600 dark:text-sky-400 font-mono">
                Model Acceptance Gate
              </div>
              <p className="text-[11px] text-sky-700/80 dark:text-sky-400/80">
                嚴格排查開賽後資料洩漏，未達標前不授予決策推薦資格。
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  )
}
