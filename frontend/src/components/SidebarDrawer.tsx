import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { formatNTD } from "@/lib/utils"
import type { Profile, WalletStatus } from "@/types"
import { useUI } from "@/context/UIContext"
import {
  X,
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
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 cursor-pointer"
          />

          {/* Drawer Content */}
          <motion.aside
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 250 }}
            className="fixed top-0 left-0 bottom-0 w-80 max-w-[85vw] bg-slate-900 border-r border-slate-800 text-slate-100 z-50 flex flex-col shadow-2xl overflow-y-auto"
          >
            {/* Header */}
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-2xl">🐕</span>
                <div>
                  <h2 className="font-black text-sm text-white tracking-tight">瘋狗流決策系統</h2>
                  <span className="text-[10px] font-mono text-emerald-400 font-bold">v2.3.0 Dev 側邊導航</span>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors cursor-pointer"
                title="收起選單 (‹)"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
            </div>

            {/* Profile Quick Card (Matching ui/navigation.py) */}
            <div className="p-4 border-b border-slate-800/80">
              {currentProfile ? (
                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-400 flex items-center gap-1">
                      <User className="w-3.5 h-3.5" />
                      當前登入玩家
                    </span>
                    <span className="text-purple-400 font-bold flex items-center gap-1 text-[11px]">
                      <ShieldCheck className="w-3 h-3" />
                      PIN 保護
                    </span>
                  </div>

                  <div className="font-black text-base text-white tracking-wide">
                    {currentProfile.name}
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/60 text-xs">
                    <div>
                      <span className="text-[10px] text-slate-400 block">💵 本週可用</span>
                      <span className="font-mono font-bold text-sky-400">
                        {formatNTD(wallet?.weekly_wallet_balance ?? 0)}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-400 block">🏆 保留儲備</span>
                      <span className="font-mono font-bold text-emerald-400">
                        {formatNTD(wallet?.prize_pool ?? 0)}
                      </span>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      onClose()
                      onLogout()
                    }}
                    className="w-full mt-2 py-1.5 px-3 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-rose-300 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    🚪 登出當前帳號
                  </button>
                </div>
              ) : (
                <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
                  🔒 尚未登入身分
                </div>
              )}
            </div>

            {/* Navigation System Pages */}
            <div className="p-4 space-y-1.5 flex-1">
              <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider px-2 block mb-2">
                🧭 系統頁面
              </span>

              <button
                onClick={() => {
                  onNavigateHome()
                  onClose()
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl hover:bg-slate-800 text-slate-200 text-xs font-bold transition-colors cursor-pointer text-left"
              >
                <span className="text-base">🐕</span>
                瘋狗流決策台 (首頁)
              </button>

              <button
                onClick={() => {
                  onClose()
                  onOpenMetricGuide()
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl hover:bg-slate-800 text-slate-200 text-xs font-bold transition-colors cursor-pointer text-left"
              >
                <BookOpen className="w-4 h-4 text-emerald-400" />
                📊 指標與資料來源說明
              </button>

              <button
                onClick={() => {
                  onClose()
                  onOpenSystemHealth()
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl hover:bg-slate-800 text-slate-200 text-xs font-bold transition-colors cursor-pointer text-left"
              >
                <Activity className="w-4 h-4 text-sky-400" />
                🔎 資料健康與研究工具
              </button>

              {isAdmin && (
                <button
                  onClick={() => {
                    onClose()
                    onOpenStorageSettings()
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl hover:bg-slate-800 text-slate-200 text-xs font-bold transition-colors cursor-pointer text-left"
                >
                  <Settings className="w-4 h-4 text-indigo-400" />
                  ⚙️ 系統設定與資料存放 (管理員)
                </button>
              )}
            </div>

            {/* Display & Theme Preferences */}
            <div className="p-4 border-t border-slate-800 space-y-3 bg-slate-950/40 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">風格主題</span>
                <div className="flex items-center gap-1 bg-slate-800 p-1 rounded-lg">
                  <button
                    onClick={() => setTheme("light")}
                    className={`p-1.5 rounded ${theme === "light" ? "bg-amber-500 text-white" : "text-slate-400 hover:text-white"}`}
                    title="淺色模式"
                  >
                    <Sun className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setTheme("dark")}
                    className={`p-1.5 rounded ${theme === "dark" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"}`}
                    title="深色模式"
                  >
                    <Moon className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setTheme("system")}
                    className={`p-1.5 rounded ${theme === "system" ? "bg-sky-600 text-white" : "text-slate-400 hover:text-white"}`}
                    title="系統跟隨"
                  >
                    <Laptop className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-slate-400">資料排版</span>
                <button
                  onClick={toggleViewMode}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium cursor-pointer"
                >
                  {viewMode === "compact" ? (
                    <>
                      <TableIcon className="w-3.5 h-3.5 text-emerald-400" />
                      精簡表格
                    </>
                  ) : (
                    <>
                      <LayoutGrid className="w-3.5 h-3.5 text-sky-400" />
                      卡片模式
                    </>
                  )}
                </button>
              </div>

              <div className="pt-2 text-center text-[10px] text-slate-500 font-mono">
                台灣運彩「瘋狗流」決策系統 v2.3.0 Dev
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
