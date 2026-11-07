import React, { useEffect, useRef, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { api } from "@/services/api"
import type { JsonRecord, ParlayRecommendation, ParlaySearchPerformance, ParlayTier, WalletStatus } from "@/types"
import { Slider } from "@/components/ui/Slider"
import { Button } from "@/components/ui/Button"
import { Card, CardContent } from "@/components/ui/Card"
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
  ChevronDown,
  ChevronUp,
  Search,
} from "lucide-react"

interface ParlayViewProps {
  wallet: WalletStatus | null
  onWalletUpdate: (wallet: WalletStatus) => void
}

type OddsMode = "banker" | "target" | "range"
type RankingMode = "WIN_PROBABILITY" | "VALUE"
type ParlayTiers = Record<ParlayTier, ParlayRecommendation[]>
type ParlayPerformance = ParlaySearchPerformance

interface ParlaySearchDiagnostics {
  normalized_option_count: number
  ready_option_count: number
  quality_option_count: number
  quality_filtered_out_option_count: number
  excluded_option_reasons: Record<string, number>
  search_event_count: number
  search_option_count: number
  checked_combinations: number
  odds_matching_combinations: number
}

interface ParlaySearchCache {
  oddsMode: OddsMode
  targetOdds: number
  tolerance: number
  minLegs: number
  minLegsCustomized?: boolean
  maxLegs: number
  rangeMin: number
  rangeMax: number
  crossSport: boolean
  selectedAlliances: string[]
  signalFilter: string
  rankingMode: RankingMode
  excludeTraps: boolean
  preferSteam: boolean
  activeTier: ParlayTier
  tiers: ParlayTiers
  hasSearched: boolean
  performance: ParlayPerformance | null
  searchComplete: boolean
  diagnostics: ParlaySearchDiagnostics | null
}

const PARLAY_CACHE_TTL_MS = 4 * 60 * 1000
let parlaySearchCache: { expiresAt: number; state: ParlaySearchCache } | null = null

