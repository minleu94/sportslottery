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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 rounded-xl bg-slate-100 dark:bg-slate-800/50 border border-slate-200/80 dark:border-slate-800/80 animate-pulse" />
        ))}
      </div>
    )
  }

  const pnl = wallet.lifetime_net_profit || 0
  const pnlSign = pnl > 0 ? "+" : ""
  const extTotal = wallet.weekly_external_deposited + wallet.external_deposit_remaining

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-3">
      {/* 1. 本週可用 */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
          <span className="flex items-center gap-1.5 font-medium">
            <Wallet className="w-3.5 h-3.5 text-slate-400" /> 本週可用餘額
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            W{wallet.current_week.split("-W")[1]}
          </span>
        </div>
        <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 tracking-tight">
          {formatNTD(wallet.weekly_wallet_balance)}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex justify-between tabular-nums">
          <span>每週上限 {formatNTD(wallet.weekly_play_cap)}</span>
        </div>
      </div>

      {/* 2. 本週已下注 */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
          <span className="flex items-center gap-1.5 font-medium">
            <Target className="w-3.5 h-3.5 text-slate-400" /> 本週已投注
          </span>
        </div>
        <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 tracking-tight">
          {formatNTD(wallet.weekly_staked)}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 tabular-nums">
          歷史累計 {formatNTD(wallet.lifetime_staked)}
        </div>
      </div>

      {/* 3. 保留儲備池 (獎金) */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
          <span className="flex items-center gap-1.5 font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /> 獲利儲備池
          </span>
          <span className={`tabular-nums font-mono text-[11px] font-medium ${pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500"}`}>
            淨利 {pnlSign}{formatNTD(pnl)}
          </span>
        </div>
        <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 tracking-tight text-emerald-600 dark:text-emerald-400">
          {formatNTD(wallet.prize_pool)}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          鎖定獲利 · 隨時可提領
        </div>
      </div>

      {/* 4. 本週外部補金 */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
          <span className="flex items-center gap-1.5 font-medium">
            <ArrowDownCircle className="w-3.5 h-3.5 text-slate-400" /> 本週外部補金
          </span>
        </div>
        <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 tracking-tight">
          NT$ {wallet.weekly_external_deposited} / {extTotal}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 tabular-nums">
          {wallet.can_deposit ? `可再補 NT$ ${wallet.external_deposit_remaining}` : "已達上限或免補"}
        </div>
      </div>
    </div>
  )
}
