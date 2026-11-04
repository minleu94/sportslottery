import React, { useState, useEffect, useMemo } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { RadarLeague, Leg } from "@/types"
import { cleanLeagueName, cleanSelectionLabel } from "@/lib/utils"
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
  Eye,
  EyeOff,
  Scale,
  Zap,
  RefreshCw,
} from "lucide-react"

interface RadarSnapshot {
  cachedAt: number
  leagues: RadarLeague[]
  legs: Leg[]
}

interface AggregatedMatch {
  matchKey: string
  eventId: string | number
  awayTeam: string
  homeTeam: string
  gameTime: string
  consensus: number
  voteCount?: number
  options: Leg[]
}

const RADAR_CACHE_TTL_MS = 3 * 60 * 1000
let radarSnapshot: RadarSnapshot | null = null

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
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    let isMounted = true
    async function loadData(forceRefresh: boolean) {
      const cached = radarSnapshot
      if (!forceRefresh && cached && Date.now() - cached.cachedAt < RADAR_CACHE_TTL_MS) {
        setLeagues(cached.leagues)
        setLegs(cached.legs)
        setError(null)
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const radarData = await api.getRadar(forceRefresh)
        // The radar endpoint refreshes and writes the source cache first. Read
        // the legs afterward so a manual refresh does not fetch each league twice.
        const legsData = await api.getLegs()
        if (isMounted) {
          const nextSnapshot = {
            cachedAt: Date.now(),
            leagues: radarData.radar || [],
            legs: legsData.legs || [],
          }
          radarSnapshot = nextSnapshot
          setLeagues(nextSnapshot.leagues)
          setLegs(nextSnapshot.legs)
        }
      } catch (err: any) {
        if (isMounted) {
          if (radarSnapshot) {
            setLeagues(radarSnapshot.leagues)
            setLegs(radarSnapshot.legs)
            setError(`更新失敗，先顯示上次資料：${err.message || "載入盤口資料失敗"}`)
          } else {
            setError(err.message || "載入盤口資料失敗")
          }
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }
    loadData(refreshVersion > 0)
    return () => {
      isMounted = false
    }
  }, [refreshVersion])

  // Total open matches across all radar leagues
  const totalOpenMatches = leagues.reduce((sum, l) => sum + (l.taiwan_market_count || 0), 0)

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

  // Sort radar leagues: GREEN (today open) first by game count descending, then YELLOW (in-season), then RED (off-season)
  const sortedLeagues = useMemo(() => {
    const statusWeight: Record<string, number> = {
      GREEN: 0,
      YELLOW: 1,
      UNKNOWN: 2,
      RED: 3,
    }
    return [...leagues].sort((a, b) => {
      const weightA = statusWeight[a.status] ?? 99
      const weightB = statusWeight[b.status] ?? 99
      if (weightA !== weightB) return weightA - weightB
      const countA = a.taiwan_market_count ?? a.active_legs_count ?? 0
      const countB = b.taiwan_market_count ?? b.active_legs_count ?? 0
      return countB - countA
    })
  }, [leagues])

  // Filter by sport pill, radar league pill click, dropdown league, & search keyword
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

      // 2. Specific league code filter from radar pill click
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

  // Group filtered legs by cleaned league name (sorted by volume: leagues with more markets first)
  const groupedByLeague = useMemo(() => {
    const map = new Map<string, Leg[]>()
    for (const leg of filteredLegs) {
      const lg = cleanLeagueName(leg.display_league || leg.league || leg.sport)
      if (!map.has(lg)) {
        map.set(lg, [])
      }
      map.get(lg)!.push(leg)
    }
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
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

  function aggregateMatches(leagueLegs: Leg[]): AggregatedMatch[] {
    const matchMap = new Map<string, AggregatedMatch>()
    for (const leg of leagueLegs) {
      const key = String(leg.event_id || `${leg.away_team}-${leg.home_team}`)
      if (!matchMap.has(key)) {
        const ev = leg.signal_evidence || {}
        matchMap.set(key, {
          matchKey: key,
          eventId: leg.event_id || "—",
          awayTeam: leg.away_team,
          homeTeam: leg.home_team,
          gameTime: leg.game_time || leg.start_time || "即時",
          consensus: typeof ev.consensus_ratio === "number" ? ev.consensus_ratio : 0.5,
          voteCount: ev.vote_count ?? undefined,
          options: [],
        })
      }
      matchMap.get(key)!.options.push(leg)
    }
    return Array.from(matchMap.values()).sort((a, b) => {
      if (a.gameTime && b.gameTime && a.gameTime !== b.gameTime) {
        return a.gameTime.localeCompare(b.gameTime)
      }
      return String(a.eventId).localeCompare(String(b.eventId))
    })
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="space-y-4"
    >
      {/* Unified Radar Control & Status Strip Card */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs space-y-3">
        {/* Top Row: Title + Sport Filter Pills + Refresh */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 tracking-tight">
              <Radio className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>賽季開盤雷達</span>
            </h2>
            <div className="flex items-center gap-2.5 text-xs text-slate-500 dark:text-slate-400">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
                開盤中
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
                暫無開盤
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-slate-400 dark:bg-slate-600 inline-block" />
                休賽季
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
            <button
              onClick={() => {
                setSelectedSport("all")
                setSelectedLeagueCode(null)
                setSelectedDropdownLeague("all")
              }}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap ${
                selectedSport === "all" && !selectedLeagueCode && selectedDropdownLeague === "all"
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900 shadow-xs"
                  : "bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
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
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap ${
                    selectedSport === sp && !selectedLeagueCode && selectedDropdownLeague === "all"
                      ? "bg-emerald-600 text-white shadow-xs"
                      : "bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
                  }`}
                >
                  {label} ({count})
                </button>
              )
            })}

            <button
              type="button"
              onClick={() => setRefreshVersion((version) => version + 1)}
              disabled={loading}
              className="ml-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-700 dark:text-slate-300 hover:border-slate-300 disabled:opacity-60 cursor-pointer shrink-0"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>更新盤口</span>
            </button>
          </div>
        </div>

        {/* Compact League Status Pill Strip (Replaces the 12 giant radar cards!) */}
        {loading ? (
          <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-100 dark:border-slate-800/80">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <Skeleton key={i} className="h-8 w-32 rounded-lg" />
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5 pt-2.5 border-t border-slate-100 dark:border-slate-800/80">
            {sortedLeagues.map((lg) => {
              const isGreen = lg.status === "GREEN"
              const isYellow = lg.status === "YELLOW"
              const displayName = cleanLeagueName(lg.name || lg.league_name || lg.code)
              const marketCount = lg.taiwan_market_count ?? lg.active_legs_count ?? 0
              const isSelected = selectedLeagueCode === lg.code

              return (
                <button
                  key={lg.code || lg.league_id || displayName}
                  type="button"
                  onClick={() => toggleLeagueClick(lg.code)}
                  title={`點擊篩選 ${displayName} 開盤項目`}
                  className={`px-2.5 py-1.5 rounded-lg border text-xs transition-colors flex items-center gap-2 cursor-pointer tabular-nums ${
                    isSelected
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 font-medium ring-1 ring-emerald-500"
                      : isGreen
                        ? "border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60 text-slate-800 dark:text-slate-200 hover:border-slate-300 dark:hover:border-slate-700"
                        : isYellow
                          ? "border-slate-200/70 dark:border-slate-800/60 bg-slate-50/30 dark:bg-slate-950/30 text-slate-500 dark:text-slate-400"
                          : "border-slate-200/50 dark:border-slate-800/40 bg-transparent text-slate-400 dark:text-slate-500"
                  }`}
                >
                  <span
                    className={`w-2 h-2 rounded-full shrink-0 ${
                      isGreen ? "bg-emerald-500" : isYellow ? "bg-amber-500" : "bg-slate-400 dark:bg-slate-600"
                    }`}
                  />
                  <span className="font-medium">{displayName}</span>
                  <span
                    className={`font-mono text-xs ${
                      marketCount > 0
                        ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                        : "text-slate-400 dark:text-slate-500"
                    }`}
                  >
                    {marketCount > 0 ? `${marketCount}場` : "無開盤"}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Live Matches Filter Bar & Accordion Controls */}
      <div className="space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm flex items-center gap-1.5">
              <Activity className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>今日開盤盤口：共 {totalOpenMatches} 場賽事 · {legs.length} 盤可選</span>
            </h3>
            <Badge variant="green" className="text-xs font-mono">
              符合篩選 {filteredLegs.length} 盤
            </Badge>
            {(selectedLeagueCode || selectedDropdownLeague !== "all") && (
              <button
                onClick={() => {
                  setSelectedLeagueCode(null)
                  setSelectedDropdownLeague("all")
                }}
                className="text-xs text-emerald-600 dark:text-emerald-400 font-medium hover:underline cursor-pointer"
              >
                清除聯賽篩選
              </button>
            )}
          </div>

          {/* Search Box & League Dropdown Filter + Expand/Collapse */}
          <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap">
            {groupedByLeague.length > 1 && (
              <div className="flex items-center gap-1.5 mr-1">
                <button
                  onClick={expandAllLeagues}
                  className="px-2 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:border-slate-300 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer flex items-center gap-1"
                >
                  <Eye className="w-3.5 h-3.5 text-slate-400" />
                  <span>展開</span>
                </button>
                <button
                  onClick={collapseAllLeagues}
                  className="px-2 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:border-slate-300 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer flex items-center gap-1"
                >
                  <EyeOff className="w-3.5 h-3.5 text-slate-400" />
                  <span>收合</span>
                </button>
              </div>
            )}

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

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : filteredLegs.length === 0 ? (
          <Card className="text-center py-12">
            <CardContent className="text-slate-500 dark:text-slate-400 text-xs">
              目前所選分類沒有符合的即時盤口。
            </CardContent>
          </Card>
        ) : viewMode === "compact" ? (
          /* Compact Table Mode */
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
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
                        {matchCount} 場 · {leagueLegs.length} 盤
                      </span>
                    </div>

                    <div className="text-xs text-slate-400 font-mono">
                      <span>{isCollapsed ? "展開" : "收合"}</span>
                    </div>
                  </div>

                  {/* League Table Content */}
                  {!isCollapsed && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-50/50 dark:bg-slate-950/30 border-b border-slate-200/80 dark:border-slate-800 text-slate-500 font-mono text-xs">
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
                                <td className="p-2.5 text-slate-500 text-xs">
                                  <div>{leg.game_time || leg.start_time || "即時"}</div>
                                  <div className="text-xs text-slate-400 font-mono">#{leg.event_id}</div>
                                </td>
                                <td className="p-2.5 font-sans font-medium text-slate-900 dark:text-slate-100">
                                  {leg.away_team} <span className="text-slate-400 font-normal">vs</span> {leg.home_team}
                                </td>
                                <td className="p-2.5 font-sans">
                                  <span className="text-xs text-slate-400 mr-1.5">[{leg.market}]</span>
                                  <span className="font-medium text-slate-900 dark:text-slate-100">
                                    {cleanSelectionLabel(leg.selection)}
                                  </span>
                                  {!ev.is_market_synthetic && isPositiveEv && (
                                    <span className="ml-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-500/20 px-1 py-0.5 rounded font-mono">
                                      +EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                                    </span>
                                  )}
                                  {!ev.is_market_synthetic && ev.sharp_fair_probability && (
                                    <span className="ml-1 text-xs font-medium text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono">
                                      去水 {(ev.sharp_fair_probability * 100).toFixed(0)}%
                                    </span>
                                  )}
                                  {ev.is_market_synthetic && (
                                    <span className="ml-1 text-xs text-slate-400 bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono">
                                      模擬數據
                                    </span>
                                  )}
                                  {!ev.is_splits_synthetic && ev.is_sharp_money_divergence && (
                                    <span className="ml-1 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-1 py-0.5 rounded">
                                      籌碼分歧
                                    </span>
                                  )}
                                  {lm.is_steam && (
                                    <span className="ml-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-1 py-0.5 rounded">
                                      順勢跳水
                                    </span>
                                  )}
                                  {lm.is_trap_warning && (
                                    <span className="ml-1 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-1 py-0.5 rounded">
                                      升水防禦
                                    </span>
                                  )}
                                </td>
                                <td className="p-2.5 w-44 font-sans">
                                  <VersusBar
                                    awayTeam={leg.away_team.slice(0, 3)}
                                    homeTeam={leg.home_team.slice(0, 3)}
                                    awayRatio={consensus}
                                    voteCount={ev.vote_count ?? undefined}
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
          /* Version C Event-Centric Match Aggregation Mode (All markets of same match grouped in one row!) */
          <div className="space-y-3.5">
            {groupedByLeague.map(([lgName, leagueLegs]) => {
              const isCollapsed = Boolean(collapsedLeagues[lgName])
              const matches = aggregateMatches(leagueLegs)

              return (
                <div
                  key={lgName}
                  className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-xs"
                >
                  {/* League Header */}
                  <div
                    onClick={() => toggleLeagueCollapse(lgName)}
                    className="px-4 py-3 bg-slate-50/80 dark:bg-slate-950/50 hover:bg-slate-100/70 dark:hover:bg-slate-900 transition-colors flex items-center justify-between cursor-pointer select-none border-b border-slate-200/70 dark:border-slate-800"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400">
                        {isCollapsed ? (
                          <ChevronRight className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                        )}
                      </span>
                      <h4 className="font-semibold text-sm text-slate-900 dark:text-slate-100">{lgName}</h4>
                      <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/60">
                        {matches.length} 場賽事 · {leagueLegs.length} 盤口
                      </span>
                    </div>
                    <span className="text-xs text-slate-400 font-mono">
                      {isCollapsed ? "展開" : "收合"}
                    </span>
                  </div>

                  {/* Aggregated Matches List (1 row per match, all market options grouped side-by-side) */}
                  {!isCollapsed && (
                    <div className="divide-y divide-slate-100 dark:divide-slate-800/80">
                      {matches.map((match) => (
                        <div
                          key={match.matchKey}
                          className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4 hover:bg-slate-50/40 dark:hover:bg-slate-950/30 transition-colors"
                        >
                          {/* Left: Match Identity & Public Consensus */}
                          <div className="lg:w-64 shrink-0 space-y-2">
                            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 font-mono">
                              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium">
                                #{match.eventId}
                              </span>
                              <span>{match.gameTime}</span>
                            </div>

                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              {match.awayTeam}{" "}
                              <span className="text-slate-400 font-normal text-xs">客 vs 主</span>{" "}
                              {match.homeTeam}
                            </div>

                            <div className="max-w-xs">
                              <VersusBar
                                awayTeam={match.awayTeam.slice(0, 3)}
                                homeTeam={match.homeTeam.slice(0, 3)}
                                awayRatio={match.consensus}
                                voteCount={match.voteCount}
                              />
                            </div>
                          </div>

                          {/* Right: Grouped Market Options for this single match */}
                          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5 flex-1">
                            {match.options.map((leg, optIdx) => {
                              const evidence = leg.signal_evidence || {}
                              const lm = evidence.line_movement || {}
                              const legEv = evidence.sharp_expected_value_pct ?? evidence.expected_value_pct
                              const isPosEv = typeof legEv === "number" && legEv > 0 && !evidence.is_market_synthetic
                              const cleanedSelection = cleanSelectionLabel(leg.selection)

                              return (
                                <div
                                  key={`${leg.market}-${leg.selection}-${optIdx}`}
                                  className={`px-3 py-2.5 rounded-lg border flex items-center justify-between gap-2 transition-colors ${
                                    isPosEv
                                      ? "bg-emerald-50/30 dark:bg-emerald-950/15 border-emerald-500/30"
                                      : "bg-slate-50/80 dark:bg-slate-950/60 border-slate-200/70 dark:border-slate-800/80"
                                  }`}
                                >
                                  <div className="space-y-1 min-w-0">
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                      <span className="px-1.5 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-700 text-xs font-medium text-slate-600 dark:text-slate-300">
                                        {leg.market}
                                      </span>
                                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-xs sm:text-sm truncate">
                                        {cleanedSelection}
                                      </span>
                                    </div>

                                    <div className="flex items-center gap-1.5 flex-wrap text-xs">
                                      {isPosEv && (
                                        <span className="inline-flex items-center gap-0.5 font-mono font-medium text-emerald-700 dark:text-emerald-400">
                                          <Flame className="w-3 h-3" />
                                          +EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                                        </span>
                                      )}
                                      {lm.is_steam && (
                                        <span className="inline-flex items-center gap-0.5 font-medium text-emerald-700 dark:text-emerald-400">
                                          <TrendingDown className="w-3 h-3" />
                                          順勢跳水
                                        </span>
                                      )}
                                      {lm.is_trap_warning && (
                                        <span className="font-medium text-amber-600 dark:text-amber-400">
                                          升水防禦
                                        </span>
                                      )}
                                      {evidence.sharp_fair_probability && !evidence.is_market_synthetic && (
                                        <span className="inline-flex items-center gap-0.5 font-mono text-slate-500 dark:text-slate-400">
                                          <Scale className="w-3 h-3 text-slate-400" />
                                          去水 {(evidence.sharp_fair_probability * 100).toFixed(0)}%
                                        </span>
                                      )}
                                      {evidence.is_sharp_money_divergence && !evidence.is_splits_synthetic && (
                                        <span className="inline-flex items-center gap-0.5 font-medium text-amber-600 dark:text-amber-400">
                                          <Zap className="w-3 h-3" />
                                          籌碼分歧
                                        </span>
                                      )}
                                      {evidence.is_market_synthetic && (
                                        <span className="text-slate-400 dark:text-slate-500 font-mono">
                                          模擬數據
                                        </span>
                                      )}
                                    </div>
                                  </div>

                                  <div className="text-right shrink-0 pl-2">
                                    <span className="font-semibold font-mono tabular-nums text-slate-900 dark:text-slate-100 text-sm sm:text-base">
                                      {leg.taiwan_odds?.toFixed(2)}x
                                    </span>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ))}
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
