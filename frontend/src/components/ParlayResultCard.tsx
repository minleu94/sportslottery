import type { ParlayRecommendation } from "@/types"
import { cleanLeagueName, cleanSelectionLabel } from "@/lib/utils"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { BookOpen, CheckCircle2, ChevronRight, TrendingDown } from "lucide-react"

interface ParlayResultCardProps {
  parlay: ParlayRecommendation
  index: number
  onShowEvidence: (parlay: ParlayRecommendation) => void
  onPlaceBet: (parlay: ParlayRecommendation) => void
}

export function ParlayResultCard({ parlay, index, onShowEvidence, onPlaceBet }: ParlayResultCardProps) {
  const legsCount = parlay.legs.length
  const rawName = (parlay.parlay_name || "").trim()
  const isGenericFoldName = !rawName || /^\d+\s*串\s*\d+$/i.test(rawName)
  const displayTitle = isGenericFoldName ? `組合 #${index + 1}` : rawName
  const foldLabel = legsCount === 1 ? "單場 1 關" : `${legsCount} 串 1`

  const hasAnySteamLeg = parlay.legs?.some((l) => {
    const lm = (l.signal_evidence || {}).line_movement as Record<string, unknown> | undefined
    return Boolean(lm?.is_steam)
  })

  const hasSharp = Boolean(parlay.has_sharp_benchmark)
  const evVal = hasSharp
    ? parlay.sharp_parlay_ev_pct
    : (parlay.parlay_ev_pct ?? (parlay.expected_value != null ? parlay.expected_value * 100 : null))
  const parlayHasSynth = parlay.legs?.some(
    (l) => l.is_market_synthetic || (l.signal_evidence || {}).is_market_synthetic
  )
  const isPosParlayEv = Boolean(hasSharp && !parlayHasSynth && evVal !== null && evVal !== undefined && evVal > 0)

  const probTitle =
    parlay.joint_probability_validation_status === "VALIDATED"
      ? "已驗證聯合機率"
      : legsCount === 1
        ? "啟發式命中率（未驗證）"
        : "啟發式聯合機率（未驗證）"

  const evTitle = hasSharp
    ? "指定來源市場估計 EV"
    : parlayHasSynth
      ? "估計 EV（模擬數據）"
      : "估計 EV（未驗證）"

  return (
    <div className="rounded-xl border border-slate-200/90 dark:border-slate-700/80 bg-white dark:bg-slate-900 overflow-hidden shadow-xs hover:border-slate-300 dark:hover:border-slate-600 transition-colors flex flex-col justify-between">
      <div>
        {/* Distinct Tinted Header Banner (Strictly 2 clean rows, visually separated from legs) */}
        <div className="px-4 py-3 bg-slate-100/80 dark:bg-slate-800/75 border-b border-slate-200/90 dark:border-slate-700/80 flex items-center justify-between gap-3">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-slate-900 dark:text-white text-sm">
                {displayTitle}
              </span>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30 font-semibold">
                {foldLabel}
              </span>
              {hasSharp && parlay.is_positive_ev && parlay.sharp_badge && (
                <Badge variant="green" className="text-xs">
                  {parlay.sharp_badge}
                </Badge>
              )}
              {hasAnySteamLeg && (
                <Badge variant="green" className="text-xs flex items-center gap-1">
                  <TrendingDown className="w-3 h-3" />
                  順勢跳水
                </Badge>
              )}
            </div>

            <div
              className="text-xs text-slate-600 dark:text-slate-300 flex items-center gap-2 flex-wrap font-mono tabular-nums"
              title={`${probTitle} · ${evTitle}${parlay.sharp_badge ? ` · ${parlay.sharp_badge}` : ""}`}
            >
              {parlay.joint_probability != null ? (
                <span>
                  {legsCount === 1 ? "命中率" : "聯合命中率"}{" "}
                  <strong className="text-slate-900 dark:text-white font-semibold">
                    {(parlay.joint_probability * 100).toFixed(1)}%
                  </strong>
                </span>
              ) : null}
              {evVal !== null && evVal !== undefined && (
                <>
                  <span className="text-slate-300 dark:text-slate-600">|</span>
                  <span
                    className={
                      isPosParlayEv
                        ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                        : "text-slate-500 dark:text-slate-400"
                    }
                  >
                    {hasSharp ? "Sharp EV" : "估計 EV"}{" "}
                    {isPosParlayEv ? `+${evVal.toFixed(1)}%` : `${evVal.toFixed(1)}%`}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Right Framed Total Odds Box */}
          <div className="text-right shrink-0 font-mono tabular-nums bg-white dark:bg-slate-950/85 px-3 py-1.5 rounded-lg border border-slate-200/90 dark:border-slate-700/80 shadow-2xs">
            <div
              className={`text-lg font-bold tracking-tight leading-none ${
                isPosParlayEv
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-slate-900 dark:text-white"
              }`}
            >
              {Number.isFinite(parlay.total_odds) ? `${parlay.total_odds.toFixed(2)}x` : "—"}
            </div>
            <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
              {legsCount === 1 ? "單場賠率" : "總賠率"}
            </div>
          </div>
        </div>

        {/* Distinct Inset Legs Track with Numbered Badges & Left Accent Bar */}
        <div className="p-3 space-y-2 bg-slate-50/70 dark:bg-slate-950/60">
          {parlay.legs.map((leg, legIndex) => {
            const isSynth = Boolean(leg.is_market_synthetic || (leg.signal_evidence || {}).is_market_synthetic)
            const legEvidence = leg.signal_evidence || {}
            const lm = (legEvidence.line_movement || {}) as Record<string, unknown>
            const sharpLegEv = legEvidence.sharp_expected_value_pct
            const hasSharpLeg =
              !isSynth &&
              legEvidence.market_source_qualification === "SHARP_QUALIFIED" &&
              sharpLegEv !== null &&
              sharpLegEv !== undefined
            const legEv = hasSharpLeg
              ? Number(sharpLegEv)
              : (leg.expected_value_pct ?? (leg.expected_value != null ? leg.expected_value * 100 : null))
            const legProb = leg.consensus_probability != null ? (leg.consensus_probability * 100).toFixed(0) : null
            const isPos = Boolean(hasSharpLeg && legEv !== null && legEv > 0)
            const cleanedLeague = cleanLeagueName(leg.display_league || leg.league || leg.sport)
            const cleanedSelection = cleanSelectionLabel(leg.selection)

            return (
              <div
                key={legIndex}
                className="p-2.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800/90 border-l-2 border-l-emerald-500 flex items-center justify-between gap-2.5 text-xs"
              >
                <div className="flex items-start gap-2.5 min-w-0 flex-1">
                  {/* Leg Sequence Number Badge */}
                  <span className="w-5 h-5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-mono text-xs font-semibold flex items-center justify-center shrink-0 mt-0.5">
                    {legIndex + 1}
                  </span>

                  <div className="space-y-1 min-w-0 flex-1">
                    {/* Line 1: League + Teams */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-slate-500 dark:text-slate-400 font-medium shrink-0">
                        {cleanedLeague} ·
                      </span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-xs sm:text-sm truncate">
                        {leg.away_team} <span className="text-slate-400 font-normal">vs</span> {leg.home_team}
                      </span>
                    </div>

                    {/* Line 2: Market Badge + Bold Selection + Concise Meta */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 font-medium text-xs">
                        {leg.market}
                      </span>
                      <span className="text-sm font-bold text-slate-900 dark:text-white mr-1">
                        {cleanedSelection}
                      </span>

                      {legProb && (
                        <span className="text-xs text-slate-500 dark:text-slate-400 font-mono tabular-nums">
                          · 機率 {legProb}%
                        </span>
                      )}

                      {legsCount > 1 && legEv !== null && (
                        <span
                          className={`text-xs font-mono tabular-nums ${
                            isPos
                              ? "text-emerald-600 dark:text-emerald-400 font-medium"
                              : "text-slate-400 dark:text-slate-500"
                          }`}
                        >
                          · EV {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
                        </span>
                      )}

                      {Boolean(lm.is_steam) && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 font-medium">
                          順勢跳水
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Right: Single Leg Odds */}
                <div className="text-right shrink-0 pl-1">
                  <span className="font-bold font-mono tabular-nums text-slate-900 dark:text-white text-sm">
                    {leg.taiwan_odds != null && Number.isFinite(leg.taiwan_odds)
                      ? `${leg.taiwan_odds.toFixed(2)}x`
                      : "—"}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Actions Bar */}
      <div className="px-4 py-2.5 bg-white dark:bg-slate-900 border-t border-slate-200/80 dark:border-slate-800/90 flex items-center justify-between gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onShowEvidence(parlay)}
          className="min-h-[44px] text-xs gap-1.5 text-slate-600 dark:text-slate-300 cursor-pointer"
        >
          <BookOpen className="w-3.5 h-3.5 text-slate-400" />
          <span>分析依據</span>
          <ChevronRight className="w-3 h-3 text-slate-400" />
        </Button>

        <Button
          variant="default"
          size="sm"
          onClick={() => onPlaceBet(parlay)}
          className="min-h-[44px] text-xs font-medium px-4 gap-1.5 cursor-pointer"
        >
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>確認下注</span>
        </Button>
      </div>
    </div>
  )
}
