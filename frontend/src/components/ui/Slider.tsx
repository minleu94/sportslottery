import * as React from "react"
import { cn } from "@/lib/utils"

export interface SliderProps {
  min: number
  max: number
  step?: number
  value: number
  onChange: (value: number) => void
  className?: string
  label?: string
  displayValue?: string
}

export const Slider: React.FC<SliderProps> = ({
  min,
  max,
  step = 1,
  value,
  onChange,
  className,
  label,
  displayValue,
}) => {
  const percentage = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex justify-between items-center text-sm">
        {label && <span className="font-medium text-slate-300">{label}</span>}
        <span className="font-bold text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-2.5 py-0.5 rounded-full text-xs">
          {displayValue || `${value}x`}
        </span>
      </div>
      <div className="relative flex items-center select-none touch-none w-full h-5">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500 focus:outline-none"
          style={{
            background: `linear-gradient(to right, #10b981 0%, #10b981 ${percentage}%, #1e293b ${percentage}%, #1e293b 100%)`,
          }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-slate-500 font-mono">
        <span>{min}x</span>
        <span>{Math.round((max + min) / 2)}x</span>
        <span>{max}x</span>
      </div>
    </div>
  )
}
