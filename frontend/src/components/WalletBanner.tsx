import React from "react"
import type { WalletStatus } from "@/types"
import { formatNTD } from "@/lib/utils"
import { Wallet, Target, ShieldCheck, ArrowDownCircle } from "lucide-react"

interface WalletBannerProps {
  wallet: WalletStatus | null
  loading?: boolean
}

export const WalletBanner: React.FC<WalletBannerProps> = ({ wallet, loading }) => {
  if (loading || !wallet) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 rounded-xl bg-slate-200 dark:bg-slate-900/60 animate-pulse border border-slate-300 dark:border-slate-800" />
        ))}
      </div>
    )
  }

  const pnl = wallet.lifetime_net_profit || 0
  const pnlSign = pnl > 0 ? "+" : ""
  const extTotal = wallet.weekly_external_deposited + wallet.external_deposit_remaining

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
      {/* 1. 本週可用 */}
      <div className="rounded-xl border border-sky-500/20 bg-gradient-to-br from-sky-500/10 dark:from-sky-950/40 to-white/80 dark:to-slate-900/80 backdrop-blur p-4 shadow-sm relative overflow-hidden group hover:border-sky-500/40 transition-colors">
        <div className="flex items-center justify-between text-xs text-sky-600 dark:text-sky-400 font-medium mb-1">
          <span className="flex items-center gap-1.5">
            <Wallet className="w-3.5 h-3.5" /> ① 本週可用餘額
          </span>
        </div>
        <div className="text-2xl font-black tabular-nums text-slate-900 dark:text-sky-100 tracking-tight">
          {formatNTD(wallet.weekly_wallet_balance)}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex justify-between">
          <span className="tabular-nums">上限 {formatNTD(wallet.weekly_play_cap)}</span>
          <span className="text-sky-600 dark:text-sky-400 font-medium">第 {wallet.current_week.split("-W")[1]} 週</span>
        </div>
      </div>

      {/* 2. 本週已下注 */}
      <div className="rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-500/10 dark:from-amber-950/40 to-white/80 dark:to-slate-900/80 backdrop-blur p-4 shadow-sm relative overflow-hidden group hover:border-amber-500/40 transition-colors">
        <div className="flex items-center justify-between text-xs text-amber-600 dark:text-amber-400 font-medium mb-1">
          <span className="flex items-center gap-1.5">
            <Target className="w-3.5 h-3.5" /> ② 本週已下注
          </span>
        </div>
        <div className="text-2xl font-black tabular-nums text-slate-900 dark:text-amber-100 tracking-tight">
          {formatNTD(wallet.weekly_staked)}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 tabular-nums">
          累計投注 {formatNTD(wallet.lifetime_staked)}
        </div>
      </div>

      {/* 3. 保留儲備池 (獎金) */}
      <div className="rounded-xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/10 dark:from-emerald-950/40 to-white/80 dark:to-slate-900/80 backdrop-blur p-4 shadow-sm relative overflow-hidden group hover:border-emerald-500/40 transition-colors">
        <div className="flex items-center justify-between text-xs text-emerald-600 dark:text-emerald-400 font-medium mb-1">
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5" /> ③ 獲利儲備池
          </span>
          <span className={`tabular-nums font-mono ${pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500 font-bold"}`}>
            淨利 {pnlSign}{formatNTD(pnl)}
          </span>
        </div>
        <div className="text-2xl font-black tabular-nums text-slate-900 dark:text-emerald-100 tracking-tight">
          {formatNTD(wallet.prize_pool)}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          鎖定獲利 · 隨時可提領
        </div>
      </div>

      {/* 4. 本週外部補金 */}
      <div className="rounded-xl border border-purple-500/20 bg-gradient-to-br from-purple-500/10 dark:from-purple-950/40 to-white/80 dark:to-slate-900/80 backdrop-blur p-4 shadow-sm relative overflow-hidden group hover:border-purple-500/40 transition-colors">
        <div className="flex items-center justify-between text-xs text-purple-600 dark:text-purple-400 font-medium mb-1">
          <span className="flex items-center gap-1.5">
            <ArrowDownCircle className="w-3.5 h-3.5" /> ④ 本週外部補金
          </span>
        </div>
        <div className="text-2xl font-black tabular-nums text-slate-900 dark:text-purple-100 tracking-tight">
          NT$ {wallet.weekly_external_deposited} / {extTotal}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 tabular-nums">
          {wallet.can_deposit ? `可再補 NT$ ${wallet.external_deposit_remaining}` : "已達上限或免補"}
        </div>
      </div>
    </div>
  )
}
