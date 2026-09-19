import test from 'node:test';
import assert from 'node:assert/strict';
import {
  correlationSummary,
  defaultSelection,
  parseSelection,
  engineeringReference,
  parseEngineeringReference,
  parsePairKey,
  pairKey,
} from '../src/engineeringAnalysis.ts';

const data = {
  signals: [
    { id: 'signal-1', equipment: 'SYN-EQP-01', startIndex: 2, endIndex: 8 },
  ],
  trend: Array.from({ length: 24 }, () => ({})),
  fab: [{ recipe: 'SYN-RCP-A' }],
};
test('Pearson reports positive and inverse associations, not a causal verdict', () => {
  assert.equal(
    correlationSummary([
      { value: 1, yieldPct: 10 },
      { value: 2, yieldPct: 20 },
      { value: 3, yieldPct: 30 },
    ]).r,
    1,
  );
  assert.equal(
    correlationSummary([
      { value: 1, yieldPct: 30 },
      { value: 2, yieldPct: 20 },
      { value: 3, yieldPct: 10 },
    ]).r,
    -1,
  );
  assert.equal('verdict' in correlationSummary([]), false);
});

test('restores only composite wafer selections registered in the current scope', () => {
  const scoped = { fab: [{ lotId: 'LOT-A', waferId: 'W01' }] };
  const selected = pairKey(scoped.fab[0]);
  assert.equal(parsePairKey(selected, scoped), selected);
  for (const value of ['LOT-B/W01', 'LOT-A/W02', null, {}, 3])
    assert.equal(parsePairKey(value, scoped), '');
});
test('insufficient, invalid and constant inputs do not become misleading zero correlation', () => {
  for (const rows of [
    [],
    [{ value: 1, yieldPct: 20 }],
    Array(3).fill({ value: 1, yieldPct: 20 }),
  ])
    assert.equal(correlationSummary(rows).r, null);
  const result = correlationSummary([
    { value: Infinity, yieldPct: 20 },
    { value: 1, yieldPct: -1 },
    { value: 2, yieldPct: 101 },
  ]);
  assert.equal(result.n, 0);
  assert.equal(result.invalid, 3);
  assert.equal(result.meanYield, null);
});

test('wafer selection keys distinguish IDs containing separators', () => {
  const first = { lotId: 'LOT/A', waferId: 'W01' };
  const second = { lotId: 'LOT', waferId: 'A/W01' };
  assert.notEqual(pairKey(first), pairKey(second));
  assert.equal(parsePairKey(pairKey(first), { fab: [second] }), '');
});
test('investigation selection validates scope IDs and ordered bounded windows', () => {
  const selection = defaultSelection(data);
  assert.deepEqual(parseSelection(selection, data), selection);
  for (const patch of [
    { start: -1 },
    { end: 24 },
    { start: 9, end: 8 },
    { start: 1.2 },
    { equipment: 'OTHER' },
    { recipe: 'OTHER' },
    { signalId: 'other' },
    { maxLagDays: 31 },
  ])
    assert.equal(parseSelection({ ...selection, ...patch }, data), null);
});
test('source references preserve a validated analysis snapshot without trusting arbitrary JSON', () => {
  const selection = { ...defaultSelection(data), recipe: 'SYN-RCP-A' };
  for (const kind of ['trend', 'corr'])
    assert.deepEqual(
      parseEngineeringReference(engineeringReference(kind, selection), data),
      selection,
    );
  for (const invalid of [
    'engineering:corr:bad',
    'engineering:corr:{}',
    'engineering:corr:[]',
    'unexpected:[]',
  ])
    assert.equal(parseEngineeringReference(invalid, data), null);
});
