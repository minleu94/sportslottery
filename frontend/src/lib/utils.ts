import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNTD(amount: number): string {
  return new Intl.NumberFormat("zh-TW", {
    style: "currency",
    currency: "TWD",
    maximumFractionDigits: 1,
    minimumFractionDigits: 0,
  }).format(amount).replace("TWD", "NT$")
}

export function formatOdds(odds: number): string {
  return odds.toFixed(2) + "x"
}

export function cleanLeagueName(league?: string | null): string {
  if (!league) return "綜合賽事"
  let s = league.trim()
  if (s.startsWith("UNKNOWN_")) {
    s = s.slice(8)
  }
  if (s === "SOCCER") return "綜合足球"
  if (s === "BASKETBALL") return "綜合籃球"
  if (s === "BASEBALL") return "綜合棒球"
  if (s === "FOOTBALL") return "美式足球"
  return s
}
