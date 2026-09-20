import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { makeEngineeringData } from '../src/engineeringData.ts';
import {
  makeInformNotes,
  semRecord,
} from '../src/investigationData.ts';
import { makeTrendFleet } from '../src/anomalyTrend.ts';
import { makeEquipmentTrace } from '../src/equipmentComparison.ts';

const fixture = JSON.parse(
  readFileSync(new URL('../../data/workbench/raw.example.json', import.meta.url), 'utf8'),
);
const raw = fixture.incidents['SYN-2026-09'];

function workspaceWithRaw(record = raw) {
  const pairs = [...new Map(
    record.engineering.fab.map((row) => [
      `${row.lotId}/${row.waferId}`,
      { lot_id: row.lotId, wafer_id: row.waferId, status: 'REGISTERED' },
    ]),
  ).values()];
  return {
    incident: {
      incident_number: 'SYN-2026-09',
      occurred_at: '2026-03-28T08:05:00.000Z',
    },
    lots: [...new Map(
      pairs.map((row) => [row.lot_id, { lot_id: row.lot_id, product_code: 'SYN', status: 'RUN' }]),
    ).values()],
    wafers: pairs,
    meetings: [],
    synthetic: true,
    as_of: '2026-03-31',
    raw: record,
  };
}

test('uses raw.example locally with seven signals, explicit patterns, and raw traces', () => {
  const workspace = workspaceWithRaw();
  const data = makeEngineeringData(workspace);

  assert.equal(data.signals.length, 7);
  assert.deepEqual(
    data.signals.map(({ id, pattern }) => ({ id, pattern: pattern ?? null })),
    raw.engineering.signals.map(({ id, pattern }) => ({ id, pattern: pattern ?? null })),
  );
  assert.deepEqual(data.trend, raw.engineering.trend);
  assert.deepEqual(makeInformNotes(data), raw.inform_notes);
  assert.deepEqual(
    makeTrendFleet(data, data.signals[0]),
    raw.trend_fleets[data.signals[0].id],
  );
  assert.deepEqual(
    makeEquipmentTrace(data, data.signals[0], 'SYN-EQP-01'),
    raw.comparison_traces[data.signals[0].id]['SYN-EQP-01'],
  );
  assert.equal(semRecord(workspace, 'SYN-LOT-09-01', 'W01').id, 'SYN-SEM-01');
});

test('does not generate substitutes when supplied raw sections are missing', () => {
  const sparseRaw = structuredClone(raw);
  sparseRaw.engineering.trend = [];
  sparseRaw.trend_fleets = {};
  sparseRaw.comparison_traces = {};
  sparseRaw.inform_notes = [];
  sparseRaw.sem_assets = [];
  const workspace = workspaceWithRaw(sparseRaw);
  const data = makeEngineeringData(workspace);

  assert.deepEqual(data.trend, []);
  assert.deepEqual(makeTrendFleet(data, data.signals[0]), []);
  assert.deepEqual(makeEquipmentTrace(data, data.signals[0], 'SYN-EQP-01'), []);
  assert.deepEqual(makeEquipmentTrace(data, data.signals[0], 'UNKNOWN-EQP'), []);
  assert.deepEqual(makeInformNotes(data), []);
  assert.equal(semRecord(workspace, 'SYN-LOT-09-01', 'W01'), null);
});
