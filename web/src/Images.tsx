import { useState, type CSSProperties } from 'react';
import {
  Focus,
  Image,
  Layers,
  Link2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { OverlayChart, WaferChart, type Die } from './charts';
import { MapView, incidentSeed } from './Views';
import type { ViewProps } from './Views';

export default function Images(props: ViewProps & { initialMode?: string }) {
  const [mode, setMode] = useState(
    ['wafer', 'sem', 'image-map', 'overlay'].includes(props.initialMode || '')
      ? props.initialMode!
      : 'wafer',
  );
  const [zoom, setZoom] = useState(1);
  const [roi, setRoi] = useState(true);
  const [selected, setSelected] = useState<Die | null>(null);
  const [opacity, setOpacity] = useState(65);
  const [showA, setShowA] = useState(true);
  const [showB, setShowB] = useState(true);
  const seed = incidentSeed(props.workspace);
  return (
    <div className="image-workspace">
      <div className="map-mode-bar" role="group" aria-label="Map 종류">
        {[
          ['wafer', 'Wafer map', Focus],
          ['sem', 'SEM image', Image],
          ['image-map', 'Image map', Image],
          ['overlay', 'Overlay map', Layers],
        ].map(([id, name, Icon]: any) => (
          <button
            className={mode === id ? 'active' : ''}
            key={id}
            onClick={() => setMode(id)}
          >
            <Icon size={14} />
            {name}
          </button>
        ))}
      </div>
      {mode === 'wafer' ? (
        <MapView {...props} />
      ) : (
        <section className="detail-view">
          <div className="section-title">
            <div>
              <h2>
                {mode === 'sem'
                  ? 'SEM image inspection'
                  : mode === 'image-map'
                    ? 'Die-to-image map'
                    : 'Layer overlay'}
              </h2>
              <span>
                {props.workspace.incident.incident_number} · 합성 뷰어
              </span>
            </div>
            <span className="status-tag amber">실측 이미지 미연결</span>
          </div>
          {mode === 'overlay' ? (
            <>
              <div className="data-notice">
                <span className="synthetic-label">합성 좌표</span>
                <span>
                  두 예시 Layer가 같은 Die grid를 공유합니다. 실측 정렬 결과가
                  아닙니다.
                </span>
              </div>
              <div className="overlay-controls">
                <label>
                  <input
                    type="checkbox"
                    checked={showA}
                    onChange={(e) => setShowA(e.target.checked)}
                  />
                  <i style={{ background: '#528ca9' }} />
                  Inspection A
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={showB}
                    onChange={(e) => setShowB(e.target.checked)}
                  />
                  <i style={{ background: '#cc846e' }} />
                  Inspection B
                </label>
                <label className="opacity-control">
                  B opacity{' '}
                  <input
                    aria-label="Overlay 투명도"
                    type="range"
                    min="0"
                    max="100"
                    value={opacity}
                    onChange={(e) => setOpacity(Number(e.target.value))}
                  />
                  <output>{opacity}%</output>
                </label>
              </div>
              <div className="overlay-stage">
                <OverlayChart
                  seed={seed}
                  opacity={opacity}
                  showA={showA}
                  showB={showB}
                />
              </div>
              <div className="selection-bar">
                <div>
                  <span className="eyebrow">LAYER COMPARISON</span>
                  <strong>
                    {showA ? 'A' : ''}
                    {showA && showB ? ' + ' : ''}
                    {showB ? `B (${opacity}%)` : ''}
                    {!showA && !showB ? '표시 Layer 없음' : ''}
                  </strong>
                </div>
                <button
                  className="outline-button"
                  onClick={() =>
                    props.attach({
                      kind: 'map',
                      id: `overlay-${seed}-${opacity}`,
                      label: '합성 Overlay map · A/B 비교',
                    })
                  }
                >
                  <Link2 size={14} />
                  검토 대상에 추가
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="data-notice">
                <span className="synthetic-label">AI 생성 합성 SEM</span>
                <span>
                  실제 결함·배율·물리적 크기의 근거로 사용할 수 없습니다.
                </span>
              </div>
              {mode === 'image-map' && (
                <div className="image-map-master">
                  <WaferChart seed={seed} compact onSelect={setSelected} />
                  <div>
                    <span className="eyebrow">SELECTED LOCATION</span>
                    <h3>
                      {selected
                        ? `Die X ${selected.x} / Y ${selected.y}`
                        : 'Die 미선택'}
                    </h3>
                    <p>실측 이미지 없음</p>
                    <small>
                      아래 이미지는 위치와 무관한 공통 합성 예시입니다.
                    </small>
                  </div>
                </div>
              )}
              <div className="image-toolbar">
                <label>
                  <input
                    type="checkbox"
                    checked={roi}
                    onChange={(e) => setRoi(e.target.checked)}
                  />
                  검토 영역 표시
                </label>
                <span />
                <button
                  className="icon-button"
                  title="SEM 축소"
                  disabled={zoom <= 1}
                  onClick={() => setZoom((z) => Math.max(1, z - 0.25))}
                >
                  <ZoomOut size={17} />
                </button>
                <output>{Math.round(zoom * 100)}%</output>
                <button
                  className="icon-button"
                  title="SEM 확대"
                  disabled={zoom >= 3}
                  onClick={() => setZoom((z) => Math.min(3, z + 0.25))}
                >
                  <ZoomIn size={17} />
                </button>
                <button
                  className="icon-button"
                  title="SEM 배율 초기화"
                  onClick={() => setZoom(1)}
                >
                  <RotateCcw size={15} />
                </button>
              </div>
              <div className="sem-viewport">
                <div
                  className="sem-image-stage"
                  style={{ '--image-zoom': zoom } as CSSProperties}
                >
                  <img
                    src="/assets/synthetic-sem.png"
                    alt="실제 측정이 아닌 AI 생성 반도체 line-space 합성 SEM 이미지"
                  />
                  {roi && (
                    <button
                      className="sem-roi"
                      title="합성 검토 영역 첨부"
                      onClick={() =>
                        props.attach({
                          kind: 'image',
                          id: 'synthetic-sem-roi-01',
                          label: '합성 SEM · 검토 영역 01',
                        })
                      }
                    >
                      <span>ROI 01 · Synthetic</span>
                    </button>
                  )}
                </div>
              </div>
              <div className="selection-bar">
                <div>
                  <span className="eyebrow">IMAGE SOURCE</span>
                  <strong>synthetic-sem.png</strong>
                </div>
                <button
                  className="outline-button"
                  onClick={() =>
                    props.attach({
                      kind: 'image',
                      id: 'synthetic-sem',
                      label: 'AI 생성 합성 SEM',
                    })
                  }
                >
                  <Link2 size={14} />
                  검토 대상에 추가
                </button>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
