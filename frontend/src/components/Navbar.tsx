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
  Crown,
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
    light: <Sun className="w-3.5 h-3.5 text-amber-500" />,
    dark: <Moon className="w-3.5 h-3.5 text-indigo-400" />,
  }

  const isAdmin = currentProfile?.name === "Archie" || currentProfile?.id === "default"

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 dark:border-slate-800/80 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md transition-colors">
      <div className="max-w-7xl mx-auto px-3 sm:px-4 py-2 sm:py-2.5 xl:py-3 flex flex-col xl:flex-row xl:items-center justify-between gap-2 xl:gap-3">
        {/* Row 1 on < xl (Mobile & Tablet) / Left Section on >= xl (Desktop) */}
        <div className="flex items-center justify-between gap-2 min-w-0">
          {/* Brand & Mascot */}
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            {onToggleSidebar && (
              <button
                onClick={onToggleSidebar}
                className="w-8 h-8 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/60 text-slate-700 dark:text-slate-300 flex items-center justify-center transition-colors cursor-pointer shrink-0"
                title="展開系統側邊欄"
                aria-label="打開側邊欄"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            )}

            {/* Dog Mascot Logo */}
            <span className="text-2xl select-none leading-none shrink-0" role="img" aria-label="瘋狗流">
              🐕
            </span>

            <div className="min-w-0">
              <div className="flex items-center gap-1.5 sm:gap-2">
                <h1 className="font-semibold text-sm sm:text-base xl:text-lg text-slate-900 dark:text-slate-100 tracking-tight whitespace-nowrap">
                  <span className="hidden sm:inline">台灣運彩 </span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-bold">瘋狗流</span> 決策台
                </h1>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700/70 shrink-0">
                  v2.3.0
                </span>
              </div>
              <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 truncate max-w-[210px] sm:max-w-xs md:max-w-md xl:max-w-none">
                高倍串關期望值分析 · 週額度風控 · 目前【{isAdmin ? "👑 管理員 Archie" : (currentProfile?.name || "主帳號")}】
              </p>
            </div>
          </div>

          {/* Quick Controls on Mobile & Tablet (< xl) */}
          <div className="flex xl:hidden items-center gap-1.5 shrink-0">
            {/* View Mode Toggle (sm:flex) */}
            <button
              onClick={toggleViewMode}
              className="hidden sm:flex items-center gap-1 px-2 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer"
              title="切換檢視模式"
            >
              {viewMode === "cards" ? <TableIcon className="w-3.5 h-3.5" /> : <LayoutGrid className="w-3.5 h-3.5" />}
              <span className="hidden md:inline">{viewMode === "cards" ? "緊湊" : "卡片"}</span>
            </button>

            {/* Theme Toggle */}
            <button
              onClick={cycleTheme}
              className="p-1.5 sm:px-2 sm:py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-slate-600 dark:text-slate-300 transition-colors cursor-pointer flex items-center gap-1 text-xs"
              title="切換深淺模式"
            >
              {themeIcon[theme]}
              <span className="hidden md:inline capitalize">{theme === "system" ? "自動" : theme === "light" ? "亮色" : "暗色"}</span>
            </button>

            {/* Refresh */}
            <button
              onClick={onRefresh}
              disabled={refreshing}
              className="p-1.5 sm:px-2 sm:py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-slate-600 dark:text-slate-300 transition-colors cursor-pointer flex items-center gap-1 text-xs"
              title="更新盤口與即時賠率"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin text-emerald-500" : ""}`} />
              <span className="hidden md:inline">更新盤口</span>
            </button>

            {/* Profile Quick Chip on Mobile & Tablet */}
            {currentProfile && (
              <button
                onClick={() => onTabChange("profile")}
                className={`flex items-center gap-1 px-2 py-1.5 rounded-lg border text-xs font-medium transition-all cursor-pointer ${
                  isAdmin
                    ? "bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/30 text-amber-700 dark:text-amber-300"
                    : "bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800 dark:hover:bg-slate-700/80 border-slate-200 dark:border-slate-700/70 text-slate-700 dark:text-slate-300"
                }`}
                title="前往帳號設定與權限總覽"
              >
                {isAdmin ? (
                  <>
                    <Crown className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                    <span className="font-semibold max-w-[70px] sm:max-w-none truncate">{currentProfile.name}</span>
                  </>
                ) : (
                  <>
                    <User className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span className="max-w-[60px] sm:max-w-none truncate">{currentProfile.name}</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Navigation Tabs Bar & Desktop Controls (XL) */}
        <div className="flex items-center justify-between xl:justify-end gap-2 overflow-x-auto scrollbar-none pb-0.5 xl:pb-0 min-w-0">
          {/* Navigation Segments */}
          <div className="flex bg-slate-100/90 dark:bg-slate-950/80 p-1 rounded-xl border border-slate-200/80 dark:border-slate-800 shrink-0">
            {tabs.map((tab) => {
              const active = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => onTabChange(tab.id)}
                  className={`flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap cursor-pointer ${
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

          {/* Desktop Controls (XL only - to keep single row clean on large displays) */}
          <div className="hidden xl:flex items-center gap-1.5 shrink-0">
            {/* Desktop View Mode Toggle */}
            <button
              onClick={toggleViewMode}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer"
              title="切換檢視模式"
            >
              {viewMode === "cards" ? <TableIcon className="w-3.5 h-3.5" /> : <LayoutGrid className="w-3.5 h-3.5" />}
              <span>{viewMode === "cards" ? "緊湊" : "卡片"}</span>
            </button>

            {/* Desktop Theme Switcher */}
            <button
              onClick={cycleTheme}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 transition-colors cursor-pointer"
              title="切換深淺模式"
            >
              {themeIcon[theme]}
              <span className="capitalize">{theme === "system" ? "自動" : theme === "light" ? "亮色" : "暗色"}</span>
            </button>

            {/* Desktop Refresh Button */}
            <button
              onClick={onRefresh}
              disabled={refreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-slate-700/70 text-xs font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors cursor-pointer"
              title="更新盤口與即時賠率"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin text-emerald-500" : ""}`} />
              <span>更新盤口</span>
            </button>

            {/* Desktop Profile Quick Link */}
            {currentProfile && (
              <button
                onClick={() => onTabChange("profile")}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all cursor-pointer ${
                  isAdmin
                    ? "bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/30 text-amber-700 dark:text-amber-300 shadow-xs"
                    : "bg-slate-100 hover:bg-slate-200/70 dark:bg-slate-800/80 dark:hover:bg-slate-700/80 border-slate-200 dark:border-slate-700/70 text-slate-700 dark:text-slate-300"
                }`}
                title="點擊前往個人帳號與風控設定"
              >
                {isAdmin ? (
                  <>
                    <Crown className="w-3.5 h-3.5 text-amber-500" />
                    <span className="font-semibold">👑 管理員 · {currentProfile.name}</span>
                  </>
                ) : (
                  <>
                    <User className="w-3.5 h-3.5 text-slate-400" />
                    <span>👤 {currentProfile.name}</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
