import { mean, median, sampleCorrelation } from 'simple-statistics';
import type { ChangeEvent, EngineeringData, Signal } from './engineeringData';

export type InvestigationSelection = {
  signalId: string;
  start: number;
  end: number;
  rangeSelected?: boolean;
  equipment: string;
  recipe: string;
  maxLagDays: number;
};

export function pairKey(row: { lotId: string; waferId: string }): string {
  return JSON.stringify([row.lotId, row.waferId]);
}

export function selectFabRows(
  data: EngineeringData,
  selection: InvestigationSelection,
) {
  const signal = data.signals.find((row) => row.id === selection.signalId);
  const from = data.trend[selection.start]?.timestamp;
  const to = data.trend[selection.end]?.timestamp;
  if (!signal || !from || !to) return [];
  const rows = data.fab.filter(
    (row) =>
      row.step === signal.step &&
      row.timestamp >= from &&
      row.timestamp <= to &&
      (!selection.equipment || row.equipment === selection.equipment) &&
      (!selection.recipe || row.recipe === selection.recipe),
  );
  return [...new Map(rows.map((row) => [pairKey(row), row])).values()];
}

export function parsePairKey(value: unknown, data: EngineeringData): string {
  return typeof value === 'string' &&
    data.fab.some((row) => pairKey(row) === value)
    ? value
    : '';
}

export function defaultSelection(
  data: EngineeringData,
): InvestigationSelection {
  const signal = data.signals[0];
  return {
    signalId: signal?.id || '',
    start: 0,
    end: Math.max(0, data.trend.length - 1),
    rangeSelected: false,
    equipment: signal?.equipment || '',
    recipe: '',
    maxLagDays: 14,
  };
}

export function parseSelection(
  value: unknown,
  data: EngineeringData,
): InvestigationSelection | null {
  if (!value || typeof value !== 'object') return null;
  const s = value as InvestigationSelection;
  if (
    !data.signals.some((signal) => signal.id === s.signalId) ||
    !Number.isInteger(s.start) ||
    !Number.isInteger(s.end) ||
    s.start < 0 ||
    s.end < s.start ||
    s.end >= data.trend.length ||
    (s.rangeSelected !== undefined && typeof s.rangeSelected !== 'boolean') ||
    !Number.isInteger(s.maxLagDays) ||
    s.maxLagDays < 0 ||
    s.maxLagDays > 30 ||
    typeof s.equipment !== 'string' ||
    (s.equipment !== '' &&
      !data.signals.some((signal) => signal.equipment === s.equipment)) ||
    typeof s.recipe !== 'string' ||
    (s.recipe !== '' && !data.fab.some((row) => row.recipe === s.recipe))
  )
    return null;
  return {
    signalId: s.signalId,
    start: s.rangeSelected === false ? 0 : s.start,
    end: s.rangeSelected === false ? data.trend.length - 1 : s.end,
    ...(s.rangeSelected === undefined
      ? {}
      : { rangeSelected: s.rangeSelected }),
    equipment: s.equipment,
    recipe: s.recipe,
    maxLagDays: s.maxLagDays,
  };
}

export function correlationSummary(
  rows: { value: number; yieldPct: number }[],
) {
  const valid = rows.filter(
    (row) =>
      Number.isFinite(row.value) &&
      Number.isFinite(row.yieldPct) &&
      row.yieldPct >= 0 &&
      row.yieldPct <= 100,
  );
  const x = valid.map((row) => row.value),
    y = valid.map((row) => row.yieldPct);
  const reason =
    valid.length < 3
      ? '표본 부족 (3쌍 미만)'
      : new Set(x).size < 2 || new Set(y).size < 2
        ? '변동 없음'
        : null;
  const r = reason ? null : sampleCorrelation(x, y);
  return {
    n: valid.length,
    r: r !== null && Number.isFinite(r) ? Math.max(-1, Math.min(1, r)) : null,
    reason,
    meanYield: valid.length ? mean(y) : null,
    invalid: rows.length - valid.length,
  };
}

export type SignalWindowStats = {
  n: number;
  median: number | null;
  min: number | null;
  max: number | null;
  from: string | null;
  to: string | null;
};

