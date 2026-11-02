import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { WalletStatus, Ticket } from "@/types"
import { formatNTD } from "@/lib/utils"
import { triggerWinConfetti } from "@/lib/confetti"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { Card, CardContent } from "@/components/ui/Card"
import { Dialog } from "@/components/ui/Dialog"
import { Skeleton } from "@/components/ui/Skeleton"
import {
  Wallet,
  Trophy,
  XCircle,
  ArrowUpRight,
  ArrowDownLeft,
  Clock,
  History,
  AlertTriangle,
  Info,
} from "lucide-react"

interface WalletViewProps {
  wallet: WalletStatus | null
  onWalletUpdate: (wallet: WalletStatus) => void
}

export const WalletView: React.FC<WalletViewProps> = ({ wallet, onWalletUpdate }) => {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loadingTickets, setLoadingTickets] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [infoAlert, setInfoAlert] = useState<string | null>(null)

  // Modals
  const [depositOpen, setDepositOpen] = useState(false)
  const [depositAmount, setDepositAmount] = useState(100)
  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [withdrawAmount, setWithdrawAmount] = useState(100)

  // Settle Modal
  const [settleTicket, setSettleTicket] = useState<Ticket | null>(null)
  const [settleResult, setSettleResult] = useState<"WON" | "LOST" | "VOID">("WON")
  const [customPayout, setCustomPayout] = useState<number>(0)
  const [settling, setSettling] = useState(false)

  useEffect(() => {
    let isMounted = true
    if (wallet?.profile_id) {
      setLoadingTickets(true)
      api.getTickets(wallet.profile_id)
        .then((res) => {
          if (isMounted) setTickets(res.tickets || [])
        })
        .catch((err) => {
          console.error(err)
        })
        .finally(() => {
          if (isMounted) setLoadingTickets(false)
        })
    }
    return () => {
      isMounted = false
    }
  }, [wallet?.profile_id])

  async function reloadTickets(profileId: string) {
    try {
      const res = await api.getTickets(profileId)
      setTickets(res.tickets || [])
    } catch (err) {
      console.error(err)
    }
  }

  async function handleDeposit() {
    if (!wallet) return
    try {
      const res = await api.depositWallet(wallet.profile_id, depositAmount)
      onWalletUpdate(res.wallet_status)
      setDepositOpen(false)
      setInfoAlert(null)
    } catch (err: any) {
      setActionError(err.message || "補金失敗")
    }
  }

  async function handleWithdraw() {
    if (!wallet) return
    try {
      const res = await api.withdrawWallet(wallet.profile_id, withdrawAmount)
      onWalletUpdate(res.wallet_status)
      setWithdrawOpen(false)
      setInfoAlert(null)
    } catch (err: any) {
      setActionError(err.message || "提領失敗")
    }
  }

  function openSettleModal(ticket: Ticket, result: "WON" | "LOST" | "VOID") {
    setSettleTicket(ticket)
    setSettleResult(result)
    setCustomPayout(result === "WON" ? ticket.potential_payout : 0)
  }

  async function confirmSettle() {
    if (!settleTicket || !wallet) return
    setSettling(true)
    setActionError(null)
    try {
      const payout = settleResult === "WON" ? customPayout : undefined
      const res = await api.settleTicket(settleTicket.ticket_id, settleResult, payout)
      if (res.wallet_status) onWalletUpdate(res.wallet_status)
      await reloadTickets(wallet.profile_id)

      if (settleResult === "WON") {
        triggerWinConfetti()
      }
      setSettleTicket(null)
    } catch (err: any) {
      setActionError(err.message || "結算注單失敗")
    } finally {
      setSettling(false)
    }
  }

  const openTickets = tickets.filter((t) => t.status === "PENDING")
  const settledTickets = tickets.filter((t) => t.status !== "PENDING")

  const canDeposit = Boolean(wallet?.can_deposit)
  const canWithdraw = Boolean(wallet && wallet.prize_pool > 0)

  const depositReason = !wallet
    ? "載入中..."
    : wallet.weekly_wallet_balance >= wallet.weekly_play_cap
    ? `目前本週可用餘額已達每週上限 NT$ ${wallet.weekly_play_cap.toFixed(0)}，符合風控守則，無需額外補金。`
    : wallet.external_deposit_remaining <= 0
    ? `本週外部補金上限已達 NT$ ${wallet.weekly_external_deposited.toFixed(0)}，待下週一刷新。`
    : `本週尚可補金 NT$ ${wallet.external_deposit_remaining.toFixed(0)}`

  const withdrawReason = !wallet
    ? "載入中..."
    : wallet.prize_pool <= 0
    ? `獲利儲備池目前餘額為 NT$ 0。中獎結算後將自動存入儲備池。`
    : `獲利儲備池共有 NT$ ${wallet.prize_pool.toFixed(1)} 可供提領`

  function onClickDeposit() {
    if (canDeposit) {
      setDepositAmount(Math.min(100, wallet?.external_deposit_remaining || 100))
      setDepositOpen(true)
      setInfoAlert(null)
    } else {
      setInfoAlert(depositReason)
    }
  }

  function onClickWithdraw() {
    if (canWithdraw) {
      setWithdrawAmount(wallet?.prize_pool || 0)
      setWithdrawOpen(true)
      setInfoAlert(null)
    } else {
      setInfoAlert(withdrawReason)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="space-y-5"
    >
      {/* Capital Management Header & Action Buttons */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 tracking-tight">
            <Wallet className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            資金帳本與額度風控
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            每週外部損失上限 NT$ {wallet?.weekly_play_cap || 200} · 獲利全額鎖定於儲備池
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap">
          {/* Deposit Button */}
          <button
            onClick={onClickDeposit}
            title={depositReason}
            className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer ${
              canDeposit
                ? "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 border-slate-900 dark:border-slate-100 shadow-xs hover:bg-slate-800 dark:hover:bg-slate-200"
                : "bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-700"
            }`}
          >
            <ArrowDownLeft className="w-3.5 h-3.5 text-slate-400" />
            <span>本週補金</span>
            {!canDeposit && (
              <span className="text-[10px] bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-500 font-mono">
                免補
              </span>
            )}
          </button>

          {/* Withdraw Button */}
          <button
            onClick={onClickWithdraw}
            title={withdrawReason}
            className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer ${
              canWithdraw
                ? "bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-600 shadow-xs"
                : "bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-700"
            }`}
          >
            <ArrowUpRight className="w-3.5 h-3.5" />
            <span>提領儲備</span>
            {!canWithdraw && (
              <span className="text-[10px] bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-500 font-mono">
                NT$0
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Explanatory Info Alert for Button Clicks */}
      {infoAlert && (
        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 text-xs flex items-center justify-between gap-3 shadow-xs">
          <div className="flex items-center gap-2">
            <Info className="w-4 h-4 shrink-0 text-slate-400" />
            <span>{infoAlert}</span>
          </div>
          <button
            onClick={() => setInfoAlert(null)}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-sm font-semibold p-1 cursor-pointer"
          >
            ✕
          </button>
        </div>
      )}

      {actionError && (
        <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}

      {/* Active / Open Tickets Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            進行中未結算注單 ({openTickets.length})
          </h3>
          <span className="text-xs text-slate-400">賽事完結後可手動結算</span>
        </div>

        {loadingTickets ? (
          <Skeleton className="h-28 w-full" />
        ) : openTickets.length === 0 ? (
          <Card className="text-center py-8">
            <CardContent className="text-slate-500 dark:text-slate-400 text-xs">
              目前沒有進行中的注單。可前往「串關決策」選擇組合下注。
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {openTickets.map((t) => (
              <div
                key={t.ticket_id}
                className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs space-y-3"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-slate-400">
                    #{t.ticket_id.slice(0, 10)}
                  </span>
                  <Badge variant="yellow" className="text-[10px]">
                    待開獎
                  </Badge>
                </div>

                <div className="space-y-1.5 pt-1 border-t border-slate-100 dark:border-slate-800">
                  {t.legs?.map((leg, lIdx) => (
                    <div key={lIdx} className="text-xs flex justify-between items-center">
                      <span className="text-slate-700 dark:text-slate-300">
                        {leg.away_team} vs {leg.home_team}
                      </span>
                      <span className="font-mono font-medium text-slate-900 dark:text-slate-100">
                        {leg.selection} ({leg.odds}x)
                      </span>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-800 text-xs">
                  <div className="tabular-nums">
                    下注: <span className="font-medium text-slate-900 dark:text-slate-100">{formatNTD(t.stake)}</span> · 賠率:{" "}
                    <span className="font-mono font-medium">{t.placed_odds.toFixed(2)}x</span>
                  </div>
                  <div className="text-emerald-600 dark:text-emerald-400 font-medium tabular-nums">
                    預計派彩: {formatNTD(t.potential_payout)}
                  </div>
                </div>

                {/* Settle Action Buttons */}
                <div className="flex gap-2 pt-1">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openSettleModal(t, "WON")}
                    className="flex-1 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 hover:bg-emerald-50 dark:hover:bg-emerald-950/30 text-xs font-medium cursor-pointer"
                  >
                    <Trophy className="w-3.5 h-3.5 mr-1" />
                    中獎結算
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openSettleModal(t, "LOST")}
                    className="flex-1 text-rose-600 dark:text-rose-400 border-rose-500/20 hover:bg-rose-50 dark:hover:bg-rose-950/30 text-xs font-medium cursor-pointer"
                  >
                    <XCircle className="w-3.5 h-3.5 mr-1" />
                    未過關
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Historical Settled Tickets Section */}
      <div className="space-y-3 pt-3 border-t border-slate-200/80 dark:border-slate-800">
        <h3 className="font-semibold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-2">
          <History className="w-4 h-4 text-slate-400" />
          歷史結算紀錄 (共 {settledTickets.length} 張)
        </h3>

        {settledTickets.length === 0 ? (
          <div className="p-8 text-center text-slate-400 text-xs">暫無已結算的歷史紀錄。</div>
        ) : (
          <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-50 dark:bg-slate-950/60 border-b border-slate-200 dark:border-slate-800 text-slate-500 text-[11px]">
                  <tr>
                    <th className="p-3">單號 / 日期</th>
                    <th className="p-3">組合說明</th>
                    <th className="p-3 text-right">本金</th>
                    <th className="p-3 text-right">賠率</th>
                    <th className="p-3 text-center">結果</th>
                    <th className="p-3 text-right">實收派彩</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60">
                  {settledTickets.map((t) => {
                    const isWon = t.status === "WON"
                    const isLost = t.status === "LOST"
                    return (
                      <tr key={t.ticket_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                        <td className="p-3">
                          <div className="text-slate-800 dark:text-slate-200 font-medium">
                            #{t.ticket_id.slice(0, 8)}
                          </div>
                          <div className="text-[10px] text-slate-400">
                            {new Date(t.created_at).toLocaleDateString("zh-TW")}
                          </div>
                        </td>
                        <td className="p-3 font-sans text-slate-700 dark:text-slate-300">{t.notes || "串關組合"}</td>
                        <td className="p-3 text-right tabular-nums">{formatNTD(t.stake)}</td>
                        <td className="p-3 text-right tabular-nums text-slate-900 dark:text-slate-100 font-medium">{t.placed_odds.toFixed(2)}x</td>
                        <td className="p-3 text-center font-sans">
                          <Badge
                            variant={isWon ? "green" : isLost ? "destructive" : "secondary"}
                            className="text-[10px]"
                          >
                            {isWon ? "過關" : isLost ? "未過關" : "取消"}
                          </Badge>
                        </td>
                        <td className={`p-3 text-right tabular-nums font-medium ${isWon ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}`}>
                          {formatNTD(t.actual_payout || 0)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Settlement Dialog */}
      <Dialog
        open={Boolean(settleTicket)}
        onClose={() => setSettleTicket(null)}
        title={settleResult === "WON" ? "中獎注單結算" : "標記未過關"}
      >
        <div className="space-y-4">
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {settleResult === "WON"
              ? "中獎派彩將全額撥入【獲利儲備池】，鎖定獲利。"
              : "將此注單結算為未過關，損失已於投注當下由每週限額扣除。"}
          </p>

          {settleResult === "WON" && (
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">實收中獎派彩金額 (NT$)</label>
              <input
                type="number"
                value={customPayout}
                onChange={(e) => setCustomPayout(Number(e.target.value))}
                className="w-full px-3 py-1.5 bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-emerald-600 dark:text-emerald-400 font-mono tabular-nums font-semibold text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-slate-200 dark:border-slate-800">
            <Button variant="ghost" onClick={() => setSettleTicket(null)} disabled={settling}>
              取消
            </Button>
            <Button
              variant={settleResult === "WON" ? "default" : "destructive"}
              onClick={confirmSettle}
              disabled={settling}
            >
              確認結算
            </Button>
          </div>
        </div>
      </Dialog>

      {/* Deposit Dialog */}
      <Dialog open={depositOpen} onClose={() => setDepositOpen(false)} title="補充每週可用額度">
        <div className="space-y-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            依照每週嚴格風控原則，每週外部補金不可超過上限（剩餘可補額度：NT$ {wallet?.external_deposit_remaining || 0}）。
          </p>
          <input
            type="number"
            min={10}
            max={wallet?.external_deposit_remaining || 200}
            step={10}
            value={depositAmount}
            onChange={(e) => setDepositAmount(Number(e.target.value))}
            className="w-full px-3 py-1.5 bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-slate-900 dark:text-slate-100 font-mono tabular-nums text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDepositOpen(false)}>取消</Button>
            <Button variant="default" onClick={handleDeposit}>確認補金</Button>
          </div>
        </div>
      </Dialog>

      {/* Withdraw Dialog */}
      <Dialog open={withdrawOpen} onClose={() => setWithdrawOpen(false)} title="提領獲利儲備池">
        <div className="space-y-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            獲利儲備池目前餘額為 NT$ {wallet?.prize_pool || 0}。
          </p>
          <input
            type="number"
            min={1}
            max={wallet?.prize_pool || 0}
            value={withdrawAmount}
            onChange={(e) => setWithdrawAmount(Number(e.target.value))}
            className="w-full px-3 py-1.5 bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-slate-900 dark:text-slate-100 font-mono tabular-nums font-semibold text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setWithdrawOpen(false)}>取消</Button>
            <Button variant="default" onClick={handleWithdraw}>確認提領</Button>
          </div>
        </div>
      </Dialog>
    </motion.div>
  )
}
