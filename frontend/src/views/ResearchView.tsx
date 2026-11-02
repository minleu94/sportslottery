import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { api } from "@/services/api"
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

export const ResearchView: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [marketSummary, setMarketSummary] = useState<any>(null)
  const [_loadingMarket, setLoadingMarket] = useState(true)
  const [_loadingAnalytics, setLoadingAnalytics] = useState(true)
  const [apiKeyInput, setApiKeyInput] = useState("")
  const [showKeyForm, setShowKeyForm] = useState(false)
  const [submittingKey, setSubmittingKey] = useState(false)
  const [runningCycle, setRunningCycle] = useState(false)
  const [togglingScheduler, setTogglingScheduler] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: "success" | "error"; text: string } | null>(null)

  useEffect(() => {
    loadAnalytics()
  }, [])

  async function loadAnalytics() {
    api.getMarketResearchSummary()
      .then((res) => {
        setMarketSummary(res)
        setLoadingMarket(false)
      })
      .catch(() => setLoadingMarket(false))

    api.getResearchAnalytics()
      .then((res) => {
        setData(res)
        setLoadingAnalytics(false)
      })
      .catch(() => setLoadingAnalytics(false))
  }

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
      if (updated) setMarketSummary(updated)
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
      await api.triggerMarketPipelineCycle()
      setFeedbackMsg({
        type: "success",
        text: "✓ 前瞻驗證週期已執行完成，已同步盤口、校驗不可篡改快照並更新驗證指標！",
      })
      const [resAnalytics, resMarket] = await Promise.all([
        api.getResearchAnalytics().catch(() => null),
        api.getMarketResearchSummary().catch(() => null),
      ])
      setData(resAnalytics)
      setMarketSummary(resMarket)
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
    } catch (err: any) {
      setFeedbackMsg({ type: "error", text: err.message || "更新排程設定失敗" })
    } finally {
      setTogglingScheduler(false)
    }
  }

  const portfolio = data?.shadow_portfolio || {}
  const theOdds = marketSummary?.the_odds_api || {}
  const snaps = marketSummary?.snapshots || {}
  const fwd = marketSummary?.forward_evaluation || {}
  const opMode = marketSummary?.live_status || theOdds?.operating_mode || "SYNTHETIC_FIXTURE"
  const sampleSize = fwd?.sample_size || 0
  const sched = marketSummary?.scheduler || {}

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
      </div>

      {/* Global Market Intelligence & Continuous Forward Pipeline Banner */}
      <Card className="border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
        <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Globe className="w-4 h-4 text-slate-400" />
              <span>國際即時市場情報與前瞻驗證閉環</span>
            </CardTitle>
            <div className="flex items-center gap-2">
              {opMode === "LIVE_VERIFIED" || opMode === "LIVE_API" ? (
                <Badge variant="green" className="gap-1.5 py-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                  LIVE (真實國際市場已驗證)
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
              ) : (
                <Badge variant="secondary" className="gap-1.5 py-0.5 text-slate-400">
                  SYNTHETIC (合成展示模式)
                </Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          {/* Operational Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* 1. Market Live Status */}
            <div className="p-3 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 space-y-1">
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>國際盤口來源</span>
                <Activity className="w-3.5 h-3.5 text-slate-400" />
              </div>
              <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono">
                The Odds API
              </div>
              <div className="text-[11px] text-slate-400 truncate">
                {theOdds?.key_masked ? `金鑰: ${theOdds.key_masked}` : "尚未配置 Key"}
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                {theOdds?.last_successful_fetch_utc
                  ? `最近成功: ${new Date(theOdds.last_successful_fetch_utc).toLocaleTimeString()}`
                  : theOdds?.has_api_key
                  ? "等待連線測試或首次排程"
                  : "降級合成展示"}
              </div>
            </div>

            {/* 2. Quota Usage Tracker */}
            <div className="p-3 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 space-y-1">
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>本月配額 (500/月)</span>
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
                {theOdds?.requests_used_this_month || 0} / {theOdds?.monthly_budget || theOdds?.monthly_quota || 500}
              </div>
              <div className="text-[11px] text-slate-600 dark:text-slate-400 font-medium truncate tabular-nums">
                官方剩餘: {theOdds?.official_remaining ?? theOdds?.requests_remaining_est ?? 500} Credits
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                日排程預算: {theOdds?.daily_schedulable_budget || 0} (手動保留 50)
              </div>
            </div>

            {/* 3. Snapshots Accumulation */}
            <div className="p-3 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 space-y-1">
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>歷史快照 / 已結算</span>
                <Database className="w-3.5 h-3.5 text-slate-400" />
              </div>
              <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
                {snaps?.total_count || data?.total_snapshots || 0} / {snaps?.settled_count || 0}
              </div>
              <div className="text-[11px] text-slate-600 dark:text-slate-400 font-medium truncate">
                有效前瞻: {snaps?.forward_eligible_count || 0}
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                歷史基線封存: {snaps?.legacy_unverified_count || 0} 筆
              </div>
            </div>

            {/* 4. Forward Gate Status */}
            <div className="p-3 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 space-y-1">
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>前瞻驗證樣本 (N)</span>
                <span className="text-[11px] font-mono font-medium text-slate-400">門檻 30</span>
              </div>
              <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
                {sampleSize} / 30
              </div>
              <div className="text-[11px] truncate">
                <span className="text-slate-600 dark:text-slate-400 font-medium">
                  {fwd?.status === "SHADOW_MODE_ACCUMULATING" ? "影子累積中 (0/30)" : (fwd?.status || "影子累積中")}
                </span>
              </div>
              <div className="text-[10px] text-slate-400 truncate">
                {fwd?.acceptance_gate_qualified ? "已通過驗證閘門" : "未達驗證門檻"}
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
                  <span className="text-emerald-500 font-bold text-[10px]">(成功)</span>
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
                    ? new Date(sched.next_run_utc).toLocaleTimeString()
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
                    : "bg-rose-500/10 border border-rose-500/30 text-rose-400"
                }`}
              >
                {feedbackMsg.type === "success" ? (
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
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

      {/* Snapshot Stats Header Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur shadow-sm">
          <div className="text-xs text-slate-500 dark:text-slate-400">歷史盤口快照總數</div>
          <div className="text-2xl font-black tabular-nums text-emerald-600 dark:text-emerald-400 font-mono mt-1">
            {(snaps?.total_count || data?.total_snapshots || 0).toLocaleString()}
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">獨立觀測樣本</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur shadow-sm">
          <div className="text-xs text-slate-500 dark:text-slate-400">影子投組勝率</div>
          <div className="text-2xl font-black tabular-nums text-amber-500 dark:text-amber-400 font-mono mt-1">
            {((portfolio?.win_rate || 0) * 100).toFixed(1)}%
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            {portfolio?.total_tickets || 0} 筆影子模擬單
          </div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur shadow-sm">
          <div className="text-xs text-slate-500 dark:text-slate-400">影子投組 ROI</div>
          <div className="text-2xl font-black tabular-nums text-sky-600 dark:text-sky-400 font-mono mt-1">
            {portfolio?.roi ? `${(portfolio.roi * 100).toFixed(1)}%` : "0.0%"}
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">虛擬回測收益率</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur shadow-sm">
          <div className="text-xs text-slate-500 dark:text-slate-400">前瞻族群追蹤</div>
          <div className="text-2xl font-black tabular-nums text-purple-600 dark:text-purple-400 font-mono mt-1">
            {snaps?.settled_count || data?.cohort?.resolved_count || 0}
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">已結算校準樣本</div>
        </div>
      </div>

      {/* Research Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Consensus & Crowd breakdown */}
        <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="w-4 h-4 text-sky-500" />
              社群大眾投票分組校準
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <p className="text-xs text-slate-600 dark:text-slate-400">
              分析玩運彩社群公眾投票不同比例（如 50%、60%、70%）在真實開獎中的勝率與 EV 偏差。
            </p>
            <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 p-3 text-xs text-slate-700 dark:text-slate-300">
              <div className="font-semibold text-emerald-600 dark:text-emerald-400 mb-1">統計觀察重點：</div>
              <ul className="list-disc list-inside space-y-1 text-slate-500 dark:text-slate-400">
                <li>大眾選票 &gt; 70% 之熱門場次常具備降水效應。</li>
                <li>逆向升水（莊家受熱反而調高賠率）往往為高風險陷阱。</li>
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
              Poisson 分佈足球模型、MLB Elo 動態評分與玩運彩殺手大神榜首信號之交叉驗證。
            </p>
            <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 p-3 text-xs text-slate-700 dark:text-slate-300">
              <div className="font-semibold text-amber-600 dark:text-amber-400 mb-1">多來源獨立支持原則：</div>
              <p className="text-slate-500 dark:text-slate-400">
                當「大神推薦」、「大眾投票」與「模型估計」三者有 2 項以上同向支持時，串關成功率顯著提升。
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
              {sampleSize >= 30 ? "ACCEPTANCE GATE ACTIVE" : "SHADOW LOGGING ACTIVE"}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
            系統嚴格遵守 Phase 4 前瞻驗證承諾：任何新接入之國際市場資料或預測訊號在累積滿 30 筆真實結算樣本前，強制以<strong>影子模式 (Shadow Mode)</strong> 運作，
            不允許未經考驗的模型單方面調高下注推薦信心。
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
              <div className="text-xs font-bold text-emerald-600 dark:text-emerald-400">基準 2：國際 Sharp 尖銳公允</div>
              <div className="text-lg font-black text-emerald-600 dark:text-emerald-400 font-mono">
                Pinnacle / Consensus
              </div>
              <p className="text-[11px] text-emerald-700/80 dark:text-emerald-400/80">
                去抽水無水公允勝率，量化正期望值 (+EV) 的真實指針。
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
