import { median, quantileSorted } from 'simple-statistics';
import {
  signalMember,
  type AnomalyPattern,
  type EngineeringData,
  type Signal,
  seededNormalNoise,
} from './engineeringData.ts';
import {
  changeTiming,
  pointInSelection,
  selectionTimeWindows,
  type InvestigationSelection,
} from './engineeringAnalysis.ts';
import { makeEquipmentTrace } from './equipmentComparison.ts';

const HOUR = 3600000;
const fleetColors = ['#7EB8DA', '#A8D8A8', '#D4A8D4', '#F0C987'];
export const metricUnits = { temperature: '°C', queue: 'h', availability: '%' };

export type TrendDisplayOptions = {
  members: string[];
  dimOthers: boolean;
  zoomToSelection: boolean;
  showChanges: boolean;
  showLegend?: boolean;
};

export type TrendLegendGroup = {
  member: string;
  color: string;
  points: number[][];
};

export type TrendBoxSummary = TrendLegendGroup & {
  count: number;
  box: [number, number, number, number, number] | null;
  outliers: number[];
};

export function anomalyPattern(signal: Signal): AnomalyPattern {
  return signal.pattern ?? 'drift';
}

function usesEquipmentAxis(signal: Signal) {
  return !signal.legendAxis || signal.legendAxis === 'eqp_id';
}

function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length,
  );
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function inSignalWindow(signal: Signal, index: number) {
  return index >= signal.startIndex && index <= signal.endIndex;
}

function targetPatternValue(
  data: EngineeringData,
  signal: Signal,
  index: number,
  sample: number,
  spread: number,
) {
  const pattern = anomalyPattern(signal);
  const incidentSeed = data.trend[0]?.timestamp ?? '';
  const noise =
    seededNormalNoise(
      `${incidentSeed}:${signal.id}:target:${index}:${sample}`,
    ) * spread * 0.8;
  const active = inSignalWindow(signal, index);
  const progress = clamp(
    (index - signal.startIndex) /
      Math.max(1, signal.endIndex - signal.startIndex),
    0,
    1,
  );
  const normal = data.trend[index][signal.metric] + noise;
  if (pattern === 'drift') {
    const direction = signal.metric === 'availability' ? -1 : 1;
    return normal + (active ? direction * progress * spread * 0.3 : 0);
  }
  if (pattern === 'abrupt_level_shift') {
    return normal + (active ? spread * 0.3 : 0);
  }
  if (pattern === 'spike') {
    const spike = active && sample === 2 && (index - signal.startIndex) % 5 === 2;
    return normal + (spike ? spread * 2.8 : 0);
  }
  if (pattern === 'variance_burst') {
    const burstNoise =
      seededNormalNoise(`${signal.id}:variance:${index}:${sample}`) *
      spread *
      (active ? 1.25 : 0.8);
    return data.trend[index][signal.metric] + burstNoise;
  }
  return normal +
    (active
      ? Math.sin((index - signal.startIndex) * Math.PI * 0.5) * spread * 0.75
      : 0);
}

export function makeTrendFleet(data: EngineeringData, signal: Signal) {
  if (data.trendFleets) return data.trendFleets[signal.id] || [];
  const before = data.trend.slice(0, Math.max(1, signal.onsetIndex));
  const measuredSpread = standardDeviation(
    before.map((row) => row[signal.metric]),
  );
  const spread = Math.max(
    measuredSpread,
    signal.metric === 'temperature'
      ? 0.045
      : signal.metric === 'queue'
        ? 0.025
        : 0.055,
  );
  const members = [
    signalMember(signal),
    ...Array.from({ length: 4 }, (_, i) => `SYN-REF-${i + 1}`),
  ].filter(Boolean);
  return members.map((member, memberIndex) => ({
    member,
    highlighted: memberIndex === 0,
    points: data.trend.flatMap((row, index) =>
      Array.from({ length: 6 }, (_, sample) => {
        const offset = (sample - 2.5) / 8;
        const noise =
          seededNormalNoise(
            `${data.trend[0]?.timestamp ?? ''}:${signal.id}:member:${member}:normal:${index}:${sample}`,
          ) *
          spread *
          0.8;
        return [
          Date.parse(row.timestamp) + offset * HOUR,
          memberIndex === 0
            ? signal.pattern
              ? targetPatternValue(
                  data,
                  signal,
                  index,
                  sample,
                  spread,
                )
              : row[signal.metric] + (sample === 2 ? 0 : noise)
            : row[signal.metric] +
              noise +
              (memberIndex - 2) * spread * 0.18,
        ];
      }),
    ),
  }));
}

