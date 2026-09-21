import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compositeOverlayVectors,
  fitOverlayVectors,
  makeOverlayFixture,
} from '../src/overlayVectors.ts';

test('builds deterministic vectors from the same synthetic X/Y coordinates', () => {
  const first = makeOverlayFixture('LOT-A', 'W01');
  const repeat = makeOverlayFixture('LOT-A', 'W01');
  assert.deepEqual(first, repeat);
  assert.ok(first.points.length > 3);
  assert.ok(
    first.points.every(
      (point) => Number.isFinite(point.dx) && Number.isFinite(point.dy),
    ),
  );
});

function overlayFixture(lotId, waferId, points) {
  return { lotId, waferId, points };
}

test('composites vector components on a common grid and marks contributors', () => {
  const locations = [
    [-3, -3],
    [3, -3],
    [3, 3],
    [-3, 3],
  ];
  const first = locations.map(([x, y]) => ({
    x,
    y,
    dx: x + y + 6,
    dy: x - y,
  }));
  const second = locations.map(([x, y]) => ({
    x,
    y,
    dx: x + y + 16,
    dy: x - y + 20,
  }));
  const result = compositeOverlayVectors(
    [
      overlayFixture('LOT-A', 'W01', first),
      overlayFixture('LOT-A', 'W02', second),
    ],
    4,
    2,
  );
  const center = result.points.find((point) => point.x === 0 && point.y === 0);
  assert.deepEqual(center, {
    x: 0,
    y: 0,
    dx: 11,
    dy: 10,
    contributors: 2,
  });
  assert.equal(result.waferCount, 2);
  assert.ok(result.points.every((point) => point.contributors === 2));
});

test('does not extrapolate vector components outside a wafer hull', () => {
  const result = compositeOverlayVectors(
    [
      overlayFixture('LOT-A', 'W01', [
        { x: -3, y: -3, dx: 0, dy: 0 },
        { x: 3, y: -3, dx: 6, dy: 6 },
        { x: -3, y: 3, dx: 6, dy: -6 },
      ]),
    ],
    4,
    2,
  );
  assert.equal(
    result.points.some((point) => point.x === 2 && point.y === 2),
    false,
  );
});

test('fits both vector components with QR and reports exact residual vectors', () => {
  const points = [
    [-2, -1],
    [1, -2],
    [3, 2],
    [-1, 3],
  ].map(([x, y]) => ({
    x,
    y,
    dx: 1 + 2 * x + 3 * y,
    dy: -2 + 0.5 * x - 1.5 * y,
  }));
  const result = fitOverlayVectors(points);
  assert.ok(result);
  assert.ok(result.rmsResidual < 1e-10);
  assert.ok(result.rmsRaw > 0);
  assert.ok(
    result.coefficients.dx.every(
      (value, index) => Math.abs(value - [1, 2, 3][index]) < 1e-10,
    ),
  );
  assert.ok(
    result.coefficients.dy.every(
      (value, index) => Math.abs(value - [-2, 0.5, -1.5][index]) < 1e-10,
    ),
  );
  result.raw.forEach((point, index) => {
    assert.equal(result.residual[index].dx, point.dx - result.fit[index].dx);
    assert.equal(result.residual[index].dy, point.dy - result.fit[index].dy);
  });
});

test('reports nonzero residual for a nonlinear vector field', () => {
  const result = fitOverlayVectors([
    { x: -1, y: -1, dx: 1, dy: 0 },
    { x: 1, y: -1, dx: 1, dy: 0 },
    { x: 1, y: 1, dx: 1, dy: 0 },
    { x: -1, y: 1, dx: 1, dy: 0 },
    { x: 0, y: 0, dx: 0, dy: 0 },
  ]);
  assert.ok(result);
  assert.ok(result.rmsResidual > 0.1);
});

test('returns null for insufficient, nonfinite, or degenerate fit inputs', () => {
  assert.equal(
    fitOverlayVectors([
      { x: 0, y: 0, dx: 1, dy: 1 },
      { x: 1, y: 0, dx: 2, dy: 1 },
    ]),
    null,
  );
  assert.equal(
    fitOverlayVectors([
      { x: 0, y: 0, dx: 1, dy: 1 },
      { x: 1, y: 1, dx: 2, dy: 1 },
      { x: 2, y: 2, dx: 3, dy: 1 },
    ]),
    null,
  );
  assert.equal(
    fitOverlayVectors([
      { x: 0, y: 0, dx: 1, dy: 1 },
      { x: 1, y: 0, dx: Number.NaN, dy: 1 },
      { x: 0, y: 1, dx: 1, dy: 2 },
    ]),
    null,
  );
});
