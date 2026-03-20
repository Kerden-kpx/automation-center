import { toFiniteNumber } from "../utils/valueFormat";

import type { ReactNode } from "react";

type ConversionRateBadgeProps = {
  value: unknown;
  period?: unknown;
  fallback?: ReactNode;
};

export function ConversionRateBadge({
  value,
  period,
  fallback = "-",
}: ConversionRateBadgeProps) {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return <>{fallback}</>;

  const percentText = `${(parsed * 100).toFixed(2)}%`;
  const periodText = period ? String(period).trim() : "";
  const isWeekly = periodText.includes("周");
  const percentClass = isWeekly ? "text-[#F59E0B]" : "text-[#2E7CF6]";

  if (!periodText) {
    return <span className={`${percentClass} font-bold`}>{percentText}</span>;
  }

  const periodClass = isWeekly
    ? "border-[#F59E0B] text-[#F59E0B]"
    : "border-[#2E7CF6] text-[#2E7CF6]";

  return (
    <span className={`inline-flex items-center gap-1 ${percentClass} font-bold`}>
      <span>{percentText}</span>
      <span className={`px-1.5 py-0.5 text-[10px] leading-none rounded-md border font-bold ${periodClass}`}>
        {periodText}
      </span>
    </span>
  );
}
