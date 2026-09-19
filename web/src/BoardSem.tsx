import { useEffect, useRef, useState, type PointerEvent } from 'react';
import {
  Columns2,
  Image,
  Maximize2,
  RotateCcw,
  ScanLine,
  X,
} from 'lucide-react';
import type { Workspace } from './api';
import type { FabRow } from './engineeringData';
import { pairKey } from './engineeringAnalysis';
import { semRecord } from './investigationData';

export default function BoardSem({
  workspace,
  focused,
  compare,
  selected,
  onFocus,
}: {
  workspace: Workspace;
  focused?: FabRow;
  compare?: FabRow;
  selected: FabRow[];
  onFocus: (row: FabRow) => void;
}) {
  const [requestedMode, setMode] = useState<'single' | 'compare' | 'wipe'>(
    'compare',
  );
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [wipe, setWipe] = useState(50);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
    null,
  );
  const dialog = useRef<HTMLDialogElement>(null);
  const a = focused && semRecord(workspace, focused.lotId, focused.waferId);
  const b = compare && semRecord(workspace, compare.lotId, compare.waferId);
  const mode =
    requestedMode === 'wipe' && (!a || !b) ? 'compare' : requestedMode;
  const reset = () => {
    drag.current = null;
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setWipe(50);
  };
  useEffect(reset, [
    focused?.lotId,
    focused?.waferId,
    compare?.lotId,
    compare?.waferId,
  ]);
  useEffect(() => {
    if (expanded) dialog.current?.showModal();
  }, [expanded]);
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const rect = event.currentTarget.getBoundingClientRect(),
      limit = (zoom - 1) * 50;
    const clamp = (v: number) => Math.max(-limit, Math.min(limit, v));
    setPan({
      x: clamp(
        drag.current.px + ((event.clientX - drag.current.x) / rect.width) * 100,
      ),
      y: clamp(
        drag.current.py +
          ((event.clientY - drag.current.y) / rect.height) * 100,
      ),
    });
  };
  const imageStyle = {
    transform: `translate(${pan.x}%,${pan.y}%) scale(${zoom})`,
  };
  const pane = (row: FabRow | undefined, label: string) => {
    const record = row && semRecord(workspace, row.lotId, row.waferId);
    return (
      <figure>
        <div
          className="sem-image-viewport"
          style={{
            cursor: zoom > 1 ? 'grab' : 'zoom-in',
            touchAction: zoom > 1 ? 'none' : 'auto',
          }}
          onDoubleClick={() => {
            setZoom(zoom > 1 ? 1 : 2);
            setPan({ x: 0, y: 0 });
          }}
          onPointerDown={(event) => {
            if (zoom <= 1) return;
            drag.current = {
              x: event.clientX,
              y: event.clientY,
              px: pan.x,
              py: pan.y,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={move}
          onPointerUp={() => {
            drag.current = null;
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
          onLostPointerCapture={() => {
            drag.current = null;
          }}
        >
          {record ? (
            <img
              draggable={false}
              style={imageStyle}
              src={record.src}
              alt={`${label} ${record.lotId}/${record.waferId} · ${record.description} · 합성`}
            />
          ) : (
            <div className="sem-missing">
              <Image size={20} />
              <span>{row ? 'SEM 미등록' : '선택 없음'}</span>
            </div>
          )}
        </div>
        <figcaption>
          <b>{label}</b> {row ? `${row.lotId}/${row.waferId}` : '없음'}
          <small>
            {row?.equipment} · {record?.description || '원본 미연결'}
          </small>
        </figcaption>
      </figure>
    );
  };
  const controls = (
    <div className="sem-inspection-controls">
      <label>
        View{' '}
        <input
          aria-label="SEM 확대 배율"
          type="range"
          min={1}
          max={4}
          step={0.25}
          value={zoom}
          onChange={(e) => {
            setZoom(+e.target.value);
            setPan({ x: 0, y: 0 });
          }}
        />
        <output>{zoom.toFixed(2)}×</output>
      </label>
      <button
        className="icon-button"
        title="SEM 배율·위치 초기화"
        onClick={reset}
      >
        <RotateCcw size={13} />
      </button>
      {mode === 'wipe' && (
        <label>
          A / B{' '}
          <input
            aria-label="SEM A B 비교 경계"
            type="range"
            min={0}
            max={100}
            value={wipe}
            onChange={(e) => setWipe(+e.target.value)}
          />
          <output>{wipe}%</output>
        </label>
      )}
    </div>
  );
  const content = (
    <div className={`sem-preview ${mode === 'compare' ? 'comparison' : ''}`}>
      {mode === 'wipe' && a && b ? (
        <figure>
          <div className="sem-wipe">
            <img style={imageStyle} src={a.src} alt="SEM A 합성" />
            <div
              className="sem-wipe-b"
              style={{ clipPath: `inset(0 0 0 ${wipe}%)` }}
            >
              <img style={imageStyle} src={b.src} alt="SEM B 합성" />
            </div>
            <i style={{ left: `${wipe}%` }} />
          </div>
          <figcaption>
            A {focused?.waferId} / B {compare?.waferId}
            <small>AI 합성 · 픽셀 정렬 / 배율 미검증</small>
          </figcaption>
        </figure>
      ) : (
        <>
          {pane(focused, 'A')}
          {mode !== 'single' && pane(compare, 'B')}
        </>
      )}
    </div>
  );
  const modes = (
    <div className="sem-modes" role="group" aria-label="SEM 표시 방식">
      {(
        [
          { id: 'single', title: '선택 SEM', Icon: Image },
          { id: 'compare', title: 'SEM 두 개 비교', Icon: Columns2 },
          { id: 'wipe', title: 'SEM A B 경계 비교', Icon: ScanLine },
        ] as const
      ).map(({ id, title, Icon }) => (
        <button
          key={id}
          className="icon-button"
          title={title}
          aria-pressed={mode === id}
          disabled={id === 'wipe' && (!a || !b)}
          onClick={() => setMode(id)}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
  return (
    <>
      <header>
        <h2>SEM A / B</h2>
        {modes}
        <button
          className="icon-button"
          title="SEM 확대"
          onClick={() => setExpanded(true)}
        >
          <Maximize2 size={14} />
        </button>
      </header>
      {controls}
      {content}
      <div className="sem-thumbnails" aria-label="선택 Wafer SEM 목록">
        {selected.map((row) => {
          const record = semRecord(workspace, row.lotId, row.waferId);
          return (
            <button
              key={pairKey(row)}
              title={`${row.lotId}/${row.waferId} SEM · ${row.equipment}`}
              aria-label={`${row.lotId}/${row.waferId} SEM 선택`}
              aria-pressed={!!focused && pairKey(row) === pairKey(focused)}
              onClick={() => onFocus(row)}
            >
              {record ? <img src={record.src} alt="" /> : <Image size={14} />}
              <span>{row.waferId}</span>
            </button>
          );
        })}
      </div>
      <footer>AI 합성 · 실제 SEM / 결함 판정 미연결</footer>
      {expanded && (
        <dialog
          ref={dialog}
          className="sem-dialog"
          onCancel={() => setExpanded(false)}
          onClose={() => setExpanded(false)}
        >
          <header>
            <h2>SEM 비교</h2>
            {modes}
            <button
              className="icon-button"
              title="SEM 확대 닫기"
              onClick={() => setExpanded(false)}
            >
              <X size={18} />
            </button>
          </header>
          {controls}
          {content}
        </dialog>
      )}
    </>
  );
}
