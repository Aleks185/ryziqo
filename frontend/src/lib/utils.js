import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

const riskPercent = new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 0 });

export function formatRiskPercent(score) {
  return Number.isFinite(score) ? riskPercent.format(score) : "—";
}