export type SignalWindowSummary = {
  baseline: SignalWindowStats;
  selected: SignalWindowStats;
  deltaMedian: number | null;
  comparable: boolean;
  reason:
    | 'invalid-range'
    | 'insufficient-baseline'
    | 'insufficient-selected'
    | null;
  onsetAt: string | null;
  metric: Signal['metric'] | null;
  equipment: string;
  item: string;
};

const SIGNAL_METRICS: readonly Signal['metric'][] = [
  'temperature',
  'queue',
  'availability',
];

function isSignalMetric(value: unknown): value is Signal['metric'] {
  return (
    typeof value === 'string' &&
    SIGNAL_METRICS.includes(value as Signal['metric'])
  );
}

function emptySignalWindowStats(): SignalWindowStats {
  return { n: 0, median: null, min: null, max: null, from: null, to: null };
}

function signalWindowStats(
  data: EngineeringData,
  metric: Signal['metric'] | null,
  indexes: number[],
): SignalWindowStats {
  if (!metric) return emptySignalWindowStats();
  const points = indexes.flatMap((index) => {
    const row = data.trend[index];
    if (!row || typeof row.timestamp !== 'string') return [];
    const timestamp = Date.parse(row.timestamp);
    const value = row[metric];
    if (!Number.isFinite(timestamp) || !Number.isFinite(value)) return [];
    return [{ timestamp, timestampText: row.timestamp, value }];
  });
  if (!points.length) return emptySignalWindowStats();
  const values = points.map((point) => point.value);
  const ordered = [...points].sort((a, b) => a.timestamp - b.timestamp);
  return {
    n: values.length,
    median: median(values),
    min: Math.min(...values),
    max: Math.max(...values),
    from: ordered[0].timestampText,
    to: ordered.at(-1)!.timestampText,
  };
}

function validWindowIndexes(
  data: EngineeringData,
  signal: Signal | undefined,
  selection: InvestigationSelection,
) {
  return Boolean(
    signal &&
      Array.isArray(data?.trend) &&
      Number.isInteger(signal.onsetIndex) &&
      signal.onsetIndex >= 0 &&
      signal.onsetIndex < data.trend.length &&
      Number.isInteger(selection.start) &&
      Number.isInteger(selection.end) &&
      selection.start >= 0 &&
      selection.start <= selection.end &&
      selection.end < data.trend.length,
  );
}

export function summarizeSignalWindow(
  data: EngineeringData,
  selection: InvestigationSelection,
): SignalWindowSummary {
  const signal = data?.signals?.find((row) => row.id === selection?.signalId);
  const metric = isSignalMetric(signal?.metric) ? signal.metric : null;
  const equipment =
    typeof signal?.equipment === 'string' ? signal.equipment : '';
  const item = typeof signal?.item === 'string' ? signal.item : '';
  const empty = emptySignalWindowStats();
  if (!signal || !validWindowIndexes(data, signal, selection)) {
    return {
      baseline: empty,
      selected: emptySignalWindowStats(),
      deltaMedian: null,
      comparable: false,
      reason: 'invalid-range',
      onsetAt: null,
      metric,
      equipment,
      item,
    };
  }

  const baselineEnd = Math.min(signal.onsetIndex, selection.start);
  const baseline = signalWindowStats(
    data,
    metric,
    Array.from({ length: baselineEnd }, (_, index) => index),
  );
  const selected = signalWindowStats(
    data,
    metric,
    Array.from(
      { length: selection.end - selection.start + 1 },
      (_, offset) => selection.start + offset,
    ),
  );
  const comparable = baseline.n >= 3 && selected.n >= 3;
  return {
    baseline,
    selected,
    deltaMedian: comparable ? selected.median! - baseline.median! : null,
    comparable,
    reason: comparable
      ? null
      : baseline.n < 3
        ? 'insufficient-baseline'
        : 'insufficient-selected',
    onsetAt:
      typeof data.trend[signal.onsetIndex].timestamp === 'string' &&
      Number.isFinite(Date.parse(data.trend[signal.onsetIndex].timestamp))
        ? data.trend[signal.onsetIndex].timestamp
        : null,
    metric,
    equipment,
    item,
  };
}

