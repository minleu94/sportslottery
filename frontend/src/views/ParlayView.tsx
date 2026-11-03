import React, { useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { api } from "@/services/api"
import type { ParlayRecommendation, ParlaySearchPerformance, ParlayTier, WalletStatus } from "@/types"
import { Slider } from "@/components/ui/Slider"
import { Button } from "@/components/ui/Button"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { Skeleton } from "@/components/ui/Skeleton"
import { EvidenceDrawer } from "@/components/EvidenceDrawer"
import { BetModal } from "@/components/BetModal"
import { EVHeatmapChart } from "@/components/charts/EVHeatmapChart"
import { ParlayResultCard } from "@/components/ParlayResultCard"
import {
  Flame,
  AlertCircle,
  Shield,
  Target,
  Sliders,
  TrendingUp,
  Zap,
} from "lucide-react"

interface ParlayViewProps {
  wallet: WalletStatus | null
  onWalletUpdate: (wallet: WalletStatus) => void
}

type OddsMode = "banker" | "target" | "range"
type ParlayTiers = Record<ParlayTier, ParlayRecommendation[]>
type ParlayPerformance = ParlaySearchPerformance

interface ParlaySearchCache {
  oddsMode: OddsMode
  targetOdds: number
  tolerance: number
  minLegs: number
  maxLegs: number
  rangeMin: number
  rangeMax: number
  crossSport: boolean
  selectedAlliances: string[]
  signalFilter: string
  excludeTraps: boolean
  preferSteam: boolean
  activeTier: ParlayTier
  tiers: ParlayTiers
  hasSearched: boolean
  performance: ParlayPerformance | null
  searchComplete: boolean
}

const PARLAY_CACHE_TTL_MS = 4 * 60 * 1000
let parlaySearchCache: { expiresAt: number; state: ParlaySearchCache } | null = null

function readParlaySearchCache(): ParlaySearchCache | null {
  if (!parlaySearchCache || Date.now() >= parlaySearchCache.expiresAt) {
    parlaySearchCache = null
    return null
  }
  return parlaySearchCache.state
}

function writeParlaySearchCache(state: ParlaySearchCache) {
  parlaySearchCache = { state, expiresAt: Date.now() + PARLAY_CACHE_TTL_MS }
}

function emptyParlayTiers(): ParlayTiers {
  return { high_consensus: [], aggressive: [], moonshot: [] }
}

export const ParlayView: React.FC<ParlayViewProps> = ({ wallet, onWalletUpdate }) => {
  const [restoredSearch] = useState<ParlaySearchCache | null>(() => readParlaySearchCache())
  // Strategy & Odds Mode
  const [oddsMode, setOddsMode] = useState<OddsMode>(restoredSearch?.oddsMode ?? "banker")
  const [targetOdds, setTargetOdds] = useState<number>(restoredSearch?.targetOdds ?? 2.5)
  const [tolerance, setTolerance] = useState<number>(restoredSearch?.tolerance ?? 0.35)
  const [minLegs, setMinLegs] = useState<number>(restoredSearch?.minLegs ?? 2)
  const [maxLegs, setMaxLegs] = useState<number>(restoredSearch?.maxLegs ?? 3)

  // Range Slider state (for Range mode)
  const [rangeMin, setRangeMin] = useState<number>(restoredSearch?.rangeMin ?? 1.8)
  const [rangeMax, setRangeMax] = useState<number>(restoredSearch?.rangeMax ?? 4.0)

  // Cross-sport & Alliances
  const [crossSport, setCrossSport] = useState<boolean>(restoredSearch?.crossSport ?? true)
  const [selectedAlliances, setSelectedAlliances] = useState<string[]>(restoredSearch?.selectedAlliances ?? ["1", "3", "4"])

  // Quality & Smart Filters
  const [signalFilter, setSignalFilter] = useState<string>(restoredSearch?.signalFilter ?? "value_only")
  const [excludeTraps, setExcludeTraps] = useState<boolean>(restoredSearch?.excludeTraps ?? false)
  const [preferSteam, setPreferSteam] = useState<boolean>(restoredSearch?.preferSteam ?? true)

  const [searching, setSearching] = useState(false)
  const [hasSearched, setHasSearched] = useState<boolean>(restoredSearch?.hasSearched ?? false)
  const [error, setError] = useState<string | null>(null)

  const [activeTier, setActiveTier] = useState<ParlayTier>(restoredSearch?.activeTier ?? "high_consensus")
  const [tiers, setTiers] = useState<ParlayTiers>(restoredSearch?.tiers ?? emptyParlayTiers())
  const [searchPerformance, setSearchPerformance] = useState<ParlayPerformance | null>(restoredSearch?.performance ?? null)
  const [searchComplete, setSearchComplete] = useState<boolean>(restoredSearch?.searchComplete ?? true)

  // Modals state
  const [selectedParlayForEvidence, setSelectedParlayForEvidence] = useState<ParlayRecommendation | null>(null)
  const [selectedParlayForBet, setSelectedParlayForBet] = useState<ParlayRecommendation | null>(null)

  useEffect(() => {
    writeParlaySearchCache({
      oddsMode,
      targetOdds,
      tolerance,
      minLegs,
      maxLegs,
      rangeMin,
      rangeMax,
      crossSport,
      selectedAlliances,
      signalFilter,
      excludeTraps,
      preferSteam,
      activeTier,
      tiers,
      hasSearched,
      performance: searchPerformance,
      searchComplete,
    })
  }, [oddsMode, targetOdds, tolerance, minLegs, maxLegs, rangeMin, rangeMax, crossSport, selectedAlliances, signalFilter, excludeTraps, preferSteam, activeTier, tiers, hasSearched, searchPerformance, searchComplete])

  const allianceOptions = [
    { id: "1", label: "NBA 籃球" },
    { id: "3", label: "MLB 美棒" },
    { id: "4", label: "足球" },
    { id: "6", label: "CPBL 中職" },
    { id: "7", label: "NPB 日職" },
    { id: "9", label: "NFL 美式足球" },
  ]

  const rangePresets = [
    { label: "低倍率組合 (1.8x – 4.0x)", min: 1.8, max: 4.0, target: 2.5, minL: 2, maxL: 3, filter: "value_only" },
    { label: "中低倍率組合 (4.0x – 10.0x)", min: 4.0, max: 10.0, target: 6.0, minL: 2, maxL: 4, filter: "value_only" },
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
    setSearchPerformance(null)
    setSearchComplete(false)
    writeParlaySearchCache({
      oddsMode, targetOdds, tolerance, minLegs, maxLegs, rangeMin, rangeMax,
      crossSport, selectedAlliances, signalFilter, excludeTraps, preferSteam,
      activeTier, tiers, hasSearched: true, performance: null, searchComplete: false,
    })

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

      const nextActiveTier = res.tiers.high_consensus.length > 0
        ? "high_consensus"
        : res.tiers.aggressive.length > 0
          ? "aggressive"
          : res.tiers.moonshot.length > 0
            ? "moonshot"
            : activeTier
      setTiers(res.tiers)
      setActiveTier(nextActiveTier)
      setSearchPerformance(res.performance ?? null)
      setSearchComplete(res.search_complete)
      writeParlaySearchCache({
        oddsMode, targetOdds, tolerance, minLegs, maxLegs, rangeMin, rangeMax,
        crossSport, selectedAlliances, signalFilter, excludeTraps, preferSteam,
        activeTier: nextActiveTier, tiers: res.tiers, hasSearched: true,
        performance: res.performance ?? null, searchComplete: res.search_complete,
      })
    } catch (err: any) {
      setError(err.message || "搜尋串關失敗")
      setSearchComplete(true)
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
              串關組合研究台 (1.5x – 500x 賠率範圍)
            </CardTitle>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              依目前資料與篩選條件搜尋候選；倍率、情報支持和勝率代表不同資訊，估計 EV 尚未證明可預測收益。
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
                  低倍率銀行家模式
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  1.5x – 6x 搜尋範圍 · 2~3 關
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
                  低倍率串關搜尋範圍
                </div>
                <p className="text-slate-600 dark:text-slate-400">
                  以 2~3 關、總倍率約 1.5x ~ 6.0x 搜尋組合。較低倍率不代表命中率較高或風險較低；個別勝率與 EV 仍受來源、資料完整度及未校準估計影響。
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
                  <option value="value_only">估計價值優先（含未校準機率條件）</option>
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
                    <span>排除標記為逆向升水的候選</span>
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={preferSteam}
                      onChange={(e) => setPreferSteam(e.target.checked)}
                      className="rounded text-emerald-600 focus:ring-0 cursor-pointer"
                    />
                    <span>排序偏好賠率跳動訊號（不代表方向有效）</span>
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
              <span>高情報支持</span>
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

          {!searching && searchPerformance && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500 dark:text-slate-400 tabular-nums">
              <span>資料 {searchPerformance.taiwan_fetch_ms.toFixed(0)} ms</span>
              <span>訊號 {searchPerformance.signal_enrichment_ms.toFixed(0)} ms</span>
              <span>組合 {searchPerformance.parlay_search_ms.toFixed(0)} ms</span>
              <span>總計 {searchPerformance.total_ms.toFixed(0)} ms</span>
              <span>前處理快取 {searchPerformance.prepared_legs_cache_hit ? "命中" : "建立"}</span>
            </div>
          )}
          {!searching && !searchComplete && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
              搜尋預算已用完；目前候選尚未保證涵蓋完整搜尋空間。
            </div>
          )}

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
                  可調整搜尋範圍或查看候選拒絕原因；若缺乏合格資料，先不產生組合是正常結果。
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <AnimatePresence>
                {currentList.map((parlay, idx) => (
                  <ParlayResultCard
                    key={parlay.parlay_id || idx}
                    parlay={parlay}
                    index={idx}
                    onShowEvidence={setSelectedParlayForEvidence}
                    onPlaceBet={setSelectedParlayForBet}
                  />
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
