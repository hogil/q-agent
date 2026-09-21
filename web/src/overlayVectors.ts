import { Matrix, QrDecomposition } from 'ml-matrix';

import {
  compositeMetrologyMaps,
  makeMetrologyFixture,
  METROLOGY_RADIUS,
  SYNTHETIC_SOURCE_LABEL,
  type MetrologyFixture,
} from './metrologyMap.ts';

export type OverlayVectorPoint = {
  x: number;
  y: number;
  dx: number;
  dy: number;
  contributors?: number;
};

export type OverlayFixture = {
  lotId: string;
  waferId: string;
  points: OverlayVectorPoint[];
};

export function makeOverlayFixture(
  lotId: string,
  waferId: string,
): OverlayFixture {
  const xMeasurements = makeMetrologyFixture(
    lotId,
    waferId,
    'overlay-x',
  ).points;
  const yMeasurements = makeMetrologyFixture(
    lotId,
    waferId,
    'overlay-y',
  ).points;
  if (xMeasurements.length !== yMeasurements.length)
    throw new Error('Overlay X/Y fixture lengths must match');
  return {
    lotId,
    waferId,
    points: xMeasurements.map((xPoint, index) => {
      const yPoint = yMeasurements[index];
      if (xPoint.x !== yPoint.x || xPoint.y !== yPoint.y)
        throw new Error('Overlay X/Y fixture coordinates must match');
      return { x: xPoint.x, y: xPoint.y, dx: xPoint.value, dy: yPoint.value };
    }),
  };
}

function finiteOverlayPoints(points: readonly OverlayVectorPoint[]) {
  return points.filter(
    (point) =>
      Number.isFinite(point.x) &&
      Number.isFinite(point.y) &&
      Number.isFinite(point.dx) &&
      Number.isFinite(point.dy),
  );
}

function asMetrologyFixtures(
  fixtures: readonly OverlayFixture[],
  component: 'dx' | 'dy',
  radius: number,
): MetrologyFixture[] {
  return fixtures.map((fixture) => ({
    lotId: fixture.lotId,
    waferId: fixture.waferId,
    metric: component === 'dx' ? 'overlay-x' : 'overlay-y',
    unit: 'nm',
    radius,
    points: finiteOverlayPoints(fixture.points).map((point) => ({
      x: point.x,
      y: point.y,
      value: point[component],
    })),
    sourceLabel: SYNTHETIC_SOURCE_LABEL,
  }));
}

export function compositeOverlayVectors(
  fixtures: OverlayFixture[],
  radius = METROLOGY_RADIUS,
  step = 4,
): { points: OverlayVectorPoint[]; waferCount: number } {
  const dxMap = compositeMetrologyMaps(
    asMetrologyFixtures(fixtures, 'dx', radius),
    radius,
    step,
  );
  const dyMap = compositeMetrologyMaps(
    asMetrologyFixtures(fixtures, 'dy', radius),
    radius,
    step,
  );
  const dyByCoordinate = new Map(
    dyMap.grid.map((point) => [`${point.x},${point.y}`, point]),
  );
  const points: OverlayVectorPoint[] = [];
  for (const dxPoint of dxMap.grid) {
    const dyPoint = dyByCoordinate.get(`${dxPoint.x},${dxPoint.y}`);
    if (!dyPoint || dyPoint.contributors !== dxPoint.contributors) continue;
    points.push({
      x: dxPoint.x,
      y: dxPoint.y,
      dx: dxPoint.value,
      dy: dyPoint.value,
      contributors: dxPoint.contributors,
    });
  }
  return { points, waferCount: fixtures.length };
}

function copyPoint(point: OverlayVectorPoint): OverlayVectorPoint {
  const copy: OverlayVectorPoint = {
    x: point.x,
    y: point.y,
    dx: point.dx,
    dy: point.dy,
  };
  if (point.contributors !== undefined) copy.contributors = point.contributors;
  return copy;
}

