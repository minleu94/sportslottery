import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { RadarLeague, Leg } from "@/types"
import { cleanLeagueName } from "@/lib/utils"
import { Card, CardContent } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Skeleton } from "@/components/ui/Skeleton"
import { VersusBar } from "@/components/VersusBar"
import { Sparkline } from "@/components/charts/Sparkline"
import { useUI } from "@/context/UIContext"
import { Radio, Activity, AlertCircle, Search, Flame, TrendingDown, Filter } from "lucide-react"

export const RadarView: React.FC = () => {
  const { viewMode } = useUI()
  const [leagues, setLeagues] = useState<RadarLeague[]>([])
  const [legs, setLegs] = useState<Leg[]>([])
  const [selectedSport, setSelectedSport] = useState<string>("all")
  const [selectedLeagueCode, setSelectedLeagueCode] = useState<string | null>(null)
  const [searchKeyword, setSearchKeyword] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    setError(null)
    try {
      const [radarData, legsData] = await Promise.all([
        api.getRadar(),
        api.getLegs(),
      ])
      setLeagues(radarData.radar || [])
      setLegs(legsData.legs || [])
    } catch (err: any) {
      setError(err.message || "載入失敗")
    } finally {
      setLoading(false)
    }
  }

  // Total open matches across all radar leagues
  const totalOpenMatches = leagues.reduce((sum, l) => sum + (l.taiwan_market_count || 0), 0)

  // Filter by sport pill, radar league card click, & search keyword
  const filteredLegs = legs.filter((l) => {
    const cleanedLg = cleanLeagueName(l.league).toLowerCase()
    
    // 1. Sport filter
    const matchesSport =
      selectedSport === "all" ||
      l.sport === selectedSport ||
      cleanedLg.includes(selectedSport.toLowerCase())

    if (!matchesSport) return false

    // 2. Specific league code filter from radar card click
    if (selectedLeagueCode) {
      const codeUpper = selectedLeagueCode.toUpperCase()
      const matchesLeague =
        (l.league && l.league.toUpperCase().includes(codeUpper)) ||
        (codeUpper === "SOCCER_GLOBAL" && (l.sport === "soccer" || l.league?.toLowerCase().includes("soccer"))) ||
        (codeUpper === "PREMIER" && (l.league?.includes("英超") || l.league?.toUpperCase().includes("PREMIER"))) ||
        (codeUpper === "LALIGA" && (l.league?.includes("西甲") || l.league?.toUpperCase().includes("LALIGA"))) ||
        (codeUpper === "CHAMPIONS" && (l.league?.includes("歐冠") || l.league?.toUpperCase().includes("CHAMPIONS"))) ||
        (codeUpper === "NBA" && (l.league?.toUpperCase().includes("NBA") || l.sport === "basketball")) ||
        (codeUpper === "WNBA" && (l.league?.toUpperCase().includes("WNBA"))) ||
        (codeUpper === "KBO" && (l.league?.toUpperCase().includes("KBO") || l.league?.includes("韓") || l.league?.includes("韓國"))) ||
        (codeUpper === "MLB" && (l.league?.toUpperCase().includes("MLB") || l.league?.includes("美棒"))) ||
        (codeUpper === "CPBL" && (l.league?.toUpperCase().includes("CPBL") || l.league?.includes("中職"))) ||
        (codeUpper === "NPB" && (l.league?.toUpperCase().includes("NPB") || l.league?.includes("日棒"))) ||
        (codeUpper === "NHL" && (l.league?.toUpperCase().includes("NHL") || l.sport === "hockey")) ||
        (codeUpper === "NFL" && (l.league?.toUpperCase().includes("NFL") || l.sport === "football"))
      if (!matchesLeague) return false
    }

    // 3. Keyword filter
    if (!searchKeyword.trim()) return true
    const kw = searchKeyword.trim().toLowerCase()
    return (
      (l.away_team && l.away_team.toLowerCase().includes(kw)) ||
      (l.home_team && l.home_team.toLowerCase().includes(kw)) ||
      cleanedLg.includes(kw) ||
      (l.event_id && String(l.event_id).includes(kw)) ||
      (l.market && l.market.toLowerCase().includes(kw)) ||
      (l.selection && l.selection.toLowerCase().includes(kw))
    )
  })

  const sports = Array.from(new Set(legs.map((l) => l.sport).filter(Boolean)))

  function toggleLeagueClick(code: string) {
    if (selectedLeagueCode === code) {
      setSelectedLeagueCode(null)
    } else {
      setSelectedLeagueCode(code)
      setSelectedSport("all")
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      {/* Overview Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-black text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Radio className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
            📡 今日賽季雷達 (Season Radar)
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            🟢 綠燈：賽季中且今日台彩有開盤；🟡 黃燈：賽季中但今日無開盤；🔴 紅燈：休賽季
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
          <button
            onClick={() => {
              setSelectedSport("all")
              setSelectedLeagueCode(null)
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
              selectedSport === "all" && !selectedLeagueCode
                ? "bg-slate-800 text-white dark:bg-slate-700"
                : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            全部 ({legs.length})
          </button>
          {sports.map((sp) => {
            const count = legs.filter((l) => l.sport === sp).length
            return (
              <button
                key={sp}
                onClick={() => {
                  setSelectedSport(sp)
                  setSelectedLeagueCode(null)
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer capitalize whitespace-nowrap ${
                  selectedSport === sp && !selectedLeagueCode
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                }`}
              >
                {sp === "soccer" ? "⚽ 足球" : sp === "basketball" ? "🏀 籃球/NBA" : sp === "baseball" ? "⚾ 棒球" : sp} ({count})
              </button>
            )
          })}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-600 dark:text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Radar Status Grid (Interactive: click to filter) */}
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {leagues.map((lg) => {
            const isGreen = lg.status === "GREEN"
            const isYellow = lg.status === "YELLOW"
            const displayName = lg.name || lg.league_name || lg.code
            const displayIcon = lg.icon || "⚽"
            const marketCount = lg.taiwan_market_count ?? lg.active_legs_count ?? 0
            const isSelected = selectedLeagueCode === lg.code

            return (
              <div
                key={lg.code || lg.league_id || displayName}
                onClick={() => toggleLeagueClick(lg.code)}
                className={`p-3.5 rounded-xl border transition-all flex flex-col justify-between cursor-pointer hover:shadow-md ${
                  isSelected
                    ? "ring-2 ring-emerald-500 border-emerald-500 bg-emerald-500/20"
                    : isGreen
                    ? "border-emerald-500/40 bg-emerald-500/10 dark:bg-emerald-950/20 hover:border-emerald-500"
                    : isYellow
                    ? "border-amber-500/30 bg-amber-500/5 dark:bg-amber-950/10 opacity-80 hover:opacity-100"
                    : "border-slate-200 dark:border-slate-800 bg-slate-100/50 dark:bg-slate-900/40 opacity-50 hover:opacity-80"
                }`}
                title={`點擊可直接篩選 ${displayName} 開盤項目`}
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <Badge
                      variant={isGreen ? "green" : isYellow ? "yellow" : "secondary"}
                      className="text-[10px] px-1.5 py-0"
                    >
                      {isGreen ? "🟢 開盤中" : isYellow ? "🟡 賽程中" : "🔴 休賽季"}
                    </Badge>
                    <span className="text-xs">{lg.light_emoji || (isGreen ? "🟢" : isYellow ? "🟡" : "🔴")}</span>
                  </div>

                  <div className="font-bold text-sm text-slate-900 dark:text-slate-100 truncate" title={displayName}>
                    {displayIcon} {displayName}
                  </div>

                  <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 line-clamp-1">
                    {marketCount > 0 ? (
                      <span className="text-emerald-600 dark:text-emerald-400 font-bold">{marketCount} 場賽事開盤</span>
                    ) : (
                      lg.status_text || "今日暫無開盤"
                    )}
                  </div>
                </div>

                {lg.opportunity_badge && (
                  <div className="mt-2 text-[10px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded inline-block self-start">
                    {lg.opportunity_badge}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Live Legs / Matches Header & Search Bar */}
      <div className="space-y-3 pt-2">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-bold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-1.5">
                <Activity className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                今日開盤對戰詳情：共 {totalOpenMatches} 場賽事、{legs.length} 個玩法選項可選
              </h3>
              <Badge variant="green" className="text-[11px] font-mono">
                符合篩選: {filteredLegs.length} 盤
              </Badge>
              {selectedLeagueCode && (
                <button
                  onClick={() => setSelectedLeagueCode(null)}
                  className="text-[10px] text-emerald-500 dark:text-emerald-400 underline cursor-pointer"
                >
                  清除聯賽鎖定 [✕]
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
              💡 說明：每場賽事 (如 NBA 10 場、韓棒 1 場、足球 43 場) 開放讓分、不讓分、大小分等複數玩法，故玩法選項總數高於場次。
            </p>
          </div>

          {/* Search Box */}
          <div className="relative w-full sm:w-72">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="搜尋球隊、聯賽或編號..."
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-xs text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:border-emerald-500"
            />
          </div>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : filteredLegs.length === 0 ? (
          <Card className="text-center py-12">
            <CardContent className="text-slate-500 dark:text-slate-400">目前所選分類沒有符合的即時盤口。</CardContent>
          </Card>
        ) : viewMode === "compact" ? (
          /* Compact Trader Mode (High Density Table View) */
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/60 overflow-hidden shadow">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-100 dark:bg-slate-950/80 border-b border-slate-200 dark:border-slate-800 text-slate-500 font-mono">
                  <tr>
                    <th className="p-2.5">聯賽 / 時間</th>
                    <th className="p-2.5">對決賽事 (客 vs 主)</th>
                    <th className="p-2.5">推薦選項</th>
                    <th className="p-2.5">大眾投票對決</th>
                    <th className="p-2.5 text-center">趨勢</th>
                    <th className="p-2.5 text-right">台彩賠率</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800/60 font-mono">
                  {filteredLegs.map((leg, idx) => {
                    const ev = leg.signal_evidence || {}
                    const consensus = ev.consensus_ratio || 0.5
                    const lm = ev.line_movement || {}
                    const legEv = ev.sharp_expected_value_pct ?? ev.expected_value_pct
                    const isPositiveEv = typeof legEv === "number" && legEv > 0

                    return (
                      <tr key={idx} className="hover:bg-slate-100/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-2.5 text-slate-500">
                          <div className="font-semibold text-slate-700 dark:text-slate-300">
                            {cleanLeagueName(leg.league || leg.sport)}
                          </div>
                          <div className="text-[10px] text-slate-400">
                            {leg.game_time || leg.start_time || "即時"} · #{leg.event_id}
                          </div>
                        </td>
                        <td className="p-2.5 font-sans font-semibold text-slate-900 dark:text-slate-200">
                          {leg.away_team} <span className="text-slate-400 font-normal">vs</span> {leg.home_team}
                        </td>
                        <td className="p-2.5 font-sans">
                          <span className="text-[11px] text-slate-400 mr-1">[{leg.market}]</span>
                          <strong className="text-emerald-600 dark:text-emerald-400">{leg.selection}</strong>
                          {isPositiveEv && (
                            <span className="ml-1.5 text-[10px] font-bold text-emerald-500 bg-emerald-500/10 px-1 py-0.5 rounded">
                              +EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                            </span>
                          )}
                          {lm.is_steam && (
                            <span className="ml-1 text-[10px] font-bold text-emerald-400">📉跳水</span>
                          )}
                          {lm.is_trap_warning && (
                            <span className="ml-1 text-[10px] font-bold text-amber-400">⚠️升水</span>
                          )}
                        </td>
                        <td className="p-2.5 w-44 font-sans">
                          <VersusBar
                            awayTeam={leg.away_team.slice(0, 3)}
                            homeTeam={leg.home_team.slice(0, 3)}
                            awayRatio={consensus}
                            voteCount={ev.vote_count}
                          />
                        </td>
                        <td className="p-2.5 w-20 text-center">
                          <Sparkline height={24} />
                        </td>
                        <td className="p-2.5 text-right font-black tabular-nums text-amber-500 dark:text-amber-400 text-sm">
                          {leg.taiwan_odds?.toFixed(2)}x
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          /* Standard Cards Mode */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredLegs.map((leg, idx) => {
              const evidence = leg.signal_evidence || {}
              const consensus = evidence.consensus_ratio || 0.5
              const votes = evidence.vote_count || null
              const lm = evidence.line_movement || {}
              const legEv = evidence.sharp_expected_value_pct ?? evidence.expected_value_pct

              return (
                <motion.div
                  key={`${leg.event_id}-${leg.market}-${leg.selection}-${idx}`}
                  whileHover={{ y: -2 }}
                  transition={{ duration: 0.2 }}
                  className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 backdrop-blur p-4 hover:border-emerald-500/40 dark:hover:border-slate-700 transition-all shadow-sm space-y-3"
                >
                  <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span className="font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-700 dark:text-slate-300 font-semibold">
                      {cleanLeagueName(leg.league || leg.sport)}
                    </span>
                    <span className="font-mono">#{leg.event_id} · {leg.game_time || leg.start_time || "即時"}</span>
                  </div>

                  <div className="font-bold text-slate-900 dark:text-slate-100 text-base">
                    {leg.away_team} <span className="text-slate-400 font-normal text-xs">客 vs 主</span> {leg.home_team}
                  </div>

                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800/80">
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-semibold">
                        {leg.market}
                      </div>
                      <div className="font-black text-slate-900 dark:text-slate-100 text-sm">
                        {leg.selection}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] text-slate-400">官方賠率</div>
                      <div className="font-black text-amber-500 dark:text-amber-400 text-lg tabular-nums">
                        {leg.taiwan_odds?.toFixed(2)}x
                      </div>
                    </div>
                  </div>

                  {/* Signals & Indicators */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {typeof legEv === "number" && legEv > 0 && (
                      <Badge variant="green" className="text-[10px] flex items-center gap-1">
                        <Flame className="w-3 h-3" />
                        +EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                      </Badge>
                    )}
                    {lm.is_steam && (
                      <Badge variant="green" className="text-[10px] flex items-center gap-1">
                        <TrendingDown className="w-3 h-3" />
                        📉 跳水順勢
                      </Badge>
                    )}
                    {lm.is_trap_warning && (
                      <Badge variant="yellow" className="text-[10px] flex items-center gap-1">
                        ⚠️ 升水誘盤防禦
                      </Badge>
                    )}
                  </div>

                  {/* Public Consensus Meter */}
                  <div className="pt-1">
                    <VersusBar
                      awayTeam={leg.away_team.slice(0, 3)}
                      homeTeam={leg.home_team.slice(0, 3)}
                      awayRatio={consensus}
                      voteCount={votes}
                    />
                  </div>
                </motion.div>
              )
            })}
          </div>
        )}
      </div>
    </motion.div>
  )
}
