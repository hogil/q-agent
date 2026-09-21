import type { Workspace } from './api';
import type { EngineeringData } from './engineeringData';
import type { InvestigationSelection } from './engineeringAnalysis';
import { Matrix, QrDecomposition } from 'ml-matrix';

export type RegressionDegree = 1 | 2 | 3;

export type HistoricalRecord = {
  id: string;
  lotId: string;
  waferId: string;
  step: string;
  item: string;
  equipment: string;
  recipe: string;
  fabAt: string;
  edsAt: string;
  temperature: number;
  queue: number;
  availability: number;
  yieldPct: number;
  bin3Pct: number;
  bin4Pct: number;
};

function hash(input: string): number {
  let value = 0x811c9dc5;
  for (let index = 0; index < input.length; index++) {
    value ^= input.charCodeAt(index);
    value = Math.imul(value, 0x01000193);
  }
  return value >>> 0;
}

function unit(input: string): number {
  return hash(input) / 0xffffffff;
}

function round(value: number, digits = 2): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function floorPercent(value: number): number {
  return Math.floor(value * 100) / 100;
}

function incidentTime(workspace: Workspace): number {
  const timestamp = Date.parse(workspace.incident.occurred_at);
  return Number.isFinite(timestamp) ? timestamp : Date.UTC(2026, 0, 15, 12);
}

export function historicalData(
  workspace: Workspace,
  data: EngineeringData,
): HistoricalRecord[] {
  if (workspace.raw?.historical_records)
    return workspace.raw.historical_records;
  const anchor = incidentTime(workspace);
  const signals = data.signals.filter(
    (signal, index, all) =>
      all.findIndex(
        (candidate) =>
          candidate.step === signal.step &&
          (candidate as typeof signal & { item: string }).item ===
            (signal as typeof signal & { item: string }).item &&
          candidate.equipment === signal.equipment &&
          candidate.recipe === signal.recipe,
      ) === index,
  );
  const records: HistoricalRecord[] = [];

  for (const [signalIndex, signal] of signals.entries()) {
    for (let itemIndex = 0; itemIndex < 18; itemIndex++) {
      const index = signalIndex * 18 + itemIndex;
      const item = (signal as typeof signal & { item: string }).item;
      const key = `SYN-HIST:${workspace.incident.incident_number}:${signal.step}:${item}:${signal.equipment}:${signal.recipe}:${itemIndex}`;
      const edsAt =
        anchor - (2 + index) * 24 * 60 * 60 * 1000 - 2 * 60 * 60 * 1000;
      const fabAt = edsAt - (4 + (hash(`${key}:lag`) % 20)) * 60 * 60 * 1000;
      const temperature = 65.4 + unit(`${key}:temperature`) * 2.4;
      const queue = 1.2 + unit(`${key}:queue`) * 4.2;
      const availability = 91 + unit(`${key}:availability`) * 8;
      const yieldPct = 86 + unit(`${key}:yield`) * 11;
      const failTotal = round(100 - round(yieldPct));
      const bin3Pct = floorPercent(failTotal * unit(`${key}:bin3`));
      const bin4Pct = floorPercent(
        Math.max(0, failTotal - bin3Pct) * unit(`${key}:bin4`),
      );
      records.push({
        id: `SYN-HIST-${String(index + 1).padStart(3, '0')}`,
        lotId: `SYN-HIST-LOT-${String(index + 1).padStart(3, '0')}`,
        waferId: `SYN-HIST-W${String(index + 1).padStart(2, '0')}`,
        step: signal.step,
        item,
        equipment: signal.equipment,
        recipe: signal.recipe,
        fabAt: new Date(fabAt).toISOString(),
        edsAt: new Date(edsAt).toISOString(),
        temperature: round(temperature),
        queue: round(queue),
        availability: round(availability),
        yieldPct: round(yieldPct),
        bin3Pct: round(bin3Pct),
        bin4Pct: round(bin4Pct),
      });
    }
  }
  return records;
}

