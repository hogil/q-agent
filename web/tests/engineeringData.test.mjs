import assert from 'node:assert/strict';
import test from 'node:test';

import { makeEngineeringData, matchFabYield } from '../src/engineeringData.ts';

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
    { lot_id: 'SYN-LOT-02', wafer_id: 'W02', status: 'HOLD' },
    { lot_id: 'SYN-LOT-01', wafer_id: 'W01', status: 'HOLD' },
    { lot_id: 'SYN-LOT-01', wafer_id: 'W01', status: 'HOLD' },
  ],
  meetings: [],
  synthetic: true,
  as_of: '2026-01-20T00:00:00.000Z',
};

test('creates deterministic, incident-scoped synthetic engineering data', () => {
  const first = makeEngineeringData(workspace);
  const second = makeEngineeringData(workspace);

  assert.deepEqual(first, second);
  assert.equal(first.trend.length, 24);
  assert.equal(first.signals.length, 3);
  assert.deepEqual(first.signals[0], {
    id: 'synthetic-signal-heater-drift',
    title: '공정 온도 상승',
    severity: 'high',
    metric: 'temperature',
    equipment: 'SYN-EQP-01',
    step: 'SYN-ETCH-10',
    item: 'SYN-TEMP',
    recipe: 'SYN-RCP-A',
    detectedAt: '2026-01-15T12:00:00.000Z',
    startIndex: 5,
    endIndex: 21,
    description: 'SYN-EQP-01 · SYN-ETCH-10 · 합성 온도 Trace',
    onsetIndex: 5,
  });
  assert.equal(first.fab.length, 2);
  for (const row of first.fab) {
    const trace = first.trend.find(
      (point) => point.timestamp === row.timestamp,
    );
    assert.ok(trace);
    assert.ok(Math.abs(row.value - trace.temperature) <= 0.11);
  }
  assert.deepEqual(
    first.fab.map(({ lotId, waferId }) => `${lotId}/${waferId}`),
    ['SYN-LOT-01/W01', 'SYN-LOT-02/W02'],
  );
  assert.equal(
    first.fab.every((row) => row.value >= 65 && row.value <= 69),
    true,
  );
  assert.deepEqual(
    first.yields,
    [],
    'current Fab wafers do not have fabricated future EDS outcomes',
  );
  assert.equal(first.wip.length, 2);
  assert.deepEqual(
    first.wip.map((row) => [row.lotId, row.wafers]),
    [
      ['SYN-LOT-01', 1],
      ['SYN-LOT-02', 1],
    ],
  );
  assert.equal(first.downtime.length, 4);
  assert.equal(first.changes.length, 4);
  for (const event of first.changes) {
    assert.ok(first.trend.some((point) => point.timestamp === event.timestamp));
    assert.ok(event.sourceRef.startsWith('synthetic://'));
    assert.ok(['recipe', 'system'].includes(event.kind));
    assert.notEqual(event.before, event.after);
  }
  assert.equal(
    first.downtime.every(
      (event) =>
        event.id.startsWith('synthetic-') &&
        event.code.startsWith('SYN-') &&
        event.description.includes('합성'),
    ),
    true,
  );
});

test('does not fabricate wafer IDs and keeps WIP scoped to registered lots', () => {
  const value = makeEngineeringData({
    ...workspace,
    lots: [
      ...workspace.lots,
      { lot_id: 'SYN-LOT-03', product_code: 'SYN', status: 'RUN' },
    ],
    wafers: [
      ...workspace.wafers,
      { lot_id: 'SYN-LOT-99', wafer_id: 'NEVER-REGISTERED', status: 'RUN' },
    ],
  });

  assert.equal(
    value.fab.some((row) => row.waferId === 'NEVER-REGISTERED'),
    false,
  );
  assert.equal(
    value.wip.some((row) => row.lotId === 'SYN-LOT-99'),
    false,
  );
  const unregisteredWipLot = value.wip.find(
    (row) => row.lotId === 'SYN-LOT-03',
  );
  assert.ok(unregisteredWipLot);
  assert.equal(unregisteredWipLot.wafers, 0);
  assert.equal(
    ['RUN', 'WAIT', 'HOLD'].includes(unregisteredWipLot.status),
    true,
  );
  assert.equal(unregisteredWipLot.step, 'SYN-ETCH-10');
});

