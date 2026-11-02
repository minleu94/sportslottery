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
    <div className={cn("space-y-1.5", className)}>
      <div className="flex justify-between items-center text-xs">
        {label && <span className="font-medium text-slate-700 dark:text-slate-300">{label}</span>}
        <span className="font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-500/20 px-2 py-0.5 rounded font-mono tabular-nums text-xs">
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
          className="w-full h-2 rounded-lg appearance-none cursor-pointer accent-emerald-600 focus:outline-none"
          style={{
            background: `linear-gradient(to right, #059669 0%, #059669 ${percentage}%, #cbd5e1 ${percentage}%, #cbd5e1 100%)`,
          }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-slate-400 font-mono tabular-nums">
        <span>{min}x</span>
        <span>{max}x</span>
      </div>
    </div>
  )
}
