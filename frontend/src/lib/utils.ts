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
    SAUDI_PRO_LEAGUE: "沙烏地職業聯賽",
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
  
  return s || "綜合賽事"
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
