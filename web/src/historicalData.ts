import type { Workspace } from './api';
import type { EngineeringData } from './engineeringData';
import type { InvestigationSelection } from './engineeringAnalysis';

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
