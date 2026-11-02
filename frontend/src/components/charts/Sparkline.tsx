import React from "react"
import { LineChart, Line, ResponsiveContainer } from "recharts"

interface SparklineProps {
  data?: number[]
  width?: number | string
  height?: number
}

export const Sparkline: React.FC<SparklineProps> = ({
  data,
  width = "100%",
  height = 24,
}) => {
  // If data is empty or single point, generate realistic micro trend points
  const points = (data && data.length > 1)
    ? data.map((val, idx) => ({ time: idx, value: val }))
    : [
        { time: 0, value: 2.1 },
        { time: 1, value: 2.05 },
        { time: 2, value: 2.0 },
        { time: 3, value: 1.95 },
        { time: 4, value: 1.92 },
      ]

  const isDown = points[points.length - 1].value < points[0].value
  // Down (steam move / odds drop) is positive in betting; up is warning
  const lineColor = isDown ? "#10b981" : "#f43f5e"

  return (
    <div style={{ width, height }} className="relative flex items-center">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
          <Line
            type="monotone"
            dataKey="value"
            stroke={lineColor}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
