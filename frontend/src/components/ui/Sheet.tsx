import * as React from "react"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

export interface SheetProps {
  open: boolean
  onClose: () => void
  title?: React.ReactNode
  description?: React.ReactNode
  children: React.ReactNode
  side?: "right" | "left" | "bottom"
  className?: string
}

export const Sheet: React.FC<SheetProps> = ({
  open,
  onClose,
  title,
  description,
  children,
  side = "right",
  className,
}) => {
  // Lock body scroll when open
  React.useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = "unset"
    }
    return () => {
      document.body.style.overflow = "unset"
    }
  }, [open])

  if (!open) return null

  const sideAnimations = {
    right: "inset-y-0 right-0 h-full w-full sm:max-w-xl border-l animate-in slide-in-from-right duration-300",
    left: "inset-y-0 left-0 h-full w-full sm:max-w-xl border-r animate-in slide-in-from-left duration-300",
    bottom: "inset-x-0 bottom-0 max-h-[85vh] w-full border-t rounded-t-2xl animate-in slide-in-from-bottom duration-300",
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity animate-in fade-in duration-200"
        onClick={onClose}
      />
      
      {/* Drawer content */}
      <div
        className={cn(
          "fixed z-50 flex flex-col bg-slate-900 border-slate-800 text-slate-100 shadow-2xl overflow-hidden",
          sideAnimations[side],
          className
        )}
      >
        <div className="flex items-center justify-between border-b border-slate-800 p-5 bg-slate-950/60">
          <div>
            {title && <h2 className="text-lg font-semibold text-slate-100">{title}</h2>}
            {description && <p className="text-sm text-slate-400 mt-0.5">{description}</p>}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {children}
        </div>
      </div>
    </div>
  )
}
