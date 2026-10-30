import React, { useState } from "react"
import { api, type SearchParlaysParams } from "@/services/api"
import type { ParlayRecommendation, WalletStatus } from "@/types"
import { Slider } from "@/components/ui/Slider"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { Skeleton } from "@/components/ui/Skeleton"
import { EvidenceDrawer } from "@/components/EvidenceDrawer"
import { BetModal } from "@/components/BetModal"
import { Flame, Sparkles, Filter, ShieldCheck, ChevronRight, CheckCircle2, AlertCircle } from "lucide-react"

interface ParlayViewProps {
  wallet: WalletStatus | null
  onWalletUpdate: (wallet: WalletStatus) => void
}

export const ParlayView: React.FC<ParlayViewProps> = ({ wallet, onWalletUpdate }) => {
  const [targetOdds, setTargetOdds] = useState<number>(20)
  const [minLegs, setMinLegs] = useState<number>(2)
  const [maxLegs, setMaxLegs] = useState<number>(5)
  const [signalFilter, setSignalFilter] = useState<string>("normal")
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

  const presetOdds = [10, 20, 50, 100, 250, 500]

  async function handleSearch() {
    setSearching(true)
    setError(null)
    setHasSearched(true)

    try {
      const res = await api.searchParlays({
        target_odds: targetOdds,
        tolerance: 0.35,
        min_legs: minLegs,
        max_legs: maxLegs,
        signal_filter: signalFilter,
        exclude_traps: excludeTraps,
        prefer_steam: preferSteam,
        search_budget: 60000,
      })

      setTiers(res.tiers)
      // Auto-select tier with results
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

  return (
    <div className="space-y-6">
      {/* Control Panel Card */}
      <Card className="border-slate-800 bg-slate-900/90 shadow-xl">
        <CardHeader className="pb-4 border-b border-slate-800/80">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Flame className="w-5 h-5 text-amber-500" />
              瘋狗看盤搜尋引擎 (10~500倍 目標串關)
            </CardTitle>
            <span className="text-xs text-slate-400">
              即時連乘台彩開盤賠率 · 嚴格過濾同場衝突
            </span>
          </div>
        </CardHeader>

        <CardContent className="space-y-5 pt-4">
          {/* Target Multiplier Slider */}
          <div className="space-y-3">
            <Slider
              min={5}
              max={500}
              step={5}
              value={targetOdds}
              onChange={setTargetOdds}
              label="🎯 目標目標賠率"
              displayValue={`${targetOdds} 倍`}
            />

            {/* Presets */}
            <div className="flex flex-wrap gap-1.5 pt-1">
              {presetOdds.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setTargetOdds(p)}
                  className={`px-3 py-1 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
                    targetOdds === p
                      ? "bg-amber-600 text-white shadow-sm"
                      : "bg-slate-800/80 text-slate-400 hover:text-slate-200 hover:bg-slate-700"
                  }`}
                >
                  {p}x
                </button>
              ))}
            </div>
          </div>

          {/* Legs & Filters Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-slate-800/80">
            {/* Legs Range */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">過關腿數 (Legs)</label>
              <div className="flex items-center gap-2">
                <select
                  value={minLegs}
                  onChange={(e) => setMinLegs(Number(e.target.value))}
                  className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono w-full cursor-pointer"
                >
                  <option value={2}>最少 2 關</option>
                  <option value={3}>最少 3 關</option>
                  <option value={4}>最少 4 關</option>
                </select>
                <span className="text-slate-500 text-xs">至</span>
                <select
                  value={maxLegs}
                  onChange={(e) => setMaxLegs(Number(e.target.value))}
                  className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono w-full cursor-pointer"
                >
                  <option value={3}>最多 3 關</option>
                  <option value={4}>最多 4 關</option>
                  <option value={5}>最多 5 關</option>
                  <option value={6}>最多 6 關</option>
                  <option value={8}>最多 8 關</option>
                </select>
              </div>
            </div>

            {/* Quality Filter */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">情報品質門檻</label>
              <select
                value={signalFilter}
                onChange={(e) => setSignalFilter(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 w-full cursor-pointer"
              >
                <option value="normal">標準 (排除無情報關卡)</option>
                <option value="value_only">價值優先 (正期望值 +EV)</option>
                <option value="strict">嚴格 (2+ 獨立情報支持)</option>
                <option value="wild">狂野 (容納所有可能盤口)</option>
              </select>
            </div>

            {/* Smart Filters */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">進階風控篩選</label>
              <div className="flex flex-col gap-1.5 pt-0.5">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={excludeTraps}
                    onChange={(e) => setExcludeTraps(e.target.checked)}
                    className="rounded bg-slate-950 border-slate-700 text-emerald-500 focus:ring-0"
                  />
                  <span>過濾莊家誘盤 (排除逆向升水)</span>
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={preferSteam}
                    onChange={(e) => setPreferSteam(e.target.checked)}
                    className="rounded bg-slate-950 border-slate-700 text-emerald-500 focus:ring-0"
                  />
                  <span>優先推薦大戶跳水 (資金加權)</span>
                </label>
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
              className="w-full md:w-auto px-8 py-2.5 font-bold text-sm bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-md gap-2"
            >
              {searching ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Signal Hub 正在高速搜尋運算...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 text-emerald-200" />
                  <span>搜尋 {targetOdds}x 串關組合</span>
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Error alert */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Section */}
      {hasSearched && (
        <div className="space-y-4">
          {/* Tier Switcher Tabs */}
          <div className="flex border-b border-slate-800 gap-2 pb-2 overflow-x-auto">
            <button
              onClick={() => setActiveTier("high_consensus")}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTier === "high_consensus"
                  ? "bg-emerald-600/30 text-emerald-400 border border-emerald-500/40"
                  : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>🥇 高共識推薦</span>
              <span className="font-mono bg-slate-800 px-1.5 py-0.2 rounded text-[10px]">
                {tiers.high_consensus.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTier("aggressive")}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTier === "aggressive"
                  ? "bg-amber-600/30 text-amber-400 border border-amber-500/40"
                  : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>🥈 積極進攻</span>
              <span className="font-mono bg-slate-800 px-1.5 py-0.2 rounded text-[10px]">
                {tiers.aggressive.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTier("moonshot")}
              className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTier === "moonshot"
                  ? "bg-purple-600/30 text-purple-400 border border-purple-500/40"
                  : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>🚀 瘋狗衝月</span>
              <span className="font-mono bg-slate-800 px-1.5 py-0.2 rounded text-[10px]">
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
            <Card className="text-center py-12 bg-slate-900/40">
              <CardContent className="space-y-2">
                <div className="text-3xl">🔍</div>
                <h4 className="font-bold text-slate-200">此梯次目前暫無符合條件的組合</h4>
                <p className="text-xs text-slate-400">
                  可以嘗試調整目標賠率（如改為 15x ~ 30x）或放寬情報門檻重試。
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {currentList.map((parlay, idx) => (
                <div
                  key={parlay.parlay_id || idx}
                  className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 shadow-lg hover:border-slate-700 transition-all space-y-4"
                >
                  {/* Parlay Card Header */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-100 text-base">
                          {parlay.parlay_name || `組合 #${idx + 1}`}
                        </span>
                        <Badge variant="blue" className="text-[10px] font-mono">
                          {parlay.legs.length} 串 1
                        </Badge>
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        各關賠率連乘 · 獨立賽事檢驗合格
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-2xl font-black text-amber-400 font-mono tracking-tight">
                        {parlay.total_odds.toFixed(2)}x
                      </div>
                      {parlay.expected_value !== undefined && parlay.expected_value !== null && (
                        <div className={`text-xs font-bold ${parlay.expected_value > 0 ? "text-emerald-400" : "text-slate-400"}`}>
                          EV: {parlay.expected_value > 0 ? "+" : ""}{(parlay.expected_value * 100).toFixed(1)}%
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Legs list inside parlay */}
                  <div className="space-y-2 pt-2 border-t border-slate-800/80">
                    {parlay.legs.map((leg, lIdx) => (
                      <div
                        key={lIdx}
                        className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/60 flex items-center justify-between text-xs"
                      >
                        <div className="space-y-0.5">
                          <div className="font-medium text-slate-300">
                            {leg.away_team} vs {leg.home_team}
                          </div>
                          <div className="text-emerald-400 font-semibold flex items-center gap-1.5">
                            <span className="text-[11px] text-slate-400">[{leg.market}]</span>
                            <span>{leg.selection}</span>
                          </div>
                        </div>

                        <div className="text-right">
                          <span className="font-bold font-mono text-amber-400 text-sm">
                            {leg.taiwan_odds?.toFixed(2)}x
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Actions Bar */}
                  <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between gap-3">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedParlayForEvidence(parlay)}
                      className="text-xs gap-1.5 text-slate-300"
                    >
                      <span>📑 Why 證據情報</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </Button>

                    <Button
                      variant="success"
                      size="sm"
                      onClick={() => setSelectedParlayForBet(parlay)}
                      className="text-xs font-bold px-4 gap-1.5"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>確認下注</span>
                    </Button>
                  </div>
                </div>
              ))}
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
    </div>
  )
}
