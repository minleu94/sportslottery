import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNTD(amount: number): string {
  const num = typeof amount === "number" && Number.isFinite(amount) ? amount : Number(amount || 0)
  return `NT$ ${Math.round(num).toLocaleString("zh-TW")}`
}

export function formatOdds(odds: number): string {
  return odds.toFixed(2) + "x"
}

export function cleanLeagueName(league?: string | null): string {
  if (!league) return "綜合賽事"
  let s = league.trim()
  // Strip UNKNOWN_ or unknown_ prefix (case-insensitive)
  s = s.replace(/^unknown[_\-\s]*/i, "").trim()
  
  const upper = s.toUpperCase()
  const leagueMap: Record<string, string> = {
    COLOMBIA_PRIMERA_A: "哥倫比亞甲級聯賽",
    COSTA_RICA_PRIMERA: "哥斯大黎加甲級聯賽",
    AFC_CHAMPIONS_LEAGUE_TWO: "亞洲冠軍二級聯賽",
    ASIAN_CHAMPIONS_LEAGUE: "亞洲冠軍聯賽",
    CONMEBOL_LIBERTADORES: "南美自由者盃",
    SAUDI_PRO_LEAGUE: "沙烏地職業聯賽",
    PREMIER: "英格蘭超級聯賽",
    LALIGA: "西班牙甲級聯賽",
    CHAMPIONS: "歐洲冠軍聯賽",
    CHAMPIONS_QUALIFYING: "歐冠資格賽",
    MLS: "美國職業足球大聯盟",
    KBO: "韓國職棒 (KBO)",
    NBA: "美國職籃 (NBA)",
    WNBA: "美國女子職籃 (WNBA)",
    MLB: "美國職棒 (MLB)",
    NPB: "日本職棒 (NPB)",
    CPBL: "中華職棒 (CPBL)",
    NFL: "美式足球 (NFL)",
    NHL: "國家冰球 (NHL)",
    SOCCER: "綜合足球",
    BASKETBALL: "綜合籃球",
    BASEBALL: "綜合棒球",
    FOOTBALL: "美式足球",
  }
  
  if (leagueMap[upper]) {
    return leagueMap[upper]
  }

  // Deduplicate repeated leading region names (including 秘/祕 variant)
  s = s.replace(/^秘魯祕魯|^祕魯秘魯/, "秘魯")
  s = s.replace(/^([\u4e00-\u9fa5]{2,4})\1+/, "$1")

  return s || "綜合賽事"
}

export function cleanSelectionLabel(selection?: string | null): string {
  if (!selection) return ""
  return selection
    .trim()
    .replace(/\s*[([（]\s*@?\d+(?:\.\d+)?x?\s*[)\]）]\s*$/i, "")
    .trim()
}

export function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID()
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0
    const v = c === "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
