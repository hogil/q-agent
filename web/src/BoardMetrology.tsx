import { useEffect, useMemo, useState } from 'react';
import { ArrowDownToLine, Link2 } from 'lucide-react';
import type { EChartsCoreOption } from 'echarts/core';
import type { CustomSeriesRenderItem } from 'echarts';
import { Chart } from './charts';
import { waferCoordinateText, type DieRegion } from './waferMaps';
import { download, type WaferGeometry } from './api';
import {
  makeMetrologyFixture,
  compositeMetrologyMaps,
  metricColor,
  METRIC_CONFIG,
  interpolateWaferGrid,
  waferOutline,
  type MetrologyMetric,
} from './metrologyMap';
import {
  makeAggregateMetrologyProfile,
  makeMetrologyProfile,
  orderProfilePoints,
  type ProfileOrder,
} from './metrologyProfile';
import './metrologyMap.css';

export type MetrologyMapProps = {
  wafers: { lotId: string; waferId: string }[];
  aggregate?: boolean;
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
  aggregate = false,
): string {
  const data = item?.data;
  const values = Array.isArray(data) ? data : data?.value;
  if (!Array.isArray(values)) return '';
  const measured = data?.kind === 'measured';
  const kind = aggregate
    ? measured
      ? `Measured mean · ${data.contributors} Wafers`
      : `Wafer mean · ${data.contributors} Wafers`
    : measured
      ? 'Measured'
      : 'Linear estimate';
  return `${kind}\n${waferCoordinateText(values[0], values[1], geometry, 'normalized')}\n${METRIC_CONFIG[metric].label}: ${formatValue(values[2], metric)} nm`;
}

function profileTooltip(
  item: any,
  metric: MetrologyMetric,
  geometry: WaferGeometry | undefined,
  radiusUnit: 'mm' | 'coord',
): string {
  const data = item?.data;
  const values = Array.isArray(data) ? data : data?.value;
  if (!Array.isArray(values)) return '';
  if (data?.kind === 'radial-mean') {
    return `Radial bin ${data.start.toFixed(1)}–${data.end.toFixed(1)} ${radiusUnit}\nMean: ${formatValue(data.mean, metric)} nm · N ${data.contributors}`;
  }
  const pointNumber = Number(data?.sourceIndex) + 1;
  const radius = Number(data?.radius);
  return `Point ${pointNumber}\n${waferCoordinateText(data.x, data.y, geometry, 'normalized')}\nRadius ${radius.toFixed(2)} ${radiusUnit}\n${METRIC_CONFIG[metric].label}: ${formatValue(data.valueNm, metric)} nm · N ${data.contributors}`;
}

