import assert from 'node:assert/strict';
import test from 'node:test';

import {
  interpolateAt,
  interpolateBarycentric,
  interpolateWaferGrid,
  compositeMetrologyMaps,
  makeMetrologyFixture,
  metricColor,
  metricRange,
  metricStats,
  normalizeMetricValue,
  sanitizeMeasuredPoints,
  selectMeasuredRegion,
} from '../src/metrologyMap.ts';

test('keeps only finite measurement points and drops duplicate coordinates', () => {
  const points = sanitizeMeasuredPoints([
    { x: 0, y: 0, value: 1 },
    { x: 0, y: 0, value: 99 },
    { x: Number.NaN, y: 1, value: 2 },
    { x: 1, y: Number.POSITIVE_INFINITY, value: 3 },
    { x: 1, y: 1, value: 4 },
  ]);
  assert.deepEqual(points, [
    { x: 0, y: 0, value: 1 },
    { x: 1, y: 1, value: 4 },
  ]);
});

test('reproduces an affine field with barycentric interpolation', () => {
  const points = [
    { x: 0, y: 0, value: 2 },
    { x: 4, y: 0, value: 10 },
    { x: 0, y: 4, value: 14 },
  ];
  assert.ok(Math.abs(interpolateBarycentric(points, 1, 1) - 7) < 1e-10);
  assert.equal(interpolateAt(points, 5, 1), null);
});

test('returns null outside the measured convex hull', () => {
  const square = [
    { x: -1, y: -1, value: 0 },
    { x: 1, y: -1, value: 1 },
    { x: 1, y: 1, value: 2 },
    { x: -1, y: 1, value: 1 },
  ];
  assert.equal(interpolateBarycentric(square, 0, 0), 1);
  assert.equal(interpolateBarycentric(square, 1.01, 0), null);
});

test('clips interpolated grid cells to the wafer circle', () => {
  const points = [
    { x: -15, y: -15, value: 0 },
    { x: 15, y: -15, value: 1 },
    { x: 15, y: 15, value: 2 },
    { x: -15, y: 15, value: 1 },
  ];
  const grid = interpolateWaferGrid(points, 16, 2);
  assert.ok(grid.length > 0);
  assert.ok(grid.every((point) => Math.hypot(point.x, point.y) <= 16 + 1e-9));
});

test('normalizes CD and signed overlay values against stable metric domains', () => {
  assert.equal(normalizeMetricValue('cd', metricRange('cd')[0]), 0);
  assert.equal(normalizeMetricValue('cd', metricRange('cd')[1]), 1);
  assert.equal(normalizeMetricValue('overlay-x', 0), 0.5);
  assert.equal(normalizeMetricValue('overlay-y', -100), 0);
  assert.equal(normalizeMetricValue('overlay-y', 100), 1);
  assert.equal(normalizeMetricValue('overlay-magnitude', 0), 0);
  assert.equal(normalizeMetricValue('overlay-magnitude', 100), 1);
  assert.equal(normalizeMetricValue('thk', 480), 0);
  assert.equal(normalizeMetricValue('thk', 520), 1);
});

test('uses deterministic distinct seeds for full lot and wafer tuples', () => {
  const first = makeMetrologyFixture('LOT-A', 'W01', 'cd');
  const repeat = makeMetrologyFixture('LOT-A', 'W01', 'cd');
  const otherWafer = makeMetrologyFixture('LOT-A', 'W02', 'cd');
  assert.deepEqual(first, repeat);
  assert.notDeepEqual(first.points, otherWafer.points);
  assert.match(first.sourceLabel, /SYNTHETIC fixture/);
  assert.equal(first.unit, 'nm');
});

test('provides a deterministic THK field distinct from CD on the same fixture', () => {
  const cd = makeMetrologyFixture('LOT-A', 'W01', 'cd');
  const thk = makeMetrologyFixture('LOT-A', 'W01', 'thk');
  assert.deepEqual(
    cd.points.map((point) => [point.x, point.y]),
    thk.points.map((point) => [point.x, point.y]),
  );
  assert.notDeepEqual(
    cd.points.map((point) => point.value),
    thk.points.map((point) => point.value),
  );
  assert.ok(
    thk.points.every((point) => point.value >= 480 && point.value <= 520),
  );
  assert.deepEqual(metricRange('thk'), [480, 520]);
});

test('uses continuous colors within fixed scales and clamps beyond their limits', () => {
  for (const metric of ['cd', 'overlay-x', 'overlay-y', 'overlay-magnitude']) {
    const [min, max] = metricRange(metric);
    assert.equal(metricColor(metric, min - 100), metricColor(metric, min));
    assert.equal(metricColor(metric, max + 100), metricColor(metric, max));
    assert.notEqual(
      metricColor(metric, min),
      metricColor(metric, (min + max) / 2),
    );
    assert.notEqual(
      metricColor(metric, max),
      metricColor(metric, (min + max) / 2),
    );
  }
  assert.notEqual(metricColor('cd', 98), metricColor('cd', 99));
  assert.equal(metricColor('overlay-x', 0), '#fffdf8');
});

