import { useMemo, useState } from 'react';
import { Maximize2, X } from 'lucide-react';
import { Chart } from './charts';
import { vectorRenderer } from './BoardOverlay';
import { fitOverlayVectors } from './overlayVectors';
import { waferOutline } from './metrologyMap';
import type { AnalysisReportData } from './api';
import type { AnalysisContext } from './engineeringAnalysis';

const kinds = ['Overlay', 'CD', 'THK', 'EDS Bin'] as const;
type Kind = typeof kinds[number];
type MapAsset = NonNullable<AnalysisReportData['map_assets']>[number];

function EvidenceMap({ kind, wafer, view }: {
  kind: Kind; wafer: MapAsset; view: 'raw' | 'fit' | 'residual';
}) {
  const option = useMemo(() => {
    const raw = wafer.overlay;
    const vectors = view === 'raw' ? raw : fitOverlayVectors(raw)?.[view] || [];
    const scalar = kind === 'CD' || kind === 'THK'
      ? wafer[kind === 'CD' ? 'cd' : 'thk'] : [];
    const bins = wafer.eds_bin;
    return {
      animation: false,
      grid: { left: 8, right: 8, top: 8, bottom: 28 },
      xAxis: { type: 'value', min: -17, max: 17, show: false },
      yAxis: { type: 'value', min: -17, max: 17, show: false },
      tooltip: { trigger: 'item', confine: true, formatter: (p: { value: number[] }) => {
        const [x, y, v, dy] = p.value;
        return `XY ${x}, ${y}<br/>${kind === 'Overlay' ? `dX ${v.toFixed(2)} / dY ${dy.toFixed(2)} nm`
          : kind === 'EDS Bin' ? `Bin ${v}` : `${kind} ${v.toFixed(2)} nm`}`;
      } },
      ...(kind === 'Overlay' ? {} : { visualMap: kind === 'EDS Bin'
        ? { type: 'piecewise', orient: 'horizontal', bottom: 0, left: 'center', itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 9 }, pieces: [
          { min: 0, max: 2, label: '0–2', color: '#a8c7cd' },
          { value: 3, label: '3', color: '#e59143' }, { value: 4, label: '4', color: '#c54558' },
        ], seriesIndex: 1, dimension: 2 }
        : { min: Math.min(...scalar.map(p => p.value)), max: Math.max(...scalar.map(p => p.value)),
          orient: 'horizontal', bottom: 0, left: 'center', itemWidth: 8, itemHeight: 75,
          text: ['nm', ''], precision: 1, textStyle: { fontSize: 9 }, seriesIndex: 1, dimension: 2,
          inRange: { color: ['#3975ad', '#68b6a3', '#e8ca65', '#cb5960'] } } }),
      series: [
        { type: 'line', data: waferOutline(16), symbol: 'none', silent: true, lineStyle: { color: '#91aaa0', width: 1 } },
        kind === 'Overlay'
          ? { type: 'custom', renderItem: vectorRenderer('#b44c51', 0.65),
            data: vectors.map(p => [p.x, p.y, p.dx, p.dy, 0, 1]) }
          : { type: 'scatter', symbol: kind === 'EDS Bin' ? 'rect' : 'circle', symbolSize: kind === 'EDS Bin' ? 5 : 12,
            data: kind === 'EDS Bin' ? bins.map(p => [p.x, p.y, p.bin]) : scalar.map(p => [p.x, p.y, p.value]) },
      ],
    };
  }, [kind, wafer, view]);
  return <Chart option={option} label={`${kind} · ${wafer.lot_id} / ${wafer.wafer_id}`} className="analysis-wafer-chart" />;
}

export default function AnalysisMaps({ context, report }: { context: AnalysisContext; report: AnalysisReportData }) {
  const [selected, setSelected] = useState('');
  const [view, setView] = useState<'raw' | 'fit' | 'residual'>('raw');
  const [expanded, setExpanded] = useState<Kind | null>(null);
  const wafers = (report.map_assets || []).filter(w => w.step === context.step && context.wafers.some(p => p.lot_id === w.lot_id && p.wafer_id === w.wafer_id));
  if (!wafers.length) return <p>저장된 Map Tool 좌표 없음 · 분석 재실행 필요</p>;
  const index = Math.max(0, wafers.findIndex(w => `${w.lot_id}/${w.wafer_id}` === selected));
  return <section className="analysis-wafer-maps" aria-label="분석 Wafer Maps">
    <header><strong>Tool 조회 Map</strong><select aria-label="분석 Map Wafer" value={`${wafers[index].lot_id}/${wafers[index].wafer_id}`}
      onChange={e => setSelected(e.target.value)}>{wafers.map(w => <option key={`${w.lot_id}/${w.wafer_id}`}>{w.lot_id}/{w.wafer_id}</option>)}</select></header>
    <div className="analysis-wafer-grid">{kinds.map(kind => <figure key={kind}>
      <header><strong>{kind}</strong><button onClick={() => setExpanded(kind)} title={`${kind} 확대`} aria-label={`${kind} 확대`}><Maximize2 size={12} /></button>
        {kind === 'Overlay' && <select aria-label="분석 Overlay 성분" value={view} onChange={e => setView(e.target.value as typeof view)}>
          <option value="raw">Raw</option><option value="fit">Fit</option><option value="residual">Res</option></select>}</header>
      <EvidenceMap kind={kind} wafer={wafers[index]} view={view} />
      <figcaption>{kind === 'EDS Bin' ? '합성 Bin 분포 · 현재 EDS 수신 전' : kind === 'Overlay' ? '측정점별 벡터 · 화살표 길이 ×0.65' : '측정점 색상 · nm'}</figcaption>
    </figure>)}</div>
    <small>저장 Tool 근거 · {wafers[index].sha256.slice(0, 12)} · 합성 Map · LLM은 수치 요약 검토</small>
    {expanded && <dialog ref={node => { if (node && !node.open) node.showModal(); }} onCancel={() => setExpanded(null)} className="analysis-map-expanded" aria-label={`${expanded} Map 확대`}>
      <header><strong>{expanded} · {wafers[index].wafer_id}</strong><button onClick={() => setExpanded(null)} aria-label="Map 확대 닫기"><X size={16} /></button></header>
      <EvidenceMap kind={expanded} wafer={wafers[index]} view={view} />
    </dialog>}
  </section>;
}
