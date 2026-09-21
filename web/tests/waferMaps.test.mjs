import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compositeWaferMaps,
  inspectWaferDie,
  compareWaferMaps,
  selectDieRegion,
  waferData,
  waferSeed,
  waferCoordinates,
  waferCoordinateText,
} from '../src/waferMaps.ts';

test('physical coordinates use configured pitch, origin and radius, never guessed units', () => {
  const geometry = {
    radius_mm: 150,
    coordinate_radius: 16,
    chip_pitch_x_mm: 8,
    chip_pitch_y_mm: 10,
    chip_origin_x_mm: 1,
    chip_origin_y_mm: -2,
  };
  assert.deepEqual(waferCoordinates(2, -1, geometry), {
    xMm: 17,
    yMm: -12,
    radiusMm: Math.hypot(17, -12),
    chipX: 2,
    chipY: -1,
  });
  const measured = waferCoordinates(8, 0, geometry, 'normalized');
  assert.deepEqual(measured, {
    xMm: 75,
    yMm: 0,
    radiusMm: 75,
    chipX: 9,
    chipY: 0,
  });
  assert.equal(waferCoordinates(0, 0, undefined), null);
  assert.match(waferCoordinateText(1, 2, undefined), /geometry 미설정/);
  assert.match(
    waferCoordinateText(2, -1, geometry),
    /X 17.00 mm · Y -12.00 mm/,
  );
});

test('rectangle selection uses coordinates in either drag direction without changing input', () => {
  const dies = [
    { x: 0, y: 1, bin: 3 },
    { x: 2, y: -1, bin: 0 },
    { x: 5, y: 5, bin: 4 },
  ];
  const snapshot = structuredClone(dies);
  assert.deepEqual(
    selectDieRegion(dies, [
      [-0.5, 2],
      [-1, 1.5],
    ]),
    dies.slice(0, 2),
  );
  assert.deepEqual(
    selectDieRegion(dies, [
      [2, -0.5],
      [1.5, -1],
    ]),
    dies.slice(0, 2),
  );
  assert.deepEqual(
    selectDieRegion(dies, [
      [8, 9],
      [8, 9],
    ]),
    [],
  );
  assert.deepEqual(selectDieRegion(dies, null), dies);
  assert.deepEqual(dies, snapshot);
  assert.throws(() =>
    selectDieRegion(dies, [
      [NaN, 1],
      [0, 1],
    ]),
  );
});

test('regional comparison excludes missing dies from rate and preserves composite observations', () => {
  const region = [
    [0, 1],
    [0, 0],
  ];
  const a = {
    lotId: 'L',
    waferId: 'A',
    gridId: 'G',
    dies: [
      { x: 0, y: 0, bin: 3 },
      { x: 1, y: 0, bin: 4 },
      { x: 2, y: 0, bin: 0 },
    ],
  };
  const b = {
    lotId: 'L',
    waferId: 'B',
    gridId: 'G',
    dies: [
      { x: 0, y: 0, bin: 0 },
      { x: 2, y: 0, bin: 3 },
    ],
  };
  const cropped = [a, b].map((map) => ({
    ...map,
    dies: selectDieRegion(map.dies, region),
  }));
  const result = compareWaferMaps(...cropped);
  assert.equal(result.validCompared, 1);
  assert.equal(result.counts.missingB, 1);
  assert.equal(result.commonFailRateA, 1);
  assert.equal(result.commonFailRateB, 0);
  const composite = selectDieRegion(compositeWaferMaps([a, b]).dies, region);
  assert.equal(
    composite.reduce((sum, die) => sum + die.observed, 0),
    3,
  );
  assert.equal(
    composite.reduce((sum, die) => sum + die.flags, 0),
    2,
  );
});

test('Die inspection preserves wafer identity and distinguishes missing observations from non-Flag bins', () => {
  const maps = [
    {
      lotId: 'L/1',
      waferId: 'W1',
      gridId: 'G',
      dies: [{ x: 10, y: 8, bin: 4 }],
    },
    {
      lotId: 'L',
      waferId: '1/W1',
      gridId: 'G',
      dies: [{ x: 10, y: 8, bin: 0 }],
    },
    { lotId: 'L3', waferId: 'W1', gridId: 'G', dies: [] },
  ];
  assert.deepEqual(inspectWaferDie(maps, [10, 8]), [
    { lotId: 'L/1', waferId: 'W1', bin: 4, flag: true },
    { lotId: 'L', waferId: '1/W1', bin: 0, flag: false },
    { lotId: 'L3', waferId: 'W1', bin: null, flag: null },
  ]);
  assert.deepEqual(inspectWaferDie(maps, null), []);
  assert.deepEqual(inspectWaferDie([], [10, 8]), []);
  const rows = inspectWaferDie(maps, [10, 8]);
  const composite = compositeWaferMaps(maps).dies[0];
  assert.equal(rows.filter((row) => row.flag === true).length, composite.flags);
  assert.equal(
    rows.filter((row) => row.bin !== null).length,
    composite.observed,
  );
});

