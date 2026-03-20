export const toFiniteNumber = (value: unknown): number | null => {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const normalized = value.trim();
    if (!normalized) return null;
    const cleaned = normalized.replace(/[$,\s]/g, "").replace(/[^\d.-]/g, "");
    if (!cleaned || cleaned === "-" || cleaned === "." || cleaned === "-.") return null;
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

export const formatText = (value: unknown, fallback = "-") => {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
};

export const formatNumber = (value: unknown, fallback = "-") => {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return fallback;
  return parsed.toLocaleString();
};

export const formatMoney = (value: unknown, fallback = "-") => {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return fallback;
  return `$${parsed.toFixed(2)}`;
};

export const formatSalesMoney = (value: unknown, fallback = "-") => {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return fallback;
  return `$${Math.round(parsed).toLocaleString()}`;
};

export const formatTrafficShare = (
  organic: unknown,
  ad: unknown,
  type: "organic" | "ad" = "organic",
) => {
  const organicValue = toFiniteNumber(organic);
  const adValue = toFiniteNumber(ad);
  if (organicValue === null || adValue === null) return "";
  const total = organicValue + adValue;
  if (total <= 0) return "";
  const targetValue = type === "organic" ? organicValue : adValue;
  const percent = (targetValue / total) * 100;
  return ` (${Math.round(percent)}%)`;
};

export const formatMonthLabel = (value: unknown) => {
  const raw = String(value || "").trim();
  if (!raw) return "-";
  const m1 = raw.match(/^(\d{4})[-/.](\d{1,2})/);
  if (m1) {
    return `${m1[1]}.${m1[2].padStart(2, "0")}`;
  }
  const m2 = raw.match(/^(\d{4})(\d{2})$/);
  if (m2) {
    return `${m2[1]}.${m2[2]}`;
  }
  return raw;
};

export const toCount = (value: unknown) => {
  const parsed = toFiniteNumber(value);
  return parsed ?? 0;
};
