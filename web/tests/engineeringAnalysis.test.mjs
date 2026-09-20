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
  selectFabRows,
  summarizeSignalWindow,
  changeTiming,
} from '../src/engineeringAnalysis.ts';

const data = {
  signals: [
    {
      id: 'signal-1',
      step: 'ETCH',
      equipment: 'SYN-EQP-01',
      startIndex: 2,
      endIndex: 8,
    },
  ],
  trend: Array.from({ length: 24 }, () => ({})),
  fab: [{ recipe: 'SYN-RCP-A' }],
};

const signalWindowData = {
  signals: [
    {
      id: 'temperature-signal',
      metric: 'temperature',
      equipment: 'EQP-A',
      item: 'TEMP-A',
      onsetIndex: 4,
    },
    {
      id: 'queue-signal',
      metric: 'queue',
      equipment: 'EQP-A',
      item: 'QUEUE-A',
      onsetIndex: 4,
    },
  ],
  trend: [
    {
      timestamp: '2026-01-01T00:00:00.000Z',
      temperature: 10,
      queue: 100,
      availability: 90,
    },
    {
      timestamp: '2026-01-01T01:00:00.000Z',
      temperature: 11,
      queue: 101,
      availability: 91,
    },
    {
      timestamp: '2026-01-01T02:00:00.000Z',
      temperature: 12,
      queue: 102,
      availability: 92,
    },
    {
      timestamp: '2026-01-01T03:00:00.000Z',
      temperature: 13,
      queue: 103,
      availability: 93,
    },
    {
      timestamp: '2026-01-01T04:00:00.000Z',
      temperature: 14,
      queue: 104,
      availability: 94,
    },
    {
      timestamp: '2026-01-01T05:00:00.000Z',
      temperature: 15,
      queue: 105,
      availability: 95,
    },
    {
      timestamp: '2026-01-01T06:00:00.000Z',
      temperature: 16,
      queue: 106,
      availability: 96,
    },
    {
      timestamp: 'not-a-timestamp',
      temperature: 17,
      queue: 107,
      availability: 97,
    },
    {
      timestamp: '2026-01-01T08:00:00.000Z',
      temperature: Number.NaN,
      queue: 108,
      availability: 98,
    },
    {
      timestamp: '2026-01-01T09:00:00.000Z',
      temperature: 19,
      queue: 109,
      availability: 99,
    },
  ],
  fab: [{ value: 9999 }],
  yields: [],
  wip: [],
  downtime: [],
  changes: [
    {
      id: 'change-b',
      equipment: 'EQP-A',
      recipe: 'RCP-A',
      kind: 'recipe',
      timestamp: '2026-01-01T05:00:00.000Z',
      before: 'A',
      after: 'B',
      sourceRef: 'S2',
    },
    {
      id: 'change-a',
      equipment: 'EQP-A',
      recipe: '',
      kind: 'system',
      timestamp: '2026-01-01T04:00:00.000Z',
      before: 'A',
      after: 'B',
      sourceRef: 'S1',
    },
    {
      id: 'other-equipment',
      equipment: 'EQP-B',
      recipe: 'RCP-A',
      kind: 'recipe',
      timestamp: '2026-01-01T05:30:00.000Z',
      before: 'A',
      after: 'B',
      sourceRef: 'S3',
    },
    {
      id: 'outside-before',
      equipment: 'EQP-A',
      recipe: 'RCP-A',
      kind: 'recipe',
      timestamp: '2025-12-31T23:00:00.000Z',
      before: 'A',
      after: 'B',
      sourceRef: 'S4',
    },
    {
      id: 'outside-after',
      equipment: 'EQP-A',
      recipe: 'RCP-A',
      kind: 'recipe',
      timestamp: '2026-01-01T10:00:00.000Z',
      before: 'A',
      after: 'B',
      sourceRef: 'S5',
    },
    {
      id: 'wrong-recipe',
      equipment: 'EQP-A',
      recipe: 'RCP-B',
      kind: 'recipe',
      timestamp: '2026-01-01T06:00:00.000Z',
      before: 'A',
      after: 'B',
      sourceRef: 'S6',
    },
  ],
};

const windowSelection = {
  signalId: 'temperature-signal',
  start: 4,
  end: 6,
  equipment: 'COUNTERFACTUAL-EQP',
  recipe: 'RCP-A',
  maxLagDays: 14,
};

