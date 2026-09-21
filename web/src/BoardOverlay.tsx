import { useMemo, useState } from 'react';
import { ArrowDownToLine } from 'lucide-react';
import type { CustomSeriesRenderItem } from 'echarts';
import { Chart } from './charts';
import { download, type WaferGeometry } from './api';
import {
  waferCoordinateText,
  selectDieRegion,
  type DieRegion,
} from './waferMaps';
import { waferOutline } from './metrologyMap';
import {
  makeOverlayFixture,
  compositeOverlayVectors,
  fitOverlayVectors,
  type OverlayVectorPoint,
} from './overlayVectors';
import './metrologyMap.css';

export type OverlayView = 'raw' | 'fit' | 'residual';
type Props = {
  wafers: { lotId: string; waferId: string }[];
  aggregate?: boolean;
  geometry?: WaferGeometry;
  vectorScale: number;
  onVectorScale: (value: number) => void;
  view: OverlayView;
  onView: (value: OverlayView) => void;
};
const views = [
  { key: 'raw', label: 'Raw', color: '#257d76' },
  { key: 'fit', label: 'Fit', color: '#397db8' },
  { key: 'residual', label: 'Res', color: '#bc5960' },
] as const;

function vectorRenderer(color: string, gain: number): CustomSeriesRenderItem {
  return (_params, api) => {
    const x = Number(api.value(0)),
      y = Number(api.value(1));
    const a = api.coord([x, y]);
    const b = api.coord([
      x + Number(api.value(2)) * gain,
      y + Number(api.value(3)) * gain,
    ]);
    const dx = b[0] - a[0],
      dy = b[1] - a[1],
      length = Math.hypot(dx, dy);
    const angle = Math.atan2(dy, dx),
      tip = Math.min(5, length * 0.45);
    const opacity = Number(api.value(5));
    return {
      type: 'group',
      children: [
        {
          type: 'circle',
          z2: 1,
          shape: { cx: a[0], cy: a[1], r: 1.5 },
          style: { fill: color, opacity },
        },
        {
          type: 'line',
          z2: 1,
          shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] },
          style: { stroke: color, lineWidth: 1.3, opacity },
        },
        {
          type: 'polyline',
          z2: 1,
          shape: {
            points: [
              [
                b[0] - tip * Math.cos(angle - 0.5),
                b[1] - tip * Math.sin(angle - 0.5),
              ],
              b,
              [
                b[0] - tip * Math.cos(angle + 0.5),
                b[1] - tip * Math.sin(angle + 0.5),
              ],
            ],
          },
          style: { stroke: color, fill: 'none', lineWidth: 1.3, opacity },
        },
      ],
    };
  };
}

