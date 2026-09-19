import { mean, sampleCorrelation } from 'simple-statistics';
import type { EngineeringData } from './engineeringData';

export type InvestigationSelection = {
  signalId: string;
  start: number;
  end: number;
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
  const from = data.trend[selection.start]?.timestamp;
  const to = data.trend[selection.end]?.timestamp;
  if (!from || !to) return [];
  const rows = data.fab.filter(
    (row) =>
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
    start: signal?.startIndex || 0,
    end: signal?.endIndex ?? Math.max(0, data.trend.length - 1),
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
    start: s.start,
    end: s.end,
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

export function engineeringReference(
  kind: 'trend' | 'corr',
  selection: InvestigationSelection,
) {
  const { signalId, start, end, equipment, recipe, maxLagDays } = selection;
  return `engineering:${kind}:${JSON.stringify([signalId, start, end, equipment, recipe, maxLagDays])}`;
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
    if (!Array.isArray(value) || value.length !== 6) return null;
    const [signalId, start, end, equipment, recipe, maxLagDays] = value;
    return parseSelection(
      { signalId, start, end, equipment, recipe, maxLagDays },
      data,
    );
  } catch {
    return null;
  }
}
