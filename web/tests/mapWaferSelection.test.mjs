import assert from 'node:assert/strict';
import test from 'node:test';

import { pairKey } from '../src/engineeringAnalysis.ts';
import { groupMapWafers, toggleMapGroup } from '../src/mapWaferGroups.ts';

const row = (lotId, waferId, equipment, recipe, extra = {}) => ({
  lotId, waferId, equipment, recipe, timestamp: '2026-01-01T00:00:00Z', step: 'S', value: 1, ...extra,
});

test('wafer grouping preserves lot and wafer identity', () => {
  const rows = [row('L/1', 'W', 'E1', 'R'), row('L', '1/W', 'E1', 'R')];
  assert.notEqual(pairKey(rows[0]), pairKey(rows[1]));
  assert.deepEqual(groupMapWafers(rows, 'wafer', 'eqp_id').map((group) => group.waferKeys), [[pairKey(rows[0])], [pairKey(rows[1])]]);
});

test('groups by lot and legend while deduplicating repeated observations', () => {
  const rows = [row('L1', 'W1', 'E1', 'R1'), row('L1', 'W1', 'E1', 'R1'), row('L1', 'W2', 'E2', 'R2')];
  assert.deepEqual(groupMapWafers(rows, 'lot', 'eqp_id')[0].waferKeys, [pairKey(rows[0]), pairKey(rows[2])]);
  assert.deepEqual(groupMapWafers(rows, 'legend', 'recipe').map((group) => group.label), ['R1', 'R2']);
  assert.deepEqual(groupMapWafers(rows, 'legend', 'eqp_id').map((group) => group.label), ['E1', 'E2']);
});

test('missing chamber metadata is explicit and present chamber values are used', () => {
  const rows = [row('L1', 'W1', 'E1', 'R1'), row('L1', 'W2', 'E1', 'R1', { chamber: 'C2' })];
  assert.deepEqual(groupMapWafers(rows, 'legend', 'chamber').map((group) => group.label), ['Chamber 미등록', 'C2']);
});

test('toggle returns a new set without mutating the input', () => {
  const checked = new Set(['keep']);
  const added = toggleMapGroup(checked, ['a', 'b'], true);
  const removed = toggleMapGroup(checked, ['keep'], false);
  assert.deepEqual([...checked], ['keep']);
  assert.deepEqual([...added], ['keep', 'a', 'b']);
  assert.deepEqual([...removed], []);
  assert.notEqual(added, checked);
  assert.notEqual(removed, checked);
});
