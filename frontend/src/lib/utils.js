import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// "YYYY-MM-DD" parsed as a local date; new Date("2026-10-05") is UTC midnight and can show the previous day.
export const formatDate = (iso) => {
  const [y, m, d] = String(iso || "").split("-").map(Number);
  return y ? new Date(y, m - 1, d).toLocaleDateString("el-GR") : "";
};
