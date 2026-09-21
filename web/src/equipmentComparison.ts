import { median } from 'simple-statistics';
import type { EngineeringData, Signal } from './engineeringData';

export type EquipmentTracePoint = {
  timestamp: string;
  value: number;
};

export type EquipmentComparisonPair = {
  timestamp: string;
  valueA: number;
  valueB: number;
  delta: number;
};

export type EquipmentComparison = {
  valid: boolean;
  reason?:
    | 'invalid-signal'
    | 'invalid-equipment'
    | 'same-equipment'
    | 'invalid-range'
    | 'empty-range'
    | 'no-pairs';
  equipmentA: string;
  equipmentB: string;
  pairs: EquipmentComparisonPair[];
  count: number;
  medianA: number | null;
  medianB: number | null;
  deltaMedian: number | null;
  meanA: number | null;
  meanB: number | null;
};

type Metric = Signal['metric'];

const METRICS: readonly Metric[] = ['temperature', 'queue', 'availability'];

function isMetric(value: unknown): value is Metric {
  return typeof value === 'string' && METRICS.includes(value as Metric);
}

function usesEquipmentAxis(signal: Signal) {
  return !signal.legendAxis || signal.legendAxis === 'eqp_id';
}

function isSignal(signal: Signal): boolean {
  return Boolean(
    signal &&
      typeof signal.id === 'string' &&
      typeof signal.item === 'string' &&
      typeof signal.step === 'string' &&
      typeof signal.equipment === 'string' &&
      signal.equipment.length > 0 &&
      isMetric(signal.metric) &&
      Number.isInteger(signal.onsetIndex),
  );
}

function hash(input: string) {
  let value = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    value ^= input.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

function unit(input: string) {
  return hash(input) / 0xffffffff;
}

function mean(values: number[]) {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function emptyComparison(
  equipmentA: string,
  equipmentB: string,
  reason: EquipmentComparison['reason'],
): EquipmentComparison {
  return {
    valid: false,
    reason,
    equipmentA,
    equipmentB,
    pairs: [],
    count: 0,
    medianA: null,
    medianB: null,
    deltaMedian: null,
    meanA: null,
    meanB: null,
  };
}

/** Equipment choices are limited to the selected signal and same-step fab fixtures. */
export function availableEquipment(
  data: EngineeringData,
  signal: Signal,
): string[] {
  if (!isSignal(signal) || !usesEquipmentAxis(signal) || !Array.isArray(data?.fab)) return [];
  return [
    ...new Set([
      signal.equipment,
      ...data.fab
        .filter(
          (row) =>
            row.step === signal.step &&
            typeof row.equipment === 'string' &&
            row.equipment.length > 0,
        )
        .map((row) => row.equipment),
    ]),
  ];
}

function peerSpread(metric: Metric) {
  if (metric === 'temperature') return 0.08;
  if (metric === 'queue') return 0.05;
  return 0.12;
}

export function makeEquipmentTrace(
  data: EngineeringData,
  signal: Signal,
  equipment: string,
): EquipmentTracePoint[] {
  if (!usesEquipmentAxis(signal)) return [];
  if (data.comparisonTraces) return data.comparisonTraces[signal.id]?.[equipment] || [];
  if (
    !isSignal(signal) ||
    typeof equipment !== 'string' ||
    !availableEquipment(data, signal).includes(equipment) ||
    !Array.isArray(data?.trend)
  ) {
    return [];
  }

  const targetTrace = data.trend.map((row) => ({
    timestamp: row.timestamp,
    value: row[signal.metric],
  }));
  if (equipment === signal.equipment) return targetTrace;

  const onset = Math.max(1, Math.min(signal.onsetIndex, data.trend.length));
  const baselineValues = targetTrace
    .slice(0, onset)
    .map((point) => point.value)
    .filter((value) => Number.isFinite(value));
  if (!baselineValues.length) return [];

  const baseline = median(baselineValues);
  const spread = peerSpread(signal.metric);
  return targetTrace.map((point, index) => {
    const noise =
      (unit(
        `${signal.id}:${signal.item}:${signal.step}:${signal.metric}:${equipment}:${point.timestamp}:${index}`,
      ) -
        0.5) *
      2 *
      spread;
    return {
      timestamp: point.timestamp,
      value: Number((baseline + noise).toFixed(6)),
    };
  });
}

export function compareEquipment(
  data: EngineeringData,
  signal: Signal,
  equipmentA: string,
  equipmentB: string,
  fromIndex: number,
  toIndex: number,
): EquipmentComparison {
  if (!isSignal(signal) || !Array.isArray(data?.trend) || !data.trend.length) {
    return emptyComparison(equipmentA, equipmentB, 'invalid-signal');
  }
  if (
    typeof equipmentA !== 'string' ||
    typeof equipmentB !== 'string' ||
    !equipmentA ||
    !equipmentB ||
    !availableEquipment(data, signal).includes(equipmentA) ||
    !availableEquipment(data, signal).includes(equipmentB)
  ) {
    return emptyComparison(equipmentA, equipmentB, 'invalid-equipment');
  }
  if (equipmentA === equipmentB) {
    return emptyComparison(equipmentA, equipmentB, 'same-equipment');
  }
  if (
    !Number.isInteger(fromIndex) ||
    !Number.isInteger(toIndex) ||
    fromIndex < 0 ||
    fromIndex >= data.trend.length ||
    toIndex < 0 ||
    toIndex >= data.trend.length
  ) {
    return emptyComparison(equipmentA, equipmentB, 'invalid-range');
  }
  if (fromIndex > toIndex) {
    return emptyComparison(equipmentA, equipmentB, 'empty-range');
  }

  const traceA = makeEquipmentTrace(data, signal, equipmentA);
  const traceB = makeEquipmentTrace(data, signal, equipmentB);
  const pairs = traceA
    .slice(fromIndex, toIndex + 1)
    .flatMap((pointA, offset) => {
      const pointB = traceB[fromIndex + offset];
      if (
        !pointB ||
        pointA.timestamp !== pointB.timestamp ||
        !Number.isFinite(pointA.value) ||
        !Number.isFinite(pointB.value)
      ) {
        return [];
      }
      return [
        {
          timestamp: pointA.timestamp,
          valueA: pointA.value,
          valueB: pointB.value,
          delta: pointA.value - pointB.value,
        },
      ];
    });
  if (!pairs.length) {
    return emptyComparison(equipmentA, equipmentB, 'no-pairs');
  }

  const valuesA = pairs.map((pair) => pair.valueA);
  const valuesB = pairs.map((pair) => pair.valueB);
  const medianA = median(valuesA);
  const medianB = median(valuesB);
  return {
    valid: true,
    equipmentA,
    equipmentB,
    pairs,
    count: pairs.length,
    medianA,
    medianB,
    deltaMedian: medianA - medianB,
    meanA: mean(valuesA),
    meanB: mean(valuesB),
  };
}
