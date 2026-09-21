import { mean, median, sampleCorrelation } from 'simple-statistics';
import {
  signalAxisLabel,
  signalMember,
  type ChangeEvent,
  type EngineeringData,
  type FabRow,
  type Signal,
} from './engineeringData.ts';

export type InvestigationSelection = {
  signalId: string;
  start: number;
  end: number;
  rangeSelected?: boolean;
  valueRange?: [number, number];
  regions: TrendSelectionRegion[];
  equipment: string;
  recipe: string;
  maxLagDays: number;
};

export type TrendSelectionRegion = [[number, number], [number, number]];

export type AnalysisContext = {
  incident_number: string;
  item: string;
  step: string;
  equipment: string;
  recipe?: string;
  from: string;
  to: string;
  wafers: { lot_id: string; wafer_id: string }[];
  sem_wafers?: { lot_id: string; wafer_id: string }[];
  map_comparison?: {
    a: { lot_id: string; wafer_id: string }[];
    b: { lot_id: string; wafer_id: string }[];
  };
  map_view?: {
    kind: 'cd' | 'thk' | 'overlay' | 'bin';
    overlay: 'raw' | 'fit' | 'residual';
  };
  trend_selection?: {
    range_selected: boolean;
    value_range: [number, number] | null;
    regions: TrendSelectionRegion[];
  };
};

export function analysisTrendSelection(
  selection: InvestigationSelection,
): NonNullable<AnalysisContext['trend_selection']> {
  const active = selection.rangeSelected !== false;
  return {
    range_selected: active,
    value_range:
      active && selection.valueRange ? [...selection.valueRange] : null,
    regions: active ? selection.regions.map(([x, y]) => [[...x], [...y]]) : [],
  };
}

export function sameAnalysisContext(a: AnalysisContext, b: AnalysisContext) {
  const mapKey = (value: AnalysisContext['map_comparison']) =>
    value
      ? JSON.stringify((['a', 'b'] as const).map((side) =>
          value[side].map((row) => JSON.stringify([row.lot_id, row.wafer_id])).sort(),
        ))
      : null;
  const trendKey = (value: AnalysisContext['trend_selection']) =>
    value
      ? JSON.stringify([
          value.range_selected,
          value.value_range,
          value.regions.map((region) => JSON.stringify(region)).sort(),
        ])
      : null;
  return (
    (
      ['incident_number', 'item', 'step', 'equipment'] as const
    ).every((key) => a[key] === b[key]) &&
    (['from', 'to'] as const).every((key) =>
      a[key] === b[key] || Date.parse(a[key]) === Date.parse(b[key]),
    ) &&
    (a.recipe ?? '') === (b.recipe ?? '') &&
    trendKey(a.trend_selection) === trendKey(b.trend_selection) &&
    JSON.stringify((a.sem_wafers ?? []).map((w) => [w.lot_id, w.wafer_id])) ===
      JSON.stringify((b.sem_wafers ?? []).map((w) => [w.lot_id, w.wafer_id])) &&
    a.map_view?.kind === b.map_view?.kind &&
    a.map_view?.overlay === b.map_view?.overlay &&
    mapKey(a.map_comparison) === mapKey(b.map_comparison) &&
    JSON.stringify(a.wafers.map((w) => [w.lot_id, w.wafer_id]).sort()) ===
      JSON.stringify(b.wafers.map((w) => [w.lot_id, w.wafer_id]).sort())
  );
}

export const MAX_TREND_REGIONS = 16;

function isTrendSelectionRegion(value: unknown): value is TrendSelectionRegion {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    value.every(
      (axis) =>
        Array.isArray(axis) &&
        axis.length === 2 &&
        axis.every(Number.isFinite) &&
        axis[0] <= axis[1],
    )
  );
}

function trendTimeWindow(
  data: EngineeringData,
  selection: InvestigationSelection,
): [number, number] | null {
  const from = data.trend[selection.start]?.timestamp;
  const to = data.trend[selection.end]?.timestamp;
  const start = from ? Date.parse(from) : NaN;
  const end = to ? Date.parse(to) : NaN;
  return Number.isFinite(start) && Number.isFinite(end)
    ? [Math.min(start, end), Math.max(start, end)]
    : null;
}

export function selectionTimeWindows(
  data: EngineeringData,
  selection: InvestigationSelection,
): [number, number][] {
  if (selection.rangeSelected === false) return [];
  const regions = Array.isArray(selection.regions)
    ? selection.regions.filter(isTrendSelectionRegion)
    : [];
  if (regions.length) return regions.map(([x]) => x);
  const window = trendTimeWindow(data, selection);
  return window ? [window] : [];
}

