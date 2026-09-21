import { useMemo, useState } from 'react';
import { X } from 'lucide-react';
import type { EChartsCoreOption } from 'echarts/core';
import type { CustomSeriesRenderItem } from 'echarts';
import { Chart } from './charts';
import { waferCoordinateText, type DieRegion } from './waferMaps';
import type { WaferGeometry } from './api';
import {
  makeMetrologyFixture,
  metricColor,
  metricStats,
  METRIC_CONFIG,
  interpolateWaferGrid,
  selectMeasuredRegion,
  waferOutline,
  type MetrologyMetric,
} from './metrologyMap';
import './metrologyMap.css';

export type MetrologyMapProps = {
  lotId: string;
  waferId: string;
  metric: MetrologyMetric;
  geometry?: WaferGeometry;
};

function formatValue(value: number | null, metric: MetrologyMetric): string {
  if (value === null) return '-';
  return value.toFixed(metric === 'cd' ? 1 : 2);
}

function tooltipText(
  item: any,
  metric: MetrologyMetric,
  geometry?: WaferGeometry,
): string {
  const data = item?.data;
  const values = Array.isArray(data) ? data : data?.value;
  if (!Array.isArray(values)) return '';
  const measured = data?.kind === 'measured';
  const kind = measured ? 'Measured' : 'Linear estimate';
  return `${kind}\n${waferCoordinateText(values[0], values[1], geometry, 'normalized')}\n${METRIC_CONFIG[metric].label}: ${formatValue(values[2], metric)} nm`;
}

export default function BoardMetrology({
  lotId,
  waferId,
  metric,
  geometry,
}: MetrologyMapProps) {
  const [areaSelection, setAreaSelection] = useState<DieRegion | null>(null);
  const fixture = useMemo(
    () => makeMetrologyFixture(lotId, waferId, metric),
    [lotId, metric, waferId],
  );
  const radius = geometry?.coordinate_radius ?? fixture.radius;
  const gridStep = radius / 64;
  const grid = useMemo(
    () => interpolateWaferGrid(fixture.points, radius, gridStep),
    [fixture, radius, gridStep],
  );
  const outline = useMemo(() => waferOutline(radius), [radius]);
  const stats = useMemo(() => metricStats(fixture.points), [fixture]);
  const areaStats = useMemo(
    () => metricStats(selectMeasuredRegion(fixture.points, areaSelection)),
    [areaSelection, fixture],
  );
  const renderCell: CustomSeriesRenderItem = (_params, api) => {
    const center = api.coord([api.value(0), api.value(1)]);
    const next = api.coord([
      Number(api.value(0)) + gridStep,
      Number(api.value(1)) + gridStep,
    ]);
    const width = Math.abs(next[0] - center[0]);
    const height = Math.abs(next[1] - center[1]);
    return {
      type: 'rect',
      z2: 0,
      shape: {
        x: center[0] - width / 2,
        y: center[1] - height / 2,
        width: width + 0.4,
        height: height + 0.4,
      },
      style: { fill: metricColor(metric, Number(api.value(2))) },
    };
  };
  const option = useMemo<EChartsCoreOption>(
    () => ({
      animation: false,
      brush: {
        toolbox: [],
        xAxisIndex: 0,
        yAxisIndex: 0,
        brushType: 'rect',
        brushMode: 'single',
        brushStyle: {
          color: 'rgba(71,126,170,0.12)',
          borderColor: '#477eaa',
          borderWidth: 1,
        },
      },
      grid: { left: '5%', right: '5%', top: '5%', bottom: '5%' },
      xAxis: { type: 'value', min: -radius, max: radius, show: false },
      yAxis: { type: 'value', min: -radius, max: radius, show: false },
      tooltip: {
        trigger: 'item',
        renderMode: 'richText',
        confine: true,
        backgroundColor: '#ffffff',
        borderColor: '#dfe6e3',
        textStyle: { color: '#304b4a', fontSize: 10 },
        formatter: (item: any) => tooltipText(item, metric, geometry),
      },
      series: [
        {
          name: 'Linear estimate',
          z: 1,
          zlevel: 0,
          type: 'custom',
          progressive: 0,
          clip: true,
          renderItem: renderCell,
          encode: { x: 0, y: 1 },
          data: grid.map((point) => ({
            value: [point.x, point.y, point.value],
            kind: point.kind,
            itemStyle: {
              color: metricColor(metric, point.value),
              opacity: 0.9,
            },
          })),
        },
        {
          name: 'Measured',
          z: 3,
          type: 'scatter',
          symbol: 'circle',
          symbolSize: 3.5,
          data: fixture.points.map((point) => ({
            value: [point.x, point.y, point.value],
            kind: 'measured',
            itemStyle: {
              color: '#ffffff',
              borderColor: metricColor(metric, point.value),
              borderWidth: 1.4,
            },
          })),
          emphasis: {
            scale: 1.45,
            itemStyle: { borderColor: '#273d42', borderWidth: 1.6 },
          },
        },
        {
          name: 'Wafer outline',
          z: 2,
          type: 'line',
          data: outline,
          showSymbol: false,
          silent: true,
          lineStyle: { color: '#6c8984', width: 1 },
        },
      ],
    }),
    [fixture, grid, metric, outline, geometry, radius, gridStep],
  );
  const scale = METRIC_CONFIG[metric];

  return (
    <section className="metrology-map" aria-label={`${scale.label} wafer map`}>
      <header className="metrology-map-header">
        <span title={`${lotId} / ${waferId}`}>
          {lotId} / {waferId}
        </span>
        <strong>nm</strong>
      </header>
      <div className="metrology-map-source" title={fixture.sourceLabel}>
        합성 측정 ·{' '}
        {geometry ? `${geometry.radius_mm * 2} mm` : 'geometry 미설정'}
      </div>
      <div className="metrology-map-stage">
        <Chart
          option={option}
          mapNavigation
          label={`${scale.label} interpolated wafer map; measured points and linear estimates`}
          className="metrology-map-chart"
          onArea={(region) => setAreaSelection(region)}
        />
      </div>
      <div className={`metrology-map-scale ${scale.kind}`} aria-hidden="true">
        <span>{scale.min}</span>
        <i />
        <span>{scale.max}</span>
      </div>
      <div className="metrology-map-legend" aria-label="Point legend">
        <span>
          <i className="measured" /> measured
        </span>
        <span>
          <i className="estimated" /> linear estimate
        </span>
      </div>
      <div className="metrology-map-stats">
        <span>
          min <b>{formatValue(stats.min, metric)}</b>
        </span>
        <span>
          median <b>{formatValue(stats.median, metric)}</b>
        </span>
        <span>
          max <b>{formatValue(stats.max, metric)}</b>
        </span>
        <span>
          n <b>{stats.n}</b>
        </span>
      </div>
      {areaSelection && (
        <div className="metrology-map-area-stats">
          <span>
            Area n {areaStats.n} | median{' '}
            {formatValue(areaStats.median, metric)} nm
          </span>
          <button
            type="button"
            className="metrology-map-clear"
            title="Clear brush"
            aria-label="Clear brush"
            onClick={() => setAreaSelection(null)}
          >
            <X size={10} />
          </button>
        </div>
      )}
      <footer className="metrology-map-footer">
        합성 측정 · Agent Tool 미연결
      </footer>
    </section>
  );
}
