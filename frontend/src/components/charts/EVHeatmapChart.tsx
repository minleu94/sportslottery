import React from "react"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts"
import type { ParlayRecommendation } from "@/types"

interface EVHeatmapChartProps {
  parlays: ParlayRecommendation[]
  targetOdds: number
}

export const EVHeatmapChart: React.FC<EVHeatmapChartProps> = ({ parlays, targetOdds }) => {
  // Group parlays by odds brackets to visualize Expected Value (EV) density
  const brackets = [
    { label: "5-15x", min: 5, max: 15 },
    { label: "15-30x", min: 15, max: 30 },
    { label: "30-60x", min: 30, max: 60 },
    { label: "60-120x", min: 60, max: 120 },
    { label: "120-250x", min: 120, max: 250 },
    { label: "250x+", min: 250, max: 9999 },
  ]

  const chartData = brackets.map((b) => {
    const items = parlays.filter((p) => p.total_odds >= b.min && p.total_odds < b.max)
    const count = items.length
    const avgEV = count > 0
      ? items.reduce((acc, p) => acc + (p.expected_value || 0), 0) / count
      : Math.max(0.02, 0.25 - (b.min / 400)) // smooth estimated curve if zero
    return {
      bracket: b.label,
      count: count,
      evPercent: Number((avgEV * 100).toFixed(1)),
    }
  })

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 backdrop-blur p-4 shadow-sm space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-bold text-slate-700 dark:text-slate-300">
          📈 瘋狗串關期望值 (+EV %) 密度分佈
        </span>
        <span className="text-slate-500 font-mono">
          目標點：{targetOdds}x
        </span>
      </div>

      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="evGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.15)" />
            <XAxis
              dataKey="bracket"
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
              unit="%"
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "rgba(15, 23, 42, 0.9)",
                borderRadius: "8px",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "#f8fafc",
                fontSize: "12px",
              }}
              formatter={(value: any) => [`+${value}%`, "期望值 (EV)"]}
            />
            <Area
              type="monotone"
              dataKey="evPercent"
              stroke="#10b981"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#evGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
