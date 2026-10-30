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

export const EVHeatmapChart: React.FC<EVHeatmapChartProps> = ({ parlays, targetOdds }) => {
  // 1. Determine dynamic brackets matching current search scale
  let brackets: { label: string; min: number; max: number }[] = []

  if (targetOdds <= 6) {
    // Banker / Low Odds scale
    brackets = [
      { label: "1.5-2.0x", min: 1.5, max: 2.0 },
      { label: "2.0-2.5x", min: 2.0, max: 2.5 },
      { label: "2.5-3.0x", min: 2.5, max: 3.0 },
      { label: "3.0-4.0x", min: 3.0, max: 4.0 },
      { label: "4.0-6.0x", min: 4.0, max: 6.0 },
    ]
  } else if (targetOdds <= 25) {
    // Medium Odds scale
    brackets = [
      { label: "5-10x", min: 5, max: 10 },
      { label: "10-15x", min: 10, max: 15 },
      { label: "15-20x", min: 15, max: 20 },
      { label: "20-25x", min: 20, max: 25 },
      { label: "25x+", min: 25, max: 9999 },
    ]
  } else if (targetOdds <= 75) {
    // High Odds scale
    brackets = [
      { label: "20-35x", min: 20, max: 35 },
      { label: "35-50x", min: 35, max: 50 },
      { label: "50-65x", min: 50, max: 65 },
      { label: "65-80x", min: 65, max: 80 },
      { label: "80x+", min: 80, max: 9999 },
    ]
  } else {
    // Moonshot scale
    brackets = [
      { label: "50-100x", min: 50, max: 100 },
      { label: "100-150x", min: 100, max: 150 },
      { label: "150-250x", min: 150, max: 250 },
      { label: "250-400x", min: 250, max: 400 },
      { label: "400x+", min: 400, max: 9999 },
    ]
  }

  // 2. Aggregate real data
  const chartData = brackets.map((b) => {
    const items = parlays.filter((p) => p.total_odds >= b.min && p.total_odds < b.max)
    const count = items.length

    let avgEV = 0
    let avgWinProb = 0

    if (count > 0) {
      const sumEV = items.reduce((acc, p) => {
        const ev = p.parlay_ev_pct ?? (p.expected_value ? p.expected_value * 100 : 0)
        return acc + ev
      }, 0)
      const sumProb = items.reduce((acc, p) => {
        const prob = p.joint_probability ?? (1 / p.total_odds)
        return acc + prob
      }, 0)
      avgEV = sumEV / count
      avgWinProb = (sumProb / count) * 100
    }

    return {
      bracket: b.label,
      count: count,
      evPercent: Number(avgEV.toFixed(1)),
      winProbPercent: Number(avgWinProb.toFixed(1)),
    }
  })

  // Summary statistics
  const totalCombos = parlays.length
  const maxEV = parlays.length > 0
    ? Math.max(...parlays.map((p) => p.parlay_ev_pct ?? (p.expected_value ? p.expected_value * 100 : 0)))
    : 0
  const maxWinProb = parlays.length > 0
    ? Math.max(...parlays.map((p) => (p.joint_probability ?? (1 / p.total_odds)) * 100))
    : 0

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 backdrop-blur p-4 shadow-sm space-y-3">
      {/* Header with Title and Real Metrics */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-200 dark:border-slate-800/80 pb-2.5">
        <div>
          <div className="font-bold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-1.5">
            <span>📊 本次搜尋組合：賠率區間與組合數分佈</span>
            <span className="text-xs font-normal text-slate-500 font-mono">
              (目標倍率：{targetOdds.toFixed(1)}x)
            </span>
          </div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
            統計各賠率區間內搜尋到的推薦串關數及平均期望值。柱狀高度代表該區間組合數量。
          </p>
        </div>

        {/* Quick Stat Badges */}
        <div className="flex items-center gap-2">
          <div className="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-300 text-xs font-semibold">
            🎯 命中組合: <span className="font-mono font-bold">{totalCombos} 組</span>
          </div>
          <div className="px-2.5 py-1 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-700 dark:text-sky-300 text-xs font-semibold">
            🛡️ 最高預估勝率: <span className="font-mono font-bold">{maxWinProb.toFixed(1)}%</span>
          </div>
          {maxEV > 0 && (
            <div className="px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-300 text-xs font-semibold">
              ⚡ 最高 EV: <span className="font-mono font-bold">+{maxEV.toFixed(1)}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Bar Chart of Combo Counts by Bracket */}
      <div className="h-36 w-full pt-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.15)" />
            <XAxis
              dataKey="bracket"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
              unit=" 組"
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "rgba(15, 23, 42, 0.95)",
                borderRadius: "8px",
                border: "1px solid rgba(255,255,255,0.15)",
                color: "#f8fafc",
                fontSize: "12px",
                boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              }}
              formatter={(value: any, name: any, item: any) => {
                if (name === "count") return [`${value} 組`, "推薦組合數"]
                return [value, name]
              }}
              labelFormatter={(label) => `賠率區間：${label}`}
            />
            <Bar dataKey="count" radius={[6, 6, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.count > 0 ? (entry.evPercent > 0 ? "#10b981" : "#3b82f6") : "#64748b33"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Explanation Footnote */}
      <div className="text-[11px] text-slate-500 dark:text-slate-400 bg-slate-100/60 dark:bg-slate-950/40 p-2.5 rounded-lg flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1.5">
          <span>💡</span>
          <span>
            <b>期望值 (+EV) 解讀：</b>期望值 = (預估勝率 × 總賠率) - 1。大於 0% 代表長期投注期望回報高於本金（戰勝台彩抽頭）。
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500 inline-block" /> 正 EV 組合
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-blue-500 inline-block" /> 穩健推薦組合
          </span>
        </div>
      </div>
    </div>
  )
}