import type { ParlayRecommendation } from "@/types"
import { cleanLeagueName } from "@/lib/utils"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { BookOpen, CheckCircle2, ChevronRight } from "lucide-react"

interface ParlayResultCardProps {
  parlay: ParlayRecommendation
  index: number
  onShowEvidence: (parlay: ParlayRecommendation) => void
  onPlaceBet: (parlay: ParlayRecommendation) => void
}

export function ParlayResultCard({ parlay, index, onShowEvidence, onPlaceBet }: ParlayResultCardProps) {
  return (
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors space-y-3.5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-900 dark:text-slate-100 text-sm">
              {parlay.parlay_name || `組合 #${index + 1}`}
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/60">
              {parlay.legs.length} 串 1
            </span>
            {parlay.sharp_badge && (
              <Badge variant={parlay.has_sharp_benchmark && parlay.is_positive_ev ? "green" : "secondary"} className="text-[10px]">
                {parlay.sharp_badge}
              </Badge>
            )}
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex items-center gap-2 flex-wrap">
            <span>賠率連乘</span>
            {parlay.joint_probability ? (
              <>
                <span>·</span>
                <span className="text-slate-700 dark:text-slate-300 font-medium font-mono tabular-nums">
                  {parlay.joint_probability_validation_status === "VALIDATED"
                    ? "聯合機率"
                    : "啟發式聯合機率（未驗證）"} {(parlay.joint_probability * 100).toFixed(1)}%
                </span>
              </>
            ) : null}
            <span>·</span>
            <span className="text-slate-400">獨立賽事檢驗</span>
          </div>
        </div>

        <div className="text-right shrink-0">
          <div className="text-xl font-semibold text-slate-900 dark:text-slate-100 font-mono tabular-nums tracking-tight">
            {parlay.total_odds.toFixed(2)}x
          </div>
          {(() => {
            const hasSharp = Boolean(parlay.has_sharp_benchmark)
            const evVal = hasSharp
              ? parlay.sharp_parlay_ev_pct
              : (parlay.parlay_ev_pct ?? (parlay.expected_value ? parlay.expected_value * 100 : null))
            if (evVal === null || evVal === undefined) return null
            const parlayHasSynth = parlay.legs?.some((l) => l.is_market_synthetic || (l.signal_evidence || {}).is_market_synthetic)
            const isPos = hasSharp && !parlayHasSynth && evVal > 0
            return (
              <div
                className={`text-xs font-medium tabular-nums font-mono flex items-center justify-end gap-1 ${
                  isPos ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"
                }`}
              >
                <span>{hasSharp ? "Sharp 基準 EV" : (parlayHasSynth ? "估計 EV（模擬）" : "估計 EV（未驗證）")}</span>
                <span>{isPos ? `+${evVal.toFixed(1)}%` : `${evVal.toFixed(1)}%`}</span>
              </div>
            )
          })()}
        </div>
      </div>

      {/* Legs list inside parlay */}
      <div className="space-y-1.5 pt-1.5 border-t border-slate-100 dark:border-slate-800">
        {parlay.legs.map((leg, legIndex) => {
          const isSynth = Boolean(leg.is_market_synthetic || (leg.signal_evidence || {}).is_market_synthetic)
          const legEvidence = leg.signal_evidence || {}
          const sharpLegEv = legEvidence.sharp_expected_value_pct
          const hasSharpLeg = !isSynth && legEvidence.market_source_qualification === "SHARP_QUALIFIED" && sharpLegEv !== null && sharpLegEv !== undefined
          const legEv = hasSharpLeg
            ? Number(sharpLegEv)
            : (leg.expected_value_pct ?? (leg.expected_value ? leg.expected_value * 100 : null))
          const legProb = leg.consensus_probability ? (leg.consensus_probability * 100).toFixed(0) : null
          const isPos = Boolean(hasSharpLeg && legEv !== null && legEv > 0)

          return (
            <div
              key={legIndex}
              className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950/60 border border-slate-200/70 dark:border-slate-800/60 flex items-center justify-between text-xs"
            >
              <div className="space-y-0.5">
                <div className="font-medium text-slate-800 dark:text-slate-200">
                  <span className="font-medium text-slate-400 mr-1.5">
                    {cleanLeagueName(leg.display_league || leg.league || leg.sport)}
                  </span>
                  {leg.away_team} vs {leg.home_team}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="text-slate-900 dark:text-slate-100 font-medium flex items-center gap-1.5">
                    <span className="text-[11px] text-slate-400">[{leg.market}]</span>
                    <span>{leg.selection}</span>
                  </div>

                  {/* Leg EV Badge */}
                  {legEv !== null && (
                    <span
                      className={`text-[10px] px-1 py-0.2 rounded font-mono font-medium ${
                        isPos
                          ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20"
                          : "bg-slate-100 dark:bg-slate-800 text-slate-500"
                      }`}
                    >
                      {hasSharpLeg
                        ? `Sharp 基準 EV ${legEv.toFixed(1)}%`
                        : isSynth ? `估計 EV ${legEv.toFixed(1)}%（模擬）` : `估計 EV ${legEv.toFixed(1)}%（未驗證）`}
                    </span>
                  )}

                  {/* Leg Prob */}
                  {legProb && (
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
                      估計機率 {legProb}%
                    </span>
                  )}
                </div>
              </div>

              <div className="text-right pl-3 shrink-0">
                <span className="font-medium font-mono tabular-nums text-slate-900 dark:text-slate-100 text-xs sm:text-sm">
                  {leg.taiwan_odds?.toFixed(2)}x
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Actions Bar */}
      <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onShowEvidence(parlay)}
          className="text-xs gap-1.5 text-slate-600 dark:text-slate-300 cursor-pointer"
        >
          <BookOpen className="w-3.5 h-3.5 text-slate-400" />
          <span>分析依據</span>
          <ChevronRight className="w-3 h-3 text-slate-400" />
        </Button>

        <Button
          variant="default"
          size="sm"
          onClick={() => onPlaceBet(parlay)}
          className="text-xs font-medium px-4 gap-1.5 cursor-pointer"
        >
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>確認下注</span>
        </Button>
      </div>
    </div>
  )
}
