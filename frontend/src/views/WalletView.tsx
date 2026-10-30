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
} from "lucide-react"

interface WalletViewProps {
  wallet: WalletStatus | null
  onWalletUpdate: (wallet: WalletStatus) => void
}

export const WalletView: React.FC<WalletViewProps> = ({ wallet, onWalletUpdate }) => {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loadingTickets, setLoadingTickets] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)

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
    if (wallet?.profile_id) {
      loadTickets(wallet.profile_id)
    }
  }, [wallet?.profile_id])

  async function loadTickets(profileId: string) {
    setLoadingTickets(true)
    try {
      const res = await api.getTickets(profileId)
      setTickets(res.tickets || [])
    } catch (err: any) {
      console.error(err)
    } finally {
      setLoadingTickets(false)
    }
  }

  async function handleDeposit() {
    if (!wallet) return
    try {
      const res = await api.depositWallet(wallet.profile_id, depositAmount)
      onWalletUpdate(res.wallet_status)
      setDepositOpen(false)
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
      await loadTickets(wallet.profile_id)
      
      // Trigger golden confetti celebration on winning settlement
      if (settleResult === "WON") {
        triggerWinConfetti()
      }
      setSettleTicket(null)
    } catch (err: any) {
      setActionError(err.message || "結算失敗")
    } finally {
      setSettling(false)
    }
  }

  const openTickets = tickets.filter((t) => t.status === "PENDING")
  const settledTickets = tickets.filter((t) => t.status !== "PENDING")

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      {/* Capital Management Header & Action Buttons */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-black text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Wallet className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
            資金紀錄與嚴格風控帳本 (Capital & Risk Governance)
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            每週外部損失上限 NT$ {wallet?.weekly_play_cap || 200} · 贏錢全數轉入獲利保留儲備池
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDepositOpen(true)}
            disabled={!wallet?.can_deposit}
            className="text-xs gap-1.5"
          >
            <ArrowDownLeft className="w-3.5 h-3.5 text-purple-500" />
            <span>本週補金</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setWithdrawAmount(wallet?.prize_pool || 0)
              setWithdrawOpen(true)
            }}
            disabled={!wallet || wallet.prize_pool <= 0}
            className="text-xs gap-1.5"
          >
            <ArrowUpRight className="w-3.5 h-3.5 text-emerald-500" />
            <span>提領獲利池</span>
          </Button>
        </div>
      </div>

      {actionError && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-600 dark:text-rose-300 text-sm flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}

      {/* Active / Open Tickets Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-500" />
            進行中未結算注單 ({openTickets.length})
          </h3>
          <span className="text-xs text-slate-500 dark:text-slate-400">賽事結束後可點擊結算</span>
        </div>

        {loadingTickets ? (
          <Skeleton className="h-32 w-full" />
        ) : openTickets.length === 0 ? (
          <Card className="text-center py-8">
            <CardContent className="text-slate-500 dark:text-slate-400 text-sm">
              目前沒有進行中的注單。可前往「🔥 瘋狗看盤」選擇心儀組合進行下注！
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {openTickets.map((t) => (
              <div
                key={t.ticket_id}
                className="rounded-xl border border-amber-500/30 bg-white/80 dark:bg-slate-900/90 backdrop-blur p-5 shadow-lg space-y-4"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-900 dark:text-slate-100">{t.notes || "瘋狗高倍串關"}</span>
                      <Badge variant="amber" className="text-[10px]">進行中</Badge>
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 font-mono">
                      單號: {t.ticket_id.slice(0, 12)}... · {new Date(t.created_at).toLocaleString("zh-TW")}
                    </div>
                  </div>

                  <div className="text-right">
                    <div className="text-xs text-slate-500 dark:text-slate-400">總賠率</div>
                    <div className="text-xl font-black tabular-nums text-amber-500 dark:text-amber-400 font-mono">
                      {t.placed_odds?.toFixed(2)}x
                    </div>
                  </div>
                </div>

                {/* Stakes & Returns */}
                <div className="grid grid-cols-2 gap-2 p-3 rounded-lg bg-slate-50 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 text-xs font-mono">
                  <div>
                    <span className="text-slate-500 dark:text-slate-400">本張注金：</span>
                    <strong className="text-slate-900 dark:text-slate-200 tabular-nums ml-1">{formatNTD(t.stake)}</strong>
                  </div>
                  <div className="text-right">
                    <span className="text-slate-500 dark:text-slate-400">預計回報：</span>
                    <strong className="text-emerald-600 dark:text-emerald-400 tabular-nums ml-1">{formatNTD(t.potential_payout)}</strong>
                  </div>
                </div>

                {/* Legs breakdown */}
                {t.legs && t.legs.length > 0 && (
                  <div className="space-y-1.5 text-xs pt-1">
                    {t.legs.map((leg: any, idx: number) => (
                      <div key={idx} className="flex justify-between text-slate-700 dark:text-slate-300">
                        <span>• {leg.away_team} vs {leg.home_team} ({leg.selection})</span>
                        <span className="font-mono tabular-nums text-amber-500 dark:text-amber-400">{leg.taiwan_odds || leg.odds}x</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Settlement Action Buttons */}
                <div className="pt-2 border-t border-slate-200 dark:border-slate-800 flex items-center justify-end gap-2">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => openSettleModal(t, "LOST")}
                    className="text-xs gap-1"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    <span>標記未過關</span>
                  </Button>

                  <Button
                    variant="success"
                    size="sm"
                    onClick={() => openSettleModal(t, "WON")}
                    className="text-xs font-bold gap-1 shadow-sm"
                  >
                    <Trophy className="w-3.5 h-3.5" />
                    <span>恭喜中獎！</span>
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* History Tickets Table */}
      <div className="space-y-3 pt-4">
        <h3 className="font-bold text-slate-800 dark:text-slate-200 text-sm flex items-center gap-2">
          <History className="w-4 h-4 text-slate-400" />
          歷史結算紀錄 (共 {settledTickets.length} 張)
        </h3>

        {settledTickets.length === 0 ? (
          <Card className="text-center py-6">
            <CardContent className="text-slate-500 dark:text-slate-400 text-xs">暫無已結算的歷史紀錄。</CardContent>
          </Card>
        ) : (
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/60 overflow-hidden shadow">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-100 dark:bg-slate-950/80 border-b border-slate-200 dark:border-slate-800 text-slate-500 uppercase font-mono">
                  <tr>
                    <th className="p-3">單號 / 時間</th>
                    <th className="p-3">項目</th>
                    <th className="p-3 text-right">注金</th>
                    <th className="p-3 text-right">賠率</th>
                    <th className="p-3 text-center">結果</th>
                    <th className="p-3 text-right">派彩</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800/60 font-mono">
                  {settledTickets.map((t) => {
                    const isWon = t.status === "WON"
                    const isLost = t.status === "LOST"
                    return (
                      <tr key={t.ticket_id} className="hover:bg-slate-100/50 dark:hover:bg-slate-800/30">
                        <td className="p-3 text-slate-500">
                          <div>{t.ticket_id.slice(0, 10)}...</div>
                          <div className="text-[10px] text-slate-400">
                            {new Date(t.created_at).toLocaleDateString("zh-TW")}
                          </div>
                        </td>
                        <td className="p-3 font-sans text-slate-800 dark:text-slate-200">{t.notes || "瘋狗高倍串關"}</td>
                        <td className="p-3 text-right tabular-nums">{formatNTD(t.stake)}</td>
                        <td className="p-3 text-right tabular-nums text-amber-500 dark:text-amber-400">{t.placed_odds.toFixed(2)}x</td>
                        <td className="p-3 text-center font-sans">
                          <Badge
                            variant={isWon ? "green" : isLost ? "destructive" : "secondary"}
                            className="text-[10px]"
                          >
                            {isWon ? "過關" : isLost ? "未過關" : "取消"}
                          </Badge>
                        </td>
                        <td className={`p-3 text-right tabular-nums font-bold ${isWon ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}`}>
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
        title={settleResult === "WON" ? "🎉 恭喜中獎！確認結算注單" : "確認標記未過關"}
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {settleResult === "WON"
              ? "系統將把中獎獎金全數自動匯入【獲利儲備池】，確保贏利不被隨意反噬！"
              : "將此注單結算為未過關，損失已於投注當下由每週限額錢包吸收。"}
          </p>

          {settleResult === "WON" && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">實收中獎派彩金額 (NT$)</label>
              <input
                type="number"
                value={customPayout}
                onChange={(e) => setCustomPayout(Number(e.target.value))}
                className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-emerald-600 dark:text-emerald-400 font-mono tabular-nums font-bold text-base focus:outline-none focus:border-emerald-500"
              />
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-slate-200 dark:border-slate-800">
            <Button variant="ghost" onClick={() => setSettleTicket(null)} disabled={settling}>
              取消
            </Button>
            <Button
              variant={settleResult === "WON" ? "success" : "destructive"}
              onClick={confirmSettle}
              disabled={settling}
            >
              確認結算
            </Button>
          </div>
        </div>
      </Dialog>

      {/* Deposit Dialog */}
      <Dialog open={depositOpen} onClose={() => setDepositOpen(false)} title="💵 補充每週可用額度">
        <div className="space-y-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            依照每週嚴格風控原則，每週外部補金不可超過上限（剩餘額度：NT$ {wallet?.external_deposit_remaining || 0}）。
          </p>
          <input
            type="number"
            min={10}
            max={wallet?.external_deposit_remaining || 200}
            step={10}
            value={depositAmount}
            onChange={(e) => setDepositAmount(Number(e.target.value))}
            className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-slate-900 dark:text-slate-100 font-mono tabular-nums text-sm"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDepositOpen(false)}>取消</Button>
            <Button variant="default" onClick={handleDeposit}>確認補金</Button>
          </div>
        </div>
      </Dialog>

      {/* Withdraw Dialog */}
      <Dialog open={withdrawOpen} onClose={() => setWithdrawOpen(false)} title="🔒 提領獲利保留池">
        <div className="space-y-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            獲利儲備池目前餘額為 NT$ {wallet?.prize_pool || 0}。提領至外部帳戶將鎖定勝利果實。
          </p>
          <input
            type="number"
            min={1}
            max={wallet?.prize_pool || 0}
            value={withdrawAmount}
            onChange={(e) => setWithdrawAmount(Number(e.target.value))}
            className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-emerald-600 dark:text-emerald-400 font-mono tabular-nums font-bold text-sm"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setWithdrawOpen(false)}>取消</Button>
            <Button variant="success" onClick={handleWithdraw}>確認提領</Button>
          </div>
        </div>
      </Dialog>
    </motion.div>
  )
}
