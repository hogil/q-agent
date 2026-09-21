import type { Workspace } from './api';
import type { InformNote } from './investigationData';
import type { EquipmentTracePoint } from './equipmentComparison';

export type TrendFleet = { member: string; highlighted: boolean; points: number[][] };

export type AnomalyPattern =
  | 'drift'
  | 'abrupt_level_shift'
  | 'spike'
  | 'variance_burst'
  | 'periodic_pattern';

export type LegendAxis = 'eqp_id' | 'chamber' | 'recipe';

export type Signal = {
  id: string;
  title: string;
  severity: 'high' | 'medium';
  metric: 'temperature' | 'queue' | 'availability';
  device: string;
  equipment: string;
  step: string;
  item: string;
  legendAxis: LegendAxis;
  highlightedMember?: string;
  recipe: string;
  detectedAt: string;
  startIndex: number;
  endIndex: number;
  description: string;
  onsetIndex: number;
  pattern?: AnomalyPattern;
};

export function signalMember(
  signal: Pick<Signal, 'legendAxis' | 'equipment' | 'highlightedMember'>,
): string {
  if (typeof signal.highlightedMember === 'string' && signal.highlightedMember.trim()) {
    return signal.highlightedMember;
  }
  return !signal.legendAxis || signal.legendAxis === 'eqp_id'
    ? signal.equipment
    : '';
}

export function signalAxisLabel(
  signal: Pick<Signal, 'legendAxis'>,
): string {
  const axis = signal.legendAxis || 'eqp_id';
  return (
    {
      eqp_id: 'Equipment',
      chamber: 'Chamber',
      recipe: 'Recipe',
    } as Record<string, string>
  )[axis] ?? axis;
}

export type TrendPoint = {
  timestamp: string;
  temperature: number;
  queue: number;
  availability: number;
};

export type FabRow = {
  lotId: string;
  waferId: string;
  timestamp: string;
  equipment: string;
  step: string;
  recipe: string;
  value: number;
};

export type YieldRow = {
  lotId: string;
  waferId: string;
  measuredAt: string;
  yieldPct: number | null;
};

export type WipRow = {
  lotId: string;
  productCode: string;
  layer: number;
  endLayer: number;
  step: string;
  equipment: string;
  recipe: string;
  status: 'RUN' | 'WAIT' | 'HOLD';
  wafers: number;
  queueHours: number;
  holdCode: string;
};

export type DownEvent = {
  id: string;
  equipment: string;
  start: string;
  end: string;
  code: string;
  category: string;
  description: string;
};

export type EquipmentState = 'RUN' | 'DOWN' | 'PM' | 'IDLE';

export type EquipmentStateInterval = {
  equipment: string;
  start: string;
  end: string;
  state: EquipmentState;
  code: string;
};

export type EngineeringData = {
  trendFleets?: Record<string, TrendFleet[]>;
  comparisonTraces?: Record<string, Record<string, EquipmentTracePoint[]>>;
  informNotes?: InformNote[];
  signals: Signal[];
  trend: TrendPoint[];
  fab: FabRow[];
  yields: YieldRow[];
  wip: WipRow[];
  downtime: DownEvent[];
  changes: ChangeEvent[];
  equipmentStates?: EquipmentStateInterval[];
};

export type ChangeEvent = {
  id: string;
  equipment: string;
  recipe: string;
  kind: 'recipe' | 'system';
  timestamp: string;
  before: string;
  after: string;
  sourceRef: string;
};

export type FabYieldMatchOptions = {
  from: string;
  to: string;
  equipment?: string;
  recipe?: string;
  maxLagDays: number;
};

export type FabYieldPair = FabRow & {
  yieldPct: number;
  measuredAt: string;
  lagDays: number;
};