test('map cohort uses inclusive Fab scope without depending on EDS presence or lag', () => {
  const fab = [
    {
      lotId: 'L1',
      waferId: 'W1',
      timestamp: '2026-01-01T02:00:00Z',
      equipment: 'E1',
      step: 'ETCH',
      recipe: 'R1',
    },
    {
      lotId: 'L1',
      waferId: 'W2',
      timestamp: '2026-01-01T04:00:00Z',
      equipment: 'E1',
      step: 'ETCH',
      recipe: 'R1',
    },
    {
      lotId: 'L2',
      waferId: 'W1',
      timestamp: '2026-01-01T03:00:00Z',
      equipment: 'E2',
      step: 'ETCH',
      recipe: 'R2',
    },
    {
      lotId: 'L1',
      waferId: 'W3',
      timestamp: '2026-01-01T05:00:00Z',
      equipment: 'E1',
      step: 'ETCH',
      recipe: 'R1',
    },
  ];
  const scoped = {
    signals: [{ id: 'signal-1', step: 'ETCH' }],
    fab: [...fab, fab[0]],
    yields: [],
    trend: [
      { timestamp: '2026-01-01T02:00:00Z' },
      { timestamp: '2026-01-01T04:00:00Z' },
    ],
  };
  const selection = {
    signalId: 'signal-1',
    start: 0,
    end: 1,
    equipment: '',
    recipe: '',
    maxLagDays: 0,
  };
  assert.deepEqual(selectFabRows(scoped, selection), fab.slice(0, 3));
  assert.deepEqual(
    selectFabRows(scoped, { ...selection, equipment: 'E1' }),
    fab.slice(0, 2),
  );
  assert.deepEqual(
    selectFabRows(scoped, { ...selection, recipe: 'R2', maxLagDays: 30 }),
    [fab[2]],
  );
  assert.deepEqual(selectFabRows(scoped, { ...selection, start: 1 }), [fab[1]]);
  assert.deepEqual(selectFabRows(scoped, { ...selection, end: 9 }), []);
});

test('filters the selected Step before dedup so a later other-Step record cannot shadow it', () => {
  const eligible = {
    lotId: 'L1',
    waferId: 'W1',
    timestamp: '2026-01-01T02:00:00Z',
    equipment: 'E2',
    step: 'ETCH',
    recipe: 'R1',
    value: 10,
  };
  const laterSameStep = {
    ...eligible,
    timestamp: '2026-01-01T03:00:00Z',
    value: 11,
  };
  const otherLot = { ...eligible, lotId: 'L2' };
  const otherStep = {
    ...eligible,
    timestamp: '2026-01-01T04:00:00Z',
    step: 'CLEAN',
    value: 99,
  };
  const scoped = {
    signals: [
      { id: 'signal-etch', step: 'ETCH', equipment: 'E1' },
      { id: 'signal-clean', step: 'CLEAN', equipment: 'E1' },
    ],
    fab: [eligible, laterSameStep, otherLot, otherStep],
    trend: [
      { timestamp: '2026-01-01T02:00:00Z' },
      { timestamp: '2026-01-01T04:00:00Z' },
    ],
  };
  const selection = {
    signalId: 'signal-etch',
    start: 0,
    end: 1,
    equipment: 'E2',
    recipe: 'R1',
    maxLagDays: 0,
  };
  assert.deepEqual(selectFabRows(scoped, selection), [laterSameStep, otherLot]);
  assert.deepEqual(
    selectFabRows(scoped, { ...selection, signalId: 'signal-clean' }),
    [otherStep],
  );
  assert.deepEqual(selectFabRows(scoped, { ...selection, equipment: '' }), [
    laterSameStep,
    otherLot,
  ]);
});

test('returns an empty cohort when the selected signal is missing or unknown', () => {
  const row = {
    lotId: 'L1',
    waferId: 'W1',
    timestamp: '2026-01-01T02:00:00Z',
    equipment: 'E1',
    step: 'ETCH',
    recipe: 'R1',
  };
  const scoped = {
    signals: [{ id: 'signal-1', step: 'ETCH' }],
    fab: [row],
    trend: [{ timestamp: row.timestamp }],
  };
  const selection = {
    signalId: 'signal-1',
    start: 0,
    end: 0,
    equipment: '',
    recipe: '',
    maxLagDays: 0,
  };
  assert.deepEqual(selectFabRows(scoped, selection), [row]);
  for (const signalId of ['', 'unknown-signal', undefined, null]) {
    assert.deepEqual(selectFabRows(scoped, { ...selection, signalId }), []);
  }
  const { signalId, ...missingSignal } = selection;
  assert.deepEqual(selectFabRows(scoped, missingSignal), []);
  assert.deepEqual(selectFabRows({ ...scoped, signals: [] }, selection), []);
});

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

