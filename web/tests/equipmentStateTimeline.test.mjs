import assert from 'node:assert/strict';
import test from 'node:test';
import {
  defaultTimelineRange,
  formatUtcInput,
  normalizeEquipmentStates,
  parseUtcInput,
} from '../src/equipmentStateData.ts';

const rows = [
  {
    equipment: 'EQP-1',
    start: '2026-01-01T00:00:00Z',
    end: '2026-01-01T02:00:00Z',
    state: 'RUN',
    code: 'R1',
  },
  {
    equipment: 'EQP-1',
    start: '2026-01-01T03:00:00Z',
    end: '2026-01-01T04:00:00Z',
    state: 'DOWN',
    code: 'D1',
  },
  {
    equipment: 'EQP-1',
    start: '2026-01-01T05:00:00Z',
    end: '2026-01-01T06:00:00Z',
    state: 'PM',
    code: 'P1',
  },
  {
    equipment: 'EQP-2',
    start: '2026-01-01T00:00:00Z',
    end: '2026-01-02T00:00:00Z',
    state: 'RUN',
    code: 'OTHER',
  },
];

test('defaults to seven days ending at the selected anomaly anchor', () => {
  const range = defaultTimelineRange(rows, 'EQP-1', '2026-01-08T12:00:00Z');
  assert.deepEqual(range, {
    from: Date.parse('2026-01-05T00:00:00Z'),
    to: Date.parse('2026-01-12T00:00:00Z'),
  });
  assert.equal(
    formatUtcInput(parseUtcInput('2026-01-08T12:00')),
    '2026-01-08T12:00',
  );
});

test('renders unknown gaps and never double-counts overlapping caller intervals', () => {
  const range = {
    from: Date.parse('2026-01-01T00:00:00Z'),
    to: Date.parse('2026-01-01T06:00:00Z'),
  };
  const segments = normalizeEquipmentStates(
    [
      ...rows,
      {
        equipment: 'EQP-1',
        start: '2026-01-01T01:00:00Z',
        end: '2026-01-01T01:30:00Z',
        state: 'IDLE',
        code: 'LATE',
      },
    ],
    'EQP-1',
    range,
  );

  assert.equal(segments[0].state, 'RUN');
  assert.ok(segments.some((segment) => segment.state === 'UNKNOWN'));
  assert.equal(
    segments.reduce((total, segment) => total + segment.end - segment.start, 0),
    range.to - range.from,
  );
  for (let index = 1; index < segments.length; index += 1) {
    assert.ok(segments[index - 1].end <= segments[index].start);
  }
  assert.deepEqual(
    segments
      .filter((segment) => segment.state !== 'UNKNOWN')
      .map((segment) => segment.state),
    ['RUN', 'IDLE', 'RUN', 'DOWN', 'PM'],
  );
});
