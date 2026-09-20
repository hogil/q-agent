import { median } from 'simple-statistics';
import type { EngineeringData, Signal } from './engineeringData';
import type { InvestigationSelection } from './engineeringAnalysis';
import { changeTiming } from './engineeringAnalysis.ts';
import { makeEquipmentTrace } from './equipmentComparison.ts';

const HOUR = 3600000;
const fleetColors = ['#7EB8DA', '#A8D8A8', '#D4A8D4', '#F0C987'];
export const metricUnits = { temperature: '°C', queue: 'h', availability: '%' };

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

// Display contract: anomaly-detection/src/data/image_renderer.py, render_overlay_display.
// Only the synthetic Q-Agent fixture is rendered; no experiment/company samples are copied.
export function anomalyTrendOption(
  data: EngineeringData,
  selection: InvestigationSelection,
  compact = false,
  comparisonEquipment = '',
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
  return {
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
          brushType: 'lineX',
          brushMode: 'single',
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
          data: [
            [
              { xAxis: Date.parse(data.trend[selection.start].timestamp) },
              { xAxis: Date.parse(data.trend[selection.end].timestamp) },
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
            ...changeTiming(data, signal, selection).map((event) => ({
              xAxis: Date.parse(event.timestamp),
              lineStyle: { color: '#a8b2ad', width: 0.7, type: 'dotted' },
              label: {
                show: true,
                formatter: event.kind === 'recipe' ? 'Recipe' : 'MES',
                position: 'insideEndTop',
                fontSize: 8,
                color: '#8a958d',
              },
            })),
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
}
