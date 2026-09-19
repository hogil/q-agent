import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DataZoomComponent,
  BrushComponent,
  LegendComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { waferData, type Die } from './waferMaps';
export { waferData, type Die } from './waferMaps';

echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DataZoomComponent,
  BrushComponent,
  LegendComponent,
  CanvasRenderer,
]);

type ChartProps = {
  option: echarts.EChartsCoreOption;
  onSelect?: (value: any) => void;
  onRange?: (range: [number, number]) => void;
  label: string;
  className?: string;
};
export function Chart({
  option,
  onSelect,
  onRange,
  label,
  className = '',
}: ChartProps) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.EChartsType | null>(null);
  const handler = useRef(onSelect);
  handler.current = onSelect;
  const rangeHandler = useRef(onRange);
  rangeHandler.current = onRange;
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, {
      renderer: 'canvas',
    });
    instance.current = chart;
    chart.on('click', (params) => handler.current?.(params));
    chart.on('brushEnd', (params: any) => {
      const range = params.areas?.[0]?.coordRange;
      if (
        Array.isArray(range) &&
        range.length === 2 &&
        range.every(Number.isFinite)
      ) {
        rangeHandler.current?.([Math.round(range[0]), Math.round(range[1])]);
      }
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    const chart = instance.current;
    if (!chart) return;
    chart.setOption(
      {
        ...option,
        ...(matchMedia('(prefers-reduced-motion: reduce)').matches
          ? { animation: false }
          : {}),
      },
      { notMerge: true },
    );
    if (rangeHandler.current)
      chart.dispatchAction({
        type: 'takeGlobalCursor',
        key: 'brush',
        brushOption: { brushType: 'lineX', brushMode: 'single' },
      });
  }, [option]);
  return (
    <div
      ref={element}
      className={`chart ${className}`}
      role="img"
      aria-label={label}
    />
  );
}

export function trendData(seed: number, days: number, metric: string) {
  return Array.from({ length: days }, (_, i) => {
    const date = new Date(Date.UTC(2026, 0, 8 - days + i));
    const drift =
      i >= days - 9 && i <= days - 4
        ? (Math.sin((i - days + 10) * 0.52) + 0.4) * 1.9
        : 0;
    const noise = Math.sin(i * 2.3 + seed) * 0.32 + Math.cos(i * 0.8) * 0.19;
    const value =
      metric === 'temperature'
        ? 65 + drift + noise
        : 1.1 + (drift + noise + 0.6) * 0.6;
    return {
      date: date.toISOString().slice(5, 10),
      value: Number(value.toFixed(2)),
      baseline: metric === 'temperature' ? 65 : 1.1,
    };
  });
}

export function TrendChart({
  seed,
  days = 30,
  metric = 'temperature',
  compact = false,
  onSelect,
}: {
  seed: number;
  days?: number;
  metric?: string;
  compact?: boolean;
  onSelect?: (label: string) => void;
}) {
  const option = useMemo(() => {
    const data = trendData(seed, days, metric);
    const temperature = metric === 'temperature';
    return {
      animationDuration: 450,
      textStyle: {
        fontFamily: 'Segoe UI, Malgun Gothic, sans-serif',
        fontSize: 10,
      },
      grid: { left: 43, right: 18, top: 20, bottom: compact ? 31 : 65 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff',
        borderColor: '#e2e5e9',
        textStyle: { color: '#333', fontSize: 12 },
        valueFormatter: (value: number) =>
          `${value} ${temperature ? '°C' : '%'}`,
      },
      xAxis: {
        type: 'category',
        data: data.map((row) => row.date),
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#e3e6ea' } },
        axisTick: { show: false },
        axisLabel: { color: '#869097', interval: Math.floor(days / 5) },
      },
      yAxis: {
        type: 'value',
        min: temperature ? 63 : 0,
        max: temperature ? 70 : 4,
        splitNumber: 4,
        axisLabel: { color: '#869097' },
        splitLine: { lineStyle: { color: '#edf0f2', type: 'dashed' } },
      },
      dataZoom: compact
        ? []
        : [
            {
              type: 'slider',
              bottom: 4,
              height: 18,
              borderColor: 'transparent',
              fillerColor: '#e0ece7',
              handleStyle: { color: '#397763' },
              textStyle: { color: '#76817e' },
            },
            { type: 'inside' },
          ],
      series: [
        {
          name: temperature ? '공정 온도 · 합성' : '불량률 · 합성',
          type: 'line',
          data: data.map((row) => row.value),
          smooth: 0.3,
          symbolSize: 5,
          showSymbol: !compact,
          itemStyle: { color: '#477f9c' },
          lineStyle: { width: 2.4 },
          markArea: {
            silent: true,
            itemStyle: { color: 'rgba(226,173,87,.10)' },
            data: [
              [
                { xAxis: data[Math.max(0, days - 9)].date },
                { xAxis: data[days - 4].date },
              ],
            ],
          },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: false },
            lineStyle: { color: '#cb9c60', type: 'dashed', width: 1 },
            data: [{ yAxis: temperature ? 67 : 2.5 }],
          },
        },
        {
          name: '기준값 · 합성',
          type: 'line',
          data: data.map((row) => row.baseline),
          symbol: 'none',
          lineStyle: { color: '#8d9dab', width: 1.4, type: 'dashed' },
        },
      ],
    };
  }, [seed, days, metric, compact]);
  return (
    <Chart
      option={option}
      label="합성 시계열 Trend 차트"
      className={compact ? 'compact-chart' : 'trend-chart'}
      onSelect={(p) =>
        onSelect?.(
          `${p.name} · ${p.value}${metric === 'temperature' ? '°C' : '%'}`,
        )
      }
    />
  );
}

