import React from "react"
import { Users } from "lucide-react"

interface VersusBarProps {
  awayTeam: string
  homeTeam: string
  awayRatio?: number
  homeRatio?: number
  voteCount?: number
  className?: string
}

export const VersusBar: React.FC<VersusBarProps> = ({
  awayTeam,
  homeTeam,
  awayRatio = 0.45,
  homeRatio = 0.55,
  voteCount,
  className = "",
}) => {
  const awayPct = Math.round(awayRatio * 100)
  const homePct = 100 - awayPct

  return (
    <div className={`space-y-1.5 ${className}`}>
      <div className="flex items-center justify-between text-[11px] font-semibold">
        <span className="text-sky-600 dark:text-sky-400 flex items-center gap-1">
          {awayTeam} <strong className="tabular-nums font-mono">{awayPct}%</strong>
        </span>
        <span className="text-[10px] text-slate-600 dark:text-slate-300 flex items-center gap-1 font-mono">
          <Users className="w-3 h-3" />
          {voteCount ? `${voteCount}票` : "社群對決"}
        </span>
        <span className="text-amber-600 dark:text-amber-400 flex items-center gap-1">
          <strong className="tabular-nums font-mono">{homePct}%</strong> {homeTeam}
        </span>
      </div>

      {/* Dual Gradient Progress Track */}
      <div className="relative h-2 w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden flex">
        <div
          className="h-full bg-gradient-to-r from-sky-500 to-sky-400 transition-all duration-500"
          style={{ width: `${awayPct}%` }}
        />
        <div
          className="h-full bg-gradient-to-l from-amber-500 to-amber-400 transition-all duration-500"
          style={{ width: `${homePct}%` }}
        />
      </div>
    </div>
  )
}