export function summarizeTrendSamples(
  data: EngineeringData,
  selection: InvestigationSelection,
) {
  const signal = data.signals.find((row) => row.id === selection.signalId);
  const points = signal
    ? (
        makeTrendFleet(data, signal).find((row) => row.highlighted)?.points ||
        []
      ).filter(
        ([timestamp, value]) =>
          Number.isFinite(timestamp) && Number.isFinite(value),
      )
    : [];
  const stats = (samples: number[][]) => {
    const values = samples.map((point) => point[1]).sort((a, b) => a - b);
    const times = samples.map((point) => point[0]).sort((a, b) => a - b);
    return {
      n: samples.length,
      median: values.length ? median(values) : null,
      iqr:
        values.length >= 3
          ? quantileSorted(values, 0.75) - quantileSorted(values, 0.25)
          : null,
      min: values[0] ?? null,
      max: values.at(-1) ?? null,
      from: times.length ? new Date(times[0]).toISOString() : null,
      to: times.length ? new Date(times.at(-1)!).toISOString() : null,
    };
  };
  const onset = signal
    ? Date.parse(data.trend[signal.onsetIndex]?.timestamp || '')
    : NaN;
  const windows = selectionTimeWindows(data, selection);
  const cutoff = Math.min(onset, ...windows.map(([from]) => from));
  const baseline = stats(points.filter(([timestamp]) => timestamp < cutoff));
  const selected = stats(
    points.filter(([timestamp, value]) =>
      pointInSelection(timestamp, value, data, selection),
    ),
  );
  const comparable = baseline.n >= 3 && selected.n >= 3;
  return {
    baseline,
    selected,
    comparable,
    deltaMedian: comparable ? selected.median! - baseline.median! : null,
  };
}

export function trendSelectionFromTime(
  data: EngineeringData,
  range: [number, number],
) {
  const nearest = (value: number) =>
    data.trend.reduce(
      (best, row, index) =>
        Math.abs(Date.parse(row.timestamp) - value) <
        Math.abs(Date.parse(data.trend[best].timestamp) - value)
          ? index
          : best,
      0,
    );
  const [a, b] = range.map(nearest);
  return { start: Math.min(a, b), end: Math.max(a, b) };
}

function selectedSignal(
  data: EngineeringData,
  selection: InvestigationSelection,
) {
  return data.signals.find((row) => row.id === selection.signalId);
}

function selectionWindow(
  data: EngineeringData,
  selection: InvestigationSelection,
): [number, number] | null {
  if (
    !Array.isArray(data?.trend) ||
    !data.trend.length ||
    !Number.isInteger(selection?.start) ||
    !Number.isInteger(selection?.end)
  ) {
    return null;
  }
  const start = Math.min(selection.start, selection.end);
  const end = Math.max(selection.start, selection.end);
  if (start < 0 || end >= data.trend.length) return null;
  const from = Date.parse(data.trend[start].timestamp);
  const to = Date.parse(data.trend[end].timestamp);
  return Number.isFinite(from) && Number.isFinite(to)
    ? [Math.min(from, to), Math.max(from, to)]
    : null;
}

function pointsInWindow(
  points: number[][],
  data: EngineeringData,
  selection: InvestigationSelection,
) {
  return points.filter(
    ([timestamp, value]) =>
      Number.isFinite(timestamp) &&
      Number.isFinite(value) &&
      pointInSelection(timestamp, value, data, selection),
  );
}

export function trendLegendGroups(
  data: EngineeringData,
  selection: InvestigationSelection,
  comparisonEquipment = '',
): TrendLegendGroup[] {
  const signal = selectedSignal(data, selection);
  const selectedWindow = selectionWindow(data, selection);
  if (!signal || !selectedWindow || !data.trend.length) return [];

  const fleet = makeTrendFleet(data, signal);
  const target = fleet.find((row) => row.highlighted);
  if (!target) return [];
  const groups: TrendLegendGroup[] = [
    {
      member: target.member,
      color: '#4878CF',
      points: pointsInWindow(target.points, data, selection),
    },
    ...fleet
      .filter((row) => !row.highlighted)
      .map((row, index) => ({
        member: row.member,
        color: fleetColors[index],
        points: pointsInWindow(row.points, data, selection),
      })),
  ];

  if (
    usesEquipmentAxis(signal) &&
    comparisonEquipment &&
    comparisonEquipment !== signal.equipment
  ) {
    const peer = makeEquipmentTrace(data, signal, comparisonEquipment);
    if (peer.length) {
      groups.push({
        member: comparisonEquipment,
        color: '#148574',
        points: pointsInWindow(
          peer.map((row) => [Date.parse(row.timestamp), row.value]),
          data,
          selection,
        ),
      });
    }
  }
  return groups;
}

