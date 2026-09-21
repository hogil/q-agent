import type { EquipmentState, EquipmentStateInterval } from './engineeringData';

export type { EquipmentState, EquipmentStateInterval } from './engineeringData';

export const EQUIPMENT_STATES = ['RUN', 'DOWN', 'PM', 'IDLE'] as const;

export type EquipmentStateSegment = {
  start: number;
  end: number;
  state: EquipmentState | 'UNKNOWN';
  code?: string;
};

export type TimelineRange = {
  from: number;
  to: number;
};

const DAY = 24 * 60 * 60 * 1000;

export function parseEquipmentTime(value: string): number | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function parseUtcInput(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  return parseEquipmentTime(`${value}:00Z`);
}

export function formatUtcInput(timestamp: number | null): string {
  if (timestamp === null || !Number.isFinite(timestamp)) return '';
  return new Date(timestamp).toISOString().slice(0, 16);
}

function isEquipmentState(value: unknown): value is EquipmentState {
  return (
    typeof value === 'string' &&
    EQUIPMENT_STATES.includes(value as EquipmentState)
  );
}

function validIntervals(
  rows: readonly EquipmentStateInterval[],
  equipment: string,
) {
  return rows
    .map((row, index) => ({
      row,
      index,
      start: parseEquipmentTime(row.start),
      end: parseEquipmentTime(row.end),
    }))
    .filter(
      (
        item,
      ): item is {
        row: EquipmentStateInterval;
        index: number;
        start: number;
        end: number;
      } =>
        item.row.equipment === equipment &&
        isEquipmentState(item.row.state) &&
        item.start !== null &&
        item.end !== null &&
        item.end > item.start,
    );
}

export function latestEquipmentTime(
  rows: readonly EquipmentStateInterval[],
  equipment: string,
): number | null {
  const intervals = validIntervals(rows, equipment);
  return intervals.length
    ? Math.max(...intervals.map((item) => item.end))
    : null;
}

export function defaultTimelineRange(
  rows: readonly EquipmentStateInterval[],
  equipment: string,
  anchorAt?: string,
  days = 7,
): TimelineRange | null {
  const latest = latestEquipmentTime(rows, equipment);
  const anchor = anchorAt ? parseEquipmentTime(anchorAt) : null;
  const to = anchor ?? latest;
  if (to === null || !Number.isFinite(days) || days <= 0) return null;
  const halfSpan = (days * DAY) / 2;
  return { from: to - halfSpan, to: to + halfSpan };
}

export function normalizeEquipmentStates(
  rows: readonly EquipmentStateInterval[],
  equipment: string,
  range: TimelineRange,
): EquipmentStateSegment[] {
  if (range.from >= range.to) return [];
  const intervals = validIntervals(rows, equipment).filter(
    (item) => item.start < range.to && item.end > range.from,
  );
  const boundaries = new Set<number>([range.from, range.to]);
  for (const item of intervals) {
    boundaries.add(Math.max(range.from, item.start));
    boundaries.add(Math.min(range.to, item.end));
  }
  const points = [...boundaries].sort((left, right) => left - right);
  const segments: EquipmentStateSegment[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (start >= end) continue;
    const active = intervals
      .filter((item) => item.start < end && item.end > start)
      .sort(
        (left, right) => right.start - left.start || right.index - left.index,
      )[0];
    const next: EquipmentStateSegment = active
      ? { start, end, state: active.row.state, code: active.row.code }
      : { start, end, state: 'UNKNOWN' };
    const previous = segments[segments.length - 1];
    if (
      previous &&
      previous.end === next.start &&
      previous.state === next.state &&
      previous.code === next.code
    ) {
      previous.end = next.end;
    } else {
      segments.push(next);
    }
  }
  return segments;
}
