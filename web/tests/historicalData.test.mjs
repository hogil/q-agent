import assert from 'node:assert/strict';
import test from 'node:test';

import { historicalData, selectHistoricalData } from '../src/historicalData.ts';
import { makeEngineeringData } from '../src/engineeringData.ts';
import { defaultSelection } from '../src/engineeringAnalysis.ts';

const workspace = {
  incident: {
    incident_id: 'synthetic-incident-1',
    incident_number: 'SYN-2026-01',
    title: 'Synthetic incident',
    city: 'Synthetic city',
    line: 'Synthetic line',
    department: 'Synthetic department',
    occurred_at: '2026-01-15T12:00:00.000Z',
    expected_lot_count: 2,
  },
  lots: [
    { lot_id: 'SYN-LOT-01', product_code: 'SYN-PROD', status: 'HOLD' },
    { lot_id: 'SYN-LOT-02', product_code: 'SYN-PROD', status: 'RUN' },
  ],
  wafers: [
    { lot_id: 'SYN-LOT-01', wafer_id: 'W01', status: 'HOLD' },
    { lot_id: 'SYN-LOT-02', wafer_id: 'W02', status: 'HOLD' },
  ],
  meetings: [],
  synthetic: true,
  as_of: '2026-01-20T00:00:00.000Z',
};

const data = makeEngineeringData(workspace);

test('historicalData is deterministic, sufficiently sized, and uses separate IDs', () => {
  const first = historicalData(workspace, data);
  const second = historicalData(workspace, data);
  assert.deepEqual(first, second);
  assert.ok(first.length >= 32);
  assert.ok(first.every((row) => row.id.startsWith('SYN-HIST-')));
  assert.ok(first.every((row) => row.lotId.startsWith('SYN-HIST-')));
  assert.equal(
    first.some((row) =>
      data.fab.some(
        (current) =>
          current.lotId === row.lotId && current.waferId === row.waferId,
      ),
    ),
    false,
  );
  assert.ok(
    first.every((row) => row.bin3Pct + row.bin4Pct <= 100 - row.yieldPct),
  );
  assert.ok(
    first.every(
      (row) =>
        !data.yields.some(
          (current) =>
            current.lotId === row.lotId && current.waferId === row.waferId,
        ),
    ),
  );
});

test('selected historical records are completed before the current scope cutoff', () => {
  const selection = defaultSelection(data);
  const records = historicalData(workspace, data);
  const selected = selectHistoricalData(records, data, selection);
  const cutoff = data.trend[selection.start].timestamp;
  assert.ok(selected.length >= 12);
  assert.ok(selected.every((row) => row.step === data.signals[0].step));
  assert.ok(selected.every((row) => row.item === data.signals[0].item));
  assert.ok(selected.every((row) => row.edsAt < cutoff));
  assert.ok(selected.every((row) => row.fabAt <= row.edsAt));
  assert.ok(selected.every((row) => row.yieldPct >= 0 && row.yieldPct <= 100));
  assert.ok(selected.every((row) => row.bin3Pct >= 0 && row.bin3Pct <= 100));
  assert.ok(selected.every((row) => row.bin4Pct >= 0 && row.bin4Pct <= 100));
});

test('excludes future EDS, cutoff equality, inverted times, and another Step', () => {
  const selection = defaultSelection(data);
  const cutoff = data.trend[selection.start].timestamp;
  const record = selectHistoricalData(
    historicalData(workspace, data),
    data,
    selection,
  )[0];
  const invalid = [
    { ...record, edsAt: cutoff },
    { ...record, edsAt: '2099-01-01T00:00:00.000Z' },
    { ...record, fabAt: cutoff },
    { ...record, step: 'SYN-OTHER-STEP' },
    { ...record, item: 'SYN-OTHER-ITEM' },
  ];
  assert.deepEqual(selectHistoricalData(invalid, data, selection), []);
});

test('historical selection respects same-step, equipment, recipe, and optional filters', () => {
  const records = historicalData(workspace, data);
  const base = defaultSelection(data);
  const signal = data.signals[0];
  const selected = selectHistoricalData(records, data, base);
  assert.ok(selected.length > 0);
  assert.ok(
    selected.every(
      (row) =>
        row.equipment === signal.equipment && row.recipe === signal.recipe,
    ),
  );
  assert.ok(selected.every((row) => row.item === signal.item));
  assert.equal(
    selectHistoricalData(
      [
        ...records,
        { ...records[0], id: 'SYN-HIST-OTHER-ITEM', item: 'SYN-OTHER' },
      ],
      data,
      base,
    ).some((row) => row.item === 'SYN-OTHER'),
    false,
  );
  assert.equal(
    selectHistoricalData(records, data, {
      ...base,
      equipment: 'not-a-real-equipment',
    }).length,
    0,
  );
  assert.equal(
    selectHistoricalData(records, data, {
      ...base,
      recipe: 'not-a-real-recipe',
    }).length,
    0,
  );
  assert.equal(
    selectHistoricalData(records, data, {
      ...base,
      signalId: data.signals[1].id,
      equipment: '',
      recipe: '',
    }).every((row) => row.step === data.signals[1].step),
    true,
  );
});
