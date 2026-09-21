import test from 'node:test';
import assert from 'node:assert/strict';
import {
  defaultLayout,
  fitLayout,
  fitSizes,
  layoutVersion,
  layoutStorageKey,
  previousLayoutStorageKeys,
  migrateLayout,
  minimumFractions,
  minColumns,
  minWorkspace,
  moveBoundary,
  panelRows,
  parseLayout,
} from '../src/boardLayout.ts';

const sum = (values) => values.reduce((a, b) => a + b, 0);

test('new spatial layout has separate persistence and rejects incomplete or old dimensions', () => {
  const original = defaultLayout();
  assert.equal(layoutStorageKey, 'qagent:board-layout:v5');
  assert.deepEqual(
    parseLayout(JSON.stringify({ version: layoutVersion, ...original })),
    original,
  );
  for (const invalid of [
    null,
    '{',
    '{}',
    ...[1, 2, 3, 4].map((version) => JSON.stringify({ version, ...original })),
    JSON.stringify({ version: layoutVersion, ...original, rows: [-1, 1, 1] }),
    JSON.stringify({ version: layoutVersion, ...original, workspace: [0.5] }),
    JSON.stringify({
      version: layoutVersion,
      ...original,
      workspace: [0.7, null],
    }),
    JSON.stringify({
      version: layoutVersion,
      ...original,
      columns: [[1], [], []],
    }),
  ])
    assert.equal(parseLayout(invalid), null);
});

test('investigation order gives every panel one place and a two-row analysis area', () => {
  assert.deepEqual(panelRows, [
    ['signals', 'trend', 'correlation'],
    ['single-map', 'composite', 'images'],
    ['distribution', 'documents', 'production'],
  ]);
  assert.equal(new Set([...panelRows.flat(), 'assessment']).size, 10);
  const layout = defaultLayout();
  assert.ok(layout.rows[1] + layout.rows[2] >= 0.6);
  assert.ok(layout.columns[0][1] > layout.columns[0][2]);
  assert.ok(layout.columns[1][1] < layout.columns[1][2]);
});

test('migrates v4 current layout while preserving every other boundary', () => {
  assert.deepEqual(previousLayoutStorageKeys, [
    'qagent:board-layout:v4',
    'qagent:board-layout:v3',
  ]);
  const previous = {
    ...defaultLayout(),
    version: 4,
    rows: [0.42, 0.31, 0.27],
    columns: [
      [0.4, 0.38, 0.22],
      [0.2, 0.3, 0.5],
      [0.3, 0.4, 0.3],
    ],
  };
  const migrated = migrateLayout(JSON.stringify(previous));
  assert.deepEqual(migrated.rows, previous.rows);
  assert.deepEqual(migrated.workspace, previous.workspace);
  assert.deepEqual(migrated.columns, [
    previous.columns[0],
    [0.3, 0.3, 0.4],
    previous.columns[2],
  ]);
  assert.deepEqual(
    parseLayout(JSON.stringify({ version: 5, ...migrated })),
    migrated,
  );
});

test('migrates v3 wafer-list space while preserving every other boundary', () => {
  const previous = {
    ...defaultLayout(),
    version: 3,
    rows: [0.42, 0.31, 0.27],
    columns: [
      [0.4, 0.38, 0.22],
      [0.2, 0.18, 0.2, 0.42],
      [0.3, 0.4, 0.3],
    ],
  };
  const migrated = migrateLayout(JSON.stringify(previous));
  assert.deepEqual(migrated.rows, previous.rows);
  assert.deepEqual(migrated.workspace, previous.workspace);
  assert.deepEqual(migrated.columns, [
    previous.columns[0],
    [0.3, 0.3, 0.4],
    previous.columns[2],
  ]);
  assert.deepEqual(
    parseLayout(JSON.stringify({ version: 5, ...migrated })),
    migrated,
  );
  for (const raw of [
    null,
    '{',
    JSON.stringify({ ...previous, version: 2 }),
    JSON.stringify({
      ...previous,
      columns: [previous.columns[0], [0.2, 0.3, 0.5], previous.columns[2]],
    }),
    JSON.stringify({
      ...previous,
      columns: [
        previous.columns[0],
        [-0.1, 0.18, 0.2, 0.72],
        previous.columns[2],
      ],
    }),
    JSON.stringify({ ...previous, columns: defaultLayout().columns }),
  ])
    assert.equal(migrateLayout(raw), null);
});

