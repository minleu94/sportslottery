import React from "react"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import type { ParlayRecommendation } from "@/types"

interface EVHeatmapChartProps {
  parlays: ParlayRecommendation[]
  targetOdds: number
}

// Custom high-contrast tooltip matching unslop tokens
const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-3 rounded-lg shadow-md text-xs space-y-1 z-50 min-w-40">
        <div className="font-medium text-slate-900 dark:text-slate-100 border-b border-slate-100 dark:border-slate-800 pb-1 flex items-center justify-between gap-3">
          <span>區間：{label}</span>
          <span className="font-mono text-emerald-600 dark:text-emerald-400 tabular-nums">{data.count} 組</span>
        </div>
        <div className="flex items-center justify-between gap-4 text-slate-600 dark:text-slate-300">
          <span className="text-slate-400">推薦組合：</span>
          <span className="font-medium font-mono tabular-nums">{data.count} 組</span>
        </div>
        {data.count > 0 && (
          <>
            <div className="flex items-center justify-between gap-4 text-slate-600 dark:text-slate-300">
              <span className="text-slate-400">平均勝率：</span>
              <span className="font-medium font-mono tabular-nums">{data.winProbPercent}%</span>
            </div>
            <div className="flex items-center justify-between gap-4 text-slate-600 dark:text-slate-300">
              <span className="text-slate-400">平均期望值：</span>
              <span className={`font-medium font-mono tabular-nums ${data.evPercent > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>
                {data.evPercent > 0 ? `+${data.evPercent}%` : `${data.evPercent}%`}
              </span>
            </div>
          </>
        )}
      </div>
    )
  }
  return null
}

export const EVHeatmapChart: React.FC<EVHeatmapChartProps> = ({ parlays, targetOdds }) => {
  // 1. Determine dynamic brackets matching current search scale
  let brackets: { label: string; min: number; max: number }[] = []

  if (targetOdds <= 6) {
    brackets = [
      { label: "1.5-2.0x", min: 1.5, max: 2.0 },
      { label: "2.0-2.5x", min: 2.0, max: 2.5 },
      { label: "2.5-3.0x", min: 2.5, max: 3.0 },
      { label: "3.0-4.0x", min: 3.0, max: 4.0 },
      { label: "4.0-6.0x", min: 4.0, max: 6.0 },
    ]
  } else if (targetOdds <= 25) {
    brackets = [
      { label: "6-10x", min: 6, max: 10 },
      { label: "10-15x", min: 10, max: 15 },
      { label: "15-20x", min: 15, max: 20 },
      { label: "20-25x", min: 20, max: 25 },
      { label: "25x+", min: 25, max: 999 },
    ]
  } else if (targetOdds <= 100) {
    brackets = [
      { label: "25-40x", min: 25, max: 40 },
      { label: "40-60x", min: 40, max: 60 },
      { label: "60-80x", min: 60, max: 80 },
      { label: "80-100x", min: 80, max: 100 },
      { label: "100x+", min: 100, max: 999 },
    ]
  } else {
    brackets = [
      { label: "75-120x", min: 75, max: 120 },
      { label: "120-200x", min: 120, max: 200 },
      { label: "200-300x", min: 200, max: 300 },
      { label: "300-500x", min: 300, max: 500 },
      { label: "500x+", min: 500, max: 9999 },
    ]
  }

  // 2. Aggregate metrics for each bracket
  const chartData = brackets.map((b) => {
    const inBracket = parlays.filter((p) => p.total_odds >= b.min && p.total_odds < b.max)
    const count = inBracket.length

    let avgEV = 0
    let avgWinProb = 0

    if (count > 0) {
      const sumEV = inBracket.reduce((sum, p) => {
        const val = p.parlay_ev_pct ?? (p.expected_value ? p.expected_value * 100 : 0)
        return sum + val
      }, 0)
      avgEV = sumEV / count

      const sumWin = inBracket.reduce((sum, p) => sum + (p.joint_probability || 0), 0)
      avgWinProb = (sumWin / count) * 100
    }

    return {
      bracket: b.label,
      count: count,
      evPercent: Number(avgEV.toFixed(1)),
      winProbPercent: Number(avgWinProb.toFixed(1)),
    }
  })

  const totalCombos = parlays.length
  const maxWinProb = Math.max(...parlays.map((p) => (p.joint_probability || 0) * 100), 0)
  const maxEV = Math.max(
    ...parlays.map((p) => p.parlay_ev_pct ?? (p.expected_value ? p.expected_value * 100 : 0)),
    0
  )

  return (
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 space-y-3 shadow-xs">
      {/* Title & Key Highlight Badges */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
        <div>
          <h4 className="font-medium text-slate-900 dark:text-slate-100 text-sm">
            串關期望值分布 (EV Density Distribution)
          </h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            各賠率區間組合密度與期望值分佈
          </p>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          <div className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-mono">
            命中組合: <span className="font-semibold tabular-nums">{totalCombos} 組</span>
          </div>
          <div className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-mono">
            最高預估勝率: <span className="font-semibold text-emerald-600 dark:text-emerald-400 tabular-nums">{maxWinProb.toFixed(1)}%</span>
          </div>
          {maxEV > 0 && (
            <div className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-mono">
              最高 EV: <span className="font-semibold text-emerald-600 dark:text-emerald-400 tabular-nums">+{maxEV.toFixed(1)}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Bar Chart of Combo Counts by Bracket */}
      <div className="h-36 w-full pt-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.12)" />
            <XAxis
              dataKey="bracket"
              tick={{ fontSize: 11, fill: "#8b949e" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#8b949e" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
              unit=" 組"
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.count > 0 ? (entry.evPercent > 0 ? "#10b981" : "#475569") : "#e2e8f0"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Explanation Footnote */}
      <div className="text-[11px] text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-950/40 p-2.5 rounded-lg flex items-center justify-between flex-wrap gap-2">
        <div>
          <span>
            <b>期望值 (+EV) 解讀：</b>期望值 = (預估勝率 × 總賠率) - 1。大於 0% 代表長期投注期望回報高於本金。
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> 正 EV 組合
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-slate-500 inline-block" /> 穩健推薦組合
          </span>
        </div>
      </div>
    </div>
  )
}
