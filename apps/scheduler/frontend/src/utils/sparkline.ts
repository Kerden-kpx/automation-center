export type SalesSparklinePoint = {
  month: string;
  salesVolume: number;
  salesAmount: number | null;
};

export type SparklineGeometry = {
  width: number;
  height: number;
  points: ReadonlyArray<readonly [number, number]>;
  polyline: string;
  area: string;
};

type BuildSalesSparklinePointsInput = {
  monthlySalesTrend?: Array<{
    month?: unknown;
    salesVolume?: unknown;
    salesAmount?: unknown;
  }>;
  fallback?: {
    month?: unknown;
    salesVolume?: unknown;
    salesAmount?: unknown;
  };
  limit?: number;
};

const toFiniteNumber = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export const buildSalesSparklinePoints = ({
  monthlySalesTrend,
  fallback,
  limit = 12,
}: BuildSalesSparklinePointsInput): SalesSparklinePoint[] => {
  const source = (Array.isArray(monthlySalesTrend) ? monthlySalesTrend : [])
    .map((row) => {
      const salesVolume = toFiniteNumber(row?.salesVolume);
      if (salesVolume === null || salesVolume < 0) return null;
      const salesAmount = toFiniteNumber(row?.salesAmount);
      return {
        month: String(row?.month || ""),
        salesVolume,
        salesAmount,
      } as SalesSparklinePoint;
    })
    .filter(Boolean) as SalesSparklinePoint[];

  const trimmed = source.slice(-limit);
  if (trimmed.length > 0) {
    return trimmed;
  }

  const fallbackSalesVolume = toFiniteNumber(fallback?.salesVolume);
  if (fallbackSalesVolume === null || fallbackSalesVolume < 0) {
    return [];
  }

  return [
    {
      month: String(fallback?.month || ""),
      salesVolume: fallbackSalesVolume,
      salesAmount: toFiniteNumber(fallback?.salesAmount),
    },
  ];
};

export const buildSparklineGeometry = (
  points: SalesSparklinePoint[],
  width: number,
  height: number,
): SparklineGeometry | null => {
  if (!Array.isArray(points) || points.length === 0) {
    return null;
  }

  const max = Math.max(...points.map((point) => point.salesVolume));
  const min = Math.min(...points.map((point) => point.salesVolume));
  const span = max - min || 1;

  const coordinates = points.map((point, index) => {
    const x = points.length <= 1 ? width : (index / (points.length - 1)) * width;
    const y = height - ((point.salesVolume - min) / span) * height;
    return [Number(x.toFixed(2)), Number(y.toFixed(2))] as const;
  });

  const polyline = coordinates.map(([x, y]) => `${x},${y}`).join(" ");
  const area = `0,${height} ${polyline} ${width},${height}`;

  return {
    width,
    height,
    points: coordinates,
    polyline,
    area,
  };
};

export const findNearestSparklineIndex = (
  points: ReadonlyArray<readonly [number, number]>,
  relativeX: number,
): number => {
  if (!Array.isArray(points) || points.length === 0) {
    return 0;
  }

  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;

  points.forEach(([x], index) => {
    const distance = Math.abs(x - relativeX);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });

  return nearestIndex;
};
