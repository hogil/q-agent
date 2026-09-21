import type { WaferGeometry } from './api';
import type { MeasurementPoint } from './metrologyMap';

export type ProfileOrder = 'point' | 'radius';

export type ProfilePoint = MeasurementPoint & {
  sourceIndex: number;
  selectionKey: string;
  radius: number;
  contributors: number;
};

export type RadialMeanPoint = {
  x: number;
  start: number;
  end: number;
  mean: number;
  contributors: number;
  kind: 'radial-mean';
};

export type MetrologyProfile = {
  points: ProfilePoint[];
  radialMeans: RadialMeanPoint[];
  edgeRadius: number;
  radiusUnit: 'mm' | 'coord';
};

export function profileRadius(
  point: Pick<MeasurementPoint, 'x' | 'y'>,
  geometry: WaferGeometry | undefined,
): number {
  if (geometry) {
    const mmPerUnit = geometry.radius_mm / geometry.coordinate_radius;
    return Math.hypot(point.x * mmPerUnit, point.y * mmPerUnit);
  }
  return Math.hypot(point.x, point.y);
}

export function orderProfilePoints(
  points: readonly ProfilePoint[],
  order: ProfileOrder,
): ProfilePoint[] {
  if (order === 'point') return [...points];
  return [...points].sort(
    (left, right) => left.radius - right.radius || left.sourceIndex - right.sourceIndex,
  );
}

function coordinateKey(x: number, y: number): string {
  return JSON.stringify([x, y]);
}

export function makeRadialMeans(
  points: readonly ProfilePoint[],
  edgeRadius: number,
  binCount = 8,
): RadialMeanPoint[] {
  if (!Number.isFinite(edgeRadius) || edgeRadius <= 0 || points.length === 0)
    return [];
  const count = Math.max(1, Math.floor(binCount));
  const width = edgeRadius / count;
  const bins = Array.from({ length: count }, (_, index) => ({
    start: index * width,
    end: (index + 1) * width,
    sum: 0,
    radiusSum: 0,
    contributors: 0,
  }));
  for (const point of points) {
    if (
      !Number.isFinite(point.radius) ||
      point.radius < 0 ||
      point.radius > edgeRadius + 1e-9 ||
      !Number.isFinite(point.value)
    )
      continue;
    const index = Math.min(count - 1, Math.floor(point.radius / width));
    const bin = bins[index];
    if (!bin) continue;
    bin.sum += point.value;
    bin.radiusSum += point.radius;
    bin.contributors += 1;
  }
  return bins
    .filter((bin) => bin.contributors > 0)
    .map((bin) => ({
      x: bin.radiusSum / bin.contributors,
      start: bin.start,
      end: bin.end,
      mean: bin.sum / bin.contributors,
      contributors: bin.contributors,
      kind: 'radial-mean' as const,
    }));
}

export function makeMetrologyProfile(
  points: readonly MeasurementPoint[],
  geometry: WaferGeometry | undefined,
  coordinateRadius: number,
  binCount = 8,
): MetrologyProfile {
  const edgeRadius = geometry?.radius_mm ?? coordinateRadius;
  const profilePoints = points.flatMap((point, sourceIndex) => {
    if (
      !Number.isFinite(point.x) ||
      !Number.isFinite(point.y) ||
      !Number.isFinite(point.value)
    )
      return [];
    const radius = profileRadius(point, geometry);
    if (!Number.isFinite(radius) || radius < 0 || radius > edgeRadius + 1e-9)
      return [];
    return [
      {
        ...point,
        sourceIndex,
        selectionKey: coordinateKey(point.x, point.y),
        radius,
        contributors: 1,
      },
    ];
  });
  const radiusUnit = geometry ? 'mm' : 'coord';
  return {
    points: profilePoints,
    radialMeans: makeRadialMeans(profilePoints, edgeRadius, binCount),
    edgeRadius,
    radiusUnit,
  };
}

export function makeAggregateMetrologyProfile(
  pointSets: readonly (readonly MeasurementPoint[])[],
  geometry: WaferGeometry | undefined,
  coordinateRadius: number,
  binCount = 8,
): MetrologyProfile {
  const sums = new Map<
    string,
    { x: number; y: number; sum: number; contributors: number }
  >();
  for (const points of pointSets) {
    const seen = new Set<string>();
    for (const point of points) {
      if (
        !Number.isFinite(point.x) ||
        !Number.isFinite(point.y) ||
        !Number.isFinite(point.value)
      )
        continue;
      const key = coordinateKey(point.x, point.y);
      if (seen.has(key)) continue;
      seen.add(key);
      const entry = sums.get(key);
      if (entry) {
        entry.sum += point.value;
        entry.contributors += 1;
      } else {
        sums.set(key, {
          x: point.x,
          y: point.y,
          sum: point.value,
          contributors: 1,
        });
      }
    }
  }
  const edgeRadius = geometry?.radius_mm ?? coordinateRadius;
  const profilePoints = [...sums.values()].flatMap((point, sourceIndex) => {
    const radius = profileRadius(point, geometry);
    if (!Number.isFinite(radius) || radius < 0 || radius > edgeRadius + 1e-9)
      return [];
    return [
      {
        x: point.x,
        y: point.y,
        value: point.sum / point.contributors,
        sourceIndex,
        selectionKey: coordinateKey(point.x, point.y),
        radius,
        contributors: point.contributors,
      },
    ];
  });
  return {
    points: profilePoints,
    radialMeans: makeRadialMeans(profilePoints, edgeRadius, binCount),
    edgeRadius,
    radiusUnit: geometry ? 'mm' : 'coord',
  };
}