export function trendBoxSummaries(
  data: EngineeringData,
  selection: InvestigationSelection,
  comparisonEquipment = '',
): TrendBoxSummary[] {
  return trendLegendGroups(data, selection, comparisonEquipment).map(
    (group) => {
      const values = group.points
        .map(([, value]) => value)
        .filter((value) => Number.isFinite(value))
        .sort((left, right) => left - right);
      if (!values.length) {
        return { ...group, count: 0, box: null, outliers: [] };
      }

      const q1 = quantileSorted(values, 0.25);
      const med = quantileSorted(values, 0.5);
      const q3 = quantileSorted(values, 0.75);
      const iqr = q3 - q1;
      const lowerFence = q1 - 1.5 * iqr;
      const upperFence = q3 + 1.5 * iqr;
      const outliers = values.filter(
        (value) => value < lowerFence || value > upperFence,
      );
      const observed = values.filter(
        (value) => value >= lowerFence && value <= upperFence,
      );
      const box: [number, number, number, number, number] = [
        observed[0] ?? values[0],
        q1,
        med,
        q3,
        observed.at(-1) ?? values.at(-1)!,
      ];
      return { ...group, count: values.length, box, outliers };
    },
  );
}

function displayPoint(
  point: number[],
  member: string,
  display: TrendDisplayOptions | undefined,
  data: EngineeringData,
  selection: InvestigationSelection,
) {
  if (!display) return point;
  const hasFilter =
    display.members.length > 0 || selection.rangeSelected !== false;
  const selected =
    (display.members.length === 0 || display.members.includes(member)) &&
    pointInSelection(point[0], point[1], data, selection);
  return {
    value: point,
    itemStyle: {
      opacity: !hasFilter
        ? 0.75
        : selected
          ? 0.95
          : display.dimOthers
            ? 0.1
            : 0.75,
    },
  };
}

export function trendBoxPlotOption(
  data: EngineeringData,
  selection: InvestigationSelection,
  comparisonEquipment = '',
  display: TrendDisplayOptions,
) {
  const signal = selectedSignal(data, selection);
  const summaries = trendBoxSummaries(data, selection, comparisonEquipment);
  const unit = signal ? metricUnits[signal.metric] : '';
  const selected = new Set(display.members);
  const opacity = (member: string) =>
    display.dimOthers && selected.size > 0 && !selected.has(member) ? 0.12 : 1;
  const categories = summaries.map((group) => group.member);
  const categoryLegend = summaries.map((group) => ({
    name: group.member,
    icon: 'roundRect',
    itemStyle: {
      color: group.color,
      borderColor: group.color,
      opacity: opacity(group.member),
    },
  }));
  const categoryRich = Object.fromEntries(
    summaries.map((group, index) => [
      `swatch${index}`,
      {
        color: group.color,
        fontSize: 10,
        fontWeight: 'bold',
        opacity: opacity(group.member),
      },
    ]),
  );
  const boxData = summaries.map((group) => ({
    name: group.member,
    kind: 'box' as const,
    value: group.box,
    group: group.member,
    count: group.count,
    outliers: group.outliers,
    box: group.box,
    itemStyle: {
      color: `${group.color}55`,
      borderColor: group.color,
      borderWidth: 1.2,
      opacity: opacity(group.member),
    },
  }));
  const outlierData = summaries.flatMap((group, categoryIndex) =>
    group.outliers.map((value) => ({
      name: group.member,
      kind: 'outlier' as const,
      value: [categoryIndex, value],
      group: group.member,
      count: group.count,
      itemStyle: { color: group.color, opacity: opacity(group.member) },
    })),
  );
  return {
    animation: false,
    grid: {
      left: 49,
      right: display.showLegend === false ? 12 : 109,
      top: 17,
      bottom: 43,
    },
    legend: {
      show: display.showLegend !== false,
      type: 'scroll',
      right: 0,
      top: 2,
      bottom: 2,
      width: 100,
      data: categoryLegend,
      selectedMode: false,
    },
    tooltip: {
      trigger: 'item',
      renderMode: 'richText',
      confine: true,
      textStyle: { fontSize: 10 },
      rich: {
        title: { fontWeight: 'bold' },
        label: { color: '#65706b' },
      },
      formatter: (params: {
        data?: {
          kind?: 'box' | 'outlier';
          group?: string;
          count?: number;
          box?: [number, number, number, number, number] | null;
          outliers?: number[];
        };
        value?: number[] | null;
      }) => {
        const group = params.data?.group ?? '';
        const count = params.data?.count ?? 0;
        const format = (value: number | undefined) =>
          Number.isFinite(value) ? value!.toFixed(3) : '-';
        if (params.data?.kind === 'outlier') {
          const raw = Array.isArray(params.value) ? params.value[1] : NaN;
          return `{title|${group}} · N ${count}\nRaw ${format(raw)} ${unit}`;
        }
        const box = params.data?.box;
        return `{title|${group}} · N ${count} · ${unit}\nLow ${format(box?.[0])} / Q1 ${format(box?.[1])}\nMedian ${format(box?.[2])}\nQ3 ${format(box?.[3])} / High ${format(box?.[4])}\nOutliers ${params.data?.outliers?.length ?? 0}`;
      },
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        fontSize: 9,
        interval: 0,
        hideOverlap: true,
        rotate: 25,
        rich: categoryRich,
        formatter: (value: string) => {
          const index = categories.indexOf(value);
          return index < 0 ? value : `{swatch${index}|●} ${value}`;
        },
      },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: `Value (${unit})`,
      nameLocation: 'middle',
      nameGap: 36,
      scale: true,
      splitNumber: 3,
      axisLabel: {
        fontSize: 9,
        formatter: (value: number) => Number(value.toFixed(2)).toString(),
      },
      splitLine: { lineStyle: { color: '#edf0f0' } },
    },
    series: [
      { name: 'Distribution', type: 'boxplot', data: boxData },
      { name: 'Outliers', type: 'scatter', data: outlierData, symbolSize: 7 },
    ],
  };
}