function isCollinear(points: readonly OverlayVectorPoint[]): boolean {
  let first = 0;
  let second = 1;
  let maxDistanceSquared = 0;
  for (let left = 0; left < points.length; left++) {
    for (let right = left + 1; right < points.length; right++) {
      const dx = points[left].x - points[right].x;
      const dy = points[left].y - points[right].y;
      const distanceSquared = dx * dx + dy * dy;
      if (distanceSquared > maxDistanceSquared) {
        maxDistanceSquared = distanceSquared;
        first = left;
        second = right;
      }
    }
  }
  if (maxDistanceSquared <= Number.EPSILON) return true;
  const anchor = points[first];
  const direction = points[second];
  const scale = Math.sqrt(maxDistanceSquared);
  let maxCross = 0;
  for (const point of points) {
    const cross =
      (direction.x - anchor.x) * (point.y - anchor.y) -
      (direction.y - anchor.y) * (point.x - anchor.x);
    maxCross = Math.max(maxCross, Math.abs(cross));
  }
  return maxCross <= 1e-10 * Math.max(1, scale * scale);
}

function vectorFromSolution(
  point: OverlayVectorPoint,
  dx: number,
  dy: number,
): OverlayVectorPoint {
  const result: OverlayVectorPoint = { x: point.x, y: point.y, dx, dy };
  if (point.contributors !== undefined) result.contributors = point.contributors;
  return result;
}

function rms(points: readonly OverlayVectorPoint[]): number {
  return Math.sqrt(
    points.reduce((sum, point) => sum + point.dx ** 2 + point.dy ** 2, 0) /
      points.length,
  );
}

export function fitOverlayVectors(points: readonly OverlayVectorPoint[]): {
  raw: OverlayVectorPoint[];
  fit: OverlayVectorPoint[];
  residual: OverlayVectorPoint[];
  rmsRaw: number;
  rmsResidual: number;
  coefficients: { dx: [number, number, number]; dy: [number, number, number] };
} | null {
  if (
    points.length < 3 ||
    points.some(
      (point) =>
        !Number.isFinite(point.x) ||
        !Number.isFinite(point.y) ||
        !Number.isFinite(point.dx) ||
        !Number.isFinite(point.dy) ||
        (point.contributors !== undefined &&
          !Number.isFinite(point.contributors)),
    )
  )
    return null;
  const raw = points.map(copyPoint);
  if (isCollinear(raw)) return null;

  const design = new Matrix(raw.map((point) => [1, point.x, point.y]));
  const qr = new QrDecomposition(design);
  if (!qr.isFullRank()) return null;
  let dxSolution: Matrix;
  let dySolution: Matrix;
  try {
    dxSolution = qr.solve(new Matrix(raw.map((point) => [point.dx])));
    dySolution = qr.solve(new Matrix(raw.map((point) => [point.dy])));
  } catch {
    return null;
  }
  const dxCoefficients = [
    dxSolution.get(0, 0),
    dxSolution.get(1, 0),
    dxSolution.get(2, 0),
  ] as [number, number, number];
  const dyCoefficients = [
    dySolution.get(0, 0),
    dySolution.get(1, 0),
    dySolution.get(2, 0),
  ] as [number, number, number];
  if (
    [...dxCoefficients, ...dyCoefficients].some(
      (coefficient) => !Number.isFinite(coefficient),
    )
  )
    return null;

  const fit = raw.map((point) =>
    vectorFromSolution(
      point,
      dxCoefficients[0] + dxCoefficients[1] * point.x + dxCoefficients[2] * point.y,
      dyCoefficients[0] + dyCoefficients[1] * point.x + dyCoefficients[2] * point.y,
    ),
  );
  const residual = raw.map((point, index) =>
    vectorFromSolution(
      point,
      point.dx - fit[index].dx,
      point.dy - fit[index].dy,
    ),
  );
  return {
    raw,
    fit,
    residual,
    rmsRaw: rms(raw),
    rmsResidual: rms(residual),
    coefficients: { dx: dxCoefficients, dy: dyCoefficients },
  };
}
