import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "success" | "amber"
  size?: "default" | "sm" | "lg" | "icon"
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    const baseStyles = "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500 disabled:pointer-events-none disabled:opacity-40 cursor-pointer active:scale-[0.98]"
    
    const variants = {
      default: "bg-emerald-600 text-white hover:bg-emerald-500 dark:bg-emerald-600 dark:hover:bg-emerald-500 shadow-xs",
      destructive: "bg-rose-600 text-white hover:bg-rose-500 dark:bg-rose-600 dark:hover:bg-rose-500 shadow-xs",
      outline: "border border-slate-300 dark:border-slate-700/80 bg-transparent hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200",
      secondary: "bg-slate-100 dark:bg-slate-800/90 text-slate-800 dark:text-slate-100 hover:bg-slate-200 dark:hover:bg-slate-700/80 border border-slate-200/60 dark:border-slate-700/50",
      ghost: "hover:bg-slate-100 dark:hover:bg-slate-800/80 hover:text-slate-900 dark:hover:text-slate-100 text-slate-600 dark:text-slate-400",
      link: "text-emerald-600 dark:text-emerald-400 underline-offset-4 hover:underline p-0 h-auto",
      success: "bg-emerald-600 text-white hover:bg-emerald-500 shadow-xs",
      amber: "bg-amber-600 text-white hover:bg-amber-500 shadow-xs",
    }

    const sizes = {
      default: "h-9 px-3.5 py-1.5",
      sm: "h-8 rounded-md px-2.5 text-xs",
      lg: "h-10 rounded-lg px-6 text-sm sm:text-base",
      icon: "h-8 w-8 rounded-lg",
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
