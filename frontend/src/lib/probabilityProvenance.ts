import type { Leg, LegSignalEvidence, ParlayRecommendation } from "@/types"

export type ProbabilitySource =
  | "ACCEPTED_MODEL"
  | "SHADOW_MODEL"
  | "SHARP_MARKET"
  | "INTERNATIONAL_MARKET"
  | "TAIWAN_DEVIG"
  | "TAIWAN_BREAKEVEN"
  | "UNVALIDATED_MODEL"
  | "UNVERIFIED_ESTIMATE"
  | "UNAVAILABLE"

export interface ProbabilityInfo {
  value: number | null
  source: ProbabilitySource
  label: string
  validationLabel: string
}

const asProbability = (value: unknown): number | null => {
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) && parsed > 0 && parsed < 1 ? parsed : null
}

const asFiniteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null

const evidenceOf = (leg: Leg): LegSignalEvidence => leg.signal_evidence || {}

export function getLegProbabilityInfo(leg: Leg): ProbabilityInfo {
  const evidence = evidenceOf(leg)
  const consensus = asProbability(leg.consensus_probability ?? evidence.consensus_probability)
  const status = String(evidence.probability_status || "").toUpperCase()
  const qualification = String(evidence.market_source_qualification || "").toUpperCase()
  const synthetic = Boolean(leg.is_market_synthetic || evidence.is_market_synthetic || evidence.is_synthetic)

  if (synthetic) {
    return { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "模擬資料不作正式依據" }
  }
  if (status === "CALIBRATED_MODEL_ESTIMATE" && Array.isArray(evidence.model_accepted_ids) && evidence.model_accepted_ids.length > 0) {
    const value = consensus ?? asProbability(evidence.model_probability_calibrated)
    return value === null
      ? { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "已驗收模型機率缺漏" }
      : { value, source: "ACCEPTED_MODEL", label: "已驗收模型預測", validationLabel: "單關模型已驗收；串關機率仍未驗證" }
  }
  if (status === "UNVALIDATED_MODEL_ESTIMATE" || status === "UNVALIDATED_MODEL_FUSION_ESTIMATE") {
    return consensus === null
      ? { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "未驗證模型機率缺漏" }
      : { value: consensus, source: "UNVALIDATED_MODEL", label: "未驗證模型估計", validationLabel: "未經模型驗證" }
  }

  const benchmarkStatus = String(evidence.market_benchmark_status || "").toUpperCase()
  const sharpProbability = asProbability(evidence.sharp_fair_probability)
  const benchmark = asProbability(evidence.market_benchmark_fair_probability)
  if (!synthetic && benchmarkStatus === "AVAILABLE" && qualification === "SHARP_QUALIFIED" && sharpProbability !== null) {
    return { value: sharpProbability, source: "SHARP_MARKET", label: "合格 Sharp 市場估計", validationLabel: "市場基準；非模型驗證" }
  }
  if (!synthetic && benchmarkStatus === "AVAILABLE" && qualification === "INTERNATIONAL_MARKET" && benchmark !== null) {
    return { value: benchmark, source: "INTERNATIONAL_MARKET", label: "合格國際市場估計", validationLabel: "市場基準；非模型驗證" }
  }

  const fair = asProbability(evidence.market_fair_probability)
  const fairMethod = String(evidence.market_fair_method || "").toUpperCase()
  if (fair !== null && ["COMPLETE_MARKET_PROPORTIONAL", "TWO_WAY_PROPORTIONAL"].includes(fairMethod)) {
    return { value: fair, source: "TAIWAN_DEVIG", label: "台彩完整盤口去水位估計", validationLabel: "市場基準；未經模型驗證" }
  }

  if (consensus !== null && status && status !== "MARKET_BASELINE_ONLY") {
    return { value: consensus, source: "UNVERIFIED_ESTIMATE", label: "未驗證估計", validationLabel: "來源或驗證狀態不足" }
  }

  const implied = asProbability(evidence.market_implied_probability)
    ?? (Number.isFinite(leg.taiwan_odds) && leg.taiwan_odds > 1 ? asProbability(1 / leg.taiwan_odds) : null)
  return implied === null
    ? { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "缺少有效機率來源" }
    : { value: implied, source: "TAIWAN_BREAKEVEN", label: "台彩賠率損益兩平機率", validationLabel: "僅為損益平衡門檻，不是勝率" }
}