const binColors = ['#e5e9e8', '#87b7aa', '#397f72', '#e4b46b', '#c47669'];

export function WaferChart({
  seed,
  compact = false,
  filter = 'all',
  onSelect,
}: {
  seed: number;
  compact?: boolean;
  filter?: string;
  onSelect?: (die: Die) => void;
}) {
  const option = useMemo(() => {
    const dice = waferData(seed);
    return {
      animation: false,
      grid: { left: '5%', right: '5%', top: '5%', bottom: '5%' },
      xAxis: { type: 'value', min: -18, max: 18, show: false },
      yAxis: { type: 'value', min: -18, max: 18, show: false },
      tooltip: {
        formatter: (p: any) =>
          `Die (${p.value[0]}, ${p.value[1]})<br/>${p.value[2] >= 3 ? 'Edge flag' : 'Reference'} · 합성`,
        textStyle: { fontSize: 12 },
      },
      series: [
        {
          type: 'scatter',
          symbol: 'rect',
          symbolSize: compact ? 5.5 : 9,
          data: dice.map((die) => ({
            value: [die.x, die.y, die.bin],
            itemStyle: {
              color:
                filter === 'flagged' && die.bin < 3
                  ? '#f1f3f2'
                  : binColors[die.bin],
            },
          })),
          emphasis: {
            scale: 1.5,
            itemStyle: { borderColor: '#183d35', borderWidth: 1 },
          },
        },
      ],
    };
  }, [seed, compact, filter]);
  return (
    <Chart
      option={option}
      label="합성 Wafer die map"
      className={compact ? 'wafer-chart compact-wafer' : 'wafer-chart'}
      onSelect={(p) =>
        onSelect?.({ x: p.value[0], y: p.value[1], bin: p.value[2] })
      }
    />
  );
}

export function OverlayChart({
  seed,
  opacity,
  showA,
  showB,
}: {
  seed: number;
  opacity: number;
  showA: boolean;
  showB: boolean;
}) {
  const option = useMemo(
    () => ({
      animation: false,
      grid: { left: '5%', right: '5%', top: '5%', bottom: '5%' },
      xAxis: { type: 'value', min: -18, max: 18, show: false },
      yAxis: { type: 'value', min: -18, max: 18, show: false },
      tooltip: {
        formatter: (p: any) =>
          `${p.seriesName} · Die (${p.value[0]}, ${p.value[1]})`,
      },
      series: [
        {
          name: 'Reference grid',
          type: 'scatter',
          symbol: 'rect',
          symbolSize: 9,
          silent: true,
          data: waferData(seed).map((d) => [d.x, d.y]),
          itemStyle: { color: '#e8eced' },
        },
        {
          name: 'Inspection A · 합성',
          type: 'scatter',
          symbol: 'rect',
          symbolSize: 9,
          data: showA
            ? waferData(seed)
                .filter((d) => d.bin >= 3)
                .map((d) => [d.x, d.y])
            : [],
          itemStyle: { color: '#528ca9', opacity: 0.9 },
        },
        {
          name: 'Inspection B · 합성',
          type: 'scatter',
          symbol: 'circle',
          symbolSize: 7,
          data: showB
            ? waferData(seed + 7)
                .filter((d) => d.bin >= 2)
                .map((d) => [d.x, d.y])
            : [],
          itemStyle: { color: '#cc846e', opacity: opacity / 100 },
        },
      ],
    }),
    [seed, opacity, showA, showB],
  );
  return (
    <Chart
      option={option}
      className="wafer-chart overlay-chart"
      label="동일 합성 좌표의 Wafer Overlay map"
    />
  );
}