export default function BoardMetrology({
  wafers,
  aggregate = false,
  metric,
  geometry,
}: MetrologyMapProps) {
  const [areaSelection, setAreaSelection] = useState<DieRegion | null>(null);
  const [profileOrder, setProfileOrder] = useState<ProfileOrder>('radius');
  const [showPointLine, setShowPointLine] = useState(true);
  const [selectedSourceIndex, setSelectedSourceIndex] = useState<string | null>(
    null,
  );
  const fixtures = useMemo(
    () =>
      wafers.map(({ lotId, waferId }) => {
        const fixture = makeMetrologyFixture(lotId, waferId, metric);
        return {
          ...fixture,
          radius: geometry?.coordinate_radius ?? fixture.radius,
        };
      }),
    [wafers, metric, geometry?.coordinate_radius],
  );
  const fixture = fixtures[0];
  const radius = geometry?.coordinate_radius ?? fixture?.radius ?? 16;
  const gridStep = radius / 64;
  const field = useMemo(
    () =>
      aggregate
        ? compositeMetrologyMaps(fixtures, radius, gridStep)
        : {
            grid: interpolateWaferGrid(fixture?.points || [], radius, gridStep),
            waferCount: fixtures.length,
            measurementCount: fixture?.points.length || 0,
          },
    [fixtures, aggregate, radius, gridStep],
  );
  const grid = field.grid;
  const individualMeasured = fixture?.points || [];
  const showProfile = metric === 'cd' || metric === 'thk';
  const profile = useMemo(
    () =>
      aggregate
        ? makeAggregateMetrologyProfile(
            fixtures.map((item) => item.points),
            geometry,
            radius,
          )
        : makeMetrologyProfile(individualMeasured, geometry, radius),
    [aggregate, fixtures, geometry, individualMeasured, radius],
  );
  const measured = profile.points;
  const orderedProfilePoints = useMemo(
    () => orderProfilePoints(profile.points, profileOrder),
    [profile.points, profileOrder],
  );
  const waferKey = wafers.map(({ lotId, waferId }) => `${lotId}\u0000${waferId}`).join('|');
  useEffect(() => {
    setSelectedSourceIndex(null);
  }, [metric, waferKey, aggregate, geometry?.coordinate_radius]);
  const outline = useMemo(() => waferOutline(radius), [radius]);
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
      grid: { left: 1, right: 1, top: 1, bottom: 1 },
      xAxis: { type: 'value', min: -radius, max: radius, show: false },
      yAxis: { type: 'value', min: -radius, max: radius, show: false },
      tooltip: {
        trigger: 'item',
        renderMode: 'richText',
        confine: true,
        backgroundColor: '#ffffff',
        borderColor: '#dfe6e3',
        textStyle: { color: '#304b4a', fontSize: 10 },
        formatter: (item: any) =>
          tooltipText(item, metric, geometry, aggregate),
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
            contributors: 'contributors' in point ? point.contributors : 1,
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
          data: measured.map((point) => ({
            value: [point.x, point.y, point.value],
            kind: 'measured',
            sourceIndex: point.sourceIndex,
            selectionKey: point.selectionKey,
            contributors: point.contributors,
            itemStyle: {
              color:
                point.selectionKey === selectedSourceIndex ? '#273d42' : '#ffffff',
              borderColor:
                point.selectionKey === selectedSourceIndex
                  ? '#273d42'
                  : metricColor(metric, point.value),
              borderWidth: point.selectionKey === selectedSourceIndex ? 2 : 1.4,
            },
            symbolSize: point.selectionKey === selectedSourceIndex ? 6 : 3.5,
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
    [fixtures, grid, metric, outline, geometry, radius, gridStep, aggregate, measured, selectedSourceIndex],
  );
  const profileOption = useMemo<EChartsCoreOption>(
    () => {
      const radiusMode = profileOrder === 'radius';
      const pointData = orderedProfilePoints.map((point) => ({
        value: [radiusMode ? point.radius : point.sourceIndex + 1, point.value],
        x: point.x,
        y: point.y,
        valueNm: point.value,
        radius: point.radius,
        sourceIndex: point.sourceIndex,
        selectionKey: point.selectionKey,
        contributors: point.contributors,
        kind: 'measured',
        itemStyle: {
          color:
            point.selectionKey === selectedSourceIndex
              ? '#273d42'
              : metricColor(metric, point.value),
          borderColor: '#ffffff',
          borderWidth: point.selectionKey === selectedSourceIndex ? 1.8 : 1,
        },
        symbolSize: point.selectionKey === selectedSourceIndex ? 7 : 5,
      }));
      const radialData = profile.radialMeans.map((bin) => ({
        value: [bin.x, bin.mean],
        start: bin.start,
        end: bin.end,
        mean: bin.mean,
        contributors: bin.contributors,
        kind: bin.kind,
      }));
      return {
        animation: false,
        grid: { left: 38, right: 7, top: 12, bottom: 30 },
        xAxis: {
          type: 'value',
          splitNumber: 3,
          minInterval: radiusMode ? undefined : 1,
          min: radiusMode ? 0 : 0.5,
          max: radiusMode
            ? profile.edgeRadius
            : Math.max(1.5, ...orderedProfilePoints.map((point) => point.sourceIndex + 1.5)),
          name: radiusMode
            ? `Radius (${profile.radiusUnit})`
            : 'Point order',
          nameLocation: 'middle',
          nameGap: 21,
          nameTextStyle: { color: '#70817a', fontSize: 9 },
          axisLabel: {
            color: '#71817b',
            fontSize: 9,
            hideOverlap: true,
            formatter: (value: number) =>
              radiusMode ? value.toFixed(0) : String(Math.round(value)),
          },
          axisLine: { lineStyle: { color: '#cfdad5' } },
          splitLine: { lineStyle: { color: '#edf1ef' } },
        },
        yAxis: {
          type: 'value',
          splitNumber: 2,
          name: `${METRIC_CONFIG[metric].label} (nm)`,
          nameLocation: 'middle',
          nameGap: 30,
          nameTextStyle: { color: '#70817a', fontSize: 9 },
          axisLabel: { color: '#71817b', fontSize: 9, hideOverlap: true },
          axisLine: { lineStyle: { color: '#cfdad5' } },
          splitLine: { lineStyle: { color: '#edf1ef' } },
          scale: true,
        },
        tooltip: {
          trigger: 'item',
          renderMode: 'richText',
          confine: true,
          backgroundColor: '#ffffff',
          borderColor: '#dfe6e3',
          textStyle: { color: '#304b4a', fontSize: 10 },
          formatter: (item: any) =>
            profileTooltip(item, metric, geometry, profile.radiusUnit),
        },
        series: [
          ...(radiusMode
            ? [
                {
                  name: 'Radial-bin mean',
                  type: 'line',
                  data: radialData,
                  symbol: 'circle',
                  symbolSize: 5,
                  connectNulls: false,
                  lineStyle: { color: '#c1764f', width: 1.8 },
                  itemStyle: { color: '#c1764f', borderColor: '#ffffff' },
                },
              ]
            : showPointLine
              ? [
                  {
                    name: 'Point order',
                    type: 'line',
                    data: pointData,
                    symbol: 'none',
                    lineStyle: { color: '#8fa99f', width: 1.2 },
                  },
                ]
              : []),
          {
            name: 'Measured points',
            type: 'scatter',
            data: pointData,
            z: 3,
            emphasis: { scale: 1.35 },
          },
        ],
      };
    },
    [
      geometry,
      metric,
      orderedProfilePoints,
      profile,
      profileOrder,
      selectedSourceIndex,
      showPointLine,
    ],
  );
  const scale = METRIC_CONFIG[metric];

  return (
    <section
      className="metrology-map"
      aria-label={`${scale.label} wafer map`}
      data-selected-point={selectedSourceIndex ?? 'none'}
    >
      <header className="metrology-map-header">
        <span
          title={wafers
            .map((row) => `${row.lotId} / ${row.waferId}`)
            .join(', ')}
        >
          {aggregate
            ? `${scale.label} · ${wafers.length} Wafers · 좌표별 평균`
            : `${fixture?.lotId} / ${fixture?.waferId}`}
        </span>
        <strong>nm</strong>
        {aggregate && (
          <button
            className="icon-button"
            title={`${scale.label} 합성 Map 다운로드`}
            aria-label={`${scale.label} 합성 Map 다운로드`}
            onClick={() =>
              download(
                `${metric}-composite-map.json`,
                JSON.stringify(
                  {
                    synthetic: true,
                    metric,
                    unit: 'nm',
                    wafers,
                    geometry,
                    method:
                      'mean of per-wafer linear interpolation; missing excluded',
                    physicalAlignmentVerified: false,
                    ...field,
                  },
                  null,
                  2,
                ),
                'application/json',
              )
            }
          >
            <ArrowDownToLine size={12} />
          </button>
        )}
      </header>
      <div className={`metrology-map-stage${showProfile ? ' has-profile' : ''}`}>
        <div className="metrology-map-canvas-frame">
          <Chart
            option={option}
            mapNavigation
            areaSelection={areaSelection}
            label={`${scale.label} ${aggregate ? 'composite mean' : 'individual'} wafer map`}
            className="metrology-map-chart"
            onSelect={(item) => {
              if (item?.data?.kind === 'measured')
                setSelectedSourceIndex(item.data.selectionKey);
            }}
            onClearSelection={() => setSelectedSourceIndex(null)}
            onArea={(region) => setAreaSelection(region)}
          />
        </div>
        {showProfile && (
          <aside className="metrology-profile" aria-label={`${scale.label} edge profile`}>
            <header className="metrology-profile-header">
              <span>Edge profile</span>
              <button
                type="button"
                className="icon-button metrology-profile-line-toggle"
                title="Point mode connecting line"
                aria-label="Point mode connecting line"
                aria-pressed={showPointLine}
                disabled={profileOrder === 'radius'}
                onClick={() => setShowPointLine((value) => !value)}
              >
                <Link2 size={12} />
              </button>
            </header>
            <div className="metrology-profile-switch" role="group" aria-label="Profile x-axis">
              <button
                type="button"
                aria-pressed={profileOrder === 'point'}
                onClick={() => setProfileOrder('point')}
              >
                Point order
              </button>
              <button
                type="button"
                aria-pressed={profileOrder === 'radius'}
                onClick={() => setProfileOrder('radius')}
              >
                Radius({profile.radiusUnit})
              </button>
            </div>
            <Chart
              option={profileOption}
              label={`${scale.label} measured point profile`}
              className="metrology-profile-chart"
              onSelect={(item) => {
                if (item?.data?.kind === 'measured')
                  setSelectedSourceIndex(item.data.selectionKey);
              }}
              onClearSelection={() => setSelectedSourceIndex(null)}
            />
          </aside>
        )}
      </div>
    </section>
  );
}
