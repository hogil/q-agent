import assert from 'node:assert/strict';
import test from 'node:test';

import {
  fitHistoricalRegression,
  historicalData,
  selectHistoricalData,
} from '../src/historicalData.ts';
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

test('historicalData reads configured shared records, including an explicitly empty set', () => {
  const records = historicalData(workspace, data).slice(0, 2);
  assert.equal(
    historicalData(
      { ...workspace, raw: { historical_records: records } },
      data,
    ),
    records,
  );
  assert.deepEqual(
    historicalData({ ...workspace, raw: { historical_records: [] } }, data),
    [],
  );
});

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

test('fits exact linear, quadratic, and cubic curves across the observed range', () => {
  const cases = [
    { degree: 1, fn: (x) => 2 + 3 * x, xs: [-2, -1, 0, 1, 2] },
    { degree: 2, fn: (x) => 1 - 2 * x + 0.5 * x ** 2, xs: [-2, -1, 0, 1, 2] },
    {
      degree: 3,
      fn: (x) => -1 + x - 0.5 * x ** 2 + 0.25 * x ** 3,
      xs: [-2, -1, 0, 1, 2, 3],
    },
  ];
  for (const { degree, fn, xs } of cases) {
    const result = fitHistoricalRegression(
      xs.map((x) => [x, fn(x)]),
      degree,
    );
    assert.ok(result);
    assert.equal(result.n, xs.length);
    assert.equal(result.curve.length, 81);
    assert.equal(result.curve[0][0], xs[0]);
    assert.equal(result.curve[80][0], xs.at(-1));
    for (const index of [0, 20, 40, 60, 80]) {
      assert.ok(
        Math.abs(result.curve[index][1] - fn(result.curve[index][0])) < 1e-9,
      );
    }
    assert.ok(result.rSquared !== null && result.rSquared > 1 - 1e-12);
  }
});

test('rejects invalid degrees and insufficient total or distinct observations', () => {
  assert.equal(fitHistoricalRegression([], 1), null);
  assert.equal(
    fitHistoricalRegression(
      [
        [0, 1],
        [1, 2],
      ],
      3,
    ),
    null,
  );
  assert.equal(
    fitHistoricalRegression(
      [
        [0, 1],
        [0, 2],
        [1, 3],
      ],
      2,
    ),
    null,
  );
  assert.equal(
    fitHistoricalRegression(
      [
        [0, 1],
        [1, 2],
        [2, 3],
      ],
      0,
    ),
    null,
  );
  assert.equal(
    fitHistoricalRegression(
      [
        [0, 1],
        [0, 2],
        [0, 3],
      ],
      1,
    ),
    null,
  );
});

test('filters nonfinite pairs and leaves the input untouched', () => {
  const points = [
    [0, 1],
    [Number.NaN, 2],
    [1, 2],
    [2, Number.POSITIVE_INFINITY],
  ];
  const snapshot = points.map((point) => [...point]);
  const result = fitHistoricalRegression(points, 1);
  assert.ok(result);
  assert.equal(result.n, 2);
  assert.deepEqual(points, snapshot);
});

test('rejects numerically dependent cubic columns despite distinct X values', () => {
  assert.equal(
    fitHistoricalRegression(
      [
        [0, 1],
        [1e-15, 2],
        [2e-15, 3],
        [1, 4],
      ],
      3,
    ),
    null,
  );
});

test('returns null R squared for a constant response', () => {
  const result = fitHistoricalRegression(
    [
      [0, 4],
      [1, 4],
      [2, 4],
    ],
    1,
  );
  assert.ok(result);
  assert.equal(result.rSquared, null);
  assert.ok(result.curve.every(([, y]) => Math.abs(y - 4) < 1e-12));
});

test('R squared uses total response variation and retains repeated X observations', () => {
  const fit = fitHistoricalRegression(
    [
      [0, 1],
      [1, 2],
      [2, 2],
    ],
    1,
  );
  assert.ok(fit);
  assert.ok(Math.abs(fit.rSquared - 0.75) < 1e-12);
  const repeated = fitHistoricalRegression(
    [
      [0, 0],
      [0, 2],
      [1, 2],
    ],
    1,
  );
  assert.ok(repeated);
  assert.equal(repeated.n, 3);
  assert.ok(Math.abs(repeated.curve[0][1] - 1) < 1e-12);
  assert.ok(Math.abs(repeated.curve.at(-1)[1] - 2) < 1e-12);
  assert.ok(Math.abs(repeated.rSquared - 0.25) < 1e-12);
});

test('has valid nondecreasing R squared for noisy nested polynomial fits', () => {
  const points = [
    [0, 1],
    [1, 2.2],
    [2, 2.7],
    [3, 4.4],
    [4, 5.1],
    [5, 6.8],
    [6, 8],
  ];
  const fits = [1, 2, 3].map((degree) =>
    fitHistoricalRegression(points, degree),
  );
  assert.ok(
    fits.every(
      (fit) => fit && fit.rSquared !== null && Number.isFinite(fit.rSquared),
    ),
  );
  assert.ok(fits[1].rSquared >= fits[0].rSquared - 1e-12);
  assert.ok(fits[2].rSquared >= fits[1].rSquared - 1e-12);
});

test('handles a large X offset with a small signal span', () => {
  const points = [-2, -1, 0, 1, 2, 3].map((delta) => [
    1e9 + delta,
    4 + 0.5 * delta,
  ]);
  const result = fitHistoricalRegression(points, 1);
  assert.ok(result);
  assert.equal(result.n, points.length);
  for (const [x, y] of result.curve) {
    assert.ok(Math.abs(y - (4 + 0.5 * (x - 1e9))) < 1e-8);
  }
});
