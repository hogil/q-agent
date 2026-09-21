import test from 'node:test';
import assert from 'node:assert/strict';
import {
  defaultLayout,
  fitLayout,
  fitSizes,
  minimumFractions,
  moveBoundary,
  parseLayout,
} from '../src/boardLayout.ts';
const sum = (values) => values.reduce((a, b) => a + b, 0);
test('layout storage is versioned, finite, complete and normalized', () => {
  const original = defaultLayout();
  assert.deepEqual(
    parseLayout(JSON.stringify({ version: 1, ...original })),
    original,
  );
  for (const invalid of [
    null,
    '{',
    '{}',
    JSON.stringify({ version: 2, ...original }),
    JSON.stringify({ version: 1, ...original, rows: [-1, 1, 1] }),
    JSON.stringify({ version: 1, ...original, columns: [[1], [], []] }),
  ])
    assert.equal(parseLayout(invalid), null);
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
