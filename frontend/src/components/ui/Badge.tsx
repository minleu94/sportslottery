import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "green" | "yellow" | "red" | "amber" | "blue"
}

export const Badge: React.FC<BadgeProps> = ({ className, variant = "default", ...props }) => {
  const variants = {
    default: "border-transparent bg-emerald-500/20 text-emerald-400 border border-emerald-500/30",
    secondary: "border-transparent bg-slate-800 text-slate-300",
    destructive: "border-transparent bg-rose-500/20 text-rose-400 border border-rose-500/30",
    outline: "border-slate-700 text-slate-300",
    green: "border-emerald-500/30 bg-emerald-950/60 text-emerald-400",
    yellow: "border-amber-500/30 bg-amber-950/60 text-amber-300",
    red: "border-rose-500/30 bg-rose-950/60 text-rose-400",
    amber: "border-amber-500/30 bg-amber-900/50 text-amber-300",
    blue: "border-sky-500/30 bg-sky-950/60 text-sky-400",
  }

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        variants[variant],
        className
      )}
      {...props}
    />
  )
}
