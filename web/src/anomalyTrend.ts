import { median, quantileSorted } from 'simple-statistics';
import type { EngineeringData, Signal } from './engineeringData';
import type { InvestigationSelection } from './engineeringAnalysis';
import { changeTiming } from './engineeringAnalysis.ts';
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

export function makeTrendFleet(data: EngineeringData, signal: Signal) {
  const before = data.trend.slice(0, Math.max(1, signal.onsetIndex));
  const baseline = median(before.map((row) => row[signal.metric]));
  const spread = signal.metric === 'temperature' ? 0.22 : 0.16;
  const members = [
    signal.equipment,
    ...Array.from({ length: 4 }, (_, i) => `SYN-REF-${i + 1}`),
  ];
  return members.map((member, memberIndex) => ({
    member,
    highlighted: memberIndex === 0,
    points: data.trend.flatMap((row, index) =>
      Array.from({ length: 6 }, (_, sample) => {
        const offset = (sample - 2.5) / 8;
        const noise = Math.sin(
          (index + 1) * 13.7 + sample * 7.3 + memberIndex * 2.1,
        );
        return [
          Date.parse(row.timestamp) + offset * HOUR,
          memberIndex === 0
            ? row[signal.metric] + (sample === 2 ? 0 : noise * spread * 0.8)
            : baseline +
              noise * spread +
              Math.cos(index * 1.3 + memberIndex) * spread * 0.5,
        ];
      }),
    ),
  }));
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
  window: [number, number] | null,
  valueRange?: [number, number],
) {
  if (!window) return [];
  return points.filter(
    ([timestamp, value]) =>
      Number.isFinite(timestamp) &&
      Number.isFinite(value) &&
      timestamp >= window[0] &&
      timestamp <= window[1] &&
      (!valueRange || (value >= valueRange[0] && value <= valueRange[1])),
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
  const window: [number, number] =
    selection.rangeSelected === false ? [-Infinity, Infinity] : selectedWindow;
  const valueRange =
    selection.rangeSelected === false ? undefined : selection.valueRange;

  const fleet = makeTrendFleet(data, signal);
  const target = fleet.find((row) => row.highlighted);
  if (!target) return [];
  const groups: TrendLegendGroup[] = [
    {
      member: target.member,
      color: '#4878CF',
      points: pointsInWindow(target.points, window, valueRange),
    },
    ...fleet
      .filter((row) => !row.highlighted)
      .map((row, index) => ({
        member: row.member,
        color: fleetColors[index],
        points: pointsInWindow(row.points, window, valueRange),
      })),
  ];

  if (comparisonEquipment && comparisonEquipment !== signal.equipment) {
    const peer = makeEquipmentTrace(data, signal, comparisonEquipment);
    if (peer.length) {
      groups.push({
        member: comparisonEquipment,
        color: '#148574',
        points: pointsInWindow(
          peer.map((row) => [Date.parse(row.timestamp), row.value]),
          window,
          valueRange,
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
  window: [number, number] | null,
  valueRange?: [number, number],
) {
  if (!display) return point;
  const hasFilter = display.members.length > 0 || window !== null;
  const selected =
    (display.members.length === 0 || display.members.includes(member)) &&
    (window === null || (point[0] >= window[0] && point[0] <= window[1])) &&
    (!valueRange || (point[1] >= valueRange[0] && point[1] <= valueRange[1]));
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
      data: categories,
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
      axisLabel: { fontSize: 9, interval: 0, hideOverlap: true, rotate: 25 },
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
    comparisonEquipment !== signal.equipment
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
  const normal = `${signal.equipment} · N`;
  const abnormal = `${signal.equipment} · A`;
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
          data:
            selection.rangeSelected === false
              ? []
              : [
                  [
                    {
                      xAxis: Date.parse(data.trend[selection.start].timestamp),
                      ...(selection.valueRange
                        ? { yAxis: selection.valueRange[0] }
                        : {}),
                    },
                    {
                      xAxis: Date.parse(data.trend[selection.end].timestamp),
                      ...(selection.valueRange
                        ? { yAxis: selection.valueRange[1] }
                        : {}),
                    },
                  ],
                ],
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
    const valueRange = window ? selection.valueRange : undefined;
    const pointData = (points: number[][], member: string) =>
      points.map((point) =>
        displayPoint(point, member, display, window, valueRange),
      );
    const xAxis = { ...option.xAxis };
    const yAxis = { ...option.yAxis };
    if (display.zoomToSelection && window) {
      const padding = Math.max((window[1] - window[0]) * 0.05, HOUR * 0.5);
      xAxis.min = window[0] - padding;
      xAxis.max = window[1] + padding;
      if (valueRange) {
        const margin = Math.max((valueRange[1] - valueRange[0]) * 0.08, 0.01);
        yAxis.min = valueRange[0] - margin;
        yAxis.max = valueRange[1] + margin;
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
            ? signal.equipment
            : series.name === `${comparisonEquipment} · B`
              ? comparisonEquipment
              : series.name,
        ),
      })),
    };
  }
  return option;
}
