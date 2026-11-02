import React from "react"
import { Users } from "lucide-react"

interface VersusBarProps {
  awayTeam: string
  homeTeam: string
  awayRatio?: number
  voteCount?: number
  className?: string
}

export const VersusBar: React.FC<VersusBarProps> = ({
  awayTeam,
  homeTeam,
  awayRatio = 0.45,
  voteCount,
  className = "",
}) => {
  const awayPct = Math.round(awayRatio * 100)
  const homePct = 100 - awayPct

  return (
    <div className={`space-y-1 ${className}`}>
      <div className="flex items-center justify-between text-[11px] font-medium">
        <span className="text-slate-700 dark:text-slate-300 flex items-center gap-1">
          {awayTeam} <span className="tabular-nums font-mono text-slate-500">{awayPct}%</span>
        </span>
        <span className="text-[10px] text-slate-400 flex items-center gap-1 font-mono">
          <Users className="w-3 h-3" />
          {voteCount ? `${voteCount}票` : "公眾"}
        </span>
        <span className="text-slate-700 dark:text-slate-300 flex items-center gap-1">
          <span className="tabular-nums font-mono text-slate-500">{homePct}%</span> {homeTeam}
        </span>
      </div>

      {/* Progress Track */}
      <div className="relative h-1.5 w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden flex">
        <div
          className="h-full bg-slate-400 dark:bg-slate-500 transition-all duration-300"
          style={{ width: `${awayPct}%` }}
        />
        <div
          className="h-full bg-emerald-600 dark:bg-emerald-500 transition-all duration-300"
          style={{ width: `${homePct}%` }}
        />
      </div>
    </div>
  )
}
