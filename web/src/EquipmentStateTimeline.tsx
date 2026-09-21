import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import {
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Expand,
  Minimize2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import {
  defaultTimelineRange,
  EQUIPMENT_STATES,
  formatUtcInput,
  normalizeEquipmentStates,
  parseEquipmentTime,
  parseUtcInput,
  type EquipmentStateInterval,
  type EquipmentStateSegment,
  type TimelineRange,
} from './equipmentStateData';
import './equipmentStateTimeline.css';

export type EquipmentStateTimelineProps = {
  equipment: string;
  equipmentStates?: readonly EquipmentStateInterval[];
  equipmentOptions?: readonly string[];
  anchorAt?: string;
  defaultDays?: number;
  compact?: boolean;
  className?: string;
  onEquipmentChange?: (equipment: string) => void;
  onRangeChange?: (range: { from: string; to: string }) => void;
};

const MIN_SPAN = 15 * 60 * 1000;
const MAX_SPAN = 365 * 24 * 60 * 60 * 1000;
const COLORS: Record<EquipmentStateSegment['state'], string> = {
  RUN: '#8fcceb',
  DOWN: '#df756d',
  PM: '#e6c45d',
  IDLE: '#a9d8ae',
  UNKNOWN: '#c5cbd0',
};

function clampRange(range: TimelineRange): TimelineRange {
  const span = Math.min(MAX_SPAN, Math.max(MIN_SPAN, range.to - range.from));
  const midpoint = (range.from + range.to) / 2;
  return { from: midpoint - span / 2, to: midpoint + span / 2 };
}

function formatTick(timestamp: number, compact: boolean) {
  const date = new Date(timestamp);
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    month: 'short',
    day: '2-digit',
    ...(compact ? {} : { hour: '2-digit', minute: '2-digit', hour12: false }),
  }).format(date);
}

function ticksFor(range: TimelineRange, count: number) {
  return Array.from({ length: count }, (_, index) => {
    const ratio = index / (count - 1);
    return { timestamp: range.from + (range.to - range.from) * ratio, ratio };
  });
}

function rangeLabel(range: TimelineRange | null) {
  if (!range) return 'No state history';
  return `${new Date(range.from).toISOString()} to ${new Date(range.to).toISOString()}`;
}

