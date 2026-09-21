import assert from 'node:assert/strict';
import test from 'node:test';

import {
  makeAggregateMetrologyProfile,
  makeMetrologyProfile,
  orderProfilePoints,
  profileRadius,
} from '../src/metrologyProfile.ts';

const geometry = {
  radius_mm: 150,
  coordinate_radius: 16,
  chip_pitch_x_mm: 1,
  chip_pitch_y_mm: 1,
  chip_origin_x_mm: 0,
  chip_origin_y_mm: 0,
};

test('does not count duplicate coordinates in a wafer as additional wafers', () => {
  const profile = makeAggregateMetrologyProfile([
    [{ x: 1, y: 1, value: 10 }, { x: 1, y: 1, value: 999 }],
    [{ x: 1, y: 1, value: 20 }],
  ], geometry, 16);
  assert.equal(profile.points[0].value, 15);
  assert.equal(profile.points[0].contributors, 2);
});

test('converts normalized measurement coordinates to the wafer radius in mm', () => {
  assert.equal(profileRadius({ x: 8, y: 0 }, geometry), 75);
  assert.equal(profileRadius({ x: 0, y: -16 }, geometry), 150);
});

test('computes radial-bin means with missing measurements excluded', () => {
  const profile = makeMetrologyProfile(
    [
      { x: 0, y: 0, value: 10 },
      { x: 2, y: 0, value: 20 },
      { x: 8, y: 0, value: 40 },
      { x: 16, y: 0, value: 60 },
      { x: Number.NaN, y: 0, value: 999 },
      { x: 4, y: 0, value: Number.NaN },
    ],
    undefined,
    16,
    4,
  );
  assert.equal(profile.points.length, 4);
  assert.deepEqual(
    profile.radialMeans.map(({ x, mean, contributors }) => [x, mean, contributors]),
    [
      [1, 15, 2],
      [8, 40, 1],
      [16, 60, 1],
    ],
  );
});

test('keeps a rising radial gradient visible in the binned means', () => {
  const profile = makeMetrologyProfile(
    [
      { x: 0, y: 0, value: 100 },
      { x: 4, y: 0, value: 110 },
      { x: 8, y: 0, value: 120 },
      { x: 12, y: 0, value: 130 },
    ],
    undefined,
    16,
    4,
  );
  assert.deepEqual(profile.radialMeans.map(({ mean }) => mean), [100, 110, 120, 130]);
});

test('supports fixture point order and stable radius ordering', () => {
  const profile = makeMetrologyProfile(
    [
      { x: 8, y: 0, value: 1 },
      { x: 0, y: 0, value: 2 },
      { x: 4, y: 0, value: 3 },
    ],
    undefined,
    16,
  );
  assert.deepEqual(
    orderProfilePoints(profile.points, 'point').map(({ sourceIndex }) => sourceIndex),
    [0, 1, 2],
  );
  assert.deepEqual(
    orderProfilePoints(profile.points, 'radius').map(({ sourceIndex }) => sourceIndex),
    [1, 2, 0],
  );
});

test('aggregates corresponding measured coordinates with contributor counts', () => {
  const profile = makeAggregateMetrologyProfile(
    [
      [
        { x: 0, y: 0, value: 100 },
        { x: 4, y: 0, value: 110 },
      ],
      [
        { x: 0, y: 0, value: 104 },
        { x: 4, y: 0, value: Number.NaN },
      ],
    ],
    undefined,
    16,
  );
  assert.deepEqual(
    profile.points.map(({ x, value, contributors }) => [x, value, contributors]),
    [
      [0, 102, 2],
      [4, 110, 1],
    ],
  );
});
