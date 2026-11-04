import React from "react"
import { Sheet } from "@/components/ui/Sheet"
import { Badge } from "@/components/ui/Badge"
import type { ParlayRecommendation, Leg, PredictionSignal } from "@/types"
import { cleanLeagueName } from "@/lib/utils"
import { ShieldCheck, Users, Globe, Coins } from "lucide-react"
import { getLegProbabilityInfo, getModelEstimateInfo, getParlayEvInfo, getParlayProbabilityInfo, getQualifiedMarketBenchmarkInfo, getTaiwanFairProbabilityInfo } from "@/lib/probabilityProvenance"

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
  const probabilityInfo = getParlayProbabilityInfo(parlay)
  const evInfo = getParlayEvInfo(parlay)
  const totalOdds = parlay.total_odds_exact ?? parlay.total_odds

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <span>推薦關卡情報與分析依據</span>
          <span className="text-xs font-mono font-medium text-slate-700 dark:text-slate-300 px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
            {totalOdds.toFixed(3)}x
          </span>
        </div>
      }
      description={`${parlay.legs.length === 1 ? "單場" : `${parlay.legs.length} 串 1`} · 共 ${parlay.legs.length} 關`}
    >
      <div className="space-y-4">
        {/* Summary Card */}
        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 space-y-1.5">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">總賠率與期望值</div>
          <div className="flex items-center justify-between">
            <span className="text-2xl font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums">
              {totalOdds.toFixed(3)} 倍
            </span>
            <span className="text-right">
              <span className={`block text-sm font-medium ${evInfo.credible && evInfo.value !== null && evInfo.value > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-amber-700 dark:text-amber-300"}`}>
                EV: {evInfo.value === null ? "無有效估計" : `${evInfo.value > 0 ? "+" : ""}${evInfo.value.toFixed(1)}%`}
              </span>
              <span className="block text-[10px] text-slate-500 dark:text-slate-400">{evInfo.label}</span>
            </span>
          </div>
          <div className="text-xs text-slate-600 dark:text-slate-300">
            {probabilityInfo.value === null ? "無有效估計" : `${parlay.legs.length === 1 ? "單場估計機率" : "估計聯合機率"} ${(probabilityInfo.value * 100).toFixed(1)}% · ${probabilityInfo.label}`}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {probabilityInfo.validationLabel}。賠率以台灣運彩盤口為準；估計 EV 使用上方標示的機率來源。
          </p>
        </div>

        {/* Legs Detailed Evidence */}
        <div className="space-y-3">
          <h4 className="text-sm font-medium text-slate-800 dark:text-slate-200 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            各關詳細訊號解析 (共 {parlay.legs.length} 關)
          </h4>

          {parlay.legs.map((leg: Leg, index: number) => {
            const ev = leg.signal_evidence || {}
            const consensus = ev.consensus_ratio ? Math.round(ev.consensus_ratio * 100) : null
            const votes = ev.vote_count
            const legProbability = getLegProbabilityInfo(leg)
            const taiwanFair = getTaiwanFairProbabilityInfo(ev)
            const marketBenchmark = getQualifiedMarketBenchmarkInfo(ev)
            const modelEstimate = getModelEstimateInfo(ev)
            const impliedProbability = typeof ev.market_implied_probability === "number"
              ? ev.market_implied_probability
              : leg.taiwan_odds > 1 ? 1 / leg.taiwan_odds : null

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
                  {/* Qualified external market benchmark */}
                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <Globe className="w-4 h-4 text-emerald-500 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">合格外部市場基準</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">
                        {marketBenchmark.value === null ? "無有效估計" : `${(marketBenchmark.value * 100).toFixed(1)}% · ${marketBenchmark.label}`}
                      </div>
                      <div className="text-[10px] text-slate-500">{marketBenchmark.validationLabel}</div>
                    </div>
                  </div>

                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <ShieldCheck className="w-4 h-4 text-sky-500 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">台彩完整盤口去水</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">{taiwanFair.value === null ? "無有效估計" : `${(taiwanFair.value * 100).toFixed(1)}%`}</div>
                      <div className="text-[10px] text-slate-500">{taiwanFair.validationLabel}</div>
                    </div>
                  </div>

                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <Coins className="w-4 h-4 text-amber-500 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">台彩賠率隱含／損益兩平</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">{impliedProbability === null ? "無有效估計" : `${(impliedProbability * 100).toFixed(1)}%`}</div>
                      <div className="text-[10px] text-slate-500">只表示損益平衡門檻，不是勝率</div>
                    </div>
                  </div>

                  <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 flex items-center gap-2 shadow-xs">
                    <ShieldCheck className="w-4 h-4 text-violet-500 shrink-0" />
                    <div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">模型預測</div>
                      <div className="font-bold text-slate-800 dark:text-slate-200">{modelEstimate.value === null ? "無有效估計" : `${(modelEstimate.value * 100).toFixed(1)}% · ${modelEstimate.label}`}</div>
                      <div className="text-[10px] text-slate-500">{modelEstimate.validationLabel}</div>
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
                            {ev.is_splits_synthetic ? (
                              <span className="text-[10px] text-slate-400 ml-1 font-mono">(模擬樣本)</span>
                            ) : (
                              ev.is_sharp_money_divergence && <span className="text-[10px] text-amber-500 ml-1">⚡分歧</span>
                            )}
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
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">大眾社群投票 · 非勝率</div>
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

                <div className="text-[11px] text-slate-500 dark:text-slate-400">
                  本關機率：{legProbability.value === null ? "無有效估計" : `${(legProbability.value * 100).toFixed(1)}% · ${legProbability.label}`}（{legProbability.validationLabel}）
                </div>

                {/* Signals breakdown if any */}
                {leg.signals && leg.signals.length > 0 && (
                  <div className="pt-2 border-t border-slate-200 dark:border-slate-800/60 space-y-1">
                    <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">觸發信號：</div>
                    <div className="flex flex-wrap gap-1.5">
                      {leg.signals.map((sig: PredictionSignal, sIdx: number) => (
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
