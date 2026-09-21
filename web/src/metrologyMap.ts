import { Delaunay } from 'd3-delaunay';

export type MetrologyMetric =
  | 'cd'
  | 'thk'
  | 'overlay-x'
  | 'overlay-y'
  | 'overlay-magnitude';

export type MeasurementPoint = {
  x: number;
  y: number;
  value: number;
};

export type InterpolatedPoint = MeasurementPoint & { kind: 'estimated' };

export type MetricStats = {
  min: number | null;
  median: number | null;
  max: number | null;
  n: number;
};

export type MetricScale = {
  min: number;
  max: number;
  kind: 'sequential' | 'diverging';
};

export const METROLOGY_RADIUS = 16;
export const SYNTHETIC_SOURCE_LABEL =
  'SYNTHETIC fixture | no actual data | no causality claim';

export const METRIC_CONFIG: Record<
  MetrologyMetric,
  MetricScale & { label: string }
> = {
  cd: { label: 'CD', min: 94, max: 110, kind: 'sequential' },
  thk: { label: 'THK', min: 480, max: 520, kind: 'sequential' },
  'overlay-x': { label: 'Overlay X', min: -2.4, max: 2.4, kind: 'diverging' },
  'overlay-y': { label: 'Overlay Y', min: -2.4, max: 2.4, kind: 'diverging' },
  'overlay-magnitude': {
    label: 'Overlay magnitude',
    min: 0,
    max: 3,
    kind: 'sequential',
  },
};

const SEQUENTIAL_COLORS = [
  '#2f5f9b',
  '#2e8b8b',
  '#65b78a',
  '#d6c35c',
  '#f1d36b',
];
const DIVERGING_COLORS = [
  '#3268a8',
  '#8db9d5',
  '#fffdf8',
  '#e8a39a',
  '#b33f4d',
];

const SAMPLE_LOCATIONS = Array.from({ length: 8 }, (_, row) =>
  Array.from({ length: 8 }, (_, column) => ({
    x: -14 + column * 4,
    y: -14 + row * 4,
  })).filter((point) => Math.hypot(point.x, point.y) <= 15),
).flat();

