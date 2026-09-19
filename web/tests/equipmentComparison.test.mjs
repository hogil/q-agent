import assert from 'node:assert/strict';
import test from 'node:test';
import {
  availableEquipment,
  compareEquipment,
  makeEquipmentTrace,
} from '../src/equipmentComparison.ts';

const signal = {
  id: 'signal-1',
  title: 'Temperature drift',
  severity: 'high',
  metric: 'temperature',
  equipment: 'EQP-A',
  step: 'ETCH',
  item: 'TEMP',
  recipe: 'RCP-A',
  detectedAt: '2026-01-01T04:00:00.000Z',
  startIndex: 1,
  endIndex: 3,
  description: 'synthetic fixture',
  onsetIndex: 2,
};

const data = {
  signals: [signal],
  trend: [
    { timestamp: '2026-01-01T00:00:00.000Z', temperature: 10, queue: 1, availability: 99 },
    { timestamp: '2026-01-01T01:00:00.000Z', temperature: 11, queue: 1.1, availability: 98 },
    { timestamp: '2026-01-01T02:00:00.000Z', temperature: 13, queue: 1.2, availability: 97 },
    { timestamp: '2026-01-01T03:00:00.000Z', temperature: 14, queue: 1.3, availability: 96 },
  ],
  fab: [
    { lotId: 'L1', waferId: 'W1', timestamp: '2026-01-01T00:00:00.000Z', equipment: 'EQP-A', step: 'ETCH', recipe: 'RCP-A', value: 10 },
    { lotId: 'L1', waferId: 'W2', timestamp: '2026-01-01T00:00:00.000Z', equipment: 'EQP-B', step: 'ETCH', recipe: 'RCP-A', value: 10 },
    { lotId: 'L1', waferId: 'W3', timestamp: '2026-01-01T00:00:00.000Z', equipment: 'OTHER-STEP', step: 'CLEAN', recipe: 'RCP-A', value: 10 },
  ],
  yields: [],
  wip: [],
  downtime: [],
  changes: [],
};

test('derives available equipment from the signal and same-step fab rows', () => {
  assert.deepEqual(availableEquipment(data, signal), ['EQP-A', 'EQP-B']);
});

test('keeps selected equipment values identical to the signal metric trend', () => {
  assert.deepEqual(makeEquipmentTrace(data, signal, 'EQP-A'), [
    { timestamp: data.trend[0].timestamp, value: 10 },
    { timestamp: data.trend[1].timestamp, value: 11 },
    { timestamp: data.trend[2].timestamp, value: 13 },
    { timestamp: data.trend[3].timestamp, value: 14 },
  ]);
});

test('makes a reproducible deterministic peer trace from the pre-onset baseline', () => {
  const first = makeEquipmentTrace(data, signal, 'EQP-B');
  const second = makeEquipmentTrace(data, signal, 'EQP-B');
  assert.deepEqual(first, second);
  assert.equal(first.length, data.trend.length);
  assert.ok(first.every((point) => Number.isFinite(point.value)));
  assert.ok(first.every((point) => point.timestamp === data.trend[first.indexOf(point)].timestamp));
  assert.ok(first.every((point) => point.value > 9.9 && point.value < 11.1));
});

test('returns only the inclusive requested range and aligned numeric summaries', () => {
  const result = compareEquipment(data, signal, 'EQP-A', 'EQP-B', 1, 2);
  assert.equal(result.valid, true);
  assert.equal(result.count, 2);
  assert.deepEqual(result.pairs.map((pair) => pair.timestamp), [
    data.trend[1].timestamp,
    data.trend[2].timestamp,
  ]);
  assert.deepEqual(result.pairs.map((pair) => pair.valueA), [11, 13]);
  assert.ok(result.pairs.every((pair) => Number.isFinite(pair.valueB)));
  assert.ok(Number.isFinite(result.medianA));
  assert.ok(Number.isFinite(result.medianB));
  assert.ok(Number.isFinite(result.deltaMedian));
  assert.ok(Number.isFinite(result.meanA));
  assert.ok(Number.isFinite(result.meanB));
});

test('does not fabricate a delta for same-equipment comparison', () => {
  const result = compareEquipment(data, signal, 'EQP-A', 'EQP-A', 0, 3);
  assert.equal(result.valid, false);
  assert.equal(result.reason, 'same-equipment');
  assert.equal(result.count, 0);
  assert.equal(result.deltaMedian, null);
  assert.deepEqual(result.pairs, []);
});

test('reports empty and unknown comparison inputs as invalid', () => {
  assert.equal(compareEquipment(data, signal, 'EQP-A', 'EQP-B', 2, 1).reason, 'empty-range');
  assert.equal(compareEquipment(data, signal, 'EQP-A', 'UNKNOWN', 0, 3).reason, 'invalid-equipment');
  assert.deepEqual(makeEquipmentTrace(data, signal, 'UNKNOWN'), []);
});