test('Die inspection rejects invalid coordinates, map identities and untrusted bin data', () => {
  const map = {
    lotId: 'L',
    waferId: 'W',
    gridId: 'G',
    dies: [{ x: 0, y: 0, bin: 3 }],
  };
  for (const point of [
    [NaN, 0],
    [0, Infinity],
    [0.5, 0],
  ])
    assert.throws(() => inspectWaferDie([map], point));
  assert.throws(() => inspectWaferDie([map, map], [0, 0]));
  assert.throws(() =>
    inspectWaferDie([map, { ...map, waferId: 'W2', gridId: 'H' }], [0, 0]),
  );
  assert.throws(() => inspectWaferDie([{ ...map, gridId: '' }], [0, 0]));
  assert.throws(() =>
    inspectWaferDie([{ ...map, dies: [{ x: 0, y: 0, bin: -1 }] }], [0, 0]),
  );
  assert.throws(() =>
    inspectWaferDie([{ ...map, dies: [...map.dies, ...map.dies] }], [0, 0]),
  );
});

test('waferData is deterministic and keeps the existing die count', () => {
  assert.deepEqual(waferData(17), waferData(17));
  assert.equal(waferData(17).length, 795);
});

test('waferSeed hashes a JSON tuple without separator collisions', () => {
  assert.equal(
    waferSeed('incident', 'lot', 'wafer'),
    waferSeed('incident', 'lot', 'wafer'),
  );
  assert.notEqual(waferSeed('ab', 'c', 'd'), waferSeed('a', 'bc', 'd'));
});

test('compositeWaferMaps handles empty and one-map inputs', () => {
  assert.deepEqual(compositeWaferMaps([]), { waferCount: 0, dies: [] });
  assert.deepEqual(
    compositeWaferMaps([
      {
        lotId: 'L1',
        waferId: 'W1',
        gridId: 'G',
        dies: [{ x: 1, y: 0, bin: 3 }],
      },
    ]),
    {
      waferCount: 1,
      dies: [{ x: 1, y: 0, flags: 1, observed: 1, percent: 100 }],
    },
  );
});

test('compositeWaferMaps aggregates selected wafers with per-coordinate denominators', () => {
  const first = {
    lotId: 'L1',
    waferId: 'W1',
    gridId: 'G',
    dies: [
      { x: 1, y: 0, bin: 3 },
      { x: 0, y: 1, bin: 1 },
    ],
  };
  const second = {
    lotId: 'L2',
    waferId: 'W1',
    gridId: 'G',
    dies: [
      { x: 1, y: 0, bin: 0 },
      { x: 0, y: -1, bin: 4 },
    ],
  };
  assert.deepEqual(compositeWaferMaps([first, second]), {
    waferCount: 2,
    dies: [
      { x: 0, y: -1, flags: 1, observed: 1, percent: 100 },
      { x: 1, y: 0, flags: 1, observed: 2, percent: 50 },
      { x: 0, y: 1, flags: 0, observed: 1, percent: 0 },
    ],
  });
  assert.equal(compositeWaferMaps([first]).dies.length, 2);
});

test('compositeWaferMaps rejects mixed grids, duplicate wafers, duplicate coordinates, and invalid die values', () => {
  const base = {
    lotId: 'L1',
    waferId: 'W1',
    gridId: 'G',
    dies: [{ x: 0, y: 0, bin: 0 }],
  };
  assert.throws(() =>
    compositeWaferMaps([base, { ...base, lotId: 'L2', gridId: 'H' }]),
  );
  assert.throws(() => compositeWaferMaps([base, { ...base }]));
  assert.throws(() =>
    compositeWaferMaps([
      {
        ...base,
        dies: [
          { x: 0, y: 0, bin: 0 },
          { x: 0, y: 0, bin: 1 },
        ],
      },
    ]),
  );
  for (const die of [
    { x: 0.5, y: 0, bin: 0 },
    { x: 0, y: Number.NaN, bin: 0 },
    { x: 0, y: 0, bin: 1.5 },
  ]) {
    assert.throws(() => compositeWaferMaps([{ ...base, dies: [die] }]));
  }
});
