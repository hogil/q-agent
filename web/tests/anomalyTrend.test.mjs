import assert from 'node:assert/strict';
import test from 'node:test';
import {
  anomalyTrendOption,
  trendSelectionFromTime,
} from '../src/anomalyTrend.ts';
import { makeEquipmentTrace } from '../src/equipmentComparison.ts';

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
    {
      timestamp: '2026-01-01T00:00:00.000Z',
      temperature: 10,
      queue: 1,
      availability: 99,
    },
    {
      timestamp: '2026-01-01T01:00:00.000Z',
      temperature: 11,
      queue: 1.1,
      availability: 98,
    },
    {
      timestamp: '2026-01-01T02:00:00.000Z',
      temperature: 13,
      queue: 1.2,
      availability: 97,
    },
    {
      timestamp: '2026-01-01T03:00:00.000Z',
      temperature: 14,
      queue: 1.3,
      availability: 96,
    },
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

const comparisonData = {
  ...data,
  fab: [
    {
      lotId: 'SYN-LOT-2',
      waferId: 'W01',
      timestamp: data.trend[1].timestamp,
      equipment: 'EQP-2',
      step: 'ETCH',
      recipe: 'RCP-A',
      value: 11,
    },
    {
      lotId: 'SYN-LOT-3',
      waferId: 'W01',
      timestamp: data.trend[1].timestamp,
      equipment: 'EQP-3',
      step: 'CLEAN',
      recipe: 'RCP-A',
      value: 11,
    },
  ],
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
  assert.equal(
    option.series.every((series) => series.type === 'scatter'),
    true,
  );

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

test('keeps the default fleet stable with omitted or empty comparison equipment', () => {
  const expectedNames = [
    'SYN-REF-1',
    'SYN-REF-2',
    'SYN-REF-3',
    'SYN-REF-4',
    'EQP-1 · N',
    'EQP-1 · A',
  ];
  for (const compact of [false, true]) {
    const original = anomalyTrendOption(data, selection, compact);
    const omitted = anomalyTrendOption(comparisonData, selection, compact);
    const empty = anomalyTrendOption(comparisonData, selection, compact, '');

    // Compare serializable options separately from formatter closures.
    assert.deepEqual(
      JSON.parse(JSON.stringify(omitted)),
      JSON.parse(JSON.stringify(original)),
    );
    assert.deepEqual(
      JSON.parse(JSON.stringify(empty)),
      JSON.parse(JSON.stringify(original)),
    );
    assert.deepEqual(omitted.legend.data, expectedNames);
    assert.deepEqual(
      omitted.series.map((series) => series.name),
      expectedNames,
    );
    assert.ok(
      omitted.series
        .slice(0, 4)
        .every((series) => series.data.length === data.trend.length * 6),
    );
    assert.equal(
      omitted.series[4].data.length + omitted.series[5].data.length,
      data.trend.length * 6,
    );
    assert.deepEqual(
      omitted.series.slice(4).map((series) => series.itemStyle.color),
      ['#4878CF', '#D62728'],
    );
    assert.equal(omitted.brush?.brushType, compact ? undefined : 'lineX');
    const point = {
      seriesName: expectedNames[4],
      value: [Date.parse(data.trend[0].timestamp), 10],
    };
    assert.equal(
      omitted.tooltip.formatter(point),
      original.tooltip.formatter(point),
    );
    assert.equal(
      empty.tooltip.formatter(point),
      original.tooltip.formatter(point),
    );
  }
});

for (const [description, equipment] of [
  ['the selected equipment itself', 'EQP-1'],
  ['an unknown equipment ID', 'UNKNOWN-EQP'],
  ['equipment registered only for another Step', 'EQP-3'],
]) {
  test(`omits comparison series and legend entries for ${description}`, () => {
    for (const compact of [false, true]) {
      const original = anomalyTrendOption(comparisonData, selection, compact);
      const option = anomalyTrendOption(
        comparisonData,
        selection,
        compact,
        equipment,
      );
      assert.deepEqual(option.series, original.series);
      assert.deepEqual(option.legend.data, original.legend.data);
      assert.equal(option.yAxis.min, original.yAxis.min);
      assert.equal(option.yAxis.max, original.yAxis.max);
      assert.equal(
        option.series.some((series) => series.name === `${equipment} · B`),
        false,
      );
      assert.equal(option.legend.data.includes(`${equipment} · B`), false);
    }
  });
}

test('renders same-step EQP-2 at exactly the helper timestamps and values', () => {
  const signal = comparisonData.signals[0];
  const expected = makeEquipmentTrace(comparisonData, signal, 'EQP-2').map(
    ({ timestamp, value }) => [Date.parse(timestamp), value],
  );
  assert.equal(expected.length, data.trend.length);

  for (const compact of [false, true]) {
    const original = anomalyTrendOption(comparisonData, selection, compact);
    const option = anomalyTrendOption(
      comparisonData,
      selection,
      compact,
      'EQP-2',
    );
    const peers = option.series.filter((series) => series.name === 'EQP-2 · B');
    assert.equal(peers.length, 1);
    const peer = peers[0];
    assert.equal(peer.type, 'scatter');
    assert.deepEqual(peer.data, expected);
    assert.ok(peer.data.every((point) => point.every(Number.isFinite)));
    assert.ok(
      peer.data.every(
        ([, value]) => value >= option.yAxis.min && value <= option.yAxis.max,
      ),
    );
    assert.deepEqual(
      option.series.filter((series) => series.name !== peer.name),
      original.series,
    );
    assert.deepEqual(option.legend.data, [...original.legend.data, peer.name]);
    assert.ok(
      original.series
        .slice(-2)
        .every((series) => series.itemStyle.color !== peer.itemStyle.color),
    );
    assert.equal(option.brush?.brushType, compact ? undefined : 'lineX');
  }
});

test('switching the selected signal updates B values and axis/tooltip units for every metric', () => {
  const metrics = [
    ['temperature', 'TEMP', '°C'],
    ['queue', 'QUEUE', 'h'],
    ['availability', 'AVAIL', '%'],
  ];
  const scoped = {
    ...comparisonData,
    signals: metrics.map(([metric, item]) => ({
      ...data.signals[0],
      id: `signal-${metric}`,
      metric,
      item,
    })),
  };
  const peerValues = [];

  for (const [index, [, , unit]] of metrics.entries()) {
    const signal = scoped.signals[index];
    const option = anomalyTrendOption(
      scoped,
      { ...selection, signalId: signal.id },
      false,
      'EQP-2',
    );
    const peer = option.series.find((series) => series.name === 'EQP-2 · B');
    assert.ok(peer);
    const expected = makeEquipmentTrace(scoped, signal, 'EQP-2').map(
      ({ timestamp, value }) => [Date.parse(timestamp), value],
    );
    assert.deepEqual(peer.data, expected);
    assert.equal(option.yAxis.name, `Value (${unit})`);
    const tooltip = option.tooltip.formatter({
      seriesName: peer.name,
      value: peer.data[0],
    });
    assert.ok(tooltip.includes(peer.name));
    assert.ok(tooltip.endsWith(`Value ${expected[0][1].toFixed(3)} ${unit}`));
    peerValues.push(peer.data.map(([, value]) => value));
  }

  assert.notDeepEqual(peerValues[0], peerValues[1]);
  assert.notDeepEqual(peerValues[0], peerValues[2]);
  assert.notDeepEqual(peerValues[1], peerValues[2]);
});
