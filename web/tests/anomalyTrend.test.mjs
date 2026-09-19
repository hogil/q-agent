import assert from 'node:assert/strict';
import test from 'node:test';
import {
  anomalyTrendOption,
  trendSelectionFromTime,
} from '../src/anomalyTrend.ts';

const data = {
  signals: [
    {
      id: 'signal-1',
      title: 'Temperature drift',
      severity: 'high',
      metric: 'temperature',
      equipment: 'EQP-1',
      step: 'ETCH',
      item: 'TEMP',
      recipe: 'RCP-A',
      detectedAt: '2026-01-01T04:00:00.000Z',
      startIndex: 1,
      endIndex: 3,
      description: 'fixture',
      onsetIndex: 2,
    },
  ],
  trend: [
    { timestamp: '2026-01-01T00:00:00.000Z', temperature: 10, queue: 1, availability: 99 },
    { timestamp: '2026-01-01T01:00:00.000Z', temperature: 11, queue: 1.1, availability: 98 },
    { timestamp: '2026-01-01T02:00:00.000Z', temperature: 13, queue: 1.2, availability: 97 },
    { timestamp: '2026-01-01T03:00:00.000Z', temperature: 14, queue: 1.3, availability: 96 },
  ],
  fab: [],
  yields: [],
  wip: [],
  downtime: [],
  changes: [],
};

const selection = {
  signalId: 'signal-1',
  start: 1,
  end: 3,
  equipment: 'EQP-1',
  recipe: 'RCP-A',
  maxLagDays: 14,
};

test('maps a brushed datetime range to ordered nearest trend indexes', () => {
  const range = [
    Date.parse('2026-01-01T02:42:00.000Z'),
    Date.parse('2026-01-01T00:18:00.000Z'),
  ];
  assert.deepEqual(trendSelectionFromTime(data, range), { start: 0, end: 3 });
});

test('builds a datetime scatter overlay with split target colors and median baseline', () => {
  const option = anomalyTrendOption(data, selection);
  assert.equal(option.xAxis.type, 'time');
  assert.equal(option.yAxis.type, 'value');
  assert.equal(option.xAxis.min, Date.parse(data.trend[0].timestamp) - 1800000);
  assert.equal(option.series.every((series) => series.type === 'scatter'), true);

  const normal = option.series.find((series) => series.name === 'EQP-1 · N');
  const abnormal = option.series.find((series) => series.name === 'EQP-1 · A');
  assert.equal(normal.itemStyle.color, '#4878CF');
  assert.equal(abnormal.itemStyle.color, '#D62728');
  assert.equal(
    normal.data.every(
      (point) => point[0] < Date.parse(data.trend[2].timestamp),
    ),
    true,
  );
  assert.equal(
    abnormal.data.every(
      (point) => point[0] >= Date.parse(data.trend[2].timestamp),
    ),
    true,
  );
  assert.equal(
    normal.markLine.data.some((line) => line.yAxis !== undefined),
    true,
  );
  assert.equal(
    normal.markLine.data.some(
      (line) => line.xAxis === Date.parse(data.trend[2].timestamp),
    ),
    true,
  );
});