export function getTaiwanFairProbabilityInfo(evidence: LegSignalEvidence): ProbabilityInfo {
  const probability = asProbability(evidence.market_fair_probability)
  const method = String(evidence.market_fair_method || "").toUpperCase()
  if (probability !== null && ["COMPLETE_MARKET_PROPORTIONAL", "TWO_WAY_PROPORTIONAL"].includes(method)) {
    return { value: probability, source: "TAIWAN_DEVIG", label: "台彩完整盤口去水位估計", validationLabel: "市場基準；未經模型驗證" }
  }
  return { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "缺少完整台彩盤口" }
}

export function getQualifiedMarketBenchmarkInfo(evidence: LegSignalEvidence): ProbabilityInfo {
  const qualification = String(evidence.market_source_qualification || "").toUpperCase()
  const available = String(evidence.market_benchmark_status || "").toUpperCase() === "AVAILABLE"
  if (evidence.is_market_synthetic || !available) {
    return { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "沒有合格外部市場資料" }
  }
  if (qualification === "SHARP_QUALIFIED") {
    const sharpProbability = asProbability(evidence.sharp_fair_probability)
    return sharpProbability === null
      ? { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "缺少 Sharp 專屬去水機率" }
      : { value: sharpProbability, source: "SHARP_MARKET", label: "合格 Sharp 市場估計", validationLabel: "來源、盤口與時間條件合格" }
  }
  if (qualification === "INTERNATIONAL_MARKET") {
    const probability = asProbability(evidence.market_benchmark_fair_probability)
    return probability === null
      ? { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "缺少國際市場綜合機率" }
      : { value: probability, source: "INTERNATIONAL_MARKET", label: "合格國際市場去水位估計", validationLabel: "市場基準；不是模型驗證" }
  }
  return { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "來源資格未通過" }
}

export function getLegEvInfo(leg: Leg): { value: number | null; label: string } {
  const probability = getLegProbabilityInfo(leg)
  if (probability.source === "SHARP_MARKET" || probability.source === "INTERNATIONAL_MARKET") {
    const odds = asFiniteNumber(leg.taiwan_odds)
    const value = probability.value !== null && odds !== null && odds > 1
      ? (probability.value * odds - 1) * 100
      : null
    return {
      value,
      label: probability.source === "SHARP_MARKET" ? "Sharp EV" : "國際市場 EV",
    }
  }

  const evPct = asFiniteNumber(leg.expected_value_pct)
  const ev = asFiniteNumber(leg.expected_value)
  const value = evPct ?? (ev !== null ? ev * 100 : null)
  return { value, label: "估計 EV" }
}

export function getModelEstimateInfo(evidence: LegSignalEvidence): ProbabilityInfo {
  const accepted = Array.isArray(evidence.model_accepted_ids) && evidence.model_accepted_ids.length > 0
  const acceptedProbability = asProbability(evidence.model_probability_calibrated)
  if (accepted && String(evidence.probability_status || "").toUpperCase() === "CALIBRATED_MODEL_ESTIMATE" && acceptedProbability !== null) {
    return { value: acceptedProbability, source: "ACCEPTED_MODEL", label: "已驗收模型預測", validationLabel: "模型已通過驗收" }
  }
  const candidates = Array.isArray(evidence.model_candidate_provenances) ? evidence.model_candidate_provenances : []
  const candidate = candidates.find((item) => {
    if (!item || typeof item !== "object") return false
    const row = item as Record<string, unknown>
    return String(row.acceptance_status || "").toUpperCase() !== "ACCEPTED"
      && asProbability(row.raw_probability) !== null
  }) as Record<string, unknown> | undefined
  const shadow = asProbability(candidate?.raw_probability ?? evidence.model_candidate_probability_fused)
  if (shadow !== null) {
    return { value: shadow, source: "SHADOW_MODEL", label: "未驗收 Shadow 模型候選", validationLabel: "只供研究；不作推薦勝率" }
  }
  return { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "沒有模型預測" }
}

