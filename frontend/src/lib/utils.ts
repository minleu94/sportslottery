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
