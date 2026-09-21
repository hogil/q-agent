import { pairKey } from './engineeringAnalysis.ts';
import type { FabRow, LegendAxis } from './engineeringData.ts';

type FabRowWithChamber = FabRow & { chamber?: string | null };

export type MapWaferGroup = {
  key: string;
  label: string;
  waferKeys: string[];
};

function legendValue(row: FabRowWithChamber, axis: LegendAxis): string {
  if (axis === 'eqp_id') return row.equipment || 'Equipment 미등록';
  if (axis === 'recipe') return row.recipe || 'Recipe 미등록';
  return row.chamber?.trim() || 'Chamber 미등록';
}

function groupValue(row: FabRowWithChamber, mode: 'legend' | 'lot' | 'wafer', axis: LegendAxis) {
  if (mode === 'legend') return legendValue(row, axis);
  if (mode === 'lot') return row.lotId;
  return `${row.lotId} / ${row.waferId}`;
}

export function groupMapWafers(
  rows: readonly FabRow[],
  mode: 'legend' | 'lot' | 'wafer',
  axis: LegendAxis,
): MapWaferGroup[] {
  const groups = new Map<string, MapWaferGroup>();
  for (const row of rows) {
    const typedRow = row as FabRowWithChamber;
    const value = groupValue(typedRow, mode, axis);
    const groupKey = mode === 'wafer' ? pairKey(row) : `${mode}:${value}`;
    const group = groups.get(groupKey) ?? {
      key: groupKey,
      label: value,
      waferKeys: [],
    };
    const waferKey = pairKey(row);
    if (!group.waferKeys.includes(waferKey)) group.waferKeys.push(waferKey);
    groups.set(groupKey, group);
  }
  return [...groups.values()];
}

export function toggleMapGroup(
  checked: ReadonlySet<string>,
  waferKeys: readonly string[],
  enabled: boolean,
): Set<string> {
  const next = new Set(checked);
  for (const key of waferKeys) {
    if (enabled) next.add(key);
    else next.delete(key);
  }
  return next;
}
