import test from 'node:test';
import assert from 'node:assert/strict';
import {
  defaultLayout,
  fitLayout,
  fitSizes,
  layoutVersion,
  migrateLayout,
  minimumFractions,
  moveBoundary,
  parseLayout,
} from '../src/boardLayout.ts';
const sum = (values) => values.reduce((a, b) => a + b, 0);
test('layout storage is versioned, finite, complete and normalized', () => {
  const original = defaultLayout();
  assert.deepEqual(
    parseLayout(JSON.stringify({ version: layoutVersion, ...original })),
    original,
  );
  for (const invalid of [
    null,
    '{',
    '{}',
    JSON.stringify({ version: 1, ...original }),
    JSON.stringify({ version: layoutVersion, ...original, rows: [-1, 1, 1] }),
    JSON.stringify({
      version: layoutVersion,
      ...original,
      columns: [[1], [], []],
    }),
  ])
    assert.equal(parseLayout(invalid), null);
});
test('new defaults reserve more body height and narrow only the composite map', () => {
  const layout = defaultLayout();
  assert.deepEqual(layout.rows, [0.38, 0.29, 0.33]);
  assert.equal(layout.columns[1][1], 2 / 12);
  assert.equal(layout.columns[1][2], 1.5 / 12);
  assert.equal(layout.columns[1][0], 2.5 / 12);
});
test('v1 migration updates untouched defaults without wiping customized dimensions', () => {
  const legacy = {
    version: 1,
    rows: [0.4125, 0.3375, 0.25],
    columns: [
      [0.4, 0.35, 0.25],
      [2 / 12, 2 / 12, 2 / 12, 3 / 12, 3 / 12],
      [4 / 12, 3 / 12, 5 / 12],
    ],
  };
  const migrated = migrateLayout(JSON.stringify(legacy));
  assert.deepEqual(migrated?.rows, defaultLayout().rows);
  assert.deepEqual(migrated?.columns[0], legacy.columns[0]);
  assert.deepEqual(migrated?.columns[1], defaultLayout().columns[1]);
  assert.deepEqual(migrated?.columns[2], defaultLayout().columns[2]);

  const customRows = [0.3, 0.35, 0.35];
  const custom = migrateLayout(JSON.stringify({ ...legacy, rows: customRows }));
  assert.deepEqual(custom?.rows, customRows);
});
test('v1 migration repairs undersized analysis and oversized composite without resetting other panels', () => {
  const columns = [
    [0.4, 0.35, 0.25],
    [0.15, 0.15, 0.3, 0.2, 0.2],
    [0.3, 0.3, 0.4],
  ];
  const result = migrateLayout(
    JSON.stringify({ version: 1, rows: [0.5, 0.3, 0.2], columns }),
  );
  assert.equal(result.rows[2], 0.33);
  assert.ok(Math.abs(result.rows[0] / result.rows[1] - 5 / 3) < 1e-10);
  assert.equal(result.columns[1][2], 0.125);
  assert.equal(result.columns[1][1], columns[1][1]);
  assert.deepEqual(result.columns[1].slice(3), columns[1].slice(3));
  assert.deepEqual(result.columns[0], columns[0]);
  assert.deepEqual(result.columns[2], columns[2]);
  assert.ok(Math.abs(sum(result.columns[1]) - 1) < 1e-10);
});
test('diagonal resizing keeps adjacent rows and columns packed at limits', () => {
  const original = defaultLayout();
  const fitted = fitLayout(original, 1366, 778);
  const mins = minimumFractions([340, 340, 260], 1364);
  const moved = moveBoundary(fitted.columns[0], 0, 10, mins);
  assert.ok(Math.abs(sum(moved) - 1) < 1e-12);
  assert.ok(Math.abs(moved[1] - mins[1]) < 1e-12);
  assert.equal(moved[2], fitted.columns[0][2]);
  assert.deepEqual(original, defaultLayout());
  assert.deepEqual(moveBoundary(moved, -1, 2, mins), moved);
  assert.deepEqual(moveBoundary(moved, 0, NaN, mins), moved);
});
test('responsive minimum sizes preserve all panels without overflow', () => {
  for (const [width, height] of [
    [1920, 958],
    [1366, 646],
    [1101, 530],
    [390, 300],
  ]) {
    const result = fitLayout(defaultLayout(), width, height);
    for (const row of [result.rows, ...result.columns]) {
      assert.ok(row.every((n) => Number.isFinite(n) && n > 0));
      assert.ok(Math.abs(sum(row) - 1) < 1e-12);
    }
  }
  fitSizes([0.01, 0.49, 0.5], [0.2, 0.2, 0.2]).forEach((value, i) =>
    assert.ok(
      Math.abs(value - [0.2, (0.8 * 0.49) / 0.99, (0.8 * 0.5) / 0.99][i]) <
        1e-12,
    ),
  );
});