export function pointInSelection(
  timestamp: number,
  value: number,
  data: EngineeringData,
  selection: InvestigationSelection,
): boolean {
  if (selection.rangeSelected === false) return true;
  const regions = Array.isArray(selection.regions)
    ? selection.regions.filter(isTrendSelectionRegion)
    : [];
  if (regions.length) {
    return regions.some(
      ([[from, to], [low, high]]) =>
        timestamp >= from && timestamp <= to && value >= low && value <= high,
    );
  }
  const window = trendTimeWindow(data, selection);
  return Boolean(
    window &&
      timestamp >= window[0] &&
      timestamp <= window[1] &&
      (!selection.valueRange ||
        (value >= selection.valueRange[0] && value <= selection.valueRange[1])),
  );
}

export function pairKey(row: { lotId: string; waferId: string }): string {
  return JSON.stringify([row.lotId, row.waferId]);
}

export function selectFabRows(
  data: EngineeringData,
  selection: InvestigationSelection,
) {
  const signal = data.signals.find((row) => row.id === selection.signalId);
  const windows = selectionTimeWindows(data, selection);
  if (!signal || (selection.rangeSelected !== false && !windows.length))
    return [];
  const rows = data.fab.filter((row) => {
    const timestamp =
      typeof row.timestamp === 'string' ? Date.parse(row.timestamp) : NaN;
    return (
      row.step === signal.step &&
      (selection.rangeSelected === false ||
        (Number.isFinite(timestamp) &&
          windows.some(
            ([from, to]) => timestamp >= from && timestamp <= to,
          ))) &&
      (!selection.equipment || row.equipment === selection.equipment) &&
      (!selection.recipe || row.recipe === selection.recipe)
    );
  });
  return [...new Map(rows.map((row) => [pairKey(row), row])).values()];
}

export function selectTrendFabRows(
  data: EngineeringData,
  signalId: string,
): FabRow[] {
  const times = data.trend.flatMap((row, index) => {
    const timestamp =
      typeof row.timestamp === 'string' ? Date.parse(row.timestamp) : NaN;
    return Number.isFinite(timestamp) ? [{ timestamp, index }] : [];
  });
  if (!times.length) return [];
  const first = times.reduce((a, b) => (a.timestamp <= b.timestamp ? a : b));
  const last = times.reduce((a, b) => (a.timestamp >= b.timestamp ? a : b));
  return selectFabRows(data, {
    signalId,
    start: first.index,
    end: last.index,
    rangeSelected: true,
    regions: [],
    equipment: '',
    recipe: '',
    maxLagDays: 0,
  });
}

export function parsePairKey(value: unknown, data: EngineeringData): string {
  return typeof value === 'string' &&
    data.fab.some((row) => pairKey(row) === value)
    ? value
    : '';
}

export function defaultSelection(
  data: EngineeringData,
  signalId?: string,
): InvestigationSelection {
  const signal =
    data.signals.find((row) => row.id === signalId) || data.signals[0];
  const equipment =
    signal && (!signal.legendAxis || signal.legendAxis === 'eqp_id')
      ? signalMember(signal)
      : '';
  const recipe = signal?.legendAxis === 'recipe' ? signalMember(signal) : '';
  return {
    signalId: signal?.id || '',
    start: 0,
    end: Math.max(0, data.trend.length - 1),
    rangeSelected: false,
    regions: [],
    equipment,
    recipe,
    maxLagDays: 14,
  };
}

export function clearTrendSelection(
  data: EngineeringData,
  selection: InvestigationSelection,
): InvestigationSelection {
  return {
    ...selection,
    start: 0,
    end: Math.max(0, data.trend.length - 1),
    rangeSelected: false,
    valueRange: undefined,
    regions: [],
  };
}

export type SignalFabScope = {
  axis: Signal['legendAxis'];
  member: string;
  exact: boolean;
  limitation: string | null;
};

