import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { RadarLeague, Leg } from "@/types"
import { Card, CardContent } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Skeleton } from "@/components/ui/Skeleton"
import { VersusBar } from "@/components/VersusBar"
import { Sparkline } from "@/components/charts/Sparkline"
import { useUI } from "@/context/UIContext"
import { Radio, Activity, AlertCircle } from "lucide-react"

export const RadarView: React.FC = () => {
  const { viewMode } = useUI()
  const [leagues, setLeagues] = useState<RadarLeague[]>([])
  const [legs, setLegs] = useState<Leg[]>([])
  const [selectedSport, setSelectedSport] = useState<string>("all")
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

  const filteredLegs = selectedSport === "all"
    ? legs
    : legs.filter((l) => l.sport === selectedSport || l.league.toLowerCase().includes(selectedSport.toLowerCase()))

  const sports = Array.from(new Set(legs.map((l) => l.sport).filter(Boolean)))

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
            賽季雷達 (Season Radar)
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            即時監控台灣運彩官方開盤賽事與 ESPN 國際賽程比對
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
          <button
            onClick={() => setSelectedSport("all")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
              selectedSport === "all"
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
                onClick={() => setSelectedSport(sp)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer capitalize ${
                  selectedSport === sp
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                }`}
              >
                {sp} ({count})
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

      {/* Radar Status Grid */}
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
            return (
              <div
                key={lg.league_id || lg.league_name}
                className={`p-3.5 rounded-xl border transition-all ${
                  isGreen
                    ? "border-emerald-500/40 bg-emerald-500/10 dark:bg-emerald-950/20"
                    : isYellow
                    ? "border-amber-500/30 bg-amber-500/5 dark:bg-amber-950/10 opacity-75"
                    : "border-slate-200 dark:border-slate-800 bg-slate-100/50 dark:bg-slate-900/40 opacity-50"
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <Badge
                    variant={isGreen ? "green" : isYellow ? "yellow" : "secondary"}
                    className="text-[10px] px-1.5 py-0"
                  >
                    {isGreen ? "🟢 開盤中" : isYellow ? "🟡 賽程中" : "🔴 休賽季"}
                  </Badge>
                  {isGreen && (
                    <span className="text-[11px] font-mono tabular-nums text-emerald-600 dark:text-emerald-400 font-bold">
                      {lg.active_legs_count} 盤
                    </span>
                  )}
                </div>
                <div className="font-bold text-sm text-slate-800 dark:text-slate-200 truncate" title={lg.league_name}>
                  {lg.league_name}
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 line-clamp-1">
                  {lg.reason || (isGreen ? "今日有開盤賽事" : "目前暫無開盤")}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Live Legs / Matches */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-1.5">
            <Activity className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
            今日即時開盤項目 (共 {filteredLegs.length} 個盤口可選)
          </h3>
          <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
            來源：玩運彩即時盤口
          </span>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : filteredLegs.length === 0 ? (
          <Card className="text-center py-12">
            <CardContent className="text-slate-500 dark:text-slate-400">目前所選分類沒有可下注的即時盤口。</CardContent>
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
                    return (
                      <tr key={idx} className="hover:bg-slate-100/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-2.5 text-slate-500">
                          <div>{leg.league || leg.sport}</div>
                          <div className="text-[10px]">{leg.game_time || leg.start_time || "即時"}</div>
                        </td>
                        <td className="p-2.5 font-sans font-semibold text-slate-900 dark:text-slate-200">
                          {leg.away_team} <span className="text-slate-400 font-normal">vs</span> {leg.home_team}
                        </td>
                        <td className="p-2.5 font-sans">
                          <span className="text-[11px] text-slate-400 mr-1">[{leg.market}]</span>
                          <strong className="text-emerald-600 dark:text-emerald-400">{leg.selection}</strong>
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

              return (
                <motion.div
                  key={`${leg.event_id}-${leg.market}-${leg.selection}-${idx}`}
                  whileHover={{ y: -2 }}
                  transition={{ duration: 0.2 }}
                  className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 backdrop-blur p-4 hover:border-emerald-500/40 dark:hover:border-slate-700 transition-all shadow-sm space-y-3"
                >
                  <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span className="font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-700 dark:text-slate-300">
                      {leg.league || leg.sport}
                    </span>
                    <span>{leg.game_time || leg.start_time || "即時"}</span>
                  </div>

                  <div className="font-bold text-slate-900 dark:text-slate-100 text-base">
                    <span className="text-slate-700 dark:text-slate-300">{leg.away_team}</span>
                    <span className="text-slate-400 mx-2 font-normal">vs</span>
                    <span className="text-slate-900 dark:text-slate-100">{leg.home_team}</span>
                  </div>

                  {/* Dual Versus Bar */}
                  <VersusBar
                    awayTeam={leg.away_team}
                    homeTeam={leg.home_team}
                    awayRatio={consensus}
                    voteCount={votes}
                  />

                  {/* Market & Odds Row */}
                  <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-slate-800/80">
                    <div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">{leg.market}</div>
                      <div className="text-sm font-semibold text-emerald-600 dark:text-emerald-400 mt-0.5">
                        {leg.selection}
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <div className="w-16 hidden sm:block">
                        <Sparkline height={28} />
                      </div>
                      <div className="text-right">
                        <div className="text-xs text-slate-500 dark:text-slate-400">台彩賠率</div>
                        <div className="text-lg font-black tabular-nums text-amber-500 dark:text-amber-400 font-mono">
                          {leg.taiwan_odds?.toFixed(2)}x
                        </div>
                      </div>
                    </div>
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
