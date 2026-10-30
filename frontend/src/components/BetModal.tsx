import React, { useState, useEffect } from "react"
import { Dialog } from "@/components/ui/Dialog"
import { Button } from "@/components/ui/Button"
import { formatNTD, generateUUID } from "@/lib/utils"
import type { ParlayRecommendation, WalletStatus } from "@/types"
import { api } from "@/services/api"
import { CheckCircle2, AlertTriangle, Loader2 } from "lucide-react"

interface BetModalProps {
  open: boolean
  onClose: () => void
  parlay: ParlayRecommendation | null
  wallet: WalletStatus | null
  onSuccess: (updatedWallet: WalletStatus) => void
}

export const BetModal: React.FC<BetModalProps> = ({
  open,
  onClose,
  parlay,
  wallet,
  onSuccess,
}) => {
  const [stake, setStake] = useState<number>(20)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [idempotencyKey, setIdempotencyKey] = useState<string>("")

  useEffect(() => {
    if (open) {
      setError(null)
      setSuccess(false)
      // Generate fresh UUID for new bet confirmation
      setIdempotencyKey(generateUUID())
    } else {
      setIdempotencyKey("")
    }
  }, [open, parlay])

  if (!parlay) return null

  const maxStakeAllowed = wallet
    ? Math.min(wallet.weekly_wallet_balance, wallet.weekly_play_cap - wallet.weekly_staked)
    : 0
  const canAfford = maxStakeAllowed >= 10 && stake <= maxStakeAllowed
  const potentialPayout = Math.round(stake * parlay.total_odds)

  async function handleConfirmBet() {
    if (!wallet || !parlay) return
    setError(null)
    setSubmitting(true)

    // Ensure we have an active idempotency key for this attempt
    const activeKey = idempotencyKey || generateUUID()
    if (!idempotencyKey) {
      setIdempotencyKey(activeKey)
    }

    try {
      const res = await api.placeTicket({
        profile_id: wallet.profile_id,
        legs: parlay.legs,
        stake: stake,
        placed_odds: parlay.total_odds,
        recommendation_odds: parlay.total_odds,
        parlay_name: parlay.parlay_name,
        entry_mode: "recommendation",
        idempotency_key: activeKey,
      })

      setSuccess(true)
      setTimeout(() => {
        setSuccess(false)
        setIdempotencyKey("")
        onClose()
        if (res.wallet_status) onSuccess(res.wallet_status)
      }, 1200)
    } catch (err: any) {
      // Keep activeKey on error so retrying uses the same idempotency key
      setError(err.message || "下注失敗")
    } finally {
      setSubmitting(false)
    }
  }

  function handleStakeSelect(amt: number) {
    if (amt !== stake) {
      setStake(amt)
      setError(null)
      // When stake changes, generate a fresh idempotency key
      setIdempotencyKey(generateUUID())
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="🎯 確認下注注單"
      description={`組合：${parlay.parlay_name} · 共 ${parlay.legs.length} 關`}
    >
      <div className="space-y-4">
        {success ? (
          <div className="py-8 text-center space-y-3">
            <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto animate-bounce" />
            <h4 className="text-lg font-bold text-slate-100">下注成功！已記錄於注單流水帳</h4>
            <p className="text-xs text-slate-400">已自本週可用餘額扣除 NT$ {stake}</p>
          </div>
        ) : (
          <>
            {/* Bet Summary Banner */}
            <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">綜合總賠率</span>
                <span className="text-xl font-black text-amber-400 font-mono">
                  {parlay.total_odds.toFixed(2)}x
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">預期中獎總回報</span>
                <span className="text-xl font-black text-emerald-400 font-mono">
                  {formatNTD(potentialPayout)}
                </span>
              </div>
            </div>

            {/* Stake Input */}
            <div className="space-y-2">
              <div className="flex justify-between items-center text-xs">
                <label className="font-semibold text-slate-300">投注金額 (NT$)</label>
                <span className="text-slate-400">
                  本週可用餘額：<strong className="text-slate-200">{formatNTD(wallet?.weekly_wallet_balance || 0)}</strong>
                </span>
              </div>

              <div className="flex gap-2">
                {[10, 20, 50, 100].map((amt) => (
                  <button
                    key={amt}
                    type="button"
                    onClick={() => handleStakeSelect(amt)}
                    disabled={amt > maxStakeAllowed}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                      stake === amt
                        ? "bg-emerald-600 text-white"
                        : "bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
                    }`}
                  >
                    NT${amt}
                  </button>
                ))}
              </div>

              <input
                type="number"
                min={10}
                max={maxStakeAllowed}
                step={10}
                value={stake}
                onChange={(e) => {
                  const val = Math.max(10, Number(e.target.value))
                  setStake(val)
                  setError(null)
                  setIdempotencyKey(generateUUID())
                }}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-100 font-mono text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>

            {/* Error or validation alert */}
            {!canAfford && (
              <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>
                  本週可用餘額不足（僅剩 NT$ {maxStakeAllowed.toFixed(0)}），無法下注此金額。
                </span>
              </div>
            )}

            {error && (
              <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-500/30 text-rose-300 text-xs space-y-1">
                <div className="font-semibold flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>提交失敗</span>
                </div>
                <div>{error}</div>
                <div className="text-[10px] text-slate-400">
                  提示：點選「重試下注」將使用相同冪等鍵安全重試，不會重複扣款。
                </div>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <Button variant="ghost" onClick={onClose} disabled={submitting}>
                取消
              </Button>
              <Button
                variant="success"
                onClick={handleConfirmBet}
                disabled={!canAfford || submitting}
                className="gap-2"
              >
                {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
                {error ? `重試下注 NT$ ${stake}` : `確認下注 NT$ ${stake}`}
              </Button>
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