test('overlay magnitude equals the norm of X and Y at the same measured positions', () => {
  const x = makeMetrologyFixture('LOT-A', 'W01', 'overlay-x').points;
  const y = makeMetrologyFixture('LOT-A', 'W01', 'overlay-y').points;
  const norm = makeMetrologyFixture('LOT-A', 'W01', 'overlay-magnitude').points;
  assert.ok(x.length > 3);
  x.forEach((point, index) => {
    assert.equal(point.x, y[index].x);
    assert.equal(point.y, norm[index].y);
    assert.equal(norm[index].value, Math.hypot(point.value, y[index].value));
  });
});

test('region selection uses both axes and measured values, including reversed drags', () => {
  const points = [
    { x: 0, y: 0, value: 1 },
    { x: 1, y: 1, value: 3 },
    { x: 1, y: 3, value: 99 },
    { x: 3, y: 1, value: 99 },
  ];
  assert.deepEqual(
    metricStats(
      selectMeasuredRegion(points, [
        [2, 0],
        [2, 0],
      ]),
    ),
    { min: 1, median: 2, max: 3, n: 2 },
  );
  assert.deepEqual(selectMeasuredRegion(points, null), points);
  assert.deepEqual(
    selectMeasuredRegion(points, [
      [NaN, 0],
      [0, 2],
    ]),
    [],
  );
  assert.deepEqual(metricStats([]), {
    min: null,
    median: null,
    max: null,
    n: 0,
  });
  assert.deepEqual(interpolateWaferGrid([]), []);
});

test('reports measured min, median, max, and count', () => {
  assert.deepEqual(
    metricStats([
      { x: 0, y: 0, value: 3 },
      { x: 1, y: 0, value: 1 },
      { x: 2, y: 0, value: 2 },
    ]),
    { min: 1, median: 2, max: 3, n: 3 },
  );
});

function compositeFixture(lotId, waferId, metric, points, radius = 4) {
  return {
    lotId,
    waferId,
    metric,
    unit: 'nm',
    radius,
    points,
    sourceLabel: 'SYNTHETIC fixture | no actual data | no causality claim',
  };
}

test('composites per-wafer interpolated cells and preserves missing denominators', () => {
  const square = [
    { x: -3, y: -3, value: 0 },
    { x: 3, y: -3, value: 6 },
    { x: 3, y: 3, value: 12 },
    { x: -3, y: 3, value: 6 },
  ];
  const triangle = [
    { x: -3, y: -3, value: 10 },
    { x: 3, y: -3, value: 16 },
    { x: -3, y: 3, value: 16 },
  ];
  const result = compositeMetrologyMaps(
    [
      compositeFixture('LOT-A', 'W01', 'cd', square),
      compositeFixture('LOT-A', 'W02', 'cd', triangle),
    ],
    4,
    2,
  );
  assert.equal(result.waferCount, 2);
  assert.equal(result.measurementCount, 7);
  const center = result.grid.find((point) => point.x === 0 && point.y === 0);
  assert.deepEqual(center, {
    x: 0,
    y: 0,
    value: 11,
    kind: 'estimated',
    contributors: 2,
  });
  const upperRight = result.grid.find(
    (point) => point.x === 2 && point.y === 2,
  );
  assert.deepEqual(upperRight, {
    x: 2,
    y: 2,
    value: 10,
    kind: 'estimated',
    contributors: 1,
  });
  assert.equal(
    result.grid.some((point) => point.x === 4 && point.y === 0),
    false,
  );
});

test('composite validation rejects duplicate wafers, mixed metadata, and invalid geometry', () => {
  const fixture = compositeFixture('LOT-A', 'W01', 'cd', [
    { x: -1, y: -1, value: 1 },
    { x: 1, y: -1, value: 2 },
    { x: 0, y: 1, value: 3 },
  ]);
  assert.deepEqual(compositeMetrologyMaps([]), {
    grid: [],
    waferCount: 0,
    measurementCount: 0,
  });
  assert.throws(
    () => compositeMetrologyMaps([fixture, fixture], 4),
    /Duplicate/,
  );
  assert.throws(
    () =>
      compositeMetrologyMaps(
        [fixture, { ...fixture, waferId: 'W02', metric: 'thk' }],
        4,
      ),
    /one metric/,
  );
  assert.throws(
    () =>
      compositeMetrologyMaps(
        [fixture, { ...fixture, waferId: 'W02', unit: 'um' }],
        4,
      ),
    /one unit/,
  );
  assert.throws(
    () =>
      compositeMetrologyMaps(
        [fixture, { ...fixture, waferId: 'W02', radius: 5 }],
        4,
      ),
    /radius/,
  );
  assert.throws(() => compositeMetrologyMaps([], 0), /positive finite/);
  assert.throws(() => compositeMetrologyMaps([], 4, 0), /positive finite/);
});

test('uses JSON tuple keys for distinct lot and wafer identities', () => {
  const points = [
    { x: -1, y: -1, value: 1 },
    { x: 1, y: -1, value: 2 },
    { x: 0, y: 1, value: 3 },
  ];
  const result = compositeMetrologyMaps(
    [
      compositeFixture('LOT', '\u0000W', 'cd', points),
      compositeFixture('LOT\u0000', 'W', 'cd', points),
    ],
    4,
  );
  assert.equal(result.waferCount, 2);
});
