import React from "react"
import { Sheet } from "@/components/ui/Sheet"
import { Badge } from "@/components/ui/Badge"
import type { ParlayRecommendation, Leg } from "@/types"
import { cleanLeagueName } from "@/lib/utils"
import { ShieldCheck, Users, TrendingUp, Sparkles, AlertTriangle, Globe, Coins } from "lucide-react"

interface EvidenceDrawerProps {
  open: boolean
  onClose: () => void
  parlay: ParlayRecommendation | null
}

export const EvidenceDrawer: React.FC<EvidenceDrawerProps> = ({
  open,
  onClose,
  parlay,
}) => {
  if (!parlay) return null

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <span>📑 推薦關卡情報與證據抽屜</span>
          <Badge variant="amber" className="text-xs font-mono">
            {parlay.total_odds.toFixed(2)}x
          </Badge>
        </div>
      }
      description={`組合名稱：${parlay.parlay_name} · 共 ${parlay.legs.length} 關`}
    >
      <div className="space-y-5">
        {/* Summary Card */}
        <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 space-y-2">
          <div className="text-xs font-semibold text-slate-500 dark:text-slate-400">總賠率與期望值</div>
          <div className="flex items-center justify-between">
            <span className="text-2xl font-black text-amber-500 dark:text-amber-400 font-mono">
              {parlay.total_odds.toFixed(2)} 倍
            </span>
            {parlay.expected_value !== undefined && parlay.expected_value !== null && (
              <span className={`text-sm font-bold ${parlay.expected_value > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-slate-500 dark:text-slate-400"}`}>
                EV: {parlay.expected_value > 0 ? "+" : ""}{(parlay.expected_value * 100).toFixed(1)}%
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            本組合嚴格排除同場賽事衝突，賠率以台灣運彩最新官方開盤為準。
          </p>
        </div>

        {/* Legs Detailed Evidence */}
        <div className="space-y-4">
          <h4 className="text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
            各關詳細訊號解析 (共 {parlay.legs.length} 關)
          </h4>

          {parlay.legs.map((leg: Leg, index: number) => {
            const ev = leg.signal_evidence || {}
            const consensus = ev.consensus_ratio ? Math.round(ev.consensus_ratio * 100) : null
            const votes = ev.vote_count

            return (
              <div
                key={`${leg.event_id}-${leg.selection}-${index}`}
                className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/50 space-y-3"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-slate-700 dark:text-slate-300 bg-slate-200/80 dark:bg-slate-800 px-2 py-0.5 rounded">
                    第 {index + 1} 關 · {cleanLeagueName(leg.league || leg.sport)}
                  </span>
                  <span className="text-amber-600 dark:text-amber-400 font-mono font-bold text-sm">
                    {leg.taiwan_odds?.toFixed(2)}x
                  </span>
                </div>

                <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                  {leg.away_team} vs {leg.home_team}
                </div>

                <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex items-center justify-between shadow-xs">
                  <div>
                    <span className="text-xs text-slate-500 dark:text-slate-400">{leg.market}</span>
                    <div className="font-bold text-emerald-600 dark:text-emerald-400 text-sm">{leg.selection}</div>
                  </div>
                  {leg.line && (
                    <span className="text-xs text-slate-600 dark:text-slate-300 font-mono bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded">
                      盤口基準: {leg.line}
                    </span>
                  )}
                </div>

                {/* Evidence badges & indicators */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {/* Market Fair Benchmark */}
                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <Globe className="w-4 h-4 text-emerald-500 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">國際去水公允</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">
                        {ev.sharp_fair_probability ? `${(ev.sharp_fair_probability * 100).toFixed(1)}%` : (ev.market_fair_probability ? `${(ev.market_fair_probability * 100).toFixed(1)}%` : "未對齊")}
                        {ev.sharp_expected_value_pct !== undefined && ev.sharp_expected_value_pct !== null && (
                          <span className={`text-[10px] ml-1 font-mono font-semibold ${ev.sharp_expected_value_pct > 0 ? "text-emerald-500" : "text-slate-400"}`}>
                            ({ev.sharp_expected_value_pct > 0 ? "+" : ""}{ev.sharp_expected_value_pct.toFixed(1)}% EV)
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Betting Splits */}
                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <Coins className="w-4 h-4 text-amber-500 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">國際籌碼(資金/票數)</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">
                        {ev.money_percentage !== undefined && ev.money_percentage !== null ? (
                          <span>
                            {ev.money_percentage.toFixed(0)}% / {ev.bet_percentage?.toFixed(0)}%
                            {ev.is_sharp_money_divergence && <span className="text-[10px] text-amber-500 ml-1">⚡分歧</span>}
                          </span>
                        ) : (
                          <span className="text-slate-400">研究待採集</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Crowd consensus */}
                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <Users className="w-4 h-4 text-sky-500 dark:text-sky-400 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">大眾社群投票</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">
                        {consensus !== null ? `${consensus}%` : "未開放"}
                        {votes ? <span className="text-[10px] text-slate-400 dark:text-slate-400 ml-1">({votes}票)</span> : null}
                      </div>
                    </div>
                  </div>

                  {/* Signal Quality */}
                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <ShieldCheck className="w-4 h-4 text-emerald-500 dark:text-emerald-400 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">情報品質等級</div>
                      <div className="font-bold text-emerald-600 dark:text-emerald-300">
                        {leg.evidence_quality || "STANDARD"}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Signals breakdown if any */}
                {leg.signals && leg.signals.length > 0 && (
                  <div className="pt-2 border-t border-slate-200 dark:border-slate-800/60 space-y-1">
                    <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">觸發信號：</div>
                    <div className="flex flex-wrap gap-1.5">
                      {leg.signals.map((sig: any, sIdx: number) => (
                        <Badge key={sIdx} variant="secondary" className="text-[10px]">
                          {sig.source_name || sig.type || "Signal"}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </Sheet>
  )
}