export function signalFabScope(
  data: EngineeringData,
  signal: Signal,
): SignalFabScope {
  const axis = signal.legendAxis || 'eqp_id';
  const member = signalMember(signal);
  if (axis === 'chamber') {
    return {
      axis,
      member,
      exact: false,
      limitation: `${signalAxisLabel(signal)} member is not mapped to Fab metadata`,
    };
  }
  const rows = data.fab.filter((row) =>
    axis === 'recipe'
      ? row.step === signal.step && row.recipe === member
      : row.step === signal.step && row.equipment === member,
  );
  return {
    axis,
    member,
    exact: rows.length > 0,
    limitation:
      rows.length > 0
        ? null
        : `No Fab metadata matches ${signalAxisLabel(signal)} member ${member}`,
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
    (s.valueRange !== undefined &&
      (!Array.isArray(s.valueRange) ||
        s.valueRange.length !== 2 ||
        !s.valueRange.every(Number.isFinite) ||
        s.valueRange[0] > s.valueRange[1])) ||
    (s.regions !== undefined &&
      (!Array.isArray(s.regions) ||
        s.regions.length > MAX_TREND_REGIONS ||
        !s.regions.every(isTrendSelectionRegion))) ||
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
    ...(s.rangeSelected === false || s.valueRange === undefined
      ? {}
      : { valueRange: [...s.valueRange] as [number, number] }),
    regions:
      s.rangeSelected === false
        ? []
        : (s.regions || []).map(
            (region) =>
              [[...region[0]], [...region[1]]] as TrendSelectionRegion,
          ),
    equipment: s.equipment,
    recipe: s.recipe,
    maxLagDays: s.maxLagDays,
  };
}

export function signalScopeKey(signal: Signal): string {
  return JSON.stringify([signal.legendAxis || 'eqp_id', signalMember(signal)]);
}

export function restoreSelection(
  value: unknown,
  data: EngineeringData,
): InvestigationSelection | null {
  const selection = parseSelection(value, data);
  if (!selection) return null;
  const signal = data.signals.find((row) => row.id === selection.signalId)!;
  const savedScope = (value as { signalScope?: unknown }).signalScope;
  // Legacy saved selections assumed equipment; do not reuse that filter for a new axis.
  if (
    savedScope === signalScopeKey(signal) ||
    (savedScope === undefined &&
      (!signal.legendAxis || signal.legendAxis === 'eqp_id'))
  )
    return selection;
  return defaultSelection(data, signal.id);
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
  valueRange?: [number, number],
): SignalWindowStats {
  if (!metric) return emptySignalWindowStats();
  const points = indexes.flatMap((index) => {
    const row = data.trend[index];
    if (!row || typeof row.timestamp !== 'string') return [];
    const timestamp = Date.parse(row.timestamp);
    const value = row[metric];
    if (!Number.isFinite(timestamp) || !Number.isFinite(value)) return [];
    if (valueRange && (value < valueRange[0] || value > valueRange[1]))
      return [];
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
    ).filter((index) => {
      if (selection.rangeSelected === false) return true;
      const row = data.trend[index];
      const timestamp = row ? Date.parse(row.timestamp) : NaN;
      const value = row?.[metric || 'temperature'];
      return Number.isFinite(timestamp) && Number.isFinite(value)
        ? pointInSelection(timestamp, value, data, selection)
        : false;
    }),
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
  const windows = hasSelection ? selectionTimeWindows(data, selection) : [];
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
          inSelection: windows.some(
            ([from, to]) => timestamp >= from && timestamp <= to,
          ),
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
  const {
    signalId,
    start,
    end,
    equipment,
    recipe,
    maxLagDays,
    rangeSelected,
    valueRange: rawValueRange,
    regions: rawRegions,
  } = selection;
  const regions = Array.isArray(rawRegions) ? rawRegions : [];
  const bounds =
    rawValueRange === undefined && !regions.length
      ? []
      : [rawValueRange === undefined ? null : rawValueRange];
  const regionBounds = regions.length ? [regions] : [];
  return `engineering:${kind}:${JSON.stringify([signalId, start, end, equipment, recipe, maxLagDays, ...(rangeSelected === undefined && !bounds.length && !regionBounds.length ? [] : [rangeSelected ?? true]), ...bounds, ...regionBounds])}`;
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
    if (!Array.isArray(value) || ![6, 7, 8, 9].includes(value.length))
      return null;
    const [
      signalId,
      start,
      end,
      equipment,
      recipe,
      maxLagDays,
      rangeSelected,
      rawValueRange,
      regions,
    ] = value;
    return parseSelection(
      {
        signalId,
        start,
        end,
        equipment,
        recipe,
        maxLagDays,
        rangeSelected,
        valueRange: rawValueRange === null ? undefined : rawValueRange,
        regions,
      },
      data,
    );
  } catch {
    return null;
  }
}
