import React from "react"
import type { WalletStatus } from "@/types"
import { formatNTD } from "@/lib/utils"
import { Wallet, Target, ShieldCheck, ArrowDownCircle } from "lucide-react"

interface WalletBannerProps {
  wallet: WalletStatus | null
  loading?: boolean
  compact?: boolean
  onNavigateWallet?: () => void
}

export const WalletBanner: React.FC<WalletBannerProps> = ({
  wallet,
  loading,
  compact = false,
  onNavigateWallet,
}) => {
  if (loading || !wallet) {
    if (compact) {
      return (
        <div className="h-11 rounded-xl bg-slate-100 dark:bg-slate-800/50 border border-slate-200/80 dark:border-slate-800/80 animate-pulse my-1.5" />
      )
    }
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
  const weekCode = wallet.current_week?.includes("-W")
    ? `W${wallet.current_week.split("-W")[1]}`
    : wallet.current_week || "本週"

  if (compact) {
    return (
      <button
        type="button"
        onClick={onNavigateWallet}
        disabled={!onNavigateWallet}
        className={`w-full text-left min-h-[44px] rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 px-3.5 py-2 shadow-xs flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 text-xs tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 ${
          onNavigateWallet ? "hover:border-slate-300 dark:hover:border-slate-700 cursor-pointer" : "cursor-default"
        }`}
      >
        <span className="flex flex-wrap items-center gap-x-3.5 gap-y-1">
          {/* 1. 本週可用 */}
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
            <span className="text-slate-500 dark:text-slate-400">本週可用</span>
            <strong className="font-mono font-semibold text-slate-900 dark:text-slate-100 text-xs sm:text-sm">
              {formatNTD(wallet.weekly_wallet_balance)}
            </strong>
            <span className="text-slate-500 dark:text-slate-400 font-mono">
              / {formatNTD(wallet.weekly_play_cap)}
            </span>
          </span>

          <span className="text-slate-200 dark:text-slate-800 hidden sm:inline" aria-hidden="true">|</span>

          {/* 2. 本週已投注 */}
          <span className="flex items-center gap-1.5">
            <span className="text-slate-500 dark:text-slate-400">已投注</span>
            <strong className="font-mono font-semibold text-slate-900 dark:text-slate-100">
              {formatNTD(wallet.weekly_staked)}
            </strong>
            <span className="text-slate-400 dark:text-slate-500 font-mono hidden md:inline">
              (累計 {formatNTD(wallet.lifetime_staked)})
            </span>
          </span>

          <span className="text-slate-200 dark:text-slate-800 hidden sm:inline" aria-hidden="true">|</span>

          {/* 3. 獲利儲備池 */}
          <span className="flex items-center gap-1.5">
            <span className="text-slate-500 dark:text-slate-400">獲利儲備池</span>
            <strong className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">
              {formatNTD(wallet.prize_pool)}
            </strong>
            <span
              className={`font-mono ${
                pnl >= 0 ? "text-emerald-600/80 dark:text-emerald-400/80" : "text-rose-500"
              }`}
            >
              ({pnlSign}{formatNTD(pnl)})
            </span>
          </span>

          <span className="text-slate-200 dark:text-slate-800 hidden lg:inline" aria-hidden="true">|</span>

          {/* 4. 外部補金 */}
          <span className="hidden lg:flex items-center gap-1.5">
            <span className="text-slate-500 dark:text-slate-400">外部補金</span>
            <span className="font-mono font-medium text-slate-700 dark:text-slate-300">
              NT$ {wallet.weekly_external_deposited} / {extTotal}
            </span>
            <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-mono">
              {wallet.can_deposit ? `可補 NT$ ${wallet.external_deposit_remaining}` : "免補"}
            </span>
          </span>
        </span>

        <span className="flex items-center gap-2 ml-auto text-slate-500 dark:text-slate-400 font-mono">
          <span>{weekCode} · 風控護欄保護中</span>
        </span>
        {onNavigateWallet && <span className="sr-only">點擊查看資金帳本詳細資訊</span>}
      </button>
    )
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-3">
      {/* 1. 本週可用 */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
          <span className="flex items-center gap-1.5 font-medium">
            <Wallet className="w-3.5 h-3.5 text-slate-400" /> 本週可用餘額
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            {weekCode}
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
        <div className="text-xl sm:text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100 tracking-tight truncate">
          NT$ {wallet.weekly_external_deposited} / {extTotal}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 tabular-nums">
          {wallet.can_deposit ? `可再補 NT$ ${wallet.external_deposit_remaining}` : "已達上限或免補"}
        </div>
      </div>
    </div>
  )
}
