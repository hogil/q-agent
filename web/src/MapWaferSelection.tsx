import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Search, X } from 'lucide-react';
import type { FabRow, LegendAxis } from './engineeringData';
import { pairKey } from './engineeringAnalysis';
import {
  groupMapWafers,
  toggleMapGroup,
  type MapWaferGroup,
} from './mapWaferGroups';
import './mapWaferSelection.css';

type MapWaferSelectionProps = {
  label: string;
  rows: FabRow[];
  axis: LegendAxis;
  checked: ReadonlySet<string>;
  onChange: (keys: Set<string>) => void;
};

type Mode = 'legend' | 'lot' | 'wafer';

const modeLabels: Record<Mode, string> = {
  legend: 'Legend',
  lot: 'Lot',
  wafer: 'Wafer',
};

function TriStateCheckbox({
  checked,
  mixed,
  label,
  onChange,
}: {
  checked: boolean;
  mixed?: boolean;
  label: string;
  onChange: (enabled: boolean) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (input.current) input.current.indeterminate = Boolean(mixed && !checked);
  }, [checked, mixed]);
  return (
    <input
      ref={input}
      type="checkbox"
      aria-label={label}
      checked={checked}
      onChange={(event) => onChange(event.target.checked)}
    />
  );
}

function groupMatches(group: MapWaferGroup, query: string, rowsByKey: Map<string, FabRow>) {
  if (!query) return group.waferKeys;
  const terms = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return group.waferKeys.filter((key) => {
    const row = rowsByKey.get(key);
    const text = `${group.label} ${row?.lotId ?? ''} ${row?.waferId ?? ''}`.toLocaleLowerCase();
    return terms.every((term) => text.includes(term));
  });
}

export default function MapWaferSelection({
  label,
  rows,
  axis,
  checked,
  onChange,
}: MapWaferSelectionProps) {
  const [mode, setMode] = useState<Mode>('legend');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({});
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDialogElement>(null);
  const groups = useMemo(() => groupMapWafers(rows, mode, axis), [rows, mode, axis]);
  const rowsByKey = useMemo(() => {
    const result = new Map<string, FabRow>();
    for (const row of rows) result.set(pairKey(row), row);
    return result;
  }, [rows]);
  const visibleGroups = useMemo(
    () =>
      groups
        .map((group) => ({ ...group, waferKeys: groupMatches(group, query.trim(), rowsByKey) }))
        .filter((group) => group.waferKeys.length > 0),
    [groups, query, rowsByKey],
  );
  const matchingKeys = useMemo(
    () => [...new Set(visibleGroups.flatMap((group) => group.waferKeys))],
    [visibleGroups],
  );
  const allMatching = matchingKeys.length > 0 && matchingKeys.every((key) => checked.has(key));
  const someMatching = matchingKeys.some((key) => checked.has(key));

  useLayoutEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node))
        setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus({ preventScroll: true });
      }
    };
    const placePanel = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(336, window.innerWidth - 24);
      const left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12));
      const maxHeight = Math.min(460, window.innerHeight - 24);
      const top = Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - maxHeight - 12));
      setPanelStyle({ left, top, width });
    };
    placePanel();
    panel.current?.querySelector('input')?.focus({ preventScroll: true });
    document.addEventListener('pointerdown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    window.addEventListener('resize', placePanel);
    window.addEventListener('scroll', placePanel, true);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
      window.removeEventListener('resize', placePanel);
      window.removeEventListener('scroll', placePanel, true);
    };
  }, [open]);

  const updateGroup = (waferKeys: readonly string[], enabled: boolean) =>
    onChange(toggleMapGroup(checked, waferKeys, enabled));

  return (
    <div className="map-wafer-selection">
      <div className="map-wafer-toolbar">
        <div className="map-wafer-modes" role="group" aria-label={`${label} 선택 기준`}>
          {(Object.keys(modeLabels) as Mode[]).map((value) => (
            <button
              key={value}
              type="button"
              className={value === mode ? 'is-active' : ''}
              aria-pressed={value === mode}
              title={value === 'legend' ? `Legend · ${axis === 'recipe' ? 'Recipe' : axis === 'chamber' ? 'Chamber' : 'Equipment'}` : modeLabels[value]}
              onClick={() => setMode(value)}
            >
              {modeLabels[value]}
            </button>
          ))}
        </div>
        <button
          ref={trigger}
          type="button"
          className="map-wafer-trigger"
          aria-label={`${label} 선택 열기`}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <span>{checked.size === rowsByKey.size ? '전체' : '선택'} <small>({checked.size})</small></span>
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      </div>
      {open && createPortal(
        <dialog open ref={panel} className="map-wafer-popover" style={panelStyle} aria-label={`${label} 선택`}>
          <div className="map-wafer-search">
            <Search size={14} aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="검색"
              aria-label={`${label} 선택 검색`}
            />
            {query && (
              <button type="button" aria-label={`${label} 검색 지우기`} onClick={() => setQuery('')}>
                <X size={14} aria-hidden="true" />
              </button>
            )}
          </div>
          <label className="map-wafer-all">
            <TriStateCheckbox
              checked={allMatching}
              mixed={someMatching && !allMatching}
              label={`${label} 전체 선택`}
              onChange={(enabled) => updateGroup(matchingKeys, enabled)}
            />
            <span>{query ? `검색 결과 선택 · ${matchingKeys.length}` : '전체 선택'}</span>
          </label>
          <div className="map-wafer-groups">
            {visibleGroups.map((group) => {
              const selectedCount = group.waferKeys.filter((key) => checked.has(key)).length;
              const groupChecked = selectedCount === group.waferKeys.length;
              return (
                <div className="map-wafer-group" key={group.key}>
                  <label className="map-wafer-group-label">
                    <TriStateCheckbox
                      checked={groupChecked}
                      mixed={selectedCount > 0 && !groupChecked}
                      label={`${label} ${group.label} 선택`}
                      onChange={(enabled) => updateGroup(group.waferKeys, enabled)}
                    />
                    <span>{group.label}</span>
                    <small>{selectedCount}/{group.waferKeys.length}</small>
                  </label>
                </div>
              );
            })}
            {!visibleGroups.length && <p className="map-wafer-empty">검색 결과 없음</p>}
          </div>
        </dialog>
        , document.body
      )}
    </div>
  );
}