function matchFixture() {
  return {
    fab: [
      {
        lotId: 'L1',
        waferId: 'W1',
        timestamp: '2026-01-01T00:00:00.000Z',
        equipment: 'EQ-A',
        step: 'SYN-STEP',
        recipe: 'R-A',
        value: 66,
      },
      {
        lotId: 'L2',
        waferId: 'W1',
        timestamp: '2026-01-02T00:00:00.000Z',
        equipment: 'EQ-B',
        step: 'SYN-STEP',
        recipe: 'R-B',
        value: 67,
      },
      {
        lotId: 'L3',
        waferId: 'W1',
        timestamp: '2026-01-03T00:00:00.000Z',
        equipment: 'EQ-A',
        step: 'SYN-STEP',
        recipe: 'R-A',
        value: 68,
      },
      {
        lotId: 'L4',
        waferId: 'W1',
        timestamp: '2026-01-04T00:00:00.000Z',
        equipment: 'EQ-A',
        step: 'SYN-STEP',
        recipe: 'R-A',
        value: 69,
      },
    ],
    yields: [
      {
        lotId: 'L1',
        waferId: 'W1',
        measuredAt: '2026-01-05T00:00:00.000Z',
        yieldPct: 95,
      },
      {
        lotId: 'L2',
        waferId: 'W1',
        measuredAt: '2026-01-01T00:00:00.000Z',
        yieldPct: 94,
      },
      {
        lotId: 'L3',
        waferId: 'W1',
        measuredAt: '2026-01-20T00:00:00.000Z',
        yieldPct: 93,
      },
      {
        lotId: 'L4',
        waferId: 'W1',
        measuredAt: '2026-01-06T00:00:00.000Z',
        yieldPct: null,
      },
    ],
  };
}

test('matches composite lot/wafer keys, reports missing and lag states', () => {
  const value = matchFixture();
  const result = matchFabYield(value.fab, value.yields, {
    from: '2026-01-01T00:00:00.000Z',
    to: '2026-01-04T00:00:00.000Z',
    maxLagDays: 8,
  });

  assert.equal(result.eligible, 4);
  assert.equal(result.pairs.length, 1);
  assert.deepEqual(result.pairs[0], {
    ...value.fab[0],
    yieldPct: 95,
    measuredAt: '2026-01-05T00:00:00.000Z',
    lagDays: 4,
  });
  assert.equal(result.missing, 1);
  assert.equal(result.outsideLag, 2);
  assert.equal(result.ambiguous, 0);
});

test('rejects earlier yields and invalid numeric values', () => {
  const value = matchFixture();
  const result = matchFabYield(
    [value.fab[0]],
    [{ ...value.yields[0], measuredAt: '2025-12-31T00:00:00.000Z' }],
    {
      from: '2026-01-01T00:00:00.000Z',
      to: '2026-01-01T00:00:00.000Z',
      maxLagDays: 8,
    },
  );

  assert.equal(result.pairs.length, 0);
  assert.equal(result.outsideLag, 1);

  const invalid = matchFabYield(
    [value.fab[0]],
    [{ ...value.yields[0], yieldPct: Number.NaN }],
    {
      from: '2026-01-01T00:00:00.000Z',
      to: '2026-01-01T00:00:00.000Z',
      maxLagDays: 8,
    },
  );
  assert.equal(invalid.pairs.length, 0);
  assert.equal(invalid.missing, 1);
});

test('skips ambiguous fab or yield duplicates and counts each composite key once', () => {
  const value = matchFixture();
  const result = matchFabYield(
    [value.fab[0], { ...value.fab[0], value: 67 }],
    [
      value.yields[0],
      { ...value.yields[0], measuredAt: '2026-01-06T00:00:00.000Z' },
    ],
    {
      from: '2026-01-01T00:00:00.000Z',
      to: '2026-01-10T00:00:00.000Z',
      maxLagDays: 8,
    },
  );

  assert.deepEqual(result, {
    pairs: [],
    eligible: 1,
    missing: 0,
    ambiguous: 1,
    outsideLag: 0,
  });
});

test('applies inclusive time, equipment, recipe, and lag filters', () => {
  const value = matchFixture();
  const result = matchFabYield(value.fab, value.yields, {
    from: '2026-01-01T00:00:00.000Z',
    to: '2026-01-01T00:00:00.000Z',
    equipment: 'EQ-A',
    recipe: 'R-A',
    maxLagDays: 4,
  });

  assert.equal(result.pairs.length, 1);
  assert.equal(result.pairs[0].lagDays, 4);
  assert.equal(result.eligible, 1);
});

test('returns an empty result for nonsensical date or lag options', () => {
  const value = matchFixture();
  for (const options of [
    { from: 'bad', to: '2026-01-01T00:00:00.000Z', maxLagDays: 8 },
    {
      from: '2026-01-02T00:00:00.000Z',
      to: '2026-01-01T00:00:00.000Z',
      maxLagDays: 8,
    },
    {
      from: '2026-01-01T00:00:00.000Z',
      to: '2026-01-01T00:00:00.000Z',
      maxLagDays: -1,
    },
  ]) {
    assert.deepEqual(matchFabYield(value.fab, value.yields, options), {
      pairs: [],
      eligible: 0,
      missing: 0,
      ambiguous: 0,
      outsideLag: 0,
    });
  }
});