export function EquipmentStateTimeline({
  equipment,
  equipmentStates = [],
  equipmentOptions,
  anchorAt,
  defaultDays = 7,
  compact = true,
  className = '',
  onEquipmentChange,
  onRangeChange,
}: EquipmentStateTimelineProps) {
  const [selectedEquipment, setSelectedEquipment] = useState(equipment);
  const [expanded, setExpanded] = useState(!compact);
  const [datesOpen, setDatesOpen] = useState(false);
  const [range, setRange] = useState<TimelineRange | null>(null);
  const [dragging, setDragging] = useState(false);
  const gesture = useRef<{ x: number; range: TimelineRange } | null>(null);

  const options = useMemo(
    () =>
      [
        ...new Set([
          ...(equipmentOptions ?? []),
          ...equipmentStates.map((row) => row.equipment),
          selectedEquipment,
        ]),
      ].filter(Boolean),
    [equipmentOptions, equipmentStates, selectedEquipment],
  );
  const defaultRange = useMemo(() => {
    const value = defaultTimelineRange(
      equipmentStates,
      selectedEquipment,
      anchorAt,
      defaultDays,
    );
    return value ? clampRange(value) : null;
  }, [anchorAt, defaultDays, equipmentStates, selectedEquipment]);

  useEffect(() => setSelectedEquipment(equipment), [equipment]);
  useEffect(() => setExpanded(!compact), [compact]);
  useEffect(() => setRange(defaultRange), [defaultRange]);

  const segments = useMemo(
    () =>
      range
        ? normalizeEquipmentStates(equipmentStates, selectedEquipment, range)
        : [],
    [equipmentStates, range, selectedEquipment],
  );
  const ticks = useMemo(
    () => (range ? ticksFor(range, expanded ? 7 : 5) : []),
    [expanded, range],
  );
  const anchorTimestamp = anchorAt ? parseEquipmentTime(anchorAt) : null;
  const anchorRatio =
    range &&
    anchorTimestamp !== null &&
    anchorTimestamp >= range.from &&
    anchorTimestamp <= range.to
      ? (anchorTimestamp - range.from) / (range.to - range.from)
      : null;

  function publish(next: TimelineRange, clamp = true) {
    if (
      !Number.isFinite(next.from) ||
      !Number.isFinite(next.to) ||
      next.from >= next.to ||
      (!clamp &&
        (next.to - next.from < MIN_SPAN || next.to - next.from > MAX_SPAN))
    )
      return;
    const normalized = clampRange(next);
    setRange(normalized);
    onRangeChange?.({
      from: new Date(normalized.from).toISOString(),
      to: new Date(normalized.to).toISOString(),
    });
  }

  function zoom(factor: number, ratio = 0.5) {
    if (!range) return;
    const span = range.to - range.from;
    const nextSpan = Math.max(MIN_SPAN, span * factor);
    const pivot = range.from + span * ratio;
    publish({
      from: pivot - nextSpan * ratio,
      to: pivot + nextSpan * (1 - ratio),
    });
  }

  function resetRange() {
    if (defaultRange) publish(defaultRange);
  }

  function shiftRange(direction: -1 | 1) {
    if (!range) return;
    const span = range.to - range.from;
    publish({
      from: range.from + direction * span * 0.5,
      to: range.to + direction * span * 0.5,
    });
  }

  function changeDate(side: 'from' | 'to', value: string) {
    const timestamp = parseUtcInput(value);
    if (timestamp === null || !range) return;
    const next = { ...range, [side]: timestamp };
    if (next.from >= next.to) return;
    publish(next, false);
  }

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (!range) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { x: event.clientX, range };
    setDragging(true);
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!gesture.current || !range) return;
    const width = event.currentTarget.getBoundingClientRect().width;
    if (!width) return;
    const delta =
      ((event.clientX - gesture.current.x) / width) * (range.to - range.from);
    publish({
      from: gesture.current.range.from - delta,
      to: gesture.current.range.to - delta,
    });
  }

  function endPointer(event: PointerEvent<SVGSVGElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    gesture.current = null;
    setDragging(false);
  }

  function onWheel(event: React.WheelEvent<SVGSVGElement>) {
    if (!range) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
    zoom(event.deltaY < 0 ? 0.78 : 1.28, Math.max(0, Math.min(1, ratio)));
  }

  function selectEquipment(value: string) {
    setSelectedEquipment(value);
    onEquipmentChange?.(value);
  }

  const panelClass = [
    'equipment-state-timeline',
    compact ? 'is-compact' : 'is-panel',
    expanded ? 'is-expanded' : '',
    dragging ? 'is-dragging' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <section className={panelClass} aria-label="Equipment state timeline">
      <div className="equipment-state-timeline__header">
        <div>
          <strong>설비 상태</strong>
        </div>
        <div className="equipment-state-timeline__header-actions">
          <label className="equipment-state-timeline__equipment-label">
            <span>EQP</span>
            {options.length ? (
              <select
                aria-label="설비 선택"
                value={selectedEquipment}
                onChange={(event) => selectEquipment(event.target.value)}
              >
                <option value="">설비 선택</option>
                {options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : (
              <span className="equipment-state-timeline__equipment-placeholder">
                설비 미선택
              </span>
            )}
          </label>
          <button
            type="button"
            className="equipment-state-timeline__icon-button"
            title={expanded ? '타임라인 축소' : '타임라인 확대'}
            aria-label={expanded ? '타임라인 축소' : '타임라인 확대'}
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? <Minimize2 size={14} /> : <Expand size={14} />}
          </button>
        </div>
      </div>

      <div
        className="equipment-state-timeline__toolbar"
        role="toolbar"
        aria-label="Timeline controls"
      >
        <div className="equipment-state-timeline__zoom-buttons">
          <button
            type="button"
            className="equipment-state-timeline__icon-button"
            title="이전 범위"
            aria-label="이전 범위"
            onClick={() => shiftRange(-1)}
          >
            <ChevronLeft size={14} />
          </button>
          <button
            type="button"
            className="equipment-state-timeline__icon-button"
            title="다음 범위"
            aria-label="다음 범위"
            onClick={() => shiftRange(1)}
          >
            <ChevronRight size={14} />
          </button>
          <button
            type="button"
            className="equipment-state-timeline__icon-button"
            title="확대"
            aria-label="확대"
            onClick={() => zoom(0.7)}
          >
            <ZoomIn size={14} />
          </button>
          <button
            type="button"
            className="equipment-state-timeline__icon-button"
            title="축소"
            aria-label="축소"
            onClick={() => zoom(1 / 0.7)}
          >
            <ZoomOut size={14} />
          </button>
          <button
            type="button"
            className="equipment-state-timeline__icon-button"
            title="기본 7일 범위"
            aria-label="기본 7일 범위"
            onClick={resetRange}
          >
            <RotateCcw size={14} />
          </button>
          {compact && (
            <button
              type="button"
              className="equipment-state-timeline__icon-button"
              title="기간 입력 열기"
              aria-label="기간 입력 열기"
              aria-expanded={datesOpen}
              onClick={() => setDatesOpen((value) => !value)}
            >
              <CalendarRange size={14} />
            </button>
          )}
        </div>
      </div>

      <div
        className="equipment-state-timeline__plot"
        data-range={rangeLabel(range)}
        title="드래그하여 시간 이동 · 휠로 확대/축소"
      >
        {range ? (
          <>
            <div className="equipment-state-timeline__bar">
              <svg
                className="equipment-state-timeline__svg"
                viewBox="0 0 1000 42"
                preserveAspectRatio="none"
                role="img"
                aria-label={`${selectedEquipment} state timeline from ${rangeLabel(range)}`}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={endPointer}
                onPointerCancel={endPointer}
                onWheel={onWheel}
              >
                <rect
                  className="equipment-state-timeline__track"
                  x="0"
                  y="0"
                  width="1000"
                  height="42"
                  rx="2"
                />
                {segments.map((segment, index) => {
                  const x =
                    ((segment.start - range.from) / (range.to - range.from)) *
                    1000;
                  const width =
                    ((segment.end - segment.start) / (range.to - range.from)) *
                    1000;
                  return (
                    <rect
                      key={`${segment.start}-${segment.end}-${index}`}
                      x={x}
                      y="0"
                      width={Math.max(0, width)}
                      height="42"
                      fill={COLORS[segment.state]}
                      className="equipment-state-timeline__segment"
                    >
                      <title>{`${segment.state}${segment.code ? ` · ${segment.code}` : ''}\n${new Date(segment.start).toISOString()} → ${new Date(segment.end).toISOString()}`}</title>
                    </rect>
                  );
                })}
              </svg>
              {anchorRatio !== null && (
                <span
                  className="equipment-state-timeline__anchor"
                  style={{ left: `${anchorRatio * 100}%` }}
                  role="img"
                  aria-label="감지 시각"
                >
                  감지
                </span>
              )}
            </div>
            <div className="equipment-state-timeline__axis" aria-hidden="true">
              {ticks.map((tick) => (
                <span
                  key={tick.timestamp}
                  style={{ left: `${tick.ratio * 100}%` }}
                >
                  {formatTick(tick.timestamp, !expanded)}
                </span>
              ))}
            </div>
          </>
        ) : (
          <div className="equipment-state-timeline__empty">
            선택 설비의 상태 이력이 없습니다.
          </div>
        )}
      </div>

      {(!compact || datesOpen) && (
        <div className="equipment-state-timeline__dates">
          <label>
            <span>From (UTC)</span>
            <input
              type="datetime-local"
              step="60"
              value={formatUtcInput(range?.from ?? null)}
              disabled={!range}
              onChange={(event) => changeDate('from', event.target.value)}
            />
          </label>
          <label>
            <span>To (UTC)</span>
            <input
              type="datetime-local"
              step="60"
              value={formatUtcInput(range?.to ?? null)}
              disabled={!range}
              onChange={(event) => changeDate('to', event.target.value)}
            />
          </label>
        </div>
      )}

      <div
        className="equipment-state-timeline__legend"
        aria-label="Equipment state legend"
      >
        {[...EQUIPMENT_STATES, 'UNKNOWN' as const].map((state) => (
          <span key={state}>
            <i style={{ backgroundColor: COLORS[state] }} />
            {state}
          </span>
        ))}
      </div>
    </section>
  );
}
