import assert from 'node:assert/strict';
import test from 'node:test';
import {
  anomalyTrendOption,
  anomalyPattern,
  makeTrendFleet,
  trendBoxPlotOption,
  trendBoxSummaries,
  trendLegendGroups,
  trendSelectionFromTime,
} from '../src/anomalyTrend.ts';
import { makeEquipmentTrace } from '../src/equipmentComparison.ts';
import { defaultSelection, changeTiming } from '../src/engineeringAnalysis.ts';

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

test('renders each synthetic anomaly pattern as a distinct finite target trace', () => {
  const patterns = [
    'abrupt_level_shift',
    'spike',
    'variance_burst',
    'periodic_pattern',
  ];
  const patternData = {
    ...data,
    signals: patterns.map((pattern, index) => ({
      ...data.signals[0],
      id: `pattern-${index}`,
      pattern,
      onsetIndex: 1,
      startIndex: 1,
      endIndex: 3,
    })),
  };
  const traces = patternData.signals.map((signal) => {
    assert.equal(anomalyPattern(signal), signal.pattern);
    const fleet = makeTrendFleet(patternData, signal);
    assert.equal(fleet[0].points.length, data.trend.length * 6);
    assert.ok(fleet[0].points.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y)));
    return fleet[0].points.map(([, value]) => Number(value.toFixed(6)));
  });
  for (let left = 0; left < traces.length; left += 1) {
    for (let right = left + 1; right < traces.length; right += 1) {
      assert.notDeepEqual(traces[left], traces[right]);
    }
  }
});

test('keeps the original fixture signals on their legacy raw trend path', () => {
  const fleet = makeTrendFleet(data, data.signals[0]);
  const target = fleet[0].points;
  assert.equal(target.length, data.trend.length * 6);
  assert.equal(target[2][1], data.trend[0].temperature);
  assert.equal(anomalyPattern(data.signals[0]), 'drift');
});

test('initial trend has no time shading, zoom or legend emphasis and includes all raw samples', () => {
  const initial = defaultSelection(comparisonData);
  const display = {
    members: [],
    dimOthers: true,
    zoomToSelection: true,
    showChanges: true,
  };
  const option = anomalyTrendOption(
    comparisonData,
    initial,
    false,
    'EQP-2',
    display,
  );
  assert.ok(
    option.series.every((series) =>
      series.data.every((point) => point.itemStyle.opacity === 0.75),
    ),
  );
  assert.deepEqual(
    option.series.find((series) => series.markArea).markArea.data,
    [],
  );
  assert.equal(option.xAxis.min, Date.parse(data.trend[0].timestamp) - 1800000);
  assert.equal(option.brush.transformable, true);
  const groups = trendLegendGroups(comparisonData, initial, 'EQP-2');
  assert.ok(
    groups
      .slice(0, 5)
      .every((group) => group.points.length === data.trend.length * 6),
  );
  assert.equal(groups.at(-1).points.length, data.trend.length);
  const boxes = trendBoxPlotOption(comparisonData, initial, 'EQP-2', display)
    .series[0].data;
  assert.ok(boxes.every((box) => box.itemStyle.opacity === 1));
  assert.equal(boxes[0].count, data.trend.length * 6);
});

test('a time range applies to every legend when no member is singled out', () => {
  const option = anomalyTrendOption(
    comparisonData,
    { ...selection, rangeSelected: true },
    false,
    'EQP-2',
    {
      members: [],
      dimOthers: true,
      zoomToSelection: false,
      showChanges: true,
    },
  );
  const from = Date.parse(data.trend[selection.start].timestamp);
  const to = Date.parse(data.trend[selection.end].timestamp);
  for (const series of option.series)
    for (const point of series.data)
      assert.equal(
        point.itemStyle.opacity,
        point.value[0] >= from && point.value[0] <= to ? 0.95 : 0.1,
      );
});

test('legend-only focus does not impose a hidden time range', () => {
  const option = anomalyTrendOption(
    comparisonData,
    defaultSelection(comparisonData),
    false,
    '',
    {
      members: ['SYN-REF-2'],
      dimOthers: true,
      zoomToSelection: false,
      showChanges: true,
    },
  );
  for (const series of option.series)
    assert.ok(
      series.data.every(
        (point) =>
          point.itemStyle.opacity ===
          (series.name === 'SYN-REF-2' ? 0.95 : 0.1),
      ),
    );
});

test('constrains the trend legend to one scrolling column in short panels', () => {
  const { legend } = anomalyTrendOption(
    comparisonData,
    selection,
    false,
    'EQP-2',
  );
  assert.equal(legend.type, 'scroll');
  assert.equal(legend.orient, 'vertical');
  assert.equal(legend.width, 100);
  assert.equal(legend.top, 2);
  assert.equal(legend.bottom, 2);
  assert.equal(legend.scrollDataIndex, 4);
});

