import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "success" | "amber"
  size?: "default" | "sm" | "lg" | "icon"
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    const baseStyles = "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 cursor-pointer active:scale-[0.98]"
    
    const variants = {
      default: "bg-emerald-600 text-white shadow hover:bg-emerald-500",
      destructive: "bg-rose-600 text-white shadow-sm hover:bg-rose-500",
      outline: "border border-slate-700 bg-slate-900/60 shadow-sm hover:bg-slate-800 text-slate-200",
      secondary: "bg-slate-800 text-slate-100 shadow-sm hover:bg-slate-700",
      ghost: "hover:bg-slate-800 hover:text-slate-100 text-slate-300",
      link: "text-emerald-400 underline-offset-4 hover:underline",
      success: "bg-emerald-600 text-white shadow hover:bg-emerald-500 font-semibold",
      amber: "bg-amber-600 text-white shadow hover:bg-amber-500 font-semibold",
    }

    const sizes = {
      default: "h-9 px-4 py-2",
      sm: "h-8 rounded-md px-3 text-xs",
      lg: "h-10 rounded-lg px-8 text-base",
      icon: "h-9 w-9",
    }

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"
