import { useMemo, useState } from 'react';
import { ArrowDownToLine, Contrast, Layers, X } from 'lucide-react';
import { Chart } from './charts';
import {
  compareWaferMaps,
  type WaferMap,
  type WaferComparisonCategory,
} from './waferMaps';
import { download } from './api';

const colors: Record<WaferComparisonCategory, string> = {
  bothFlag: '#78639b',
  aOnly: '#c65b62',
  bOnly: '#318dab',
  neither: '#e8eeeb',
  missingA: '#dfb652',
  missingB: '#dfb652',
};
const labels: Record<WaferComparisonCategory, string> = {
  bothFlag: '공통',
  aOnly: 'A만',
  bOnly: 'B만',
  neither: '둘 다 Flag 없음',
  missingA: 'A 미관측',
  missingB: 'B 미관측',
};
export default function BoardOverlay({
  a,
  b,
  coordinate,
  selectDie,
}: {
  a?: WaferMap;
  b?: WaferMap;
  coordinate: [number, number] | null;
  selectDie: (value: [number, number] | null) => void;
}) {
  const [mode, setMode] = useState<'difference' | 'overlay'>('difference');
  const [opacity, setOpacity] = useState(65);
  const [showA, setShowA] = useState(true);
  const [showB, setShowB] = useState(true);
  const compared = useMemo(() => {
    if (!a || !b) return { result: null, error: '' };
    try {
      return { result: compareWaferMaps(a, b), error: '' };
    } catch (e) {
      return {
        result: null,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  }, [a, b]);
  const result = compared.result;
  const selected =
    coordinate &&
    result?.dies.find((d) => d.x === coordinate[0] && d.y === coordinate[1]);
  const marker = selected
    ? {
        silent: true,
        symbol: 'rect',
        symbolSize: 11,
        label: { show: false },
        itemStyle: {
          color: 'transparent',
          borderColor: '#233a32',
          borderWidth: 1.5,
        },
        data: [{ coord: [selected.x, selected.y] }],
      }
    : undefined;
  const option = {
    animation: false,
    grid: { left: '4%', right: '4%', top: '4%', bottom: '4%' },
    xAxis: { type: 'value', min: -18, max: 18, show: false },
    yAxis: { type: 'value', min: -18, max: 18, show: false },
    tooltip: {
      renderMode: 'richText',
      formatter: (p: { value: number[] }) => {
        const d = result?.dies.find(
          (d) => d.x === p.value[0] && d.y === p.value[1],
        );
        return d
          ? `Die (${d.x},${d.y})\nA Bin ${d.binA ?? 'N/A'} · B Bin ${d.binB ?? 'N/A'}\n${labels[d.category]} · 합성`
          : '';
      },
    },
    series:
      mode === 'difference'
        ? [
            {
              type: 'scatter',
              symbol: 'rect',
              symbolSize: 5,
              markPoint: marker,
              data: (result?.dies || []).map((d) => ({
                value: [d.x, d.y],
                itemStyle: { color: colors[d.category] },
              })),
            },
          ]
        : [
            {
              type: 'scatter',
              markPoint: marker,
              symbol: 'rect',
              symbolSize: 4,
              data: (result?.dies || []).map((d) => [d.x, d.y]),
              itemStyle: { color: colors.neither },
            },
            {
              type: 'scatter',
              symbol: 'rect',
              symbolSize: 4.2,
              data: showA
                ? (a?.dies || [])
                    .filter((d) => d.bin >= 3)
                    .map((d) => [d.x, d.y])
                : [],
              itemStyle: { color: colors.aOnly },
            },
            {
              type: 'scatter',
              symbol: 'circle',
              symbolSize: 3.8,
              data: showB
                ? (b?.dies || [])
                    .filter((d) => d.bin >= 3)
                    .map((d) => [d.x, d.y])
                : [],
              itemStyle: { color: colors.bOnly, opacity: opacity / 100 },
            },
          ],
  };
  return (
    <>
      <header>
        <h2>Wafer A × B</h2>
        <div className="overlay-modes" role="group" aria-label="Map 비교 방식">
          <button
            className="icon-button"
            title="차이 Map"
            aria-pressed={mode === 'difference'}
            onClick={() => setMode('difference')}
          >
            <Contrast size={14} />
          </button>
          <button
            className="icon-button"
            title="Overlay Map"
            aria-pressed={mode === 'overlay'}
            onClick={() => setMode('overlay')}
          >
            <Layers size={14} />
          </button>
        </div>
        <button
          className="icon-button"
          title="Die 선택 해제"
          disabled={!coordinate}
          onClick={() => selectDie(null)}
        >
          <X size={14} />
        </button>
        <button
          className="icon-button"
          title="Wafer 비교 결과 다운로드"
          disabled={!result}
          onClick={() =>
            download(
              'synthetic-wafer-comparison.json',
              JSON.stringify(
                {
                  synthetic: true,
                  physicalAlignmentVerified: false,
                  a: { lotId: a?.lotId, waferId: a?.waferId },
                  b: { lotId: b?.lotId, waferId: b?.waferId },
                  ...result,
                },
                null,
                2,
              ),
            )
          }
        >
          <ArrowDownToLine size={14} />
        </button>
      </header>
      <div className="overlay-identity">
        <span>A {a ? `${a.lotId}/${a.waferId}` : '선택 없음'}</span>
        <span>B {b ? `${b.lotId}/${b.waferId}` : '선택 없음'}</span>
      </div>
      {mode === 'overlay' && (
        <div className="overlay-controls-compact">
          <label>
            <input
              type="checkbox"
              checked={showA}
              onChange={(e) => setShowA(e.target.checked)}
            />
            A
          </label>
          <label>
            <input
              type="checkbox"
              checked={showB}
              onChange={(e) => setShowB(e.target.checked)}
            />
            B
          </label>
          <input
            aria-label="Overlay B 불투명도"
            type="range"
            min={0}
            max={100}
            value={opacity}
            onChange={(e) => setOpacity(+e.target.value)}
          />
          <output>{opacity}%</output>
        </div>
      )}
      <div className="board-map-stage">
        {result ? (
          <Chart
            option={option}
            className="board-map-canvas"
            label={
              mode === 'difference'
                ? 'A B Wafer 차이 Map'
                : 'A B Wafer Overlay Map'
            }
            onSelect={(p) => selectDie([p.value[0], p.value[1]])}
          />
        ) : (
          <p className="board-empty">{compared.error || '비교 Wafer B 없음'}</p>
        )}
      </div>
      <div className="overlay-counts">
        {(['aOnly', 'bothFlag', 'bOnly'] as const).map((key) => (
          <span key={key}>
            <i style={{ background: colors[key] }} />
            {labels[key]} <b>{result?.counts[key] ?? '-'}</b>
          </span>
        ))}
        {!!result && result.counts.missingA + result.counts.missingB > 0 && (
          <span>
            <i style={{ background: colors.missingA }} />
            미관측 {result.counts.missingA + result.counts.missingB}
          </span>
        )}
      </div>
      <footer
        aria-live="polite"
        title="합성 좌표 비교 · 실측 정렬 미검증 · Flag는 Bin 3 이상 · Jaccard와 Δ는 양쪽 관측 좌표 기준"
      >
        {selected
          ? `Die (${selected.x},${selected.y}) · A ${selected.binA ?? 'N/A'} / B ${selected.binB ?? 'N/A'} · ${labels[selected.category]}`
          : result
            ? `공통 ${result.validCompared} Die · Jaccard ${result.jaccard === null ? 'N/A' : result.jaccard.toFixed(3)} · Δ Flag ${result.delta === null ? 'N/A' : (result.delta * 100).toFixed(1) + 'pp'}`
            : '합성 좌표 · 실측 정렬 미검증'}
      </footer>
    </>
  );
}