export function selectHistoricalData(
  records: HistoricalRecord[],
  data: EngineeringData,
  selection: InvestigationSelection,
): HistoricalRecord[] {
  const signal = data.signals.find(
    (candidate) => candidate.id === selection.signalId,
  );
  const cutoff = data.trend[selection.start]?.timestamp;
  if (!signal || !cutoff) return [];
  return records
    .filter(
      (record) =>
        record.step === signal.step &&
        record.item === (signal as typeof signal & { item: string }).item &&
        (!selection.equipment || record.equipment === selection.equipment) &&
        (!selection.recipe || record.recipe === selection.recipe) &&
        record.edsAt < cutoff &&
        record.fabAt <= record.edsAt,
    )
    .sort((left, right) => left.edsAt.localeCompare(right.edsAt));
}

export function fitHistoricalRegression(
  points: readonly (readonly [number, number])[],
  degree: RegressionDegree,
): { curve: [number, number][]; rSquared: number | null; n: number } | null {
  if (degree !== 1 && degree !== 2 && degree !== 3) return null;
  const finitePoints = points.filter(
    ([x, y]) => Number.isFinite(x) && Number.isFinite(y),
  );
  const distinctX = new Set(finitePoints.map(([x]) => x));
  if (finitePoints.length < degree + 1 || distinctX.size < degree + 1)
    return null;

  let xmin = finitePoints[0][0];
  let xmax = xmin;
  for (const [x] of finitePoints) {
    xmin = Math.min(xmin, x);
    xmax = Math.max(xmax, x);
  }
  const range = xmax - xmin;
  const scale = range / 2;
  const center = xmin / 2 + xmax / 2;
  if (!Number.isFinite(range) || range <= 0 || !Number.isFinite(scale))
    return null;

  const normalized = (x: number): number => (x - center) / scale;
  const design = finitePoints.map(([x]) => {
    const z = normalized(x);
    return Array.from({ length: degree + 1 }, (_, power) => z ** power);
  });
  if (design.some((row) => row.some((value) => !Number.isFinite(value))))
    return null;

  const qr = new QrDecomposition(new Matrix(design));
  if (!qr.isFullRank()) return null;
  const triangular = qr.upperTriangularMatrix;
  const diagonal = Array.from({ length: degree + 1 }, (_, i) =>
    Math.abs(triangular.get(i, i)),
  );
  const tolerance =
    Number.EPSILON * finitePoints.length * Math.max(...diagonal);
  if (diagonal.some((value) => value <= tolerance)) return null;
  let solution: Matrix;
  try {
    solution = qr.solve(new Matrix(finitePoints.map(([, y]) => [y])));
  } catch {
    return null;
  }
  const coefficients = Array.from({ length: degree + 1 }, (_, index) =>
    solution.get(index, 0),
  );
  if (coefficients.some((value) => !Number.isFinite(value))) return null;

  const predict = (x: number): number => {
    const z = normalized(x);
    let value = 0;
    for (let power = degree; power >= 0; power--)
      value = value * z + coefficients[power];
    return value;
  };
  const predictions = finitePoints.map(([x]) => predict(x));
  if (predictions.some((value) => !Number.isFinite(value))) return null;

  let mean = 0;
  let sumSquaredTotal = 0;
  for (let index = 0; index < finitePoints.length; index++) {
    const y = finitePoints[index][1];
    const delta = y - mean;
    mean += delta / (index + 1);
    sumSquaredTotal += delta * (y - mean);
  }
  let sumSquaredError = 0;
  for (let index = 0; index < finitePoints.length; index++) {
    const residual = finitePoints[index][1] - predictions[index];
    sumSquaredError += residual * residual;
  }
  if (!Number.isFinite(sumSquaredTotal) || !Number.isFinite(sumSquaredError))
    return null;
  const rSquared =
    sumSquaredTotal === 0 ? null : 1 - sumSquaredError / sumSquaredTotal;
  if (rSquared !== null && !Number.isFinite(rSquared)) return null;

  const curve: [number, number][] = Array.from({ length: 81 }, (_, index) => {
    const x =
      index === 0 ? xmin : index === 80 ? xmax : xmin + (range / 80) * index;
    return [x, predict(x)];
  });
  if (curve.some(([, y]) => !Number.isFinite(y))) return null;
  return { curve, rSquared, n: finitePoints.length };
}