function hashTuple(values: readonly string[]): number {
  let hash = 0x811c9dc5;
  for (const value of JSON.stringify(values)) {
    hash ^= value.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function metrologySeed(lotId: string, waferId: string): number {
  return hashTuple([lotId, waferId]);
}

// Versioned synthetic scenario, also checked against app/demo_images.py.
export const METROLOGY_FIXTURE_VERSION = 'synthetic-common-grid-v2';
export function syntheticAnomaly(lotId: string, waferId: string) {
  if (!/^SYN-LOT-\d+-\d+$/.test(lotId)) return 'nominal';
  if (waferId === 'W01') return 'radial';
  if (waferId === 'W03') return 'translation';
  return 'nominal';
}

type SyntheticField = {
  cd: number;
  thk: number;
  overlayX: number;
  overlayY: number;
};

function syntheticFieldValue(
  x: number,
  y: number,
  seed: number,
): SyntheticField {
  const radius = Math.hypot(x, y) / METROLOGY_RADIUS;
  const angle = Math.atan2(y, x);
  const phase = (seed % 10000) / 10000;
  return {
    cd:
      101 +
      2.8 * Math.sin(angle * 2 + phase * 6.28) +
      1.2 * Math.cos(y / 4.5 - phase * 3) +
      0.8 * radius,
    thk:
      500 +
      8.5 * Math.sin(x / 5.5 - phase * 4.5) +
      5.25 * Math.cos(y / 6.5 + phase * 2.5) +
      2.2 * radius,
    overlayX:
      1.05 * Math.sin(x / 5 + phase * 4) - 0.42 * Math.cos(y / 4 - phase * 2),
    overlayY:
      0.95 * Math.cos(y / 5 - phase * 3) + 0.38 * Math.sin(x / 4 + phase * 5),
  };
}

export function metricValue(
  field: SyntheticField,
  metric: MetrologyMetric,
): number {
  if (metric === 'cd') return field.cd;
  if (metric === 'thk') return field.thk;
  if (metric === 'overlay-x') return field.overlayX;
  if (metric === 'overlay-y') return field.overlayY;
  return Math.hypot(field.overlayX, field.overlayY);
}

export function syntheticMeasurements(
  lotId: string,
  waferId: string,
  metric: MetrologyMetric,
): MeasurementPoint[] {
  const seed = metrologySeed(lotId, waferId);
  const anomaly = syntheticAnomaly(lotId, waferId);
  return SAMPLE_LOCATIONS.map(({ x, y }) => {
    const field = syntheticFieldValue(x, y, seed);
    if (anomaly === 'radial') {
      field.overlayX += 0.22 * x;
      field.overlayY += 0.22 * y;
      const edge = (Math.hypot(x, y) / METROLOGY_RADIUS) ** 4;
      field.cd += 16 * edge;
      field.thk += 42 * edge;
    } else if (anomaly === 'translation') {
      field.overlayX += 2.4;
      field.overlayY -= 1.8;
      field.cd += 10;
      field.thk -= 28;
    }
    return {
      x,
      y,
      value: metricValue(field, metric),
    };
  });
}

export function metricRange(metric: MetrologyMetric): [number, number] {
  const config = METRIC_CONFIG[metric];
  return [config.min, config.max];
}

export function normalizeMetricValue(
  metric: MetrologyMetric,
  value: number,
): number {
  if (!Number.isFinite(value)) return Number.NaN;
  const [min, max] = metricRange(metric);
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

function parseHexColor(color: string): [number, number, number] {
  return [
    Number.parseInt(color.slice(1, 3), 16),
    Number.parseInt(color.slice(3, 5), 16),
    Number.parseInt(color.slice(5, 7), 16),
  ];
}

function colorFromScale(colors: readonly string[], normalized: number): string {
  const scaled = normalized * (colors.length - 1);
  const lowerIndex = Math.floor(scaled);
  const upperIndex = Math.min(colors.length - 1, lowerIndex + 1);
  const ratio = scaled - lowerIndex;
  const lower = parseHexColor(colors[lowerIndex]);
  const upper = parseHexColor(colors[upperIndex]);
  return `#${lower
    .map((channel, index) =>
      Math.round(channel + (upper[index] - channel) * ratio)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;
}

export function metricColor(metric: MetrologyMetric, value: number): string {
  const normalized = normalizeMetricValue(metric, value);
  if (!Number.isFinite(normalized)) return '#d9dfdf';
  return colorFromScale(
    METRIC_CONFIG[metric].kind === 'diverging'
      ? DIVERGING_COLORS
      : SEQUENTIAL_COLORS,
    normalized,
  );
}

export function sanitizeMeasuredPoints(
  points: readonly MeasurementPoint[],
): MeasurementPoint[] {
  const seen = new Set<string>();
  return points.filter((point) => {
    if (
      !Number.isFinite(point.x) ||
      !Number.isFinite(point.y) ||
      !Number.isFinite(point.value)
    )
      return false;
    const key = `${point.x},${point.y}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function triangleInterpolation(
  a: MeasurementPoint,
  b: MeasurementPoint,
  c: MeasurementPoint,
  x: number,
  y: number,
): number | null {
  const determinant = (b.y - c.y) * (a.x - c.x) + (c.x - b.x) * (a.y - c.y);
  if (Math.abs(determinant) < 1e-12) return null;
  const weightA =
    ((b.y - c.y) * (x - c.x) + (c.x - b.x) * (y - c.y)) / determinant;
  const weightB =
    ((c.y - a.y) * (x - c.x) + (a.x - c.x) * (y - c.y)) / determinant;
  const weightC = 1 - weightA - weightB;
  if (Math.min(weightA, weightB, weightC) < -1e-9) return null;
  return weightA * a.value + weightB * b.value + weightC * c.value;
}

type Triangulation = {
  points: MeasurementPoint[];
  triangles: Uint32Array;
};

function makeTriangulation(points: readonly MeasurementPoint[]): Triangulation {
  const validPoints = sanitizeMeasuredPoints(points);
  if (validPoints.length < 3)
    return { points: validPoints, triangles: new Uint32Array() };
  const delaunay = Delaunay.from(
    validPoints,
    (point) => point.x,
    (point) => point.y,
  );
  return { points: validPoints, triangles: delaunay.triangles };
}

function interpolateTriangulation(
  triangulation: Triangulation,
  x: number,
  y: number,
): number | null {
  if (triangulation.points.length < 3) return null;
  for (let index = 0; index < triangulation.triangles.length; index += 3) {
    const a = triangulation.points[triangulation.triangles[index]];
    const b = triangulation.points[triangulation.triangles[index + 1]];
    const c = triangulation.points[triangulation.triangles[index + 2]];
    const value = triangleInterpolation(a, b, c, x, y);
    if (value !== null) return value;
  }
  return null;
}

// Delaunay triangles cover the measured convex hull; barycentric weights reject everything outside it.
export function interpolateBarycentric(
  points: readonly MeasurementPoint[],
  x: number,
  y: number,
): number | null {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return interpolateTriangulation(makeTriangulation(points), x, y);
}

export function interpolateAt(
  points: readonly MeasurementPoint[],
  x: number,
  y: number,
): number | null {
  return interpolateBarycentric(points, x, y);
}

export function interpolateWaferGrid(
  points: readonly MeasurementPoint[],
  radius = METROLOGY_RADIUS,
  step = 1,
): InterpolatedPoint[] {
  if (
    !Number.isFinite(radius) ||
    radius <= 0 ||
    !Number.isFinite(step) ||
    step <= 0
  )
    throw new Error(
      'Wafer radius and grid step must be positive finite values',
    );
  const triangulation = makeTriangulation(points);
  const cells: InterpolatedPoint[] = [];
  const count = Math.floor((2 * radius) / step + 1e-9);
  for (let row = 0; row <= count; row++) {
    const y = -radius + row * step;
    for (let column = 0; column <= count; column++) {
      const x = -radius + column * step;
      if (Math.hypot(x, y) > radius + 1e-9) continue;
      const value = interpolateTriangulation(triangulation, x, y);
      if (value !== null) cells.push({ x, y, value, kind: 'estimated' });
    }
  }
  return cells;
}

export type CompositeMetrologyMap = {
  grid: (InterpolatedPoint & { contributors: number })[];
  waferCount: number;
  measurementCount: number;
};

function validateCompositeInputs(
  fixtures: readonly MetrologyFixture[],
  radius: number,
  step: number,
): void {
  if (!Number.isFinite(radius) || radius <= 0)
    throw new Error('Wafer radius must be a positive finite value');
  if (!Number.isFinite(step) || step <= 0)
    throw new Error('Grid step must be a positive finite value');
  if (fixtures.length === 0) return;

  const first = fixtures[0];
  const keys = new Set<string>();
  for (const fixture of fixtures) {
    const key = JSON.stringify([fixture.lotId, fixture.waferId]);
    if (keys.has(key)) throw new Error('Duplicate lot/wafer fixture');
    keys.add(key);
    if (fixture.metric !== first.metric)
      throw new Error('Composite fixtures must use one metric');
    if (fixture.unit !== first.unit)
      throw new Error('Composite fixtures must use one unit');
    if (
      !Number.isFinite(fixture.radius) ||
      fixture.radius <= 0 ||
      Math.abs(fixture.radius - radius) > 1e-9
    )
      throw new Error('Fixture radius must match the composite radius');
  }
}

export function compositeMetrologyMaps(
  fixtures: MetrologyFixture[],
  radius = METROLOGY_RADIUS,
  step = 1,
): CompositeMetrologyMap {
  validateCompositeInputs(fixtures, radius, step);
  if (fixtures.length === 0)
    return { grid: [], waferCount: 0, measurementCount: 0 };

  const sums = new Map<
    string,
    { x: number; y: number; sum: number; contributors: number }
  >();
  let measurementCount = 0;
  for (const fixture of fixtures) {
    const measured = sanitizeMeasuredPoints(fixture.points);
    measurementCount += measured.length;
    for (const point of interpolateWaferGrid(measured, radius, step)) {
      const key = `${point.x},${point.y}`;
      const cell = sums.get(key);
      if (cell) {
        cell.sum += point.value;
        cell.contributors += 1;
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

  const grid = [...sums.values()]
    .sort((left, right) => left.y - right.y || left.x - right.x)
    .map((cell) => ({
      x: cell.x,
      y: cell.y,
      value: cell.sum / cell.contributors,
      kind: 'estimated' as const,
      contributors: cell.contributors,
    }));
  return { grid, waferCount: fixtures.length, measurementCount };
}

export function waferOutline(radius = METROLOGY_RADIUS): [number, number][] {
  if (!Number.isFinite(radius) || radius <= 0)
    throw new Error('Wafer radius must be a positive finite value');
  return Array.from({ length: 73 }, (_, index) => {
    const angle = (index / 72) * Math.PI * 2;
    return [radius * Math.cos(angle), radius * Math.sin(angle)];
  });
}

export function metricStats(points: readonly MeasurementPoint[]): MetricStats {
  const values = sanitizeMeasuredPoints(points)
    .map((point) => point.value)
    .sort((left, right) => left - right);
  if (values.length === 0) return { min: null, median: null, max: null, n: 0 };
  const middle = Math.floor(values.length / 2);
  return {
    min: values[0],
    median:
      values.length % 2 === 0
        ? (values[middle - 1] + values[middle]) / 2
        : values[middle],
    max: values[values.length - 1],
    n: values.length,
  };
}

export function selectMeasuredRegion(
  points: readonly MeasurementPoint[],
  region: [[number, number], [number, number]] | null,
): MeasurementPoint[] {
  if (!region) return sanitizeMeasuredPoints(points);
  if (!region.flat().every(Number.isFinite)) return [];
  const [[x1, x2], [y1, y2]] = region;
  return sanitizeMeasuredPoints(points).filter(
    (point) =>
      point.x >= Math.min(x1, x2) &&
      point.x <= Math.max(x1, x2) &&
      point.y >= Math.min(y1, y2) &&
      point.y <= Math.max(y1, y2),
  );
}

export type MetrologyFixture = {
  lotId: string;
  waferId: string;
  metric: MetrologyMetric;
  unit: 'nm';
  radius: number;
  points: MeasurementPoint[];
  sourceLabel: string;
};

export function makeMetrologyFixture(
  lotId: string,
  waferId: string,
  metric: MetrologyMetric,
): MetrologyFixture {
  return {
    lotId,
    waferId,
    metric,
    unit: 'nm',
    radius: METROLOGY_RADIUS,
    points: syntheticMeasurements(lotId, waferId, metric),
    sourceLabel: SYNTHETIC_SOURCE_LABEL,
  };
}
