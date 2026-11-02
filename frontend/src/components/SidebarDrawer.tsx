import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { formatNTD } from "@/lib/utils"
import type { Profile, WalletStatus } from "@/types"
import { useUI } from "@/context/UIContext"
import {
  ChevronLeft,
  User,
  ShieldCheck,
  LogOut,
  Radio,
  BookOpen,
  Activity,
  Settings,
  Sun,
  Moon,
  Laptop,
  Table as TableIcon,
  LayoutGrid,
} from "lucide-react"

interface SidebarDrawerProps {
  open: boolean
  onClose: () => void
  currentProfile: Profile | null
  wallet: WalletStatus | null
  onLogout: () => void
  onOpenMetricGuide: () => void
  onOpenSystemHealth: () => void
  onOpenStorageSettings: () => void
  onNavigateHome: () => void
}

export const SidebarDrawer: React.FC<SidebarDrawerProps> = ({
  open,
  onClose,
  currentProfile,
  wallet,
  onLogout,
  onOpenMetricGuide,
  onOpenSystemHealth,
  onOpenStorageSettings,
  onNavigateHome,
}) => {
  const { theme, setTheme, viewMode, toggleViewMode } = useUI()

  const isAdmin = currentProfile?.name === "Archie" || currentProfile?.id === "default"

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs z-50 cursor-pointer"
          />

          {/* Drawer Content */}
          <motion.aside
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 300 }}
            className="fixed top-0 left-0 bottom-0 w-80 max-w-[85vw] bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100 z-50 flex flex-col shadow-xl overflow-y-auto"
          >
            {/* Header */}
            <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-600 dark:text-emerald-400 font-mono font-bold text-xs select-none">
                  MDS
                </div>
                <div>
                  <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100 tracking-tight">
                    瘋狗流決策系統
                  </h2>
                  <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400">
                    v2.3.0 · 系統選單
                  </span>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors cursor-pointer"
                title="收起選單"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
            </div>

            {/* Profile Quick Card */}
            <div className="p-4 border-b border-slate-200 dark:border-slate-800">
              {currentProfile ? (
                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800/80 space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1.5 font-medium">
                      <User className="w-3.5 h-3.5" />
                      當前登入玩家
                    </span>
                    <span className="text-slate-600 dark:text-slate-400 font-medium flex items-center gap-1 text-[11px]">
                      <ShieldCheck className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                      PIN 保護
                    </span>
                  </div>

                  <div className="font-semibold text-base text-slate-900 dark:text-slate-100 tracking-tight">
                    {currentProfile.name}
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-200/80 dark:border-slate-800 text-xs">
                    <div>
                      <span className="text-[10px] text-slate-500 dark:text-slate-400 block">本週可用</span>
                      <span className="font-mono font-medium text-slate-900 dark:text-slate-200">
                        {formatNTD(wallet?.weekly_wallet_balance ?? 0)}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 dark:text-slate-400 block">保留儲備</span>
                      <span className="font-mono font-medium text-emerald-600 dark:text-emerald-400">
                        {formatNTD(wallet?.prize_pool ?? 0)}
                      </span>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      onClose()
                      onLogout()
                    }}
                    className="w-full mt-2 py-1.5 px-3 rounded-lg bg-rose-50 dark:bg-rose-950/30 hover:bg-rose-100 dark:hover:bg-rose-900/40 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    登出帳號
                  </button>
                </div>
              ) : (
                <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 text-xs">
                  尚未登入身分
                </div>
              )}
            </div>

            {/* Navigation System Pages */}
            <div className="p-3 space-y-1 flex-1">
              <span className="text-[11px] font-medium text-slate-400 px-3 py-1 block">
                功能導航
              </span>

              <button
                onClick={() => {
                  onNavigateHome()
                  onClose()
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 text-xs font-medium transition-colors cursor-pointer text-left"
              >
                <Radio className="w-4 h-4 text-slate-400" />
                <span>開盤即時盤口</span>
              </button>

              <button
                onClick={() => {
                  onClose()
                  onOpenMetricGuide()
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 text-xs font-medium transition-colors cursor-pointer text-left"
              >
                <BookOpen className="w-4 h-4 text-slate-400" />
                <span>指標與資料來源說明</span>
              </button>

              <button
                onClick={() => {
                  onClose()
                  onOpenSystemHealth()
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 text-xs font-medium transition-colors cursor-pointer text-left"
              >
                <Activity className="w-4 h-4 text-slate-400" />
                <span>系統健康與資料狀態</span>
              </button>

              {isAdmin && (
                <button
                  onClick={() => {
                    onClose()
                    onOpenStorageSettings()
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 text-xs font-medium transition-colors cursor-pointer text-left"
                >
                  <Settings className="w-4 h-4 text-slate-400" />
                  <span>系統儲存路徑與設定</span>
                </button>
              )}
            </div>

            {/* Display & Theme Preferences */}
            <div className="p-4 border-t border-slate-200 dark:border-slate-800 space-y-3 bg-slate-50 dark:bg-slate-950/30 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">風格主題</span>
                <div className="flex items-center gap-1 bg-slate-200/70 dark:bg-slate-800 p-0.5 rounded-lg">
                  <button
                    onClick={() => setTheme("light")}
                    className={`p-1.5 rounded-md ${theme === "light" ? "bg-white text-slate-900 shadow-xs" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}
                    title="淺色模式"
                  >
                    <Sun className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setTheme("dark")}
                    className={`p-1.5 rounded-md ${theme === "dark" ? "bg-slate-900 text-white shadow-xs" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}
                    title="深色模式"
                  >
                    <Moon className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setTheme("system")}
                    className={`p-1.5 rounded-md ${theme === "system" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-xs" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}
                    title="系統跟隨"
                  >
                    <Laptop className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">行情排版</span>
                <button
                  onClick={toggleViewMode}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700/80 text-slate-700 dark:text-slate-200 font-medium cursor-pointer"
                >
                  {viewMode === "compact" ? (
                    <>
                      <TableIcon className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
                      精簡清單
                    </>
                  ) : (
                    <>
                      <LayoutGrid className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
                      卡片模式
                    </>
                  )}
                </button>
              </div>

              <div className="pt-1 text-center text-[10px] text-slate-400 dark:text-slate-500 font-mono">
                MadDog Sports Lottery Quant Terminal
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
