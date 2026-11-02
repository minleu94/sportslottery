import React, { useState, useEffect, useMemo } from "react"
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
import {
  Radio,
  Activity,
  AlertCircle,
  Search,
  Flame,
  TrendingDown,
  ChevronDown,
  ChevronRight,
  Layers,
  Eye,
  EyeOff,
  Scale,
  Zap,
} from "lucide-react"

export const RadarView: React.FC = () => {
  const { viewMode } = useUI()
  const [leagues, setLeagues] = useState<RadarLeague[]>([])
  const [legs, setLegs] = useState<Leg[]>([])
  const [selectedSport, setSelectedSport] = useState<string>("all")
  const [selectedLeagueCode, setSelectedLeagueCode] = useState<string | null>(null)
  const [selectedDropdownLeague, setSelectedDropdownLeague] = useState<string>("all")
  const [searchKeyword, setSearchKeyword] = useState<string>("")
  const [collapsedLeagues, setCollapsedLeagues] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    async function loadData() {
      setLoading(true)
      setError(null)
      try {
        const [radarData, legsData] = await Promise.all([
          api.getRadar(),
          api.getLegs(),
        ])
        if (isMounted) {
          setLeagues(radarData.radar || [])
          setLegs(legsData.legs || [])
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || "載入盤口資料失敗")
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }
    loadData()
    return () => {
      isMounted = false
    }
  }, [])

  // Total open matches across all radar leagues
  const totalOpenMatches = leagues.reduce((sum, l) => sum + (l.taiwan_market_count || 0), 0)

  function getLeagueBadge(name: string, sport?: string) {
    if (name.includes("籃") || name.includes("NBA") || name.includes("WNBA") || sport === "basketball") {
      return "籃球"
    }
    if (name.includes("棒") || name.includes("MLB") || name.includes("KBO") || name.includes("NPB") || name.includes("CPBL") || sport === "baseball") {
      return "棒球"
    }
    if (name.includes("冰球") || name.includes("NHL") || sport === "hockey") {
      return "冰球"
    }
    if (name.includes("美式足球") || name.includes("NFL") || sport === "football") {
      return "美足"
    }
    return "足球"
  }

  // Extract all unique leagues with match & options count for dropdown
  const leagueOptions = useMemo(() => {
    const baseLegs = selectedSport === "all" ? legs : legs.filter((l) => l.sport === selectedSport)
    const map = new Map<string, { matches: Set<string>; count: number; sport: string }>()
    for (const l of baseLegs) {
      const lgName = cleanLeagueName(l.display_league || l.league || l.sport)
      if (!map.has(lgName)) {
        map.set(lgName, { matches: new Set(), count: 0, sport: l.sport })
      }
      const entry = map.get(lgName)!
      entry.matches.add(String(l.event_id || `${l.away_team}-${l.home_team}`))
      entry.count += 1
    }
    return Array.from(map.entries())
      .map(([name, data]) => ({
        name,
        matchesCount: data.matches.size,
        legsCount: data.count,
        sport: data.sport,
      }))
      .sort((a, b) => b.legsCount - a.legsCount)
  }, [legs, selectedSport])

  // Filter by sport pill, radar league card click, dropdown league, & search keyword
  const filteredLegs = useMemo(() => {
    return legs.filter((l) => {
      const cleanedLg = cleanLeagueName(l.display_league || l.league || l.sport)
      const cleanedLgLower = cleanedLg.toLowerCase()

      // 1. Sport filter
      const matchesSport =
        selectedSport === "all" ||
        l.sport === selectedSport ||
        cleanedLgLower.includes(selectedSport.toLowerCase())

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
          (codeUpper === "WNBA" && l.league?.toUpperCase().includes("WNBA")) ||
          (codeUpper === "KBO" && (l.league?.toUpperCase().includes("KBO") || l.league?.includes("韓") || l.league?.includes("韓國"))) ||
          (codeUpper === "MLB" && (l.league?.toUpperCase().includes("MLB") || l.league?.includes("美棒"))) ||
          (codeUpper === "CPBL" && (l.league?.toUpperCase().includes("CPBL") || l.league?.includes("中職"))) ||
          (codeUpper === "NPB" && (l.league?.toUpperCase().includes("NPB") || l.league?.includes("日棒"))) ||
          (codeUpper === "NHL" && (l.league?.toUpperCase().includes("NHL") || l.sport === "hockey")) ||
          (codeUpper === "NFL" && (l.league?.toUpperCase().includes("NFL") || l.sport === "football"))
        if (!matchesLeague) return false
      }

      // 3. Dropdown league filter
      if (selectedDropdownLeague !== "all") {
        if (cleanedLg !== selectedDropdownLeague) {
          return false
        }
      }

      // 4. Keyword filter
      if (!searchKeyword.trim()) return true
      const kw = searchKeyword.trim().toLowerCase()
      return (
        (l.away_team && l.away_team.toLowerCase().includes(kw)) ||
        (l.home_team && l.home_team.toLowerCase().includes(kw)) ||
        cleanedLgLower.includes(kw) ||
        (l.event_id && String(l.event_id).includes(kw)) ||
        (l.market && l.market.toLowerCase().includes(kw)) ||
        (l.selection && l.selection.toLowerCase().includes(kw))
      )
    })
  }, [legs, selectedSport, selectedLeagueCode, selectedDropdownLeague, searchKeyword])

  // Group filtered legs by cleaned league name
  const groupedByLeague = useMemo(() => {
    const map = new Map<string, Leg[]>()
    for (const leg of filteredLegs) {
      const lg = cleanLeagueName(leg.display_league || leg.league || leg.sport)
      if (!map.has(lg)) {
        map.set(lg, [])
      }
      map.get(lg)!.push(leg)
    }
    return Array.from(map.entries())
  }, [filteredLegs])

  const sports = Array.from(new Set(legs.map((l) => l.sport).filter(Boolean)))

  function toggleLeagueClick(code: string) {
    if (selectedLeagueCode === code) {
      setSelectedLeagueCode(null)
    } else {
      setSelectedLeagueCode(code)
      setSelectedDropdownLeague("all")
      setSelectedSport("all")
    }
  }

  function toggleLeagueCollapse(lgName: string) {
    setCollapsedLeagues((prev) => ({
      ...prev,
      [lgName]: !prev[lgName],
    }))
  }

  function expandAllLeagues() {
    setCollapsedLeagues({})
  }

  function collapseAllLeagues() {
    const allCol: Record<string, boolean> = {}
    groupedByLeague.forEach(([lgName]) => {
      allCol[lgName] = true
    })
    setCollapsedLeagues(allCol)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="space-y-5"
    >
      {/* Overview Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 tracking-tight">
              <Radio className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              賽季開盤雷達
            </h2>
            <span className="text-xs text-slate-400">· 即時盤口監控</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mt-1">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
              開盤中
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
              賽季中暫無開盤
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-slate-400 dark:bg-slate-600 inline-block" />
              休賽季
            </span>
          </div>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
          <button
            onClick={() => {
              setSelectedSport("all")
              setSelectedLeagueCode(null)
              setSelectedDropdownLeague("all")
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap ${
              selectedSport === "all" && !selectedLeagueCode && selectedDropdownLeague === "all"
                ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900 shadow-xs"
                : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
            }`}
          >
            全部 ({legs.length})
          </button>
          {sports.map((sp) => {
            const count = legs.filter((l) => l.sport === sp).length
            const sportLabels: Record<string, string> = {
              soccer: "足球",
              basketball: "籃球",
              baseball: "棒球",
              hockey: "冰球",
              football: "美式足球",
            }
            const label = sportLabels[sp] || sp

            return (
              <button
                key={sp}
                onClick={() => {
                  setSelectedSport(sp)
                  setSelectedLeagueCode(null)
                  setSelectedDropdownLeague("all")
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap ${
                  selectedSport === sp && !selectedLeagueCode && selectedDropdownLeague === "all"
                    ? "bg-emerald-600 text-white shadow-xs"
                    : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
                }`}
              >
                {label} ({count})
              </button>
            )
          })}
        </div>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Season Radar Grid Cards */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {leagues.map((lg) => {
            const isGreen = lg.status === "GREEN"
            const isYellow = lg.status === "YELLOW"
            const displayName = lg.name || lg.league_name || lg.code
            const marketCount = lg.taiwan_market_count ?? lg.active_legs_count ?? 0
            const isSelected = selectedLeagueCode === lg.code

            return (
              <div
                key={lg.code || lg.league_id || displayName}
                onClick={() => toggleLeagueClick(lg.code)}
                className={`p-3 rounded-xl border transition-colors flex flex-col justify-between cursor-pointer ${
                  isSelected
                    ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30 shadow-xs ring-1 ring-emerald-500"
                    : isGreen
                    ? "border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700"
                    : isYellow
                    ? "border-slate-200/80 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-900/40 text-slate-500"
                    : "border-slate-200/60 dark:border-slate-800/50 bg-slate-50/30 dark:bg-slate-900/20 text-slate-400"
                }`}
                title={`點擊篩選 ${displayName} 開盤項目`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/60">
                      {getLeagueBadge(displayName)}
                    </span>
                    <span className="flex items-center gap-1 text-[11px]">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          isGreen ? "bg-emerald-500" : isYellow ? "bg-amber-500" : "bg-slate-400"
                        }`}
                      />
                    </span>
                  </div>

                  <div className="font-medium text-xs sm:text-sm text-slate-900 dark:text-slate-100 truncate" title={displayName}>
                    {displayName}
                  </div>

                  <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-1 tabular-nums">
                    {marketCount > 0 ? (
                      <span className="text-emerald-600 dark:text-emerald-400 font-medium">{marketCount} 場開盤</span>
                    ) : (
                      lg.status_text || "今日無開盤"
                    )}
                  </div>
                </div>

                {isGreen && (
                  <div className="mt-2.5 pt-1.5 border-t border-slate-100 dark:border-slate-800/60 flex items-center justify-between text-[10px] text-slate-400">
                    <span className="text-emerald-600 dark:text-emerald-400 font-medium">開盤中</span>
                    <span>點擊聚焦</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Live Legs / Matches Header & Filter Bar */}
      <div className="space-y-3 pt-2">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm flex items-center gap-1.5">
                <Activity className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                今日開盤盤口：共 {totalOpenMatches} 場賽事 · {legs.length} 盤可選
              </h3>
              <Badge variant="green" className="text-[10px] font-mono">
                符合篩選 {filteredLegs.length} 盤
              </Badge>
              {(selectedLeagueCode || selectedDropdownLeague !== "all") && (
                <button
                  onClick={() => {
                    setSelectedLeagueCode(null)
                    setSelectedDropdownLeague("all")
                  }}
                  className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium hover:underline cursor-pointer"
                >
                  清除聯賽篩選
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
              各賽事涵蓋讓分、不讓分、大小分等複數玩法，單一賽事含多重盤口選項。
            </p>
          </div>

          {/* Search Box & League Dropdown Filter */}
          <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap">
            {/* League Dropdown Filter */}
            <div className="relative w-full sm:w-auto">
              <select
                value={selectedDropdownLeague}
                onChange={(e) => {
                  setSelectedDropdownLeague(e.target.value)
                  if (e.target.value !== "all") {
                    setSelectedLeagueCode(null)
                  }
                }}
                className="w-full sm:w-56 px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-xs font-medium text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-500 cursor-pointer shadow-xs"
              >
                <option value="all">全部聯賽 ({leagueOptions.length} 個聯賽 · {legs.length} 盤)</option>
                {leagueOptions.map((opt) => (
                  <option key={opt.name} value={opt.name}>
                    {opt.name} ({opt.matchesCount}場 · {opt.legsCount}盤)
                  </option>
                ))}
              </select>
            </div>

            {/* Keyword Search Box */}
            <div className="relative w-full sm:w-56">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="搜尋球隊、聯賽或編號"
                value={searchKeyword}
                onChange={(e) => setSearchKeyword(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-emerald-500 shadow-xs"
              />
            </div>
          </div>
        </div>

        {/* Accordion Controls Bar */}
        {groupedByLeague.length > 1 && (
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 pt-1 pb-0.5 border-t border-slate-200/60 dark:border-slate-800/60">
            <span className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              <span>依聯賽分組收合 (共 {groupedByLeague.length} 個群組)</span>
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={expandAllLeagues}
                className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700/80 text-[11px] font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer flex items-center gap-1"
              >
                <Eye className="w-3 h-3 text-slate-400" />
                <span>全部展開</span>
              </button>
              <button
                onClick={collapseAllLeagues}
                className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700/80 text-[11px] font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer flex items-center gap-1"
              >
                <EyeOff className="w-3 h-3 text-slate-400" />
                <span>全部收合</span>
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : filteredLegs.length === 0 ? (
          <Card className="text-center py-12">
            <CardContent className="text-slate-500 dark:text-slate-400 text-xs">
              目前所選分類沒有符合的即時盤口。
            </CardContent>
          </Card>
        ) : viewMode === "compact" ? (
          /* Compact Mode */
          <div className="space-y-3">
            {groupedByLeague.map(([lgName, leagueLegs]) => {
              const isCollapsed = Boolean(collapsedLeagues[lgName])
              const matchCount = new Set(leagueLegs.map((l) => l.event_id || `${l.away_team}-${l.home_team}`)).size

              return (
                <div
                  key={lgName}
                  className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-xs transition-colors"
                >
                  {/* League Header Bar */}
                  <div
                    onClick={() => toggleLeagueCollapse(lgName)}
                    className="p-3 bg-slate-50/80 dark:bg-slate-950/50 hover:bg-slate-100/70 dark:hover:bg-slate-900 transition-colors cursor-pointer flex items-center justify-between border-b border-slate-200/70 dark:border-slate-800 select-none"
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="text-slate-400">
                        {isCollapsed ? (
                          <ChevronRight className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                        )}
                      </span>
                      <span className="font-semibold text-xs sm:text-sm text-slate-900 dark:text-slate-100">
                        {lgName}
                      </span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
                        {matchCount} 場 · {leagueLegs.length} 盤
                      </span>
                    </div>

                    <div className="text-[11px] text-slate-400 font-mono">
                      <span>{isCollapsed ? "展開" : "收合"}</span>
                    </div>
                  </div>

                  {/* League Table Content */}
                  {!isCollapsed && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-50/50 dark:bg-slate-950/30 border-b border-slate-200/80 dark:border-slate-800 text-slate-500 font-mono text-[11px]">
                          <tr>
                            <th className="p-2.5">時間 / 編號</th>
                            <th className="p-2.5">對決賽事 (客 vs 主)</th>
                            <th className="p-2.5">玩法與盤口選項</th>
                            <th className="p-2.5">公眾投票</th>
                            <th className="p-2.5 text-center">走向</th>
                            <th className="p-2.5 text-right">台彩賠率</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                          {leagueLegs.map((leg, idx) => {
                            const ev = leg.signal_evidence || {}
                            const consensus = ev.consensus_ratio || 0.5
                            const lm = ev.line_movement || {}
                            const legEv = ev.sharp_expected_value_pct ?? ev.expected_value_pct
                            const isPositiveEv = typeof legEv === "number" && legEv > 0

                            return (
                              <tr key={idx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                <td className="p-2.5 text-slate-500 text-[11px]">
                                  <div>{leg.game_time || leg.start_time || "即時"}</div>
                                  <div className="text-[10px] text-slate-400 font-mono">#{leg.event_id}</div>
                                </td>
                                <td className="p-2.5 font-sans font-medium text-slate-900 dark:text-slate-100">
                                  {leg.away_team} <span className="text-slate-400 font-normal">vs</span> {leg.home_team}
                                </td>
                                <td className="p-2.5 font-sans">
                                  <span className="text-[11px] text-slate-400 mr-1.5">[{leg.market}]</span>
                                  <span className="font-medium text-slate-900 dark:text-slate-100">{leg.selection}</span>
                                  {!ev.is_market_synthetic && isPositiveEv && (
                                    <span className="ml-1.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-500/20 px-1 py-0.5 rounded font-mono">
                                      +EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                                    </span>
                                  )}
                                  {!ev.is_market_synthetic && ev.sharp_fair_probability && (
                                    <span className="ml-1 text-[10px] font-medium text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono">
                                      去水 {(ev.sharp_fair_probability * 100).toFixed(0)}%
                                    </span>
                                  )}
                                  {ev.is_market_synthetic && (
                                    <span className="ml-1 text-[10px] text-slate-400 bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono">
                                      模擬數據
                                    </span>
                                  )}
                                  {!ev.is_splits_synthetic && ev.is_sharp_money_divergence && (
                                    <span className="ml-1 text-[10px] font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-1 py-0.5 rounded">
                                      籌碼分歧
                                    </span>
                                  )}
                                  {lm.is_steam && (
                                    <span className="ml-1 text-[10px] font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-1 py-0.5 rounded">
                                      順勢跳水
                                    </span>
                                  )}
                                  {lm.is_trap_warning && (
                                    <span className="ml-1 text-[10px] font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-1 py-0.5 rounded">
                                      升水防禦
                                    </span>
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
                                <td className="p-2.5 text-right font-medium tabular-nums text-slate-900 dark:text-slate-100 text-sm">
                                  {leg.taiwan_odds?.toFixed(2)}x
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          /* Cards Mode */
          <div className="space-y-4">
            {groupedByLeague.map(([lgName, leagueLegs]) => {
              const isCollapsed = Boolean(collapsedLeagues[lgName])
              const matchCount = new Set(leagueLegs.map((l) => l.event_id || `${l.away_team}-${l.home_team}`)).size

              return (
                <div
                  key={lgName}
                  className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 p-4 space-y-3"
                >
                  {/* League Header */}
                  <div
                    onClick={() => toggleLeagueCollapse(lgName)}
                    className="flex items-center justify-between cursor-pointer select-none pb-2 border-b border-slate-200/70 dark:border-slate-800/80"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400">
                        {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />}
                      </span>
                      <h4 className="font-semibold text-sm text-slate-900 dark:text-slate-100">{lgName}</h4>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
                        {matchCount} 場 · {leagueLegs.length} 盤
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 font-mono">
                      {isCollapsed ? "展開" : "收合"}
                    </span>
                  </div>

                  {!isCollapsed && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 pt-1">
                      {leagueLegs.map((leg, idx) => {
                        const evidence = leg.signal_evidence || {}
                        const consensus = evidence.consensus_ratio || 0.5
                        const votes = evidence.vote_count || null
                        const lm = evidence.line_movement || {}
                        const legEv = evidence.sharp_expected_value_pct ?? evidence.expected_value_pct

                        return (
                          <div
                            key={`${leg.event_id}-${leg.market}-${leg.selection}-${idx}`}
                            className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 hover:border-slate-300 dark:hover:border-slate-700 transition-colors shadow-xs space-y-3"
                          >
                            <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                              <span className="font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-slate-700 dark:text-slate-300 text-[11px] font-medium">
                                {cleanLeagueName(leg.display_league || leg.league || leg.sport)}
                              </span>
                              <span className="font-mono text-[11px]">#{leg.event_id} · {leg.game_time || leg.start_time || "即時"}</span>
                            </div>

                            <div className="font-medium text-slate-900 dark:text-slate-100 text-sm">
                              {leg.away_team} <span className="text-slate-400 font-normal text-xs">客 vs 主</span> {leg.home_team}
                            </div>

                            <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950/70 border border-slate-200/70 dark:border-slate-800">
                              <div>
                                <div className="text-[10px] text-slate-400 font-medium">
                                  {leg.market}
                                </div>
                                <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                                  {leg.selection}
                                </div>
                              </div>
                              <div className="text-right">
                                <div className="text-[10px] text-slate-400">官方賠率</div>
                                <div className="font-semibold text-slate-900 dark:text-slate-100 text-base tabular-nums">
                                  {leg.taiwan_odds?.toFixed(2)}x
                                </div>
                              </div>
                            </div>

                            {/* Signals & Indicators */}
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {typeof legEv === "number" && legEv > 0 && !evidence.is_market_synthetic && (
                                <Badge variant="green" className="text-[10px] flex items-center gap-1">
                                  <Flame className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                                  +EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                                </Badge>
                              )}
                              {evidence.is_market_synthetic && (
                                <Badge variant="secondary" className="text-[10px] text-slate-500">
                                  模擬數據
                                </Badge>
                              )}
                              {lm.is_steam && (
                                <Badge variant="green" className="text-[10px] flex items-center gap-1">
                                  <TrendingDown className="w-3 h-3" />
                                  順勢跳水
                                </Badge>
                              )}
                              {lm.is_trap_warning && (
                                <Badge variant="yellow" className="text-[10px] flex items-center gap-1">
                                  升水防禦
                                </Badge>
                              )}
                              {evidence.sharp_fair_probability && !evidence.is_market_synthetic && (
                                <Badge variant="secondary" className="text-[10px] flex items-center gap-1 font-mono">
                                  <Scale className="w-3 h-3 text-slate-400" />
                                  去水 {(evidence.sharp_fair_probability * 100).toFixed(0)}%
                                </Badge>
                              )}
                              {evidence.is_sharp_money_divergence && !evidence.is_splits_synthetic && (
                                <Badge variant="amber" className="text-[10px] flex items-center gap-1">
                                  <Zap className="w-3 h-3" />
                                  籌碼分歧
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
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </motion.div>
  )
}