// Display contract: anomaly-detection/src/data/image_renderer.py, render_overlay_display.
// Only the synthetic Q-Agent fixture is rendered; no experiment/company samples are copied.
export function anomalyTrendOption(
  data: EngineeringData,
  selection: InvestigationSelection,
  compact = false,
  comparisonEquipment = '',
  display?: TrendDisplayOptions,
) {
  const signal = data.signals.find((row) => row.id === selection.signalId);
  if (!signal || !data.trend.length) {
    return { animation: false, series: [] };
  }
  const fleet = makeTrendFleet(data, signal);
  const onsetIndex = Math.min(signal.onsetIndex, data.trend.length - 1);
  const onset = Date.parse(data.trend[onsetIndex].timestamp);
  const references = fleet.filter((row) => !row.highlighted);
  const target = fleet.find((row) => row.highlighted);
  const peer =
    usesEquipmentAxis(signal) && comparisonEquipment !== signal.equipment
      ? makeEquipmentTrace(data, signal, comparisonEquipment)
      : [];
  if (!target || !references.length) return { animation: false, series: [] };
  const baseline = median(
    references.flatMap((row) => row.points.map((point) => point[1])),
  );
  const values = [
    ...fleet.flatMap((row) => row.points.map((point) => point[1])),
    ...peer.map((row) => row.value),
  ];
  const low = Math.min(...values),
    high = Math.max(...values);
  const margin = Math.max((high - low) * 0.15, 0.05);
  const targetMember = signalMember(signal) || target.member;
  const normal = `${targetMember} · N`;
  const abnormal = `${targetMember} · A`;
  const option = {
    animation: false,
    textStyle: {
      fontFamily: 'Segoe UI, Malgun Gothic, sans-serif',
      fontSize: 10,
    },
    grid: { left: 49, right: 109, top: 17, bottom: 33 },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 0,
      top: 2,
      bottom: 2,
      width: 100,
      pageIconSize: 9,
      pageTextStyle: { fontSize: 9 },
      scrollDataIndex: references.length,
      itemWidth: 7,
      itemHeight: 7,
      itemGap: 7,
      selectedMode: false,
      textStyle: { fontSize: 9, color: '#65706b' },
      data: [
        ...references.map((row) => row.member),
        normal,
        abnormal,
        ...(peer.length ? [`${comparisonEquipment} · B`] : []),
      ],
    },
    tooltip: {
      renderMode: 'richText',
      formatter: (p: { seriesName: string; value: number[] }) =>
        `${p.seriesName}\n${new Date(p.value[0]).toISOString().slice(5, 19).replace('T', ' ')} UTC\nValue ${p.value[1].toFixed(3)} ${metricUnits[signal.metric]}`,
    },
    brush: compact
      ? undefined
      : {
          xAxisIndex: 0,
          yAxisIndex: 0,
          brushType: 'rect',
          brushMode: 'single',
          transformable: true,
          brushStyle: {
            color: 'rgba(54,127,153,.08)',
            borderColor: '#367f99',
            borderWidth: 1.5,
          },
          inBrush: { colorAlpha: 1 },
          outOfBrush: { colorAlpha: 1 },
          throttleType: 'debounce',
          throttleDelay: 100,
        },
    xAxis: {
      type: 'time',
      name: 'Time (UTC)',
      nameLocation: 'middle',
      nameGap: 21,
      splitNumber: 4,
      min: Date.parse(data.trend[0].timestamp) - HOUR * 0.5,
      max: Date.parse(data.trend.at(-1)!.timestamp) + HOUR * 0.5,
      axisLabel: {
        fontSize: 9,
        hideOverlap: true,
        formatter: (value: number) =>
          new Date(value).toISOString().slice(11, 16),
      },
      axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: '#edf0f0' } },
    },
    yAxis: {
      type: 'value',
      name: `Value (${metricUnits[signal.metric]})`,
      nameLocation: 'middle',
      nameGap: 36,
      min: Number((low - margin).toFixed(2)),
      max: Number((high + margin).toFixed(2)),
      splitNumber: 3,
      axisLabel: {
        fontSize: 9,
        formatter: (value: number) => Number(value.toFixed(2)).toString(),
      },
      splitLine: { lineStyle: { color: '#edf0f0' } },
    },
    series: [
      ...(peer.length
        ? [
            {
              name: `${comparisonEquipment} · B`,
              type: 'scatter',
              symbolSize: 6,
              data: peer.map((row) => [Date.parse(row.timestamp), row.value]),
              itemStyle: {
                color: '#148574',
                borderColor: '#fff',
                borderWidth: 0.5,
              },
              z: 4,
            },
          ]
        : []),
      ...references.map((row, index) => ({
        name: row.member,
        type: 'scatter',
        symbolSize: 3.5,
        data: row.points,
        itemStyle: { color: fleetColors[index], opacity: 0.4 },
        z: 1,
      })),
      {
        name: normal,
        type: 'scatter',
        symbolSize: 4.7,
        data: target.points.filter(([x]) => x < onset),
        itemStyle: {
          color: '#4878CF',
          opacity: 0.65,
          borderColor: '#fff',
          borderWidth: 0.3,
        },
        z: 2,
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(54,127,153,.065)' },
          data: [],
        },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          data: [
            {
              yAxis: baseline,
              lineStyle: {
                color: '#333333',
                width: 1,
                type: 'solid',
                opacity: 0.7,
              },
            },
            {
              xAxis: onset,
              lineStyle: { color: '#b8b8b8', width: 1, type: 'dashed' },
            },
            ...(display?.showChanges === false
              ? []
              : changeTiming(data, signal, selection).map((event) => ({
                  xAxis: Date.parse(event.timestamp),
                  lineStyle: { color: '#a8b2ad', width: 0.7, type: 'dotted' },
                  label: {
                    show: true,
                    formatter: event.kind === 'recipe' ? 'Recipe' : 'MES',
                    position: 'insideEndTop',
                    fontSize: 8,
                    color: '#8a958d',
                  },
                }))),
          ],
        },
      },
      {
        name: abnormal,
        type: 'scatter',
        symbolSize: 4.7,
        data: target.points.filter(([x]) => x >= onset),
        itemStyle: {
          color: '#D62728',
          opacity: 0.75,
          borderColor: '#fff',
          borderWidth: 0.3,
        },
        z: 3,
      },
    ],
  };

  if (display) {
    const window =
      selection.rangeSelected === false
        ? null
        : selectionWindow(data, selection);
    const pointData = (points: number[][], member: string) =>
      points.map((point) =>
        displayPoint(point, member, display, data, selection),
      );
    const xAxis = { ...option.xAxis };
    const yAxis = { ...option.yAxis };
    if (display.zoomToSelection && window) {
      const padding = Math.max((window[1] - window[0]) * 0.05, HOUR * 0.5);
      xAxis.min = window[0] - padding;
      xAxis.max = window[1] + padding;
      if (selection.valueRange) {
        const margin = Math.max(
          (selection.valueRange[1] - selection.valueRange[0]) * 0.08,
          0.01,
        );
        yAxis.min = selection.valueRange[0] - margin;
        yAxis.max = selection.valueRange[1] + margin;
      }
    }
    return {
      ...option,
      xAxis,
      yAxis,
      grid: { ...option.grid, right: display.showLegend === false ? 12 : 109 },
      legend: { ...option.legend, show: display.showLegend !== false },
      series: option.series.map((series) => ({
        ...series,
        data: pointData(
          series.data,
          series.name === normal || series.name === abnormal
            ? targetMember
            : series.name === `${comparisonEquipment} · B`
              ? comparisonEquipment
              : series.name,
        ),
      })),
    };
  }
  return option;
}