export function getParlayProbabilityInfo(parlay: ParlayRecommendation): ProbabilityInfo {
  const sharpProbability = parlay.has_sharp_benchmark ? asProbability(parlay.sharp_joint_probability) : null
  if (sharpProbability !== null) {
    return { value: sharpProbability, source: "SHARP_MARKET", label: "合格 Sharp 市場估計", validationLabel: "串關機率為結構式估計，未經驗證" }
  }
  const probability = asProbability(parlay.joint_probability)
  if (probability === null) {
    return { value: null, source: "UNAVAILABLE", label: "無有效估計", validationLabel: "缺少可用的串關機率" }
  }
  if (parlay.joint_probability_validation_status === "VALIDATED") {
    return { value: probability, source: "ACCEPTED_MODEL", label: "已驗證聯合機率", validationLabel: "已驗證" }
  }
  const sources = parlay.legs.map((leg) => getLegProbabilityInfo(leg).source)
  if (sources.includes("UNVALIDATED_MODEL") || sources.includes("UNVERIFIED_ESTIMATE")) {
    return { value: probability, source: "UNVALIDATED_MODEL", label: "未經模型驗證的估計", validationLabel: "不是已驗證命中率" }
  }
  const distinct = new Set(sources)
  if (distinct.size === 1 && sources[0] === "TAIWAN_BREAKEVEN") {
    return { value: probability, source: "TAIWAN_BREAKEVEN", label: "台彩損益平衡基準組合估計", validationLabel: "不是已驗證命中率" }
  }
  if (sources.every((source) => ["TAIWAN_DEVIG", "TAIWAN_BREAKEVEN"].includes(source))) {
    return { value: probability, source: "TAIWAN_DEVIG", label: "台彩市場基準組合估計", validationLabel: "串關機率未驗證" }
  }
  if (sources.every((source) => ["INTERNATIONAL_MARKET", "SHARP_MARKET"].includes(source))) {
    return { value: probability, source: "INTERNATIONAL_MARKET", label: "外部市場基準組合估計", validationLabel: "串關機率未驗證" }
  }
  if (sources.every((source) => source === "ACCEPTED_MODEL")) {
    return { value: probability, source: "ACCEPTED_MODEL", label: "已驗收模型輸入的組合估計", validationLabel: "串關機率未驗證" }
  }
  if (sources.includes("UNAVAILABLE")) {
    return { value: probability, source: "UNVERIFIED_ESTIMATE", label: "未驗證估計", validationLabel: "部分關卡缺少有效來源" }
  }
  return { value: probability, source: "UNVERIFIED_ESTIMATE", label: "混合來源組合估計", validationLabel: "串關機率未驗證" }
}

export function getParlayEvInfo(parlay: ParlayRecommendation): { value: number | null; label: string; credible: boolean } {
  const sharpProbability = parlay.has_sharp_benchmark ? asProbability(parlay.sharp_joint_probability) : null
  const odds = asFiniteNumber(parlay.total_odds_exact) ?? asFiniteNumber(parlay.total_odds)
  const sharpEv = sharpProbability !== null && odds !== null && odds > 1
    ? (sharpProbability * odds - 1) * 100
    : null
  const value = sharpEv !== null
    ? sharpEv
    : typeof parlay.parlay_ev_pct === "number" && Number.isFinite(parlay.parlay_ev_pct)
      ? parlay.parlay_ev_pct
      : typeof parlay.expected_value === "number" && Number.isFinite(parlay.expected_value)
        ? parlay.expected_value * 100
        : null
  const credible = Boolean(parlay.credible_value_basis)
  const label = sharpEv !== null
    ? "Sharp 市場估計 EV"
    : value === null
      ? "無有效 EV"
      : credible
        ? "有合格來源支持的估計 EV"
        : "估計 EV · 未經驗證"
  return { value, label, credible }
}
