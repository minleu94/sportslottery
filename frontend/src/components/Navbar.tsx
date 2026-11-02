import React from "react"
import {
  Flame,
  Radio,
  Wallet,
  User,
  BarChart2,
  RefreshCw,
  Sun,
  Moon,
  Laptop,
  LayoutGrid,
  Table as TableIcon,
  ChevronRight,
} from "lucide-react"
import { useUI, type ThemeMode } from "@/context/UIContext"
import type { Profile } from "@/types"

export type NavTab = "radar" | "parlay" | "wallet" | "profile" | "research"

interface NavbarProps {
  activeTab: NavTab
  onTabChange: (tab: NavTab) => void
  currentProfile: Profile | null
  onRefresh: () => void
  refreshing: boolean
  onToggleSidebar?: () => void
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  onTabChange,
  currentProfile,
  onRefresh,
  refreshing,
  onToggleSidebar,
}) => {
  const { theme, setTheme, viewMode, toggleViewMode } = useUI()

  const tabs: { id: NavTab; label: string; icon: React.ReactNode }[] = [
    { id: "radar", label: "今日開盤", icon: <Radio className="w-4 h-4" /> },
    { id: "parlay", label: "串關決策", icon: <Flame className="w-4 h-4" /> },
    { id: "wallet", label: "資金帳本", icon: <Wallet className="w-4 h-4" /> },
    { id: "profile", label: "帳號設定", icon: <User className="w-4 h-4" /> },
    { id: "research", label: "市場研究", icon: <BarChart2 className="w-4 h-4" /> },
  ]

  const nextTheme: Record<ThemeMode, ThemeMode> = {
    system: "light",
    light: "dark",
    dark: "system",
  }

  function cycleTheme() {
    setTheme(nextTheme[theme])
  }

  const themeIcon = {
    system: <Laptop className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />,
    light: <Sun className="w-3.5 h-3.5 text-slate-600 dark:text-slate-400" />,
    dark: <Moon className="w-3.5 h-3.5 text-slate-400" />,
  }

  return (
    <header className="border-b border-slate-200/80 dark:border-slate-800/80 bg-white/95 dark:bg-slate-900/90 backdrop-blur-md md:sticky md:top-0 z-40 transition-colors">
      <div className="max-w-7xl mx-auto px-4 py-2.5 md:py-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Brand & Identity */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {onToggleSidebar && (
              <button
                onClick={onToggleSidebar}
                className="w-8 h-8 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/60 text-slate-700 dark:text-slate-300 flex items-center justify-center transition-colors cursor-pointer"
                title="展開系統側邊欄"
                aria-label="打開側邊欄"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            )}

            {/* Geometric Quant Emblem */}
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 dark:bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-600 dark:text-emerald-400 font-mono font-bold text-xs select-none shadow-xs">
              MDS
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-semibold text-base sm:text-lg text-slate-900 dark:text-slate-100 tracking-tight">
                  台灣運彩 <span className="text-emerald-600 dark:text-emerald-400 font-bold">瘋狗流</span> 決策台
                </h1>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700/70">
                  v2.3.0
                </span>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-1">
                高倍串關期望值分析 · 週額度風控 · 玩家【{currentProfile?.name || "主帳號"}】
              </p>
            </div>
          </div>

          {/* Mobile Action Controls */}
          <div className="flex md:hidden items-center gap-1.5">
            <button
              onClick={cycleTheme}
              className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/80 text-slate-600 dark:text-slate-300"
              title="切換深淺模式"
            >
              {themeIcon[theme]}
            </button>
            <button
              onClick={onRefresh}
              disabled={refreshing}
              className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/80 text-slate-600 dark:text-slate-300"
              title="刷新盤口"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin text-emerald-500" : ""}`} />
            </button>
          </div>
        </div>

        {/* Quiet Navigation Tabs */}
        <div className="sticky top-0 z-30 -mx-4 px-4 py-1.5 bg-white/95 dark:bg-slate-900/95 md:static md:p-0 md:bg-transparent md:dark:bg-transparent flex items-center gap-2 overflow-x-auto scrollbar-none">
          <div className="flex bg-slate-100/90 dark:bg-slate-950/80 p-1 rounded-xl border border-slate-200/80 dark:border-slate-800 shrink-0">
            {tabs.map((tab) => {
              const active = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => onTabChange(tab.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap cursor-pointer ${
                    active
                      ? "bg-white dark:bg-slate-800 text-emerald-700 dark:text-emerald-400 border border-slate-200/90 dark:border-slate-700/70 shadow-xs"
                      : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-200/40 dark:hover:bg-slate-800/40"
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Desktop Compact Toggle */}
          <button
            onClick={toggleViewMode}
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer"
            title="切換檢視模式"
          >
            {viewMode === "cards" ? <TableIcon className="w-3.5 h-3.5" /> : <LayoutGrid className="w-3.5 h-3.5" />}
            <span>{viewMode === "cards" ? "緊湊" : "卡片"}</span>
          </button>

          {/* Desktop Theme Switcher */}
          <button
            onClick={cycleTheme}
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer"
            title="切換深淺模式"
          >
            {themeIcon[theme]}
            <span className="capitalize">{theme === "system" ? "自動" : theme === "light" ? "亮色" : "暗色"}</span>
          </button>

          {/* Desktop Refresh Button */}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors cursor-pointer"
            title="更新盤口與即時賠率"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin text-emerald-500" : ""}`} />
            <span>更新盤口</span>
          </button>
        </div>
      </div>
    </header>
  )
}
