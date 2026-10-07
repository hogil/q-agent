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
  assert.equal(semRecord(workspace, 'SYN-LOT-09-01', 'W01', 'SYN-TEMP').id, 'SYN-SEM-01');
  assert.equal(raw.defect_references[0].historical_record_id, 'SYN-HIST-MET-001');
  assert.equal(raw.defect_references[0].sem.image_history_id, 'SYN-HIST-SEM-BRIDGE');
  assert.equal(raw.inform_notes[0].id, 'SYN-INFORM-HIST-DEFECT-1');
  assert.equal(raw.historical_records[0].id, 'SYN-HIST-MET-001');
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

test('every synthetic Fab wafer has a registered SEM asset with varied examples', () => {
  for (const record of Object.values(fixture.incidents)) {
    const workspace = workspaceWithRaw(record);
    const paths = new Set();
    for (const signal of record.engineering.signals) {
      for (const row of record.engineering.fab) {
        const asset = semRecord(workspace, row.lotId, row.waferId, signal.item);
        assert.ok(asset, `${signal.item}/${row.lotId}/${row.waferId}`);
        assert.equal(asset.item, signal.item);
        assert.ok(readFileSync(new URL(`../public${asset.src}`, import.meta.url)).length > 0);
        paths.add(asset.src);
      }
    }
    assert.ok(paths.size >= 5);
  }
});

test('new SEM pattern assets are varied, versioned and outside the old classifier domain', () => {
  const provenance = JSON.parse(readFileSync(new URL('../public/assets/provenance.json', import.meta.url), 'utf8'));
  const families = new Set();
  for (const record of Object.values(fixture.incidents)) {
    for (const asset of record.sem_assets.filter((asset) => asset.src.endsWith('-v2.png'))) {
      families.add(asset.src);
      assert.equal(asset.analysis_mode, 'visual_only');
      assert.equal(asset.revision, 'synthetic-item-patterns-v3');
      assert.ok(asset.pattern);
      const meta = provenance[asset.src.split('/').at(-1)];
      assert.equal(meta.synthetic, true);
      assert.ok(meta.prompt.length > 100);
    }
  }
  assert.equal(families.size, 16);
  assert.match(raw.sem_assets[0].src, /thin-v2/);
  assert.match(raw.sem_assets[1].src, /line-reference-v2/);
});

test('seven items resolve different SEM families for the same wafer, never a different item', () => {
  for (const record of Object.values(fixture.incidents)) {
    const workspace = workspaceWithRaw(record);
    const wafer = record.engineering.fab[0];
    const assets = record.engineering.signals.map(({ item }) => semRecord(workspace, wafer.lotId, wafer.waferId, item));
    assert.equal(assets.length, 7);
    assert.equal(new Set(assets.map((asset) => asset.pattern)).size, 7);
    assert.equal(new Set(assets.map((asset) => asset.src)).size, 7);
    assert.equal(semRecord(workspace, wafer.lotId, wafer.waferId, 'unknown'), null);
    assert.equal(semRecord(workspace, wafer.lotId, wafer.waferId), null);
  }
});

test('all nine raw incidents use current seeded fleets and matching target comparisons', () => {
  assert.equal(Object.keys(fixture.incidents).length, 9);
  for (const [id, record] of Object.entries(fixture.incidents)) {
    for (const signal of record.engineering.signals) {
      const fleet = makeTrendFleet(record.engineering, signal);
      assert.deepEqual(
        record.trend_fleets[signal.id].map(({ points }) => points),
        fleet.map(({ points }) => points),
        `${id}/${signal.id}`,
      );
      assert.equal(signal.startIndex, signal.onsetIndex);
      const target = fleet.find((row) => row.highlighted);
      const comparison = record.comparison_traces[signal.id]?.[signal.equipment];
      comparison?.forEach((point, index) => {
        const samples = target.points.slice(index * 6, index * 6 + 6);
        const mean = samples.reduce((sum, [, value]) => sum + value, 0) / samples.length;
        assert.ok(Math.abs(point.value - mean) <= 0.000001);
      });
    }
  }
});
