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
import { Flame, Sparkles, ChevronRight, CheckCircle2, AlertCircle, Shield, Target, Sliders, Layers } from "lucide-react"

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
    { id: "1", label: "🏀 NBA" },
    { id: "3", label: "⚾ MLB" },
    { id: "4", label: "⚽ 足球" },
    { id: "6", label: "⚾ 中職" },
    { id: "7", label: "⚾ 日職" },
    { id: "9", label: "🏈 NFL" },
  ]

  const rangePresets = [
    { label: "🛡️ 銀行家模式 (1.8x ~ 4.0x)", min: 1.8, max: 4.0, target: 2.5, minL: 2, maxL: 3, filter: "value_only" },
    { label: "📈 穩中求勝 (4.0x ~ 10.0x)", min: 4.0, max: 10.0, target: 6.0, minL: 2, maxL: 4, filter: "value_only" },
    { label: "🔥 瘋狗起步 (10x ~ 25x)", min: 10.0, max: 25.0, target: 15.0, minL: 3, maxL: 5, filter: "normal" },
    { label: "🚀 瘋狗狂暴 (25x ~ 75x)", min: 25.0, max: 75.0, target: 40.0, minL: 4, maxL: 6, filter: "normal" },
    { label: "🌕 極限登月 (75x ~ 200x)", min: 75.0, max: 200.0, target: 120.0, minL: 5, maxL: 7, filter: "normal" },
    { label: "🛸 超級巨星 (200x ~ 500x)", min: 200.0, max: 500.0, target: 300.0, minL: 6, maxL: 8, filter: "wild" },
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
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      {/* Control Panel Card */}
      <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/90 shadow-xl backdrop-blur">
        <CardHeader className="pb-4 border-b border-slate-200 dark:border-slate-800/80">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <Flame className="w-5 h-5 text-amber-500" />
              🔥 瘋狗看盤決策台 (1.5x ~ 500x 串關組單 & Signal Hub)
            </CardTitle>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              設定目標總賠率，系統透過三大訊號自動搜尋最佳串關組合
            </span>
          </div>
        </CardHeader>

        <CardContent className="space-y-6 pt-5">
          {/* STEP 1: Odds Mode Selector Tabs */}
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <span>① 今天你想玩幾倍？（倍率與策略風格）</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <button
                type="button"
                onClick={() => selectMode("banker")}
                className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
                  oddsMode === "banker"
                    ? "border-emerald-500 bg-emerald-500/10 shadow-sm"
                    : "border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 font-bold text-sm text-slate-900 dark:text-slate-100">
                  <Shield className="w-4 h-4 text-emerald-500" />
                  🛡️ 穩健銀行家模式
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                  1.5x ~ 6x 高勝率 · 2~3關定海神針
                </div>
              </button>

              <button
                type="button"
                onClick={() => selectMode("target")}
                className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
                  oddsMode === "target"
                    ? "border-amber-500 bg-amber-500/10 shadow-sm"
                    : "border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 font-bold text-sm text-slate-900 dark:text-slate-100">
                  <Target className="w-4 h-4 text-amber-500" />
                  🎯 指定目標倍率
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                  自由設定目標賠率 (Target ±20%)
                </div>
              </button>

              <button
                type="button"
                onClick={() => selectMode("range")}
                className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
                  oddsMode === "range"
                    ? "border-sky-500 bg-sky-500/10 shadow-sm"
                    : "border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 hover:border-slate-300 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 font-bold text-sm text-slate-900 dark:text-slate-100">
                  <Sliders className="w-4 h-4 text-sky-500" />
                  📊 自由賠率區間
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                  6 大快捷區間 · 自由滑桿
                </div>
              </button>
            </div>

            {/* Banker Mode Explanation Banner */}
            {oddsMode === "banker" && (
              <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-800 dark:text-emerald-300 text-xs leading-relaxed space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <Shield className="w-4 h-4" />
                  穩健銀行家模式 (Banker Mode) 核心策略：
                </div>
                <p>
                  鎖定 2~3 關高勝率與正期望值 (+EV) 定海神針關卡，總倍率約 1.5x ~ 6.0x。兼具極高勝率與低風險，小額派彩全數撥入【保留儲備池】，細水長流穩健壯大每週戰力！
                </p>
                <div className="text-[11px] text-emerald-600 dark:text-emerald-400 pt-1 font-mono font-semibold">
                  鎖定搜尋賠率：1.5x ~ 6.0x (限定 2~3 關高勝率)
                </div>
              </div>
            )}

            {/* Target Mode Controls */}
            {oddsMode === "target" && (
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800 space-y-3">
                <Slider
                  min={1.5}
                  max={500}
                  step={0.5}
                  value={targetOdds}
                  onChange={setTargetOdds}
                  label="🎯 目標總倍率 (x)"
                  displayValue={`${targetOdds.toFixed(1)} 倍`}
                />
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 pt-1">
                  <span>容許浮動範圍：±{(tolerance * 100).toFixed(0)}%</span>
                  <span className="font-mono text-amber-500 font-bold">
                    搜尋區間：{(targetOdds * (1 - tolerance)).toFixed(1)}x ~ {(targetOdds * (1 + tolerance)).toFixed(1)}x
                  </span>
                </div>
              </div>
            )}

            {/* Range Mode Presets */}
            {oddsMode === "range" && (
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800 space-y-3">
                <div className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
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
                        className={`p-2.5 rounded-lg border text-left text-xs transition-all cursor-pointer font-medium ${
                          isSelected
                            ? "border-sky-500 bg-sky-500/15 text-sky-600 dark:text-sky-300 font-bold shadow-sm"
                            : "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-400 hover:border-slate-300"
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
          <div className="space-y-3 pt-4 border-t border-slate-200 dark:border-slate-800/80">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <span>② 選擇混串賽事與情報過濾</span>
            </div>

            {/* Cross-sport switch */}
            <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <label className="flex items-center gap-2 text-xs font-bold text-slate-800 dark:text-slate-200 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={crossSport}
                    onChange={(e) => setCrossSport(e.target.checked)}
                    className="rounded text-emerald-500 focus:ring-0 w-4 h-4 cursor-pointer"
                  />
                  <span>☑ 全部跨界混串 (跨界混合 NBA + MLB + 足球 + NFL + 職棒)</span>
                </label>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 ml-6">
                  {crossSport
                    ? "已啟用跨界混串！系統將跨籃球、棒球、足球、美足同時尋找最佳倍率組合。"
                    : "已切換為指定聯盟過濾模式。"}
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
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                          isSelected
                            ? "bg-emerald-600 text-white"
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
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
              {/* Legs Selection */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  過關腿數 (Legs)
                </label>
                <div className="flex items-center gap-2">
                  <select
                    value={minLegs}
                    onChange={(e) => setMinLegs(Number(e.target.value))}
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-800 dark:text-slate-200 font-mono w-full cursor-pointer"
                  >
                    <option value={2}>最少 2 關</option>
                    <option value={3}>最少 3 關</option>
                    <option value={4}>最少 4 關</option>
                  </select>
                  <span className="text-slate-400 text-xs">至</span>
                  <select
                    value={maxLegs}
                    onChange={(e) => setMaxLegs(Number(e.target.value))}
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-800 dark:text-slate-200 font-mono w-full cursor-pointer"
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
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  🛡️ 外部情報品質門檻
                </label>
                <select
                  value={signalFilter}
                  onChange={(e) => setSignalFilter(e.target.value)}
                  className="bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-800 dark:text-slate-200 w-full cursor-pointer"
                >
                  <option value="value_only">value_only (價值優先: +EV 正期望值)</option>
                  <option value="normal">normal (標準: 排除無情報關卡)</option>
                  <option value="strict">strict (嚴格: 僅限 2+ 獨立情報支持)</option>
                  <option value="wild">wild (狂野: 容納所有可能盤口)</option>
                </select>
              </div>

              {/* Smart Filters */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  進階風控篩選
                </label>
                <div className="flex flex-col gap-1.5 pt-0.5">
                  <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={excludeTraps}
                      onChange={(e) => setExcludeTraps(e.target.checked)}
                      className="rounded text-emerald-500 focus:ring-0 cursor-pointer"
                    />
                    <span>過濾莊家誘盤 (排除逆向升水)</span>
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={preferSteam}
                      onChange={(e) => setPreferSteam(e.target.checked)}
                      className="rounded text-emerald-500 focus:ring-0 cursor-pointer"
                    />
                    <span>優先推薦大戶跳水 (資金加權)</span>
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Search Trigger Button */}
          <div className="pt-3 flex justify-end">
            <Button
              variant="default"
              size="lg"
              onClick={handleSearch}
              disabled={searching}
              className="w-full md:w-auto px-8 py-2.5 font-bold text-sm bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-md gap-2 cursor-pointer"
            >
              {searching ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Signal Hub 正在運算最佳期望值組合...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 text-emerald-200" />
                  <span>搜尋 {targetOdds.toFixed(1)}x 串關組合</span>
                </>
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
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-600 dark:text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Section */}
      {hasSearched && (
        <div className="space-y-4">
          {/* Tier Switcher Tabs */}
          <div className="flex border-b border-slate-200 dark:border-slate-800 gap-2 pb-2 overflow-x-auto">
            <button
              onClick={() => setActiveTier("high_consensus")}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTier === "high_consensus"
                  ? "bg-emerald-600/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/40"
                  : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <span>🥇 高共識推薦</span>
              <span className="font-mono tabular-nums bg-white dark:bg-slate-800 px-1.5 py-0.2 rounded text-[10px]">
                {tiers.high_consensus.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTier("aggressive")}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTier === "aggressive"
                  ? "bg-amber-600/20 text-amber-600 dark:text-amber-400 border border-amber-500/40"
                  : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <span>🥈 積極進攻</span>
              <span className="font-mono tabular-nums bg-white dark:bg-slate-800 px-1.5 py-0.2 rounded text-[10px]">
                {tiers.aggressive.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTier("moonshot")}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTier === "moonshot"
                  ? "bg-purple-600/20 text-purple-600 dark:text-purple-400 border border-purple-500/40"
                  : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <span>🚀 瘋狗衝月</span>
              <span className="font-mono tabular-nums bg-white dark:bg-slate-800 px-1.5 py-0.2 rounded text-[10px]">
                {tiers.moonshot.length}
              </span>
            </button>
          </div>

          {/* Results List */}
          {searching ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-64" />
              ))}
            </div>
          ) : currentList.length === 0 ? (
            <Card className="text-center py-12">
              <CardContent className="space-y-2">
                <div className="text-3xl">🔍</div>
                <h4 className="font-bold text-slate-800 dark:text-slate-200">此梯次目前暫無符合條件的組合</h4>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  可以嘗試調整目標賠率（如改為 1.8x ~ 4.0x 穩健銀行家模式）或放寬情報門檻重試。
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <AnimatePresence>
                {currentList.map((parlay, idx) => (
                  <motion.div
                    key={parlay.parlay_id || idx}
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.25 }}
                    className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur p-5 shadow-lg hover:border-emerald-500/40 dark:hover:border-slate-700 transition-all space-y-4"
                  >
                    {/* Header */}
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-slate-900 dark:text-slate-100 text-base">
                            {parlay.parlay_name || `組合 #${idx + 1}`}
                          </span>
                          <Badge variant="blue" className="text-[10px] font-mono">
                            {parlay.legs.length} 串 1
                          </Badge>
                          {parlay.sharp_badge && (
                            <Badge variant={parlay.is_positive_ev ? "green" : "secondary"} className="text-[10px]">
                              {parlay.sharp_badge}
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex items-center gap-2 flex-wrap">
                          <span>各關賠率連乘</span>
                          {parlay.joint_probability ? (
                            <>
                              <span>·</span>
                              <span className="text-sky-600 dark:text-sky-400 font-semibold font-mono">
                                聯合預估勝率 {(parlay.joint_probability * 100).toFixed(1)}%
                              </span>
                            </>
                          ) : null}
                          <span>·</span>
                          <span className="text-slate-400">獨立賽事檢驗合格</span>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        <div className="text-2xl font-black text-amber-500 dark:text-amber-400 font-mono tabular-nums tracking-tight">
                          {parlay.total_odds.toFixed(2)}x
                        </div>
                        {(() => {
                          const evVal = parlay.parlay_ev_pct ?? (parlay.expected_value ? parlay.expected_value * 100 : null)
                          if (evVal === null || evVal === undefined) return null
                          const parlayHasSynth = parlay.legs?.some((l) => l.is_market_synthetic || (l.signal_evidence || {}).is_market_synthetic)
                          const isPos = !parlayHasSynth && evVal > 0
                          return (
                            <div
                              className={`text-xs font-bold tabular-nums font-mono flex items-center justify-end gap-1 ${
                                isPos ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"
                              }`}
                            >
                              <span>{isPos ? "⚡ +EV" : (parlayHasSynth ? "EV (模擬)" : "EV")}</span>
                              <span>{isPos ? `+${evVal.toFixed(1)}%` : `${evVal.toFixed(1)}%`}</span>
                            </div>
                          )
                        })()}
                      </div>
                    </div>

                    {/* Legs list inside parlay (with cleanLeagueName applied & leg-level EV displayed!) */}
                    <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-slate-800/80">
                      {parlay.legs.map((leg, lIdx) => {
                        const isSynth = Boolean(leg.is_market_synthetic || (leg.signal_evidence || {}).is_market_synthetic)
                        const legEv = leg.expected_value_pct ?? (leg.expected_value ? leg.expected_value * 100 : null)
                        const legProb = leg.consensus_probability ? (leg.consensus_probability * 100).toFixed(0) : null
                        const isPos = Boolean(!isSynth && (leg.is_positive_ev || (legEv !== null && legEv > 0)))

                        return (
                          <div
                            key={lIdx}
                            className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800/60 flex items-center justify-between text-xs"
                          >
                            <div className="space-y-1">
                              <div className="font-medium text-slate-800 dark:text-slate-300">
                                <span className="font-semibold text-slate-500 mr-1.5">
                                  {cleanLeagueName(leg.display_league || leg.league || leg.sport)}
                                </span>
                                {leg.away_team} vs {leg.home_team}
                              </div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <div className="text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1.5">
                                  <span className="text-[11px] text-slate-500 dark:text-slate-400">[{leg.market}]</span>
                                  <span>{leg.selection}</span>
                                </div>

                                {/* Leg EV Badge */}
                                {legEv !== null && (
                                  <span
                                    className={`text-[10px] px-1.5 py-0.2 rounded font-mono font-bold ${
                                      isPos
                                        ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                                        : "bg-slate-200 dark:bg-slate-800 text-slate-500"
                                    }`}
                                  >
                                    {isPos ? `⚡ +EV +${legEv.toFixed(1)}%` : (isSynth ? `EV ${legEv.toFixed(1)}% (模擬)` : `EV ${legEv.toFixed(1)}%`)}
                                  </span>
                                )}

                                {/* Leg Prob */}
                                {legProb && (
                                  <span className="text-[10px] text-sky-600 dark:text-sky-400 font-mono">
                                    勝率 {legProb}%
                                  </span>
                                )}

                                {/* Crowd desc */}
                                {leg.crowd_desc && (
                                  <span className="text-[10px] text-amber-600 dark:text-amber-400">
                                    {leg.crowd_desc}
                                  </span>
                                )}
                              </div>
                            </div>

                            <div className="text-right pl-3 shrink-0">
                              <span className="font-bold font-mono tabular-nums text-amber-500 dark:text-amber-400 text-sm">
                                {leg.taiwan_odds?.toFixed(2)}x
                              </span>
                            </div>
                          </div>
                        )
                      })}
                    </div>

                    {/* Actions Bar */}
                    <div className="pt-2 border-t border-slate-200 dark:border-slate-800/80 flex items-center justify-between gap-3">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedParlayForEvidence(parlay)}
                        className="text-xs gap-1.5 text-slate-600 dark:text-slate-300 cursor-pointer"
                      >
                        <span>📑 Why 證據情報</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </Button>

                      <Button
                        variant="success"
                        size="sm"
                        onClick={() => setSelectedParlayForBet(parlay)}
                        className="text-xs font-bold px-4 gap-1.5 cursor-pointer"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>確認下注</span>
                      </Button>
                    </div>
                  </motion.div>
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
