import type { ParlayRecommendation } from "@/types"
import { cleanLeagueName, cleanSelectionLabel } from "@/lib/utils"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { BookOpen, CheckCircle2, ChevronRight, TrendingDown } from "lucide-react"
import { getLegEvInfo, getLegProbabilityInfo, getParlayEvInfo, getParlayProbabilityInfo } from "@/lib/probabilityProvenance"

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
  const displayTitle = isGenericFoldName
    ? legsCount === 1 ? "單場推薦" : `組合 #${index + 1}`
    : rawName
  const foldLabel = legsCount === 1 ? "單場 1 關" : `${legsCount} 串 1`

  const hasAnySteamLeg = parlay.legs?.some((l) => {
    const lm = (l.signal_evidence || {}).line_movement as Record<string, unknown> | undefined
    return Boolean(lm?.is_steam)
  })

  const hasSharp = Boolean(parlay.has_sharp_benchmark)
  const probabilityInfo = getParlayProbabilityInfo(parlay)
  const evInfo = getParlayEvInfo(parlay)
  const evVal = evInfo.value
  const totalOdds = parlay.total_odds_exact ?? parlay.total_odds
  const parlayHasSynth = parlay.legs?.some(
    (l) => l.is_market_synthetic || (l.signal_evidence || {}).is_market_synthetic
  )
  const isPosParlayEv = Boolean(evInfo.credible && !parlayHasSynth && evVal !== null && evVal > 0)
  const lowQualityCount = parlay.legs.filter((leg) => String(leg.evidence_quality || leg.signal_evidence?.evidence_quality || "").toUpperCase() === "LOW").length
  const insufficientCount = parlay.legs.filter((leg) => String(leg.evidence_quality || leg.signal_evidence?.evidence_quality || "").toUpperCase() === "INSUFFICIENT_SIGNAL").length

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
              title={`${probabilityInfo.label} · ${probabilityInfo.validationLabel} · ${evInfo.label}${parlay.sharp_badge ? ` · ${parlay.sharp_badge}` : ""}`}
            >
              {probabilityInfo.value != null ? (
                <span>
                  {legsCount === 1 ? "單場估計機率" : "估計聯合機率"}{" "}
                  <strong className="text-slate-900 dark:text-white font-semibold">
                    {(probabilityInfo.value * 100).toFixed(1)}%
                  </strong>
                  <span className="ml-1 text-[10px] text-slate-500 dark:text-slate-400">{probabilityInfo.label}</span>
                </span>
              ) : (
                <span className="text-amber-700 dark:text-amber-300">無有效估計</span>
              )}
              {evVal !== null && (
                <>
                  <span className="text-slate-300 dark:text-slate-600">|</span>
                  <span
                    className={
                      isPosParlayEv
                        ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                        : "text-slate-500 dark:text-slate-400"
                    }
                  >
                    {evInfo.label} {evVal > 0 ? "+" : ""}{evVal.toFixed(1)}%
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
              {Number.isFinite(totalOdds) ? `${totalOdds.toFixed(3)}x` : "—"}
            </div>
            <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
              {legsCount === 1 ? "單場賠率" : "總賠率"}
            </div>
          </div>
        </div>

        {(lowQualityCount > 0 || insufficientCount > 0) && (
          <div className="mx-3 mt-2 rounded-lg border border-amber-300/70 bg-amber-50/80 px-3 py-2 text-xs text-amber-800 dark:border-amber-800/70 dark:bg-amber-950/30 dark:text-amber-200">
            情報品質偏低：{lowQualityCount > 0 ? `${lowQualityCount} 關 LOW` : ""}{lowQualityCount > 0 && insufficientCount > 0 ? "、" : ""}{insufficientCount > 0 ? `${insufficientCount} 關情報不足` : ""}。機率與 EV 僅供參考。
          </div>
        )}
        {evVal !== null && evVal < 0 && (
          <div className="mx-3 mt-2 rounded-lg border border-rose-300/70 bg-rose-50/80 px-3 py-2 text-xs text-rose-800 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-200">
            目前估計為負 EV；此候選不代表有利投注。
          </div>
        )}

        {/* Distinct Inset Legs Track with Numbered Badges & Left Accent Bar */}
        <div className="p-3 space-y-2 bg-slate-50/70 dark:bg-slate-950/60">
          {parlay.legs.map((leg, legIndex) => {
            const legEvidence = leg.signal_evidence || {}
            const lm = (legEvidence.line_movement || {}) as Record<string, unknown>
            const legEvInfo = getLegEvInfo(leg)
            const legEv = legEvInfo.value
            const legProbability = getLegProbabilityInfo(leg)
            const legProb = legProbability.value !== null ? (legProbability.value * 100).toFixed(1) : null
            const hasCredibleLegProbability = ["ACCEPTED_MODEL", "SHARP_MARKET", "INTERNATIONAL_MARKET"].includes(legProbability.source)
            const isPos = Boolean(hasCredibleLegProbability && legEv !== null && legEv > 0)
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
                        <span className="text-xs text-slate-500 dark:text-slate-400 font-mono tabular-nums" title={`${legProbability.label} · ${legProbability.validationLabel}`}>
                          · 估計 {legProb}%
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
                          · {legEvInfo.label} {legEv > 0 ? `+${legEv.toFixed(1)}` : legEv.toFixed(1)}%
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
          <span>記錄已投注注單</span>
        </Button>
      </div>
    </div>
  )
}
