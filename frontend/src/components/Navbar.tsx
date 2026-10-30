import React from "react"
import { Flame, Radio, Wallet, User, BarChart2, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/Badge"
import type { Profile } from "@/types"

export type NavTab = "radar" | "parlay" | "wallet" | "profile" | "research"

interface NavbarProps {
  activeTab: NavTab
  onTabChange: (tab: NavTab) => void
  currentProfile: Profile | null
  onRefresh: () => void
  refreshing: boolean
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  onTabChange,
  currentProfile,
  onRefresh,
  refreshing,
}) => {
  const tabs: { id: NavTab; label: string; icon: React.ReactNode }[] = [
    { id: "radar", label: "今日開盤", icon: <Radio className="w-4 h-4" /> },
    { id: "parlay", label: "瘋狗看盤", icon: <Flame className="w-4 h-4 text-amber-500" /> },
    { id: "wallet", label: "資金帳本", icon: <Wallet className="w-4 h-4" /> },
    { id: "profile", label: "個人設定", icon: <User className="w-4 h-4" /> },
    { id: "research", label: "影子前瞻", icon: <BarChart2 className="w-4 h-4" /> },
  ]

  return (
    <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 py-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Logo & Title */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl select-none">🐕</span>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-black text-lg text-slate-100 tracking-tight">
                  台灣運彩 <span className="text-emerald-400">瘋狗流</span> 決策台
                </h1>
                <Badge variant="green" className="text-[10px] px-1.5 py-0 font-mono">v2.0 Modern</Badge>
              </div>
              <p className="text-xs text-slate-400">
                10~500倍 串關決策 · 週額度風控 · 玩家【{currentProfile?.name || "主帳號"}】
              </p>
            </div>
          </div>

          {/* Mobile Refresh Button */}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="md:hidden p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 hover:text-white"
            title="重新整理盤口"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin text-emerald-400" : ""}`} />
          </button>
        </div>

        {/* Navigation Segments */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 scrollbar-none">
          <div className="flex bg-slate-900/90 p-1 rounded-xl border border-slate-800/80">
            {tabs.map((tab) => {
              const active = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => onTabChange(tab.id)}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap cursor-pointer ${
                    active
                      ? "bg-emerald-600 text-white shadow-sm"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Desktop Refresh Button */}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="hidden md:flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs font-medium text-slate-300 hover:text-white hover:border-slate-700 transition-colors cursor-pointer"
            title="更新盤口與即時賠率"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin text-emerald-400" : ""}`} />
            <span>更新盤口</span>
          </button>
        </div>
      </div>
    </header>
  )
}
