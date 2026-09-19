import assert from 'node:assert/strict';
import test from 'node:test';

import { compareWaferMaps } from '../src/waferMaps.ts';

function wafer(waferId, dies, lotId = 'LOT') {
  return { lotId, waferId, gridId: 'GRID', dies };
}

test('classifies full missing overlap without treating missing as pass', () => {
  const result = compareWaferMaps(
    wafer('A', [
      { x: -1, y: 2, bin: 3 },
      { x: 2, y: -1, bin: 1 },
    ]),
    wafer('B', [
      { x: 10, y: 0, bin: 4 },
      { x: 11, y: 0, bin: 0 },
    ]),
  );

  assert.deepEqual(result.counts, {
    bothFlag: 0,
    aOnly: 0,
    bOnly: 0,
    neither: 0,
    missingA: 2,
    missingB: 2,
  });
  assert.equal(result.validCompared, 0);
  assert.equal(result.observedCommon, 0);
  assert.equal(result.flagsA, 1);
  assert.equal(result.flagsB, 1);
  assert.equal(result.failRateA, 0.5);
  assert.equal(result.failRateB, 0.5);
  assert.equal(result.commonFailRateA, null);
  assert.equal(result.commonFailRateB, null);
  assert.equal(result.delta, null);
  assert.equal(result.jaccard, null);
  assert.deepEqual(
    result.dies.map(({ x, y, binA, binB, category }) => ({ x, y, binA, binB, category })),
    [
      { x: 2, y: -1, binA: 1, binB: null, category: 'missingB' },
      { x: 10, y: 0, binA: null, binB: 4, category: 'missingA' },
      { x: 11, y: 0, binA: null, binB: 0, category: 'missingA' },
      { x: -1, y: 2, binA: 3, binB: null, category: 'missingB' },
    ],
  );
});

test('uses comparison-common rates for signed delta and is symmetric', () => {
  const a = wafer('A', [
    { x: 0, y: 0, bin: 3 },
    { x: 1, y: 0, bin: 3 },
    { x: 2, y: 0, bin: 0 },
  ]);
  const b = wafer('B', [
    { x: 0, y: 0, bin: 3 },
    { x: 1, y: 0, bin: 0 },
    { x: 2, y: 0, bin: 0 },
  ]);

  const forward = compareWaferMaps(a, b);
  const reverse = compareWaferMaps(b, a);

  assert.deepEqual(forward.counts, {
    bothFlag: 1,
    aOnly: 1,
    bOnly: 0,
    neither: 1,
    missingA: 0,
    missingB: 0,
  });
  assert.equal(forward.validCompared, 3);
  assert.equal(forward.observedA, 3);
  assert.equal(forward.observedB, 3);
  assert.equal(forward.flagsA, 2);
  assert.equal(forward.flagsB, 1);
  assert.equal(forward.failRateA, 2 / 3);
  assert.equal(forward.failRateB, 1 / 3);
  assert.equal(forward.commonFailRateA, 2 / 3);
  assert.equal(forward.commonFailRateB, 1 / 3);
  assert.equal(forward.delta, 1 / 3);
  assert.equal(forward.jaccard, 1 / 2);
  assert.equal(reverse.delta, -forward.delta);
  assert.equal(reverse.jaccard, forward.jaccard);
  assert.deepEqual(reverse.counts, {
    bothFlag: 1,
    aOnly: 0,
    bOnly: 1,
    neither: 1,
    missingA: 0,
    missingB: 0,
  });
});

test('keeps coordinate keys distinct at boundary-looking values and applies bin 3 as a flag', () => {
  const result = compareWaferMaps(
    wafer('A', [
      { x: 1, y: 23, bin: 2 },
      { x: 12, y: 3, bin: 3 },
    ]),
    wafer('B', [
      { x: 1, y: 23, bin: 3 },
      { x: 12, y: 3, bin: 2 },
    ]),
  );

  assert.equal(result.validCompared, 2);
  assert.deepEqual(result.counts, {
    bothFlag: 0,
    aOnly: 1,
    bOnly: 1,
    neither: 0,
    missingA: 0,
    missingB: 0,
  });
  assert.equal(result.jaccard, 0);
});

test('rejects invalid comparison scope and die input', () => {
  const base = wafer('A', [{ x: 0, y: 0, bin: 0 }]);
  assert.throws(() => compareWaferMaps(base, wafer('A', [{ x: 0, y: 0, bin: 1 }])));
  assert.throws(() => compareWaferMaps(base, { ...base, waferId: 'B', gridId: 'OTHER' }));
  assert.throws(() =>
    compareWaferMaps(
      { ...base, waferId: 'C', dies: [{ x: 0, y: 0, bin: -1 }] },
      wafer('B', []),
    ),
  );
  for (const gridId of ['', '   ']) {
    assert.throws(() => compareWaferMaps({ ...base, waferId: 'C', gridId }, wafer('B', [])));
    assert.throws(() => compareWaferMaps(base, { ...wafer('B', []), gridId }));
  }
  assert.throws(() =>
    compareWaferMaps(
      {
        ...base,
        waferId: 'C',
        dies: [
          { x: 0, y: 0, bin: 0 },
          { x: 0, y: 0, bin: 1 },
        ],
      },
      wafer('B', []),
    ),
  );
  assert.throws(() => compareWaferMaps({ ...base, waferId: 'C', dies: [{ x: 0, y: 0, bin: Number.NaN }] }, wafer('B', [])));
});