export default function BoardOverlay({
  wafers,
  aggregate = false,
  geometry,
  vectorScale,
  onVectorScale,
  view: viewKey,
  onView,
}: Props) {
  const [area, setArea] = useState<DieRegion | null>(null);
  const view = views.find((item) => item.key === viewKey)!;
  const radius = geometry?.coordinate_radius ?? 16;
  const fixtures = useMemo(
    () => wafers.map((row) => makeOverlayFixture(row.lotId, row.waferId)),
    [wafers],
  );
  const raw = useMemo(
    () =>
      aggregate
        ? compositeOverlayVectors(fixtures, radius, radius / 4).points
        : fixtures[0]?.points || [],
    [fixtures, aggregate, radius],
  );
  const model = useMemo(() => fitOverlayVectors(raw), [raw]);
  const gain = (radius / 8) * vectorScale;
  const chart = useMemo(() => {
    const points: OverlayVectorPoint[] =
      view.key === 'raw' ? raw : model?.[view.key] || [];
    const selected = selectDieRegion(points, area);
    const selectedSet = new Set(selected);
    const rms = selected.length
      ? Math.sqrt(
          selected.reduce((sum, p) => sum + p.dx ** 2 + p.dy ** 2, 0) /
            selected.length,
        )
      : null;
    return {
      ...view,
      n: selected.length,
      rms,
      option: {
        animation: false,
        grid: { left: 6, right: 6, top: 6, bottom: 32 },
        xAxis: { type: 'value', min: -radius, max: radius, show: false },
        yAxis: { type: 'value', min: -radius, max: radius, show: false },
        brush: {
          toolbox: [],
          xAxisIndex: 0,
          yAxisIndex: 0,
          brushType: 'rect',
          brushMode: 'single',
        },
        tooltip: {
          trigger: 'item',
          renderMode: 'richText',
          confine: true,
          textStyle: { fontSize: 10 },
          formatter: (p: { value: number[] }) =>
            `${view.label}${aggregate ? ' · Wafer mean (보간)' : ''}\n${waferCoordinateText(p.value[0], p.value[1], geometry, 'normalized')}\nΔX ${p.value[2].toFixed(3)} nm · ΔY ${p.value[3].toFixed(3)} nm\n|Δ| ${Math.hypot(p.value[2], p.value[3]).toFixed(3)} nm${aggregate ? `\n${p.value[4]} / ${wafers.length} Wafers` : ''}`,
        },
        series: [
          {
            type: 'custom',
            z: 2,
            zlevel: 0,
            progressive: 0,
            clip: true,
            renderItem: vectorRenderer(view.color, gain),
            encode: { x: 0, y: 1 },
            data: points.map((p) => [
              p.x,
              p.y,
              p.dx,
              p.dy,
              p.contributors ?? 1,
              selectedSet.has(p) ? 1 : 0.2,
            ]),
          },
          {
            type: 'line',
            data: waferOutline(radius),
            silent: true,
            showSymbol: false,
            lineStyle: { color: '#94aaa4', width: 1 },
          },
          {
            type: 'custom',
            z: 2,
            zlevel: 0,
            silent: true,
            renderItem: vectorRenderer(view.color, gain),
            data: [[-radius * 0.3, -radius * 0.91, 1, 0, 0, 1]],
          },
        ],
      },
    };
  }, [
    view,
    raw,
    model,
    area,
    radius,
    gain,
    geometry,
    aggregate,
    wafers.length,
  ]);

  return (
    <section
      className="overlay-vector-map"
      aria-label={`${aggregate ? '전체' : '개별'} Overlay Raw Fit Res`}
    >
      <div className="overlay-vector-heading">
        <div
          className="overlay-view-switch"
          role="group"
          aria-label="Overlay 표시"
        >
          {views.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={viewKey === item.key}
              title={
                item.key === 'residual' ? 'Residual · Raw − Fit' : item.label
              }
              style={{ color: item.color }}
              onClick={() => onView(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <button
          className="icon-button"
          title="Overlay Raw Fit Res 다운로드"
          aria-label="Overlay Raw Fit Res 다운로드"
          onClick={() =>
            download(
              'overlay-raw-fit-res.json',
              JSON.stringify(
                {
                  synthetic: true,
                  unit: 'nm',
                  coordinateUnit: 'normalized',
                  geometry,
                  wafers,
                  rawKind: aggregate
                    ? 'componentwise mean of linear interpolation; missing excluded'
                    : 'synthetic measured vectors',
                  model: 'dx=a0+a1*x+a2*y; dy=b0+b1*x+b2*y',
                  physicalAlignmentVerified: false,
                  ...(model || { raw, fit: null, residual: null }),
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
      </div>
      <div className="overlay-vector-body">
        <aside className="overlay-vector-side" aria-label="Overlay RMS와 배율">
          <dl aria-live="polite">
            <dt>RMS</dt>
            <dd style={{ color: view.color }}>
              {chart.rms?.toFixed(3) ?? '-'}
              <small>nm</small>
            </dd>
          </dl>
          <div className="overlay-vector-controls">
            <label>
              Vector
              <input
                type="range"
                min="0.5"
                max="4"
                step="0.25"
                aria-label="Overlay 벡터 배율"
                value={vectorScale}
                onChange={(e) => onVectorScale(+e.target.value)}
              />
            </label>
            <output>×{vectorScale}</output>
          </div>
        </aside>
        <div className="overlay-vector-stage">
          <Chart
            option={chart.option}
            mapNavigation
            label={`Overlay ${view.label} ${aggregate ? '전체' : '개별'} 벡터 Map`}
            className="overlay-vector-chart"
            onArea={setArea}
          />
        </div>
        <aside className="overlay-vector-side" aria-label="Overlay 표본과 출처">
          <dl aria-live="polite">
            <dt>n</dt>
            <dd>{chart.n}</dd>
          </dl>
          <span title="기준 화살표 1 nm">1 nm</span>
          <div
            className="overlay-vector-source"
            title={`${wafers.map((row) => `${row.lotId}/${row.waferId}`).join(', ')} · 6-param linear · Res = Raw − Fit · 실제 보정 모델 미연결`}
          >
            <span>합성</span>
            <span>{aggregate ? '보간 평균' : '측정 예시'}</span>
            <span>{aggregate ? '정렬 가정' : '모델 미연결'}</span>
            {!model && <strong>Fit 불가</strong>}
          </div>
        </aside>
      </div>
    </section>
  );
}