test('default middle row makes Map wider and SEM narrower at 1366px', () => {
  const width = 1366;
  const workspacePixels = (width - 1) * defaultLayout().workspace[0] - 2;
  const oldMap = workspacePixels * 0.195;
  const oldSem = workspacePixels * 0.61;
  const fitted = fitLayout(defaultLayout(), width, 900);
  const newMap = workspacePixels * fitted.columns[1][0];
  const newSem = workspacePixels * fitted.columns[1][2];
  assert.ok(newMap > oldMap);
  assert.ok(newSem < oldSem);
  assert.deepEqual(fitted.columns[1], [0.3, 0.3, 0.4]);
  assert.deepEqual(minColumns[1], [220, 220, 300]);
});

test('adjacent row and column resizing preserves extent and untouched neighbors', () => {
  const original = defaultLayout();
  const fitted = fitLayout(original, 1366, 800);
  const mins = minimumFractions(minColumns[0], 1364);
  const moved = moveBoundary(fitted.columns[0], 0, 10, mins);
  assert.ok(Math.abs(sum(moved) - 1) < 1e-12);
  assert.ok(Math.abs(moved[1] - mins[1]) < 1e-12);
  assert.equal(moved[2], fitted.columns[0][2]);
  assert.deepEqual(original, defaultLayout());
  assert.deepEqual(moveBoundary(moved, -1, 2, mins), moved);
  assert.deepEqual(moveBoundary(moved, 0, NaN, mins), moved);
});

test('analysis width resizing refits lower panels without changing the top band', () => {
  const width = 1366;
  const fitted = fitLayout(defaultLayout(), width, 800);
  const workspace = moveBoundary(
    fitted.workspace,
    0,
    -10,
    minimumFractions(minWorkspace, width - 1),
  );
  const resized = fitLayout({ ...fitted, workspace }, width, 800);
  assert.ok(
    Math.abs((width - 1) * resized.workspace[0] - minWorkspace[0]) < 1e-9,
  );
  assert.deepEqual(resized.columns[0], fitted.columns[0]);
  for (let i = 1; i < 3; i++) {
    const rowWidth =
      (width - 1) * resized.workspace[0] - resized.columns[i].length + 1;
    const mins = minimumFractions(minColumns[i], rowWidth);
    resized.columns[i].forEach((n, j) => assert.ok(n + 1e-12 >= mins[j]));
  }
});

test('responsive minimum sizes keep all panels finite and normalized', () => {
  for (const [width, height] of [
    [1920, 980],
    [1366, 800],
    [1366, 668],
    [1101, 550],
    [390, 300],
  ]) {
    const result = fitLayout(defaultLayout(), width, height);
    for (const row of [result.rows, result.workspace, ...result.columns]) {
      assert.ok(row.every((n) => Number.isFinite(n) && n > 0));
      assert.ok(Math.abs(sum(row) - 1) < 1e-12);
    }
    assert.deepEqual(
      parseLayout(JSON.stringify({ version: layoutVersion, ...result })),
      result,
    );
  }
  fitSizes([0.01, 0.49, 0.5], [0.2, 0.2, 0.2]).forEach((value, i) =>
    assert.ok(
      Math.abs(value - [0.2, (0.8 * 0.49) / 0.99, (0.8 * 0.5) / 0.99][i]) <
        1e-12,
    ),
  );
});