const SEARCH_REASON_LABELS: Record<string, string> = {
  ODDS_INVALID: "賠率無效",
  ODDS_STALE: "盤口資料已過期",
  ODDS_TIME_UNKNOWN: "盤口抓取時間未知",
  ODDS_TIME_FUTURE: "盤口時間異常",
  START_TIME_UNKNOWN: "開賽時間未知",
  EVENT_STARTED: "賽事已開賽",
  LINE_UNKNOWN: "讓分或大小門檻不完整",
  MARKET_UNSUPPORTED: "玩法尚未支援",
  EVENT_ID_UNKNOWN: "賽事識別不足",
  EVENT_IDENTITY_INCOMPLETE: "主客隊識別不完整",
  DUPLICATE_EVENT: "同場賽事不可重複串入",
  INELIGIBLE_OR_INVALID_ODDS: "候選不符合資格或賠率無效",
}

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
  const [minLegsCustomized, setMinLegsCustomized] = useState<boolean>(restoredSearch?.minLegsCustomized ?? false)
  const [minLegs, setMinLegs] = useState<number>(
    restoredSearch?.oddsMode === "banker" && !restoredSearch.minLegsCustomized
      ? 1
      : restoredSearch?.minLegs ?? (restoredSearch?.oddsMode === "target" || restoredSearch?.oddsMode === "range" ? 2 : 1),
  )
  const [maxLegs, setMaxLegs] = useState<number>(restoredSearch?.maxLegs ?? 3)
  const [rankingMode, setRankingMode] = useState<RankingMode>(restoredSearch?.rankingMode ?? "WIN_PROBABILITY")

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

  // Mobile collapsible filter panel: open initially before first search, auto-collapsed after search so results show on first screen
  const [mobileFilterExpanded, setMobileFilterExpanded] = useState<boolean>(!(restoredSearch?.hasSearched ?? false))

  const [activeTier, setActiveTier] = useState<ParlayTier>(restoredSearch?.activeTier ?? "high_consensus")
  const [tiers, setTiers] = useState<ParlayTiers>(restoredSearch?.tiers ?? emptyParlayTiers())
  const [searchPerformance, setSearchPerformance] = useState<ParlayPerformance | null>(restoredSearch?.performance ?? null)
  const [searchComplete, setSearchComplete] = useState<boolean>(restoredSearch?.searchComplete ?? true)
  const [searchDiagnostics, setSearchDiagnostics] = useState<ParlaySearchDiagnostics | null>(restoredSearch?.diagnostics ?? null)
  const [pendingDeepLinkSearch, setPendingDeepLinkSearch] = useState(false)

  // Modals state
  const [selectedParlayForEvidence, setSelectedParlayForEvidence] = useState<ParlayRecommendation | null>(null)
  const [selectedParlayForBet, setSelectedParlayForBet] = useState<ParlayRecommendation | null>(null)

  useEffect(() => {
    writeParlaySearchCache({
      oddsMode,
      targetOdds,
      tolerance,
      minLegs,
      minLegsCustomized,
      maxLegs,
      rangeMin,
      rangeMax,
      crossSport,
      selectedAlliances,
      signalFilter,
      rankingMode,
      excludeTraps,
      preferSteam,
      activeTier,
      tiers,
      hasSearched,
      performance: searchPerformance,
      searchComplete,
      diagnostics: searchDiagnostics,
    })
  }, [oddsMode, targetOdds, tolerance, minLegs, minLegsCustomized, maxLegs, rangeMin, rangeMax, crossSport, selectedAlliances, signalFilter, rankingMode, excludeTraps, preferSteam, activeTier, tiers, hasSearched, searchPerformance, searchComplete, searchDiagnostics])

  const allianceOptions = [
    { id: "1", label: "NBA 籃球" },
    { id: "3", label: "MLB 美棒" },
    { id: "4", label: "足球" },
    { id: "6", label: "CPBL 中職" },
    { id: "7", label: "NPB 日職" },
    { id: "9", label: "NFL 美式足球" },
  ]

  const rangePresets = [
    { label: "低倍 (1.8–4x)", min: 1.8, max: 4.0, minL: 2, maxL: 3, filter: "value_only" },
    { label: "中低 (4–10x)", min: 4.0, max: 10.0, minL: 2, maxL: 4, filter: "value_only" },
    { label: "進取 (10–25x)", min: 10.0, max: 25.0, minL: 3, maxL: 5, filter: "normal" },
    { label: "高倍 (25–75x)", min: 25.0, max: 75.0, minL: 4, maxL: 6, filter: "normal" },
    { label: "登月 (75–200x)", min: 75.0, max: 200.0, minL: 5, maxL: 7, filter: "normal" },
    { label: "極限 (200–500x)", min: 200.0, max: 500.0, minL: 6, maxL: 8, filter: "wild" },
  ]

  function selectMode(mode: OddsMode) {
    setOddsMode(mode)
    setMinLegsCustomized(false)
    if (mode === "banker") {
      setTargetOdds(3.75)
      setTolerance(0.20)
      setMinLegs(1)
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
    setTargetOdds((preset.min + preset.max) / 2)
    setMinLegs(preset.minL)
    setMinLegsCustomized(true)
    setMaxLegs(preset.maxL)
    setSignalFilter(preset.filter)
  }

  async function handleSearch() {
    setSearching(true)
    setError(null)
    setHasSearched(true)
    setMobileFilterExpanded(false)
    setSearchPerformance(null)
    setSearchComplete(false)
    setSearchDiagnostics(null)
    writeParlaySearchCache({
      oddsMode, targetOdds, tolerance, minLegs, minLegsCustomized, maxLegs, rangeMin, rangeMax,
      crossSport, selectedAlliances, signalFilter, rankingMode, excludeTraps, preferSteam,
      activeTier, tiers, hasSearched: true, performance: null, searchComplete: false, diagnostics: null,
    })

    try {
      const alliances = crossSport ? undefined : selectedAlliances
      const res = await api.searchParlays({
        target_odds: oddsMode === "target" ? targetOdds : null,
        min_odds: oddsMode === "banker" ? 1.5 : oddsMode === "range" ? rangeMin : undefined,
        max_odds: oddsMode === "banker" ? 6.0 : oddsMode === "range" ? rangeMax : undefined,
        tolerance: tolerance,
        min_legs: minLegs,
        max_legs: maxLegs,
        alliances: alliances,
        signal_filter: signalFilter,
        ranking_mode: rankingMode,
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
      const diagnosticRecord = (res.diagnostics ?? {}) as JsonRecord
      const diagnostics: ParlaySearchDiagnostics = {
        normalized_option_count: Number(diagnosticRecord.normalized_option_count ?? 0),
        ready_option_count: Number(diagnosticRecord.ready_option_count ?? 0),
        quality_option_count: Number(diagnosticRecord.quality_option_count ?? 0),
        quality_filtered_out_option_count: Number(diagnosticRecord.quality_filtered_out_option_count ?? 0),
        excluded_option_reasons: (diagnosticRecord.excluded_option_reasons as Record<string, number>) ?? {},
        search_event_count: Number(diagnosticRecord.search_event_count ?? 0),
        search_option_count: Number(diagnosticRecord.search_option_count ?? 0),
        checked_combinations: Number(diagnosticRecord.checked_combinations ?? 0),
        odds_matching_combinations: Number(diagnosticRecord.odds_matching_combinations ?? 0),
      }
      setSearchDiagnostics(diagnostics)
      writeParlaySearchCache({
        oddsMode, targetOdds, tolerance, minLegs, minLegsCustomized, maxLegs, rangeMin, rangeMax,
        crossSport, selectedAlliances, signalFilter, rankingMode, excludeTraps, preferSteam,
        activeTier: nextActiveTier, tiers: res.tiers, hasSearched: true,
        performance: res.performance ?? null, searchComplete: res.search_complete, diagnostics,
      })
    } catch (err: any) {
      setError(err.message || "搜尋串關失敗")
      setSearchComplete(true)
    } finally {
      setSearching(false)
    }
  }

  const handleSearchRef = useRef(handleSearch)
  handleSearchRef.current = handleSearch

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get("tab") !== "parlay") return
    const mode = params.get("mode")
    const target = Number(params.get("target_odds"))
    if (mode === "banker") {
      setOddsMode("banker")
      setTargetOdds(3.75)
      setTolerance(0.2)
      setMinLegs(1)
      setMaxLegs(3)
      setSignalFilter("value_only")
      setMinLegsCustomized(false)
    } else if (mode === "target") {
      setOddsMode("target")
      if (Number.isFinite(target) && target >= 1.5 && target <= 5000) setTargetOdds(target)
      setTolerance(0.2)
      setMinLegs(2)
      setMaxLegs(5)
      setSignalFilter("normal")
      setMinLegsCustomized(false)
    }
    if (params.get("run_search") === "1") setPendingDeepLinkSearch(true)
  }, [])

  useEffect(() => {
    if (!pendingDeepLinkSearch) return
    setPendingDeepLinkSearch(false)
    void handleSearchRef.current()
  }, [pendingDeepLinkSearch])

  const currentList = tiers[activeTier] || []
  const allTiersList = [...tiers.high_consensus, ...tiers.aggressive, ...tiers.moonshot]
  const searchRangeLabel = oddsMode === "banker"
    ? "1.5~6.0x"
    : oddsMode === "range"
      ? `${rangeMin.toFixed(1)}~${rangeMax.toFixed(1)}x`
      : `${targetOdds.toFixed(1)}x`

  const modeSummaryTitle =
    oddsMode === "banker"
      ? "銀行家 1.5~6.0x"
      : oddsMode === "target"
        ? `目標 ${targetOdds.toFixed(1)}x`
        : `區間 ${rangeMin.toFixed(1)}~${rangeMax.toFixed(1)}x`

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="space-y-3"
    >
      {/* Mobile-Only Sticky Filter Summary Bar (Prevents long vertical scroll on mobile) */}
      <div className="lg:hidden sticky top-[6.5rem] sm:top-28 z-30 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-2.5 shadow-xs">
        <div className="flex items-center justify-between gap-2 text-xs">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 font-medium">
                {modeSummaryTitle}
              </span>
              <span className="font-mono text-slate-600 dark:text-slate-300">
                {minLegs === maxLegs ? `${minLegs} 關` : `${minLegs}~${maxLegs} 關`}
              </span>
              {preferSteam && (
                <span className="text-emerald-600 dark:text-emerald-400 font-medium">· 偏好跳水</span>
              )}
            </div>
            <div className="text-slate-500 dark:text-slate-400 truncate mt-1">
              排序：{rankingMode === "WIN_PROBABILITY" ? "估計聯合機率優先" : "估計 EV 優先"} ·{" "}
              {crossSport ? "全聯盟跨界混串" : `指定 ${selectedAlliances.length} 聯盟`}
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() => setMobileFilterExpanded((prev) => !prev)}
              aria-expanded={mobileFilterExpanded}
              aria-controls="parlay-filters"
              className="px-2.5 py-1.5 min-h-[44px] rounded-lg bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs font-medium text-slate-700 dark:text-slate-200 flex items-center gap-1 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            >
              <span>{mobileFilterExpanded ? "收起條件" : "調整條件"}</span>
              {mobileFilterExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {!mobileFilterExpanded && (
              <Button
                variant="default"
                size="sm"
                onClick={handleSearch}
                disabled={searching}
                aria-busy={searching}
                className="text-xs px-3 py-1.5 min-h-[44px] gap-1 cursor-pointer"
              >
                {searching ? (
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" aria-hidden="true" />
                ) : (
                  <Search className="w-3.5 h-3.5" />
                )}
                <span>{searching ? "搜尋中" : "搜尋"}</span>
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Main 12-Column Split Workbench */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 items-start">
        {/* LEFT COLUMN: Sticky Parameter Control Panel with independent hover scroll & pinned bottom Search button */}
        <div
          id="parlay-filters"
          className={`max-h-[calc(100dvh-16rem)] lg:max-h-[calc(100dvh-8rem)] lg:col-span-4 lg:sticky lg:top-28 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs overflow-hidden ${
            mobileFilterExpanded ? "flex flex-col" : "hidden lg:flex lg:flex-col"
          }`}
        >
          {/* Compact Panel Header (Pinned Top) */}
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800/90 flex items-center justify-between gap-2 shrink-0">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 tracking-tight">
              <Flame className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>串關組合研究台</span>
            </h2>
            <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
              {searchRangeLabel}
            </span>
          </div>

          {/* Independently Scrollable Controls Body (Scrolls on mouse hover when content is tall) */}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain divide-y divide-slate-100 dark:divide-slate-800/90">
            {/* Section 1: Odds Mode Selector (Preserving icons, subtitles, and Slider!) */}
            <div className="p-2.5 space-y-2">
              <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                1. 策略風格與目標倍率
              </div>

              <div className="grid grid-cols-3 gap-1.5 bg-slate-100/80 dark:bg-slate-950 p-1 rounded-xl border border-slate-200/70 dark:border-slate-800 text-xs">
                <button
                  type="button"
                  onClick={() => selectMode("banker")}
                  aria-pressed={oddsMode === "banker"}
                  className={`py-2 px-2 min-h-[44px] rounded-lg font-medium transition-colors flex flex-col items-center gap-1 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                    oddsMode === "banker"
                      ? "bg-white dark:bg-slate-800 text-emerald-700 dark:text-emerald-400 shadow-xs border border-slate-200/80 dark:border-slate-700"
                      : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <Shield className="w-3.5 h-3.5" />
                    <span>銀行家</span>
                  </div>
                  <span className="text-xs font-mono opacity-80">1.5~6x</span>
                </button>

                <button
                  type="button"
                  onClick={() => selectMode("target")}
                  aria-pressed={oddsMode === "target"}
                  className={`py-2 px-2 min-h-[44px] rounded-lg font-medium transition-colors flex flex-col items-center gap-1 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                    oddsMode === "target"
                      ? "bg-white dark:bg-slate-800 text-emerald-700 dark:text-emerald-400 shadow-xs border border-slate-200/80 dark:border-slate-700"
                      : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <Target className="w-3.5 h-3.5" />
                    <span>指定倍率</span>
                  </div>
                  <span className="text-xs font-mono opacity-80">±20%</span>
                </button>

                <button
                  type="button"
                  onClick={() => selectMode("range")}
                  aria-pressed={oddsMode === "range"}
                  className={`py-2 px-2 min-h-[44px] rounded-lg font-medium transition-colors flex flex-col items-center gap-1 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                    oddsMode === "range"
                      ? "bg-white dark:bg-slate-800 text-emerald-700 dark:text-emerald-400 shadow-xs border border-slate-200/80 dark:border-slate-700"
                      : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <Sliders className="w-3.5 h-3.5" />
                    <span>自訂區間</span>
                  </div>
                  <span className="text-xs font-mono opacity-80">6 區間</span>
                </button>
              </div>

              {oddsMode === "banker" && (
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 pt-0.5">
                  <span>低倍率穩健搜尋範圍</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">1.5x ~ 6.0x (1~3 關)</span>
                </div>
              )}

              {oddsMode === "target" && (
                <div className="space-y-2 pt-1">
                  <Slider
                    min={1.5}
                    max={500}
                    step={0.5}
                    value={targetOdds}
                    onChange={setTargetOdds}
                    label="目標總倍率 (x)"
                    displayValue={`${targetOdds.toFixed(1)} 倍`}
                  />
                  <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span>容許浮動 ±{(tolerance * 100).toFixed(0)}%</span>
                    <span className="font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {(targetOdds * (1 - tolerance)).toFixed(1)}x ~ {(targetOdds * (1 + tolerance)).toFixed(1)}x
                    </span>
                  </div>
                </div>
              )}

              {oddsMode === "range" && (
                <div className="space-y-2 pt-1">
                  <div className="grid grid-cols-2 gap-1.5">
                    {rangePresets.map((preset, pIdx) => {
                      const isSelected = rangeMin === preset.min && rangeMax === preset.max
                      return (
                        <button
                          key={pIdx}
                          type="button"
                          onClick={() => applyPreset(preset)}
                          aria-pressed={isSelected}
                          className={`p-2 min-h-[44px] rounded-lg border text-left text-xs transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                            isSelected
                              ? "border-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/30 text-emerald-800 dark:text-emerald-300 font-medium"
                              : "border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 text-slate-700 dark:text-slate-300 hover:border-slate-300"
                          }`}
                        >
                          {preset.label}
                        </button>
                      )
                    })}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 flex justify-between">
                    <span>目前搜尋區間</span>
                    <span className="font-mono text-slate-700 dark:text-slate-300">
                      {rangeMin.toFixed(1)}x ~ {rangeMax.toFixed(1)}x
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Section 2: Compact Horizontal Ranking, Separate Min/Max Legs & Quality Gate */}
            <div className="p-2.5 space-y-2 text-xs">
              <div className="font-semibold text-slate-800 dark:text-slate-200">
                2. 候選排序與情報門檻
              </div>

              <div className="space-y-2">
                <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2">
                  <label htmlFor="candidate-ranking" className="text-slate-600 dark:text-slate-400">
                    候選排序
                  </label>
                  <select
                    id="candidate-ranking"
                    value={rankingMode}
                    onChange={(e) => setRankingMode(e.target.value as RankingMode)}
                    className="w-full min-w-0 min-h-[44px] bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 cursor-pointer font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                  >
                    <option value="WIN_PROBABILITY">估計聯合機率優先（未驗證）</option>
                    <option value="VALUE">估計 EV 優先（來源見詳情）</option>
                  </select>
                </div>

                {/* Separate Min & Max Legs Dropdowns on a single compact row */}
                <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2">
                  <label htmlFor="minimum-legs" className="text-slate-600 dark:text-slate-400">
                    過關腿數
                  </label>
                  <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-1.5 w-full">
                    <select
                      id="minimum-legs"
                      aria-label="最少過關關數"
                      value={minLegs}
                      onChange={(e) => {
                        const next = Number(e.target.value)
                        setMinLegs(next)
                        setMinLegsCustomized(true)
                        if (maxLegs < next) setMaxLegs(next)
                      }}
                      className="w-full min-w-0 min-h-[44px] bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-2 py-1.5 text-xs text-slate-800 dark:text-slate-200 font-mono cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                    >
                      <option value={1}>最少 1 關</option>
                      <option value={2}>最少 2 關</option>
                      <option value={3}>最少 3 關</option>
                      <option value={4}>最少 4 關</option>
                    </select>
                    <span className="text-slate-400 text-center">~</span>
                    <select
                      aria-label="最多過關關數"
                      value={maxLegs}
                      onChange={(e) => {
                        const next = Number(e.target.value)
                        setMaxLegs(next)
                        if (minLegs > next) {
                          setMinLegs(next)
                          setMinLegsCustomized(true)
                        }
                      }}
                      className="w-full min-w-0 min-h-[44px] bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-2 py-1.5 text-xs text-slate-800 dark:text-slate-200 font-mono cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                    >
                      <option value={1}>最多 1 關</option>
                      <option value={2}>最多 2 關</option>
                      <option value={3}>最多 3 關</option>
                      <option value={4}>最多 4 關</option>
                      <option value={5}>最多 5 關</option>
                      <option value={6}>最多 6 關</option>
                      <option value={8}>最多 8 關</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2">
                  <label htmlFor="candidate-signal-filter" className="text-slate-600 dark:text-slate-400">
                    情報門檻
                  </label>
                  <select
                    id="candidate-signal-filter"
                    value={signalFilter}
                    onChange={(e) => setSignalFilter(e.target.value)}
                    className="w-full min-w-0 min-h-[44px] bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                  >
                    <option value="value_only">探索候選（含低賠率／高估計機率）</option>
                    <option value="credible_value_only">合格來源支持的正 EV</option>
                    <option value="normal">標準 (排除無情報關卡)</option>
                    <option value="strict">嚴格 (2+ 獨立情報支持)</option>
                    <option value="wild">全量 (容納所有可能盤口)</option>
                  </select>
                </div>
                <p className="pl-[4.25rem] text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                  探索候選或高估計機率不等於正 EV；來源與驗證狀態請看「分析依據」。
                </p>
              </div>
            </div>

            {/* Section 3: Cross-Sport & Line Movement Signal Checkboxes */}
            <div className="p-2.5 space-y-1 text-xs">
              <div className="font-semibold text-slate-800 dark:text-slate-200">
                3. 跨界混串與賠率跳動訊號
              </div>

              <label className="flex items-center gap-2 min-h-8 text-slate-700 dark:text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={crossSport}
                  onChange={(e) => setCrossSport(e.target.checked)}
                  className="rounded text-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-500 cursor-pointer"
                />
                <span>啟用全聯盟跨界混串 (NBA、MLB、足球混合)</span>
              </label>

              {!crossSport && (
                <div className="flex flex-wrap gap-1.5 pl-5 pt-0.5">
                  {allianceOptions.map((a) => {
                    const isSelected = selectedAlliances.includes(a.id)
                    return (
                      <button
                        key={a.id}
                        type="button"
                        aria-pressed={isSelected}
                        onClick={() => {
                          setSelectedAlliances((prev) =>
                            isSelected ? prev.filter((id) => id !== a.id) : [...prev, a.id]
                          )
                        }}
                        className={`px-2 py-1 min-h-[44px] rounded-md text-xs font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                          isSelected
                            ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                            : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"
                        }`}
                      >
                        {a.label}
                      </button>
                    )
                  })}
                </div>
              )}

              <label className="flex items-center gap-2 min-h-8 text-slate-700 dark:text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferSteam}
                  onChange={(e) => setPreferSteam(e.target.checked)}
                  className="rounded text-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-500 cursor-pointer"
                />
                <span className={preferSteam ? "text-emerald-700 dark:text-emerald-400 font-medium" : ""}>
                  排序偏好賠率跳動訊號（順勢跳水優先）
                </span>
              </label>

              <label className="flex items-center gap-2 min-h-8 text-slate-700 dark:text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={excludeTraps}
                  onChange={(e) => setExcludeTraps(e.target.checked)}
                  className="rounded text-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-500 cursor-pointer"
                />
                <span>排除標記為逆向升水的候選</span>
              </label>
            </div>
          </div>

          {/* Section 4: Sticky Pinned Bottom Search Action Button */}
          <div className="p-2.5 bg-slate-50/90 dark:bg-slate-950/80 border-t border-slate-200/80 dark:border-slate-800 shrink-0">
            <Button
              variant="default"
              size="lg"
              onClick={handleSearch}
              disabled={searching}
              className="w-full min-h-[44px] py-2 font-medium text-sm gap-2 cursor-pointer"
            >
              {searching ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>{rankingMode === "WIN_PROBABILITY" ? "正在搜尋高估計機率候選..." : "正在搜尋高估計 EV 候選..."}</span>
                </>
              ) : (
                <span>搜尋 {searchRangeLabel} 候選組合</span>
              )}
            </Button>
          </div>
        </div>

        {/* RIGHT COLUMN: Live Results Stream & Heatmap (8 cols on Desktop) */}
        <div className="lg:col-span-8 space-y-4">
          {error && (
            <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {!hasSearched ? (
            <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 text-center space-y-3 shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mx-auto">
                <Flame className="w-5 h-5" />
              </div>
              <div className="space-y-1 max-w-md mx-auto">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  準備搜尋 {searchRangeLabel} 串關組合
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  於左側設定目標倍率、過關腿數與情報門檻後點擊「搜尋候選組合」，右側將即時列出符合條件的簽單與期望值分佈。
                </p>
              </div>
              <div className="pt-1">
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleSearch}
                  disabled={searching}
                  className="text-xs px-5 py-2 cursor-pointer"
                >
                  立即搜尋 {searchRangeLabel} 候選組合
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Tier Switcher Bar + Inline Search Telemetry */}
              <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-200 dark:border-slate-800">
                <div className="flex items-center gap-1.5 overflow-x-auto">
                  <button
                    onClick={() => setActiveTier("high_consensus")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                      activeTier === "high_consensus"
                        ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
                        : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                    }`}
                  >
                    <Shield className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                    <span>高情報支持</span>
                    <span className="font-mono tabular-nums text-xs text-slate-500">
                      ({tiers.high_consensus.length})
                    </span>
                  </button>

                  <button
                    onClick={() => setActiveTier("aggressive")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                      activeTier === "aggressive"
                        ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
                        : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                    }`}
                  >
                    <TrendingUp className="w-3.5 h-3.5 text-slate-400" />
                    <span>積極進攻</span>
                    <span className="font-mono tabular-nums text-xs text-slate-500">
                      ({tiers.aggressive.length})
                    </span>
                  </button>

                  <button
                    onClick={() => setActiveTier("moonshot")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                      activeTier === "moonshot"
                        ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
                        : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                    }`}
                  >
                    <Zap className="w-3.5 h-3.5 text-slate-400" />
                    <span>高倍衝月</span>
                    <span className="font-mono tabular-nums text-xs text-slate-500">
                      ({tiers.moonshot.length})
                    </span>
                  </button>
                </div>

                {!searching && searchPerformance && (
                  <div className="flex flex-wrap gap-x-2.5 gap-y-1 text-xs text-slate-400 dark:text-slate-500 font-mono tabular-nums">
                    {preferSteam && <span className="text-emerald-600 dark:text-emerald-400">跳水訊號加權</span>}
                    <span>·</span>
                    <span>總耗時 {searchPerformance.total_ms.toFixed(0)} ms</span>
                  </div>
                )}
              </div>

              {!searching && !searchComplete && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                  搜尋預算已用完；目前候選尚未保證涵蓋完整搜尋空間。
                </div>
              )}

              {/* Results Cards Grid */}
              {searching ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                  {[1, 2, 3, 4].map((i) => (
                    <Skeleton key={i} className="h-52" />
                  ))}
                </div>
              ) : currentList.length === 0 ? (
                <Card className="text-center py-10">
                  <CardContent className="space-y-2">
                    <h4 className="font-medium text-slate-800 dark:text-slate-200 text-sm">此分類暫無符合條件的組合</h4>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      可調整搜尋範圍或查看候選拒絕原因；若缺乏合格資料，先不產生組合是正常結果。
                    </p>
                    {searchDiagnostics && (
                      <div className="mx-auto max-w-2xl rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50 p-3 text-left text-xs text-slate-600 dark:text-slate-400 space-y-1">
                        <div>
                          台彩候選 {searchDiagnostics.normalized_option_count} · 通過賽事／時效檢查 {searchDiagnostics.ready_option_count} · 通過目前情報篩選 {searchDiagnostics.quality_option_count}
                        </div>
                        {searchDiagnostics.quality_filtered_out_option_count > 0 && (
                          <div>有 {searchDiagnostics.quality_filtered_out_option_count} 筆通過基本檢查的候選，未通過目前情報篩選。</div>
                        )}
                        <div>
                          已檢查 {searchDiagnostics.checked_combinations} 組 · 符合賠率區間 {searchDiagnostics.odds_matching_combinations} 組
                        </div>
                        {Object.entries(searchDiagnostics.excluded_option_reasons).length > 0 && (
                          <ul className="list-disc pl-4">
                            {Object.entries(searchDiagnostics.excluded_option_reasons).map(([reason, count]) => (
                              <li key={reason}>{SEARCH_REASON_LABELS[reason] || reason.replaceAll("_", " ").toLowerCase()}：{count}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 items-start">
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

              {/* EV Density Heatmap Area Chart below results */}
              {allTiersList.length > 0 && (
                <EVHeatmapChart parlays={allTiersList} targetOdds={targetOdds} />
              )}
            </div>
          )}
        </div>
      </div>

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
