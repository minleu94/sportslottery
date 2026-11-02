import * as React from "react"
import { cn } from "@/lib/utils"

export const Skeleton: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  ...props
}) => {
  return (
    <div
      className={cn("animate-pulse rounded-lg bg-slate-200/70 dark:bg-slate-800/70", className)}
      {...props}
    />
  )
}