test('summarizes strict pre-onset baseline and inclusive selected boundaries', () => {
  const result = summarizeSignalWindow(signalWindowData, windowSelection);
  assert.deepEqual(result.baseline, {
    n: 4,
    median: 11.5,
    min: 10,
    max: 13,
    from: signalWindowData.trend[0].timestamp,
    to: signalWindowData.trend[3].timestamp,
  });
  assert.deepEqual(result.selected, {
    n: 3,
    median: 15,
    min: 14,
    max: 16,
    from: signalWindowData.trend[4].timestamp,
    to: signalWindowData.trend[6].timestamp,
  });
  assert.equal(result.deltaMedian, 3.5);
  assert.equal(result.comparable, true);
  assert.equal(result.reason, null);
  assert.equal(result.onsetAt, signalWindowData.trend[4].timestamp);
  assert.equal(result.metric, 'temperature');
  assert.equal(result.equipment, 'EQP-A');
  assert.equal(result.item, 'TEMP-A');
});

test('keeps valid counts while rejecting missing, NaN, and invalid timestamps', () => {
  const result = summarizeSignalWindow(signalWindowData, {
    ...windowSelection,
    start: 5,
    end: 9,
  });
  assert.equal(result.baseline.n, 4);
  assert.equal(result.selected.n, 3);
  assert.equal(result.selected.max, 19);
  assert.equal(result.comparable, true);

  const insufficient = summarizeSignalWindow(signalWindowData, {
    ...windowSelection,
    start: 2,
    end: 4,
  });
  assert.equal(insufficient.baseline.n, 2);
  assert.equal(insufficient.selected.n, 3);
  assert.equal(insufficient.deltaMedian, null);
  assert.equal(insufficient.reason, 'insufficient-baseline');
});

test('uses only the signal metric and does not fabricate a zero or use Fab values', () => {
  const queue = summarizeSignalWindow(signalWindowData, {
    ...windowSelection,
    signalId: 'queue-signal',
    start: 4,
    end: 6,
  });
  assert.equal(queue.metric, 'queue');
  assert.equal(queue.baseline.median, 101.5);
  assert.equal(queue.selected.median, 105);
  assert.equal(queue.deltaMedian, 3.5);

  const empty = summarizeSignalWindow(signalWindowData, {
    ...windowSelection,
    start: 0,
    end: 0,
  });
  assert.equal(empty.baseline.n, 0);
  assert.equal(empty.selected.n, 1);
  assert.equal(empty.deltaMedian, null);
  assert.equal(empty.reason, 'insufficient-baseline');

  const invalid = summarizeSignalWindow(signalWindowData, {
    ...windowSelection,
    start: -1,
  });
  assert.equal(invalid.reason, 'invalid-range');
  assert.equal(invalid.comparable, false);
  assert.equal(invalid.baseline.n, 0);
  assert.equal(invalid.selected.n, 0);
});

test('change timing applies equipment, optional recipe, recorded extent, and inclusive time filters', () => {
  const changes = changeTiming(
    signalWindowData,
    signalWindowData.signals[0],
    windowSelection,
  );
  assert.deepEqual(
    changes.map((event) => event.id),
    ['change-a', 'change-b'],
  );
  assert.deepEqual(
    changes.map((event) => event.minutesFromOnset),
    [0, 60],
  );
  assert.deepEqual(
    changes.map((event) => event.inSelection),
    [true, true],
  );
  assert.equal(changes[0].sourceRef, 'S1');

  const recipeFiltered = changeTiming(
    signalWindowData,
    signalWindowData.signals[0],
    {
      ...windowSelection,
      recipe: 'RCP-B',
    },
  );
  assert.deepEqual(
    recipeFiltered.map((event) => event.id),
    ['change-a', 'wrong-recipe'],
  );
  assert.deepEqual(
    recipeFiltered.map((event) => event.inSelection),
    [true, true],
  );
});

test('change timing makes no counterfactual equipment or causal assumption', () => {
  const changes = changeTiming(signalWindowData, signalWindowData.signals[0], {
    ...windowSelection,
    equipment: 'EQP-B',
    start: 6,
    end: 6,
  });
  assert.deepEqual(
    changes.map((event) => event.id),
    ['change-a', 'change-b'],
  );
  assert.equal('causal' in changes[0], false);
  assert.equal(changes[0].inSelection, false);
  assert.equal(changes[1].inSelection, false);
});
