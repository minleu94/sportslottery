import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { api } from "@/services/api"
import type { ParlayRecommendation, WalletStatus } from "@/types"
import { cleanLeagueName } from "@/lib/utils"
import { Slider } from "@/components/ui/Slider"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { Skeleton } from "@/components/ui/Skeleton"
import { EvidenceDrawer } from "@/components/EvidenceDrawer"
import { BetModal } from "@/components/BetModal"
import { EVHeatmapChart } from "@/components/charts/EVHeatmapChart"
import {
  Flame,
  ChevronRight,
  CheckCircle2,
  AlertCircle,
  Shield,
  Target,
  Sliders,
  TrendingUp,
  Zap,
  BookOpen,
} from "lucide-react"

interface ParlayViewProps {
  wallet: WalletStatus | null
  onWalletUpdate: (wallet: WalletStatus) => void
}

type OddsMode = "banker" | "target" | "range"

export const ParlayView: React.FC<ParlayViewProps> = ({ wallet, onWalletUpdate }) => {
  // Strategy & Odds Mode
  const [oddsMode, setOddsMode] = useState<OddsMode>("banker")
  const [targetOdds, setTargetOdds] = useState<number>(2.5)
  const [tolerance, setTolerance] = useState<number>(0.35)
  const [minLegs, setMinLegs] = useState<number>(2)
  const [maxLegs, setMaxLegs] = useState<number>(3)

  // Range Slider state (for Range mode)
  const [rangeMin, setRangeMin] = useState<number>(1.8)
  const [rangeMax, setRangeMax] = useState<number>(4.0)

  // Cross-sport & Alliances
  const [crossSport, setCrossSport] = useState<boolean>(true)
  const [selectedAlliances, setSelectedAlliances] = useState<string[]>(["1", "3", "4"])

  // Quality & Smart Filters
  const [signalFilter, setSignalFilter] = useState<string>("value_only")
  const [excludeTraps, setExcludeTraps] = useState<boolean>(false)
  const [preferSteam, setPreferSteam] = useState<boolean>(true)

  const [searching, setSearching] = useState(false)
  const [hasSearched, setHasSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [activeTier, setActiveTier] = useState<"high_consensus" | "aggressive" | "moonshot">("high_consensus")
  const [tiers, setTiers] = useState<{
    high_consensus: ParlayRecommendation[]
    aggressive: ParlayRecommendation[]
    moonshot: ParlayRecommendation[]
  }>({
    high_consensus: [],
    aggressive: [],
    moonshot: [],
  })

  // Modals state
  const [selectedParlayForEvidence, setSelectedParlayForEvidence] = useState<ParlayRecommendation | null>(null)
  const [selectedParlayForBet, setSelectedParlayForBet] = useState<ParlayRecommendation | null>(null)

  const allianceOptions = [
    { id: "1", label: "NBA 籃球" },
    { id: "3", label: "MLB 美棒" },
    { id: "4", label: "足球" },
    { id: "6", label: "CPBL 中職" },
    { id: "7", label: "NPB 日職" },
    { id: "9", label: "NFL 美式足球" },
  ]

  const rangePresets = [
    { label: "銀行家 (1.8x – 4.0x)", min: 1.8, max: 4.0, target: 2.5, minL: 2, maxL: 3, filter: "value_only" },
    { label: "穩健推薦 (4.0x – 10.0x)", min: 4.0, max: 10.0, target: 6.0, minL: 2, maxL: 4, filter: "value_only" },
    { label: "進取策略 (10x – 25x)", min: 10.0, max: 25.0, target: 15.0, minL: 3, maxL: 5, filter: "normal" },
    { label: "高倍進攻 (25x – 75x)", min: 25.0, max: 75.0, target: 40.0, minL: 4, maxL: 6, filter: "normal" },
    { label: "登月串關 (75x – 200x)", min: 75.0, max: 200.0, target: 120.0, minL: 5, maxL: 7, filter: "normal" },
    { label: "極限串關 (200x – 500x)", min: 200.0, max: 500.0, target: 300.0, minL: 6, maxL: 8, filter: "wild" },
  ]

  function selectMode(mode: OddsMode) {
    setOddsMode(mode)
    if (mode === "banker") {
      setTargetOdds(2.5)
      setTolerance(0.35)
      setMinLegs(2)
      setMaxLegs(3)
      setSignalFilter("value_only")
    } else if (mode === "target") {
      setTargetOdds(20.0)
      setTolerance(0.20)
      setMinLegs(2)
      setMaxLegs(5)
      setSignalFilter("normal")
    } else {
      setRangeMin(1.8)
      setRangeMax(4.0)
      setTargetOdds(2.5)
      setMinLegs(2)
      setMaxLegs(3)
    }
  }

  function applyPreset(preset: typeof rangePresets[0]) {
    setRangeMin(preset.min)
    setRangeMax(preset.max)
    setTargetOdds(preset.target)
    setMinLegs(preset.minL)
    setMaxLegs(preset.maxL)
    setSignalFilter(preset.filter)
  }

  async function handleSearch() {
    setSearching(true)
    setError(null)
    setHasSearched(true)

    try {
      const alliances = crossSport ? undefined : selectedAlliances
      const res = await api.searchParlays({
        target_odds: targetOdds,
        tolerance: tolerance,
        min_legs: minLegs,
        max_legs: maxLegs,
        alliances: alliances,
        signal_filter: signalFilter,
        exclude_traps: excludeTraps,
        prefer_steam: preferSteam,
        search_budget: 60000,
      })

      setTiers(res.tiers)
      if (res.tiers.high_consensus.length > 0) setActiveTier("high_consensus")
      else if (res.tiers.aggressive.length > 0) setActiveTier("aggressive")
      else if (res.tiers.moonshot.length > 0) setActiveTier("moonshot")
    } catch (err: any) {
      setError(err.message || "搜尋串關失敗")
    } finally {
      setSearching(false)
    }
  }

  const currentList = tiers[activeTier] || []
  const allTiersList = [...tiers.high_consensus, ...tiers.aggressive, ...tiers.moonshot]

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="space-y-5"
    >
      {/* Control Panel Card */}
      <Card className="border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
        <CardHeader className="pb-3 border-b border-slate-200/80 dark:border-slate-800">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <CardTitle className="text-base sm:text-lg flex items-center gap-2 font-semibold">
              <Flame className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              串關組合決策台 (1.5x – 500x 期望值搜尋)
            </CardTitle>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              設定目標總賠率，系統將依市場情報與正期望值 (+EV) 自動配對
            </span>
          </div>
        </CardHeader>

        <CardContent className="space-y-5 pt-4">
          {/* STEP 1: Odds Mode Selector Tabs */}
          <div className="space-y-2.5">
            <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
              1. 選擇策略風格與目標倍率
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <button
                type="button"
                onClick={() => selectMode("banker")}
                className={`p-3.5 rounded-xl border text-left transition-colors cursor-pointer ${
                  oddsMode === "banker"
                    ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20 shadow-xs"
                    : "border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
                  <Shield className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                  穩健銀行家模式
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  1.5x – 6x 高勝率 · 2~3 關定海神針
                </div>
              </button>

              <button
                type="button"
                onClick={() => selectMode("target")}
                className={`p-3.5 rounded-xl border text-left transition-colors cursor-pointer ${
                  oddsMode === "target"
                    ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20 shadow-xs"
                    : "border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
                  <Target className="w-4 h-4 text-slate-500 dark:text-slate-400" />
                  指定目標倍率
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  自由設定目標倍率 (Target ±20%)
                </div>
              </button>

              <button
                type="button"
                onClick={() => selectMode("range")}
                className={`p-3.5 rounded-xl border text-left transition-colors cursor-pointer ${
                  oddsMode === "range"
                    ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20 shadow-xs"
                    : "border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
                  <Sliders className="w-4 h-4 text-slate-500 dark:text-slate-400" />
                  自訂賠率區間
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  6 大快捷區間 · 自由滑桿
                </div>
              </button>
            </div>

            {/* Banker Mode Explanation Banner */}
            {oddsMode === "banker" && (
              <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 text-xs leading-relaxed space-y-1">
                <div className="font-medium text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                  穩健銀行家模式策略
                </div>
                <p className="text-slate-600 dark:text-slate-400">
                  鎖定 2~3 關高勝率與正期望值 (+EV) 關卡，總倍率約 1.5x ~ 6.0x。兼具高勝率與低風險，小額派彩全數撥入【保留儲備池】，穩健累積獲利戰力。
                </p>
              </div>
            )}

            {/* Target Mode Controls */}
            {oddsMode === "target" && (
              <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 space-y-2.5">
                <Slider
                  min={1.5}
                  max={500}
                  step={0.5}
                  value={targetOdds}
                  onChange={setTargetOdds}
                  label="目標總倍率 (x)"
                  displayValue={`${targetOdds.toFixed(1)} 倍`}
                />
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 pt-1">
                  <span>容許浮動範圍：±{(tolerance * 100).toFixed(0)}%</span>
                  <span className="font-mono tabular-nums text-slate-700 dark:text-slate-300">
                    搜尋區間：{(targetOdds * (1 - tolerance)).toFixed(1)}x ~ {(targetOdds * (1 + tolerance)).toFixed(1)}x
                  </span>
                </div>
              </div>
            )}

            {/* Range Mode Presets */}
            {oddsMode === "range" && (
              <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 space-y-3">
                <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                  快捷區間選擇：
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {rangePresets.map((preset, pIdx) => {
                    const isSelected = rangeMin === preset.min && rangeMax === preset.max
                    return (
                      <button
                        key={pIdx}
                        type="button"
                        onClick={() => applyPreset(preset)}
                        className={`p-2 rounded-lg border text-left text-xs transition-colors cursor-pointer ${
                          isSelected
                            ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-800 dark:text-emerald-300 font-medium"
                            : "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 hover:border-slate-300"
                        }`}
                      >
                        {preset.label}
                      </button>
                    )
                  })}
                </div>
                <div className="pt-2">
                  <Slider
                    min={1.5}
                    max={500}
                    step={0.5}
                    value={targetOdds}
                    onChange={setTargetOdds}
                    label="目標中線賠率"
                    displayValue={`${targetOdds.toFixed(1)} 倍`}
                  />
                </div>
              </div>
            )}
          </div>

          {/* STEP 2: Cross-Sport & Quality Filter Grid */}
          <div className="space-y-3 pt-3 border-t border-slate-200/80 dark:border-slate-800">
            <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
              2. 跨界混串與情報門檻
            </div>

            {/* Cross-sport switch */}
            <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-800 dark:text-slate-200 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={crossSport}
                    onChange={(e) => setCrossSport(e.target.checked)}
                    className="rounded text-emerald-600 focus:ring-0 w-4 h-4 cursor-pointer"
                  />
                  <span>啟用全聯盟跨界混串 (NBA、MLB、足球、NFL、職棒混合)</span>
                </label>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 ml-6">
                  {crossSport
                    ? "跨運動聯賽同時搜尋最佳賠率組合。"
                    : "已切換為指定聯盟手動過濾模式。"}
                </p>
              </div>

              {!crossSport && (
                <div className="flex flex-wrap gap-1.5 ml-6 sm:ml-0">
                  {allianceOptions.map((a) => {
                    const isSelected = selectedAlliances.includes(a.id)
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => {
                          setSelectedAlliances((prev) =>
                            isSelected ? prev.filter((id) => id !== a.id) : [...prev, a.id]
                          )
                        }}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                          isSelected
                            ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                            : "bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400"
                        }`}
                      >
                        {a.label}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Legs Range, Quality Filter, and Wind Controls */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
              {/* Legs Selection */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                  過關腿數 (Legs)
                </label>
                <div className="flex items-center gap-2">
                  <select
                    value={minLegs}
                    onChange={(e) => setMinLegs(Number(e.target.value))}
                    className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 font-mono w-full cursor-pointer"
                  >
                    <option value={2}>最少 2 關</option>
                    <option value={3}>最少 3 關</option>
                    <option value={4}>最少 4 關</option>
                  </select>
                  <span className="text-slate-400 text-xs">至</span>
                  <select
                    value={maxLegs}
                    onChange={(e) => setMaxLegs(Number(e.target.value))}
                    className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 font-mono w-full cursor-pointer"
                  >
                    <option value={3}>最多 3 關</option>
                    <option value={4}>最多 4 關</option>
                    <option value={5}>最多 5 關</option>
                    <option value={6}>最多 6 關</option>
                    <option value={8}>最多 8 關</option>
                  </select>
                </div>
              </div>

              {/* Quality Filter Selector */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                  情報品質門檻
                </label>
                <select
                  value={signalFilter}
                  onChange={(e) => setSignalFilter(e.target.value)}
                  className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 w-full cursor-pointer"
                >
                  <option value="value_only">價值優先 (+EV 正期望值)</option>
                  <option value="normal">標準 (排除無情報關卡)</option>
                  <option value="strict">嚴格 (2+ 獨立情報支持)</option>
                  <option value="wild">全量 (容納所有可能盤口)</option>
                </select>
              </div>

              {/* Smart Filters */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                  進階風控篩選
                </label>
                <div className="flex flex-col gap-1 pt-0.5">
                  <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={excludeTraps}
                      onChange={(e) => setExcludeTraps(e.target.checked)}
                      className="rounded text-emerald-600 focus:ring-0 cursor-pointer"
                    />
                    <span>過濾莊家誘盤 (排除逆向升水)</span>
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={preferSteam}
                      onChange={(e) => setPreferSteam(e.target.checked)}
                      className="rounded text-emerald-600 focus:ring-0 cursor-pointer"
                    />
                    <span>優先推薦資金跳水 (順勢跟隨)</span>
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Search Trigger Button */}
          <div className="pt-2 flex justify-end">
            <Button
              variant="default"
              size="lg"
              onClick={handleSearch}
              disabled={searching}
              className="w-full md:w-auto px-6 py-2 font-medium text-sm gap-2 cursor-pointer"
            >
              {searching ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>正在運算最佳期望值組合...</span>
                </>
              ) : (
                <span>搜尋 {targetOdds.toFixed(1)}x 串關組合</span>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* EV Density Heatmap Area Chart */}
      {hasSearched && allTiersList.length > 0 && (
        <EVHeatmapChart parlays={allTiersList} targetOdds={targetOdds} />
      )}

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Section */}
      {hasSearched && (
        <div className="space-y-4">
          {/* Tier Switcher Tabs */}
          <div className="flex border-b border-slate-200 dark:border-slate-800 gap-1.5 pb-2 overflow-x-auto">
            <button
              onClick={() => setActiveTier("high_consensus")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                activeTier === "high_consensus"
                  ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <Shield className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              <span>高共識推薦</span>
              <span className="font-mono tabular-nums text-[10px] text-slate-500">
                ({tiers.high_consensus.length})
              </span>
            </button>

            <button
              onClick={() => setActiveTier("aggressive")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                activeTier === "aggressive"
                  ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <TrendingUp className="w-3.5 h-3.5 text-slate-400" />
              <span>積極進攻</span>
              <span className="font-mono tabular-nums text-[10px] text-slate-500">
                ({tiers.aggressive.length})
              </span>
            </button>

            <button
              onClick={() => setActiveTier("moonshot")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                activeTier === "moonshot"
                  ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <Zap className="w-3.5 h-3.5 text-slate-400" />
              <span>高倍衝月</span>
              <span className="font-mono tabular-nums text-[10px] text-slate-500">
                ({tiers.moonshot.length})
              </span>
            </button>
          </div>

          {/* Results List */}
          {searching ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-56" />
              ))}
            </div>
          ) : currentList.length === 0 ? (
            <Card className="text-center py-10">
              <CardContent className="space-y-2">
                <h4 className="font-medium text-slate-800 dark:text-slate-200 text-sm">此分類暫無符合條件的組合</h4>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  可嘗試調整目標賠率（如改為 1.8x ~ 4.0x 穩健銀行家模式）或放寬情報門檻重試。
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <AnimatePresence>
                {currentList.map((parlay, idx) => (
                  <div
                    key={parlay.parlay_id || idx}
                    className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors space-y-3.5"
                  >
                    {/* Header */}
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-slate-900 dark:text-slate-100 text-sm">
                            {parlay.parlay_name || `組合 #${idx + 1}`}
                          </span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/60">
                            {parlay.legs.length} 串 1
                          </span>
                          {parlay.sharp_badge && (
                            <Badge variant={parlay.is_positive_ev ? "green" : "secondary"} className="text-[10px]">
                              {parlay.sharp_badge}
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex items-center gap-2 flex-wrap">
                          <span>賠率連乘</span>
                          {parlay.joint_probability ? (
                            <>
                              <span>·</span>
                              <span className="text-slate-700 dark:text-slate-300 font-medium font-mono tabular-nums">
                                聯合勝率 {(parlay.joint_probability * 100).toFixed(1)}%
                              </span>
                            </>
                          ) : null}
                          <span>·</span>
                          <span className="text-slate-400">獨立賽事檢驗</span>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        <div className="text-xl font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums tracking-tight">
                          {parlay.total_odds.toFixed(2)}x
                        </div>
                        {(() => {
                          const evVal = parlay.parlay_ev_pct ?? (parlay.expected_value ? parlay.expected_value * 100 : null)
                          if (evVal === null || evVal === undefined) return null
                          const parlayHasSynth = parlay.legs?.some((l) => l.is_market_synthetic || (l.signal_evidence || {}).is_market_synthetic)
                          const isPos = !parlayHasSynth && evVal > 0
                          return (
                            <div
                              className={`text-xs font-medium tabular-nums font-mono flex items-center justify-end gap-1 ${
                                isPos ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"
                              }`}
                            >
                              <span>{isPos ? "+EV" : (parlayHasSynth ? "EV (模擬)" : "EV")}</span>
                              <span>{isPos ? `+${evVal.toFixed(1)}%` : `${evVal.toFixed(1)}%`}</span>
                            </div>
                          )
                        })()}
                      </div>
                    </div>

                    {/* Legs list inside parlay */}
                    <div className="space-y-1.5 pt-1.5 border-t border-slate-100 dark:border-slate-800">
                      {parlay.legs.map((leg, lIdx) => {
                        const isSynth = Boolean(leg.is_market_synthetic || (leg.signal_evidence || {}).is_market_synthetic)
                        const legEv = leg.expected_value_pct ?? (leg.expected_value ? leg.expected_value * 100 : null)
                        const legProb = leg.consensus_probability ? (leg.consensus_probability * 100).toFixed(0) : null
                        const isPos = Boolean(!isSynth && (leg.is_positive_ev || (legEv !== null && legEv > 0)))

                        return (
                          <div
                            key={lIdx}
                            className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950/60 border border-slate-200/70 dark:border-slate-800/60 flex items-center justify-between text-xs"
                          >
                            <div className="space-y-0.5">
                              <div className="font-medium text-slate-800 dark:text-slate-200">
                                <span className="font-medium text-slate-400 mr-1.5">
                                  {cleanLeagueName(leg.display_league || leg.league || leg.sport)}
                                </span>
                                {leg.away_team} vs {leg.home_team}
                              </div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <div className="text-slate-900 dark:text-slate-100 font-medium flex items-center gap-1.5">
                                  <span className="text-[11px] text-slate-400">[{leg.market}]</span>
                                  <span>{leg.selection}</span>
                                </div>

                                {/* Leg EV Badge */}
                                {legEv !== null && (
                                  <span
                                    className={`text-[10px] px-1 py-0.2 rounded font-mono font-medium ${
                                      isPos
                                        ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20"
                                        : "bg-slate-100 dark:bg-slate-800 text-slate-500"
                                    }`}
                                  >
                                    {isPos ? `+EV +${legEv.toFixed(1)}%` : (isSynth ? `EV ${legEv.toFixed(1)}% (模擬)` : `EV ${legEv.toFixed(1)}%`)}
                                  </span>
                                )}

                                {/* Leg Prob */}
                                {legProb && (
                                  <span className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
                                    勝率 {legProb}%
                                  </span>
                                )}
                              </div>
                            </div>

                            <div className="text-right pl-3 shrink-0">
                              <span className="font-medium font-mono tabular-nums text-slate-900 dark:text-slate-100 text-xs sm:text-sm">
                                {leg.taiwan_odds?.toFixed(2)}x
                              </span>
                            </div>
                          </div>
                        )
                      })}
                    </div>

                    {/* Actions Bar */}
                    <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-3">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedParlayForEvidence(parlay)}
                        className="text-xs gap-1.5 text-slate-600 dark:text-slate-300 cursor-pointer"
                      >
                        <BookOpen className="w-3.5 h-3.5 text-slate-400" />
                        <span>分析依據</span>
                        <ChevronRight className="w-3 h-3 text-slate-400" />
                      </Button>

                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => setSelectedParlayForBet(parlay)}
                        className="text-xs font-medium px-4 gap-1.5 cursor-pointer"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>確認下注</span>
                      </Button>
                    </div>
                  </div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      )}

      {/* Modals & Drawers */}
      <EvidenceDrawer
        open={Boolean(selectedParlayForEvidence)}
        onClose={() => setSelectedParlayForEvidence(null)}
        parlay={selectedParlayForEvidence}
      />

      <BetModal
        open={Boolean(selectedParlayForBet)}
        onClose={() => setSelectedParlayForBet(null)}
        parlay={selectedParlayForBet}
        wallet={wallet}
        onSuccess={onWalletUpdate}
      />
    </motion.div>
  )
}