export type FabYieldMatch = {
  pairs: FabYieldPair[];
  eligible: number;
  missing: number;
  ambiguous: number;
  outsideLag: number;
};

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
const STEP = 'SYN-ETCH-10';
function emptyMatch(): FabYieldMatch {
  return {
    pairs: [],
    eligible: 0,
    missing: 0,
    ambiguous: 0,
    outsideLag: 0,
  };
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

function avalanche(value: number) {
  let mixed = (value + 0x9e3779b9) >>> 0;
  mixed = Math.imul(mixed ^ (mixed >>> 16), 0x85ebca6b) >>> 0;
  mixed = Math.imul(mixed ^ (mixed >>> 13), 0xc2b2ae35) >>> 0;
  return (mixed ^ (mixed >>> 16)) >>> 0;
}

export function seededNormalNoise(input: string) {
  const first = Math.max(
    avalanche(hash(`${input}:box-muller-u1`)) / 0x100000000,
    Number.EPSILON,
  );
  const second =
    avalanche(hash(`${input}:box-muller-u2`)) / 0x100000000;
  return Math.sqrt(-2 * Math.log(first)) * Math.cos(2 * Math.PI * second);
}

function parseTime(value: string) {
  if (typeof value !== 'string' || value.trim() === '') return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function iso(timestamp: number) {
  return new Date(timestamp).toISOString();
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function pairKey(lotId: string, waferId: string) {
  return `${lotId}\u0000${waferId}`;
}

function uniqueWafers(workspace: Workspace) {
  const seen = new Set<string>();
  const lots = new Set(workspace.lots.map((lot) => lot.lot_id));
  return workspace.wafers
    .filter(
      (wafer) =>
        lots.has(wafer.lot_id) && wafer.lot_id !== '' && wafer.wafer_id !== '',
    )
    .filter((wafer) => {
      const key = pairKey(wafer.lot_id, wafer.wafer_id);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort(
      (left, right) =>
        left.lot_id.localeCompare(right.lot_id) ||
        left.wafer_id.localeCompare(right.wafer_id),
    );
}

function uniqueLots(workspace: Workspace) {
  const seen = new Set<string>();
  return workspace.lots
    .filter((lot) => lot.lot_id !== '')
    .filter((lot) => {
      if (seen.has(lot.lot_id)) return false;
      seen.add(lot.lot_id);
      return true;
    })
    .sort((left, right) => left.lot_id.localeCompare(right.lot_id));
}

function makeAnchor(workspace: Workspace) {
  return parseTime(workspace.incident.occurred_at) ?? 0;
}

function equipmentFor(seed: string) {
  return hash(seed) % 2 === 0 ? 'SYN-EQP-01' : 'SYN-EQP-02';
}

function recipeFor(seed: string) {
  return hash(seed) % 2 === 0 ? 'SYN-RCP-A' : 'SYN-RCP-B';
}

export function makeEngineeringData(workspace: Workspace): EngineeringData {
  if (workspace.raw) return {
    ...workspace.raw.engineering,
    trendFleets: workspace.raw.trend_fleets,
    comparisonTraces: workspace.raw.comparison_traces,
    informNotes: workspace.raw.inform_notes,
  };
  const anchor = makeAnchor(workspace);
  const incidentAt = iso(anchor);
  const source = incidentAt;
  const wafers = uniqueWafers(workspace);
  const lots = uniqueLots(workspace);

  const trend = Array.from({ length: 24 }, (_, index) => {
    const progress = index / 23;
    const temperature =
      65.05 +
      progress * 0.05 +
      seededNormalNoise(`${source}:normal:temperature:${index}`) * 0.04;
    const queue =
      1.5 +
      progress * 0.02 +
      seededNormalNoise(`${source}:normal:queue:${index}`) * 0.025;
    const availability = clamp(
      99.4 -
        progress * 0.08 +
        seededNormalNoise(`${source}:normal:availability:${index}`) * 0.055,
      87,
      100,
    );
    return {
      timestamp: iso(anchor - 11 * HOUR + index * HOUR),
      temperature: Number(temperature.toFixed(2)),
      queue: Number(queue.toFixed(2)),
      availability: Number(availability.toFixed(2)),
    };
  });

  const signals: Signal[] = [
    {
      id: 'synthetic-signal-heater-drift',
      title: '공정 온도 완만한 Drift',
      severity: 'medium',
      metric: 'temperature',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-01',
      step: STEP,
      item: 'SYN-TEMP',
      legendAxis: 'eqp_id',
      recipe: 'SYN-RCP-A',
      detectedAt: incidentAt,
      startIndex: 5,
      endIndex: 21,
      description: 'SYN-EQP-01 · SYN-ETCH-10 · 합성 완만한 온도 이동 · 정상 범위와 일부 중첩',
      onsetIndex: 5,
      pattern: 'drift',
    },
    {
      id: 'synthetic-signal-queue-rise',
      title: 'Queue time 완만한 증가',
      severity: 'medium',
      metric: 'queue',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-02',
      step: STEP,
      item: 'SYN-QUEUE',
      legendAxis: 'eqp_id',
      highlightedMember: 'SYN-EQP-02',
      recipe: 'SYN-RCP-B',
      detectedAt: incidentAt,
      startIndex: 8,
      endIndex: 19,
      description: 'SYN-EQP-02 · SYN-ETCH-10 · 합성 완만한 대기시간 이동 · 정상 범위와 일부 중첩',
      onsetIndex: 8,
      pattern: 'drift',
    },
    {
      id: 'synthetic-signal-equipment-down',
      title: '설비 가동률 소폭 변동',
      severity: 'medium',
      metric: 'availability',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-02',
      step: STEP,
      item: 'SYN-AVAIL',
      legendAxis: 'eqp_id',
      highlightedMember: 'SYN-EQP-02',
      recipe: 'SYN-RCP-B',
      detectedAt: incidentAt,
      startIndex: 14,
      endIndex: 17,
      description: 'SYN-EQP-02 · 합성 소폭 가동률 변동 · 원인 판정 보류',
      onsetIndex: 14,
      pattern: 'drift',
    },
    {
      id: 'synthetic-signal-level-shift',
      title: '공정 온도 평균값 소폭 이동',
      severity: 'medium',
      metric: 'temperature',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-01',
      step: STEP,
      item: 'SYN-MEAN-SHIFT',
      legendAxis: 'eqp_id',
      recipe: 'SYN-RCP-A',
      detectedAt: incidentAt,
      startIndex: 8,
      endIndex: 17,
      description: 'SYN-EQP-01 · SYN-ETCH-10 · 합성 평균값 소폭 이동 · 급격한 변화 아님',
      onsetIndex: 8,
      pattern: 'abrupt_level_shift',
    },
    {
      id: 'synthetic-signal-spike',
      title: 'Queue 국소 소형 Spike',
      severity: 'medium',
      metric: 'queue',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-02',
      step: STEP,
      item: 'SYN-SPIKE',
      legendAxis: 'eqp_id',
      recipe: 'SYN-RCP-B',
      detectedAt: incidentAt,
      startIndex: 7,
      endIndex: 20,
      description: 'SYN-EQP-02 · SYN-ETCH-10 · 합성 간헐적 소형 Spike · 정상 변동과 중첩',
      onsetIndex: 7,
      pattern: 'spike',
    },
    {
      id: 'synthetic-signal-variance-burst',
      title: '설비 가동률 분산 소폭 증가',
      severity: 'medium',
      metric: 'availability',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-02',
      step: STEP,
      item: 'SYN-VARIANCE',
      legendAxis: 'eqp_id',
      recipe: 'SYN-RCP-B',
      detectedAt: incidentAt,
      startIndex: 9,
      endIndex: 19,
      description: 'SYN-EQP-02 · SYN-ETCH-10 · 합성 분산 소폭 증가 · 추가 확인 필요',
      onsetIndex: 9,
      pattern: 'variance_burst',
    },
    {
      id: 'synthetic-signal-periodic',
      title: '공정 온도 완만한 주기 변동',
      severity: 'medium',
      metric: 'temperature',
      device: 'SYN-DEV-01',
      equipment: 'SYN-EQP-01',
      step: STEP,
      item: 'SYN-PERIODIC',
      legendAxis: 'eqp_id',
      recipe: 'SYN-RCP-A',
      detectedAt: incidentAt,
      startIndex: 6,
      endIndex: 21,
      description: 'SYN-EQP-01 · SYN-ETCH-10 · 합성 완만한 주기 변동 · 정상 범위와 중첩',
      onsetIndex: 6,
      pattern: 'periodic_pattern',
    },
  ];

  const fab = wafers.map((wafer, index) => {
    const seed = `${source}:${wafer.lot_id}:${wafer.wafer_id}`;
    return {
      lotId: wafer.lot_id,
      waferId: wafer.wafer_id,
      timestamp: iso(anchor - 11 * HOUR + (5 + (index % 16)) * HOUR),
      equipment: equipmentFor(`${seed}:equipment`),
      step: STEP,
      recipe: recipeFor(`${seed}:recipe`),
      value: Number(
        (
          trend[5 + (index % 16)].temperature +
          (unit(`${seed}:fab`) - 0.5) * 0.2
        ).toFixed(2),
      ),
    };
  });

  const yields: YieldRow[] = [];

  const waferCounts = new Map<string, number>();
  for (const wafer of wafers) {
    waferCounts.set(wafer.lot_id, (waferCounts.get(wafer.lot_id) ?? 0) + 1);
  }
  const wip = lots.map((lot, index) => {
    const seed = `${source}:${lot.lot_id}`;
    const status = (['RUN', 'WAIT', 'HOLD'] as const)[index % 3];
    return {
      lotId: lot.lot_id,
      productCode: lot.product_code,
      layer: Number((8 + index * 1.5 + unit(`${seed}:layer`)).toFixed(1)),
      endLayer: 40,
      step: STEP,
      equipment: equipmentFor(`${seed}:equipment`),
      recipe: recipeFor(`${seed}:recipe`),
      status,
      wafers: waferCounts.get(lot.lot_id) ?? 0,
      queueHours: Number(
        (status === 'RUN'
          ? 0.5 + unit(`${seed}:queue`) * 1.5
          : status === 'WAIT'
            ? 2 + unit(`${seed}:queue`) * 8
            : 4 + unit(`${seed}:queue`) * 12
        ).toFixed(2),
      ),
      holdCode:
        status === 'HOLD'
          ? `SYN-HOLD-${String(index + 1).padStart(2, '0')}`
          : 'SYN-NONE',
    };
  });

  const downtime: DownEvent[] = Array.from({ length: 4 }, (_, index) => {
    const start = anchor - (9 - index * 3) * HOUR;
    const duration = (1 + (hash(`${source}:down:${index}`) % 3)) * HOUR;
    return {
      id: `synthetic-down-${String(index + 1).padStart(2, '0')}`,
      equipment: index % 2 === 0 ? 'SYN-EQP-01' : 'SYN-EQP-02',
      start: iso(start),
      end: iso(start + duration),
      code: `SYN-DOWN-${String(index + 1).padStart(2, '0')}`,
      category: ['보정 점검', '예방 정비', '센서 확인', '설비 복구'][index],
      description: [
        '합성 히터 보정값 점검',
        '합성 Chamber 예방 정비',
        '합성 센서 신호 확인',
        '합성 설비 상태 복구 확인',
      ][index],
    };
  });

  const changes: ChangeEvent[] = ['SYN-EQP-01', 'SYN-EQP-02'].flatMap(
    (equipment, index) => [
      {
        id: `SYN-CHANGE-R${index}`,
        equipment,
        recipe: index ? 'SYN-RCP-B' : 'SYN-RCP-A',
        kind: 'recipe' as const,
        timestamp: trend[4 + index * 3].timestamp,
        before: 'v1.6',
        after: 'v1.7',
        sourceRef: `synthetic://recipe/version-${index}`,
      },
      {
        id: `SYN-CHANGE-S${index}`,
        equipment,
        recipe: '',
        kind: 'system' as const,
        timestamp: trend[9 + index * 3].timestamp,
        before: 'Rule 2',
        after: 'Rule 3',
        sourceRef: `synthetic://mes/rule-${index}`,
      },
    ],
  );
  return { signals, trend, fab, yields, wip, downtime, changes };
}

export function matchFabYield(
  fab: FabRow[],
  yields: YieldRow[],
  options: FabYieldMatchOptions,
): FabYieldMatch {
  const from = parseTime(options.from);
  const to = parseTime(options.to);
  if (
    from === null ||
    to === null ||
    from > to ||
    !Number.isFinite(options.maxLagDays) ||
    options.maxLagDays < 0
  ) {
    return emptyMatch();
  }

  const selected = fab.filter((row) => {
    const timestamp = parseTime(row.timestamp);
    return (
      timestamp !== null &&
      timestamp >= from &&
      timestamp <= to &&
      (options.equipment === undefined ||
        row.equipment === options.equipment) &&
      (options.recipe === undefined || row.recipe === options.recipe)
    );
  });
  const groupedFab = new Map<string, FabRow[]>();
  for (const row of selected) {
    const key = pairKey(row.lotId, row.waferId);
    const rows = groupedFab.get(key) ?? [];
    rows.push(row);
    groupedFab.set(key, rows);
  }

  const groupedYields = new Map<string, YieldRow[]>();
  for (const row of yields) {
    const key = pairKey(row.lotId, row.waferId);
    const rows = groupedYields.get(key) ?? [];
    rows.push(row);
    groupedYields.set(key, rows);
  }

  const result = emptyMatch();
  const maxLagMs = options.maxLagDays * DAY;
  for (const [key, fabRows] of groupedFab) {
    result.eligible += 1;
    const yieldRows = groupedYields.get(key) ?? [];
    if (fabRows.length !== 1 || yieldRows.length > 1) {
      result.ambiguous += 1;
      continue;
    }
    if (yieldRows.length === 0) {
      result.missing += 1;
      continue;
    }
    const fabRow = fabRows[0];
    const yieldRow = yieldRows[0];
    const fabTime = parseTime(fabRow.timestamp);
    const yieldTime = parseTime(yieldRow.measuredAt);
    if (
      fabTime === null ||
      yieldTime === null ||
      !Number.isFinite(fabRow.value) ||
      !Number.isFinite(yieldRow.yieldPct) ||
      (yieldRow.yieldPct as number) < 0 ||
      (yieldRow.yieldPct as number) > 100
    ) {
      result.missing += 1;
      continue;
    }
    const lagMs = yieldTime - fabTime;
    if (lagMs < 0 || lagMs > maxLagMs) {
      result.outsideLag += 1;
      continue;
    }
    result.pairs.push({
      ...fabRow,
      yieldPct: yieldRow.yieldPct as number,
      measuredAt: yieldRow.measuredAt,
      lagDays: Number((lagMs / DAY).toFixed(4)),
    });
  }
  return result;
}