test('change markers use the same equipment, recipe and time extent as the change strip', () => {
  const event = {
    id: 'change',
    equipment: 'EQP-1',
    recipe: 'RCP-A',
    kind: 'recipe',
    timestamp: data.trend[1].timestamp,
    before: 'v1',
    after: 'v2',
    sourceRef: 'synthetic://recipe',
  };
  const fixture = {
    ...data,
    changes: [
      event,
      { ...event, id: 'wrong-recipe', recipe: 'RCP-B' },
      { ...event, id: 'other-equipment', equipment: 'EQP-2' },
      { ...event, id: 'outside', timestamp: '2025-12-31T23:00:00.000Z' },
    ],
  };
  const option = anomalyTrendOption(fixture, selection);
  const normal = option.series.find((series) => series.name === 'EQP-1 · N');
  const markers = normal.markLine.data.filter((marker) => marker.label?.show);
  assert.equal(markers.length, 1);
  assert.equal(markers[0].xAxis, Date.parse(event.timestamp));
  assert.ok(
    changeTiming(fixture, fixture.signals[0], defaultSelection(fixture)).every(
      (event) => !event.inSelection,
    ),
  );
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
    assert.equal(omitted.brush?.brushType, compact ? undefined : 'rect');
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
    assert.equal(option.brush?.brushType, compact ? undefined : 'rect');
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

test('groups exact inclusive trend samples by member and adds only a valid different peer', () => {
  const groups = trendLegendGroups(comparisonData, selection, 'EQP-2');
  assert.deepEqual(
    groups.map((group) => group.member),
    ['EQP-1', 'SYN-REF-1', 'SYN-REF-2', 'SYN-REF-3', 'SYN-REF-4', 'EQP-2'],
  );
  assert.equal(groups[0].color, '#4878CF');
  assert.deepEqual(
    groups.slice(1, 5).map((group) => group.color),
    ['#7EB8DA', '#A8D8A8', '#D4A8D4', '#F0C987'],
  );
  assert.equal(groups.at(-1).color, '#148574');
  for (const group of groups) {
    assert.ok(
      group.points.every(
        ([timestamp]) =>
          timestamp >= Date.parse(data.trend[selection.start].timestamp) &&
          timestamp <= Date.parse(data.trend[selection.end].timestamp),
      ),
    );
  }
  const fleet = makeTrendFleet(data, data.signals[0]);
  assert.deepEqual(
    groups[1].points,
    fleet[1].points.filter(
      ([timestamp]) =>
        timestamp >= Date.parse(data.trend[selection.start].timestamp) &&
        timestamp <= Date.parse(data.trend[selection.end].timestamp),
    ),
  );
  assert.equal(trendLegendGroups(comparisonData, selection, 'EQP-1').length, 5);
  assert.equal(
    trendLegendGroups(comparisonData, selection, 'UNKNOWN-EQP').length,
    5,
  );
});

test('rectangular selection uses the same X and Y bounds for point emphasis, counts and boxes', () => {
  const xy = { ...selection, rangeSelected: true, valueRange: [10.9, 11.2] };
  const display = {
    members: [],
    dimOthers: true,
    zoomToSelection: true,
    showChanges: true,
  };
  const option = anomalyTrendOption(
    comparisonData,
    xy,
    false,
    'EQP-2',
    display,
  );
  assert.equal(option.brush.brushType, 'rect');
  assert.equal(option.brush.yAxisIndex, 0);
  const [start, end] = [
    Date.parse(data.trend[xy.start].timestamp),
    Date.parse(data.trend[xy.end].timestamp),
  ];
  const points = option.series.flatMap((series) => series.data);
  const expected = points.filter(
    ({ value: [x, y] }) =>
      x >= start && x <= end && y >= xy.valueRange[0] && y <= xy.valueRange[1],
  );
  assert.ok(expected.length > 0 && expected.length < points.length);
  assert.equal(
    points.filter((p) => p.itemStyle.opacity === 0.95).length,
    expected.length,
  );
  assert.equal(
    trendLegendGroups(comparisonData, xy, 'EQP-2').reduce(
      (n, g) => n + g.points.length,
      0,
    ),
    expected.length,
  );
  assert.equal(
    trendBoxSummaries(comparisonData, xy, 'EQP-2').reduce(
      (n, g) => n + g.count,
      0,
    ),
    expected.length,
  );
  assert.ok(option.yAxis.min < xy.valueRange[0] && option.yAxis.min > 10);
  assert.ok(option.yAxis.max > xy.valueRange[1] && option.yAxis.max < 12);
  assert.deepEqual(option.series.find((s) => s.markArea).markArea.data, []);
  const empty = trendBoxSummaries(
    comparisonData,
    { ...xy, valueRange: [100, 200] },
    'EQP-2',
  );
  assert.ok(empty.every((g) => g.count === 0 && g.box === null));
});

test('disjoint rectangles keep union highlighting without persistent boxes or selected gaps', () => {
  const t1 = Date.parse(data.trend[1].timestamp);
  const t3 = Date.parse(data.trend[3].timestamp);
  const disjoint = {
    ...selection,
    rangeSelected: true,
    valueRange: [10.9, 14.1],
    regions: [
      [
        [t1 - 300000, t1 + 300000],
        [10.9, 11.2],
      ],
      [
        [t3 - 300000, t3 + 300000],
        [13.9, 14.1],
      ],
    ],
  };
  const display = {
    members: [],
    dimOthers: true,
    zoomToSelection: false,
    showChanges: true,
  };
  const option = anomalyTrendOption(
    comparisonData,
    disjoint,
    false,
    'EQP-2',
    display,
  );
  const points = option.series.flatMap((series) => series.data);
  const selectedPoints = points.filter(
    (point) =>
      point.itemStyle.opacity === 0.95 &&
      ((point.value[0] >= t1 - 300000 &&
        point.value[0] <= t1 + 300000 &&
        point.value[1] >= 10.9 &&
        point.value[1] <= 11.2) ||
        (point.value[0] >= t3 - 300000 &&
          point.value[0] <= t3 + 300000 &&
          point.value[1] >= 13.9 &&
          point.value[1] <= 14.1)),
  );
  assert.ok(selectedPoints.length > 0);
  assert.ok(
    points.every(
      (point) =>
        point.value[0] < t1 + 300000 ||
        point.value[0] > t3 - 300000 ||
        point.itemStyle.opacity !== 0.95,
    ),
  );
  assert.equal(
    trendLegendGroups(comparisonData, disjoint, 'EQP-2').reduce(
      (count, group) => count + group.points.length,
      0,
    ),
    selectedPoints.length,
  );
  assert.equal(
    trendBoxSummaries(comparisonData, disjoint, 'EQP-2').reduce(
      (count, group) => count + group.count,
      0,
    ),
    selectedPoints.length,
  );
  const markArea = option.series.find((series) => series.markArea).markArea
    .data;
  assert.deepEqual(markArea, []);
});

test('box summaries keep empty and singleton groups finite and exact', () => {
  const singletonSelection = { ...selection, start: 1, end: 1 };
  const summaries = trendBoxSummaries(
    comparisonData,
    singletonSelection,
    'EQP-2',
  );
  const target = summaries.find((group) => group.member === 'EQP-1');
  const peer = summaries.find((group) => group.member === 'EQP-2');
  assert.equal(target.count, 0);
  assert.equal(target.box, null);
  assert.deepEqual(target.outliers, []);
  assert.equal(peer.count, 1);
  const peerValue = trendLegendGroups(
    comparisonData,
    singletonSelection,
    'EQP-2',
  ).find((group) => group.member === 'EQP-2').points[0][1];
  assert.deepEqual(peer.box, [
    peerValue,
    peerValue,
    peerValue,
    peerValue,
    peerValue,
  ]);
  assert.deepEqual(peer.outliers, []);
  assert.ok(
    summaries.every(
      (group) =>
        group.box === null ||
        group.box.every((value) => Number.isFinite(value)),
    ),
  );
});

test('display options dim at point level, zoom without dropping data, and suppress only changes', () => {
  const display = {
    members: ['EQP-1'],
    dimOthers: true,
    zoomToSelection: true,
    showChanges: false,
    showLegend: false,
  };
  const option = anomalyTrendOption(data, selection, false, '', display);
  const from = Date.parse(data.trend[selection.start].timestamp);
  const to = Date.parse(data.trend[selection.end].timestamp);
  assert.equal(option.legend.show, false);
  assert.equal(option.grid.right, 12);
  assert.equal(option.xAxis.min, from - 1800000);
  assert.equal(option.xAxis.max, to + 1800000);
  const normal = option.series.find((series) => series.name === 'EQP-1 · N');
  const reference = option.series.find((series) => series.name === 'SYN-REF-1');
  assert.ok(normal.data.every((point) => point.itemStyle));
  assert.ok(reference.data.every((point) => point.itemStyle.opacity === 0.1));
  assert.ok(
    normal.data.some(
      (point) =>
        point.itemStyle.opacity === 0.95 &&
        point.value[0] >= from &&
        point.value[0] <= to,
    ),
  );
  assert.ok(normal.data.some((point) => point.itemStyle.opacity === 0.1));
  const normalMarkers = normal.markLine.data.filter(
    (marker) => marker.label?.show,
  );
  assert.deepEqual(normalMarkers, []);
  assert.ok(normal.markLine.data.some((marker) => marker.yAxis !== undefined));
  assert.ok(normal.markLine.data.some((marker) => marker.xAxis !== undefined));
});

test('boxplot keeps all groups, names each datum, and reports raw unit/group/count', () => {
  const display = {
    members: ['EQP-1', 'EQP-2'],
    dimOthers: true,
    zoomToSelection: false,
    showChanges: true,
    showLegend: false,
  };
  const option = trendBoxPlotOption(
    comparisonData,
    selection,
    'EQP-2',
    display,
  );
  const boxes = option.series.find((series) => series.type === 'boxplot');
  assert.deepEqual(
    boxes.data.map((datum) => datum.name),
    option.xAxis.data,
  );
  assert.deepEqual(
    option.legend.data.map((item) => item.name),
    option.xAxis.data,
  );
  assert.deepEqual(
    option.legend.data.map((item) => item.itemStyle.color),
    boxes.data.map((datum) => datum.itemStyle.borderColor),
  );
  assert.ok(
    option.xAxis.axisLabel
      .formatter(option.xAxis.data[0])
      .includes('{swatch0|'),
  );
  assert.equal(option.legend.show, false);
  assert.equal(option.grid.right, 12);
  const reference = boxes.data.find((datum) => datum.name === 'SYN-REF-1');
  assert.equal(reference.itemStyle.opacity, 0.12);
  const peer = boxes.data.find((datum) => datum.name === 'EQP-2');
  assert.equal(peer.itemStyle.opacity, 1);
  const boxTooltip = option.tooltip.formatter({
    data: {
      kind: 'box',
      group: peer.name,
      count: peer.count,
      box: peer.value,
      outliers: [],
    },
    value: peer.value,
  });
  assert.ok(boxTooltip.includes('EQP-2'));
  assert.ok(boxTooltip.includes('Low'));
  assert.ok(boxTooltip.includes('Q1'));
  assert.ok(boxTooltip.includes('Median'));
  assert.ok(boxTooltip.includes('Q3'));
  assert.ok(boxTooltip.includes('High'));
  assert.ok(boxTooltip.includes('N 3'));
  assert.equal(option.tooltip.confine, true);
  assert.equal(option.yAxis.scale, true);
  const rawTooltip = option.tooltip.formatter({
    data: { kind: 'outlier', group: peer.name, count: peer.count },
    value: [0, 11],
  });
  assert.ok(rawTooltip.includes('Raw 11.000 °C'));
});

test('Tukey boxes use selected sample quartiles and keep extreme samples as outliers', () => {
  const fixture = {
    ...data,
    trend: [
      ...data.trend.map((row) => ({ ...row, temperature: 11 })),
      {
        ...data.trend[0],
        timestamp: '2026-01-01T04:00:00.000Z',
        temperature: 200,
      },
    ],
  };
  const [group] = trendBoxSummaries(fixture, {
    ...selection,
    start: 0,
    end: 4,
  });
  const values = group.points.map(([, value]) => value).sort((a, b) => a - b);
  assert.equal(values.length, 24);
  // simple-statistics uses linearly interpolated (R type 7) quartiles.
  assert.equal(group.box[1], values[5] + 0.75 * (values[6] - values[5]));
  assert.equal(group.box[2], values[11] + 0.5 * (values[12] - values[11]));
  assert.equal(group.box[3], values[17] + 0.25 * (values[18] - values[17]));
  assert.ok(group.outliers.some((value) => value > 100));
  assert.ok(group.box[4] < 20);
  assert.ok(values.includes(group.box[0]));
  assert.ok(values.includes(group.box[4]));
});

test('legend focus preserves samples and axes and turning dimming off restores context opacity', () => {
  const plain = anomalyTrendOption(comparisonData, selection, false, 'EQP-2');
  for (const dimOthers of [true, false]) {
    const option = anomalyTrendOption(
      comparisonData,
      selection,
      false,
      'EQP-2',
      {
        members: ['SYN-REF-2'],
        dimOthers,
        zoomToSelection: false,
        showChanges: true,
      },
    );
    assert.equal(JSON.stringify(option.xAxis), JSON.stringify(plain.xAxis));
    assert.equal(JSON.stringify(option.yAxis), JSON.stringify(plain.yAxis));
    assert.deepEqual(
      option.series.map((series) => series.data.map((point) => point.value)),
      plain.series.map((series) => series.data),
    );
    const target = option.series.find((series) => series.name === 'EQP-1 · A');
    assert.ok(
      target.data.every(
        (point) => point.itemStyle.opacity === (dimOthers ? 0.1 : 0.75),
      ),
    );
  }
});