export type TimedChangeEvent = ChangeEvent & {
  minutesFromOnset: number;
  inSelection: boolean;
};

export function changeTiming(
  data: EngineeringData,
  signal: Signal,
  selection: InvestigationSelection,
): TimedChangeEvent[] {
  if (
    !signal ||
    typeof signal.equipment !== 'string' ||
    !Array.isArray(data?.trend) ||
    !Number.isInteger(signal.onsetIndex) ||
    signal.onsetIndex < 0 ||
    signal.onsetIndex >= data.trend.length
  ) {
    return [];
  }
  const trendTimes = data.trend.flatMap((row) => {
    const timestamp =
      typeof row.timestamp === 'string' ? Date.parse(row.timestamp) : NaN;
    return Number.isFinite(timestamp) ? [timestamp] : [];
  });
  const onsetRow = data.trend[signal.onsetIndex];
  const onset =
    typeof onsetRow.timestamp === 'string'
      ? Date.parse(onsetRow.timestamp)
      : NaN;
  if (!trendTimes.length || !Number.isFinite(onset)) return [];
  const extentFrom = Math.min(...trendTimes);
  const extentTo = Math.max(...trendTimes);
  const hasSelection =
    selection.rangeSelected !== false &&
    Number.isInteger(selection?.start) &&
    Number.isInteger(selection?.end) &&
    selection.start >= 0 &&
    selection.start <= selection.end &&
    selection.end < data.trend.length;
  const selectionTimes = hasSelection
    ? data.trend.slice(selection.start, selection.end + 1).flatMap((row) => {
        const timestamp =
          typeof row.timestamp === 'string' ? Date.parse(row.timestamp) : NaN;
        return Number.isFinite(timestamp) ? [timestamp] : [];
      })
    : [];
  const selectionFrom = selectionTimes.length
    ? Math.min(...selectionTimes)
    : NaN;
  const selectionTo = selectionTimes.length ? Math.max(...selectionTimes) : NaN;
  return (data.changes || [])
    .flatMap((event) => {
      const timestamp =
        typeof event.timestamp === 'string' ? Date.parse(event.timestamp) : NaN;
      if (
        event.equipment !== signal.equipment ||
        !Number.isFinite(timestamp) ||
        timestamp < extentFrom ||
        timestamp > extentTo ||
        (selection.recipe && event.recipe && event.recipe !== selection.recipe)
      ) {
        return [];
      }
      return [
        {
          ...event,
          minutesFromOnset: (timestamp - onset) / 60000,
          inSelection:
            Number.isFinite(selectionFrom) &&
            timestamp >= selectionFrom &&
            timestamp <= selectionTo,
        },
      ];
    })
    .sort((a, b) => {
      const time = Date.parse(a.timestamp) - Date.parse(b.timestamp);
      return time || a.id.localeCompare(b.id);
    });
}

export function engineeringReference(
  kind: 'trend' | 'corr',
  selection: InvestigationSelection,
) {
  const { signalId, start, end, equipment, recipe, maxLagDays, rangeSelected } =
    selection;
  return `engineering:${kind}:${JSON.stringify([signalId, start, end, equipment, recipe, maxLagDays, ...(rangeSelected === undefined ? [] : [rangeSelected])])}`;
}

export function parseEngineeringReference(
  reference: string,
  data: EngineeringData,
): InvestigationSelection | null {
  const prefix = reference.startsWith('engineering:corr:')
    ? 'engineering:corr:'
    : reference.startsWith('engineering:trend:')
      ? 'engineering:trend:'
      : null;
  if (!prefix) return null;
  try {
    const value = JSON.parse(reference.slice(prefix.length));
    if (!Array.isArray(value) || ![6, 7].includes(value.length)) return null;
    const [signalId, start, end, equipment, recipe, maxLagDays, rangeSelected] =
      value;
    return parseSelection(
      { signalId, start, end, equipment, recipe, maxLagDays, rangeSelected },
      data,
    );
  } catch {
    return null;
  }
}
