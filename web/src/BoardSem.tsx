import { useEffect, useRef, useState, type PointerEvent } from 'react';
import {
  Columns2,
  Hand,
  Image,
  Maximize2,
  RotateCcw,
  Scan,
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
  const [tool, setTool] = useState<'pan' | 'roi'>('roi');
  const [roi, setRoi] = useState<{
    owner: 'A' | 'B';
    bounds: { left: number; top: number; right: number; bottom: number };
  } | null>(null);
  const [failedSrc, setFailedSrc] = useState<Set<string>>(() => new Set());
  const [retryBySrc, setRetryBySrc] = useState<Record<string, number>>({});
  const [failedThumbnailSrc, setFailedThumbnailSrc] = useState<Set<string>>(
    () => new Set(),
  );
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
    null,
  );
  const roiDrag = useRef<{
    owner: 'A' | 'B';
    start: { x: number; y: number };
    viewport: HTMLDivElement;
  } | null>(null);
  const [aspectBySrc, setAspectBySrc] = useState<Record<string, number>>({});
  const dialog = useRef<HTMLDialogElement>(null);
  const a = focused && semRecord(workspace, focused.lotId, focused.waferId);
  const b = compare && semRecord(workspace, compare.lotId, compare.waferId);
  const clearThumbnailFailure = (src: string) => {
    setFailedThumbnailSrc((current) => {
      if (!current.has(src)) return current;
      const next = new Set(current);
      next.delete(src);
      return next;
    });
  };
  const markLoaded = (src: string) => {
    setFailedSrc((current) => {
      if (!current.has(src)) return current;
      const next = new Set(current);
      next.delete(src);
      return next;
    });
    clearThumbnailFailure(src);
  };
  const markFailed = (src: string) => {
    setFailedSrc((current) => {
      if (current.has(src)) return current;
      return new Set(current).add(src);
    });
  };
  const retry = (src: string) => {
    setFailedSrc((current) => {
      if (!current.has(src)) return current;
      const next = new Set(current);
      next.delete(src);
      return next;
    });
    setRetryBySrc((current) => ({
      ...current,
      [src]: (current[src] || 0) + 1,
    }));
  };
  const markThumbnailFailed = (src: string) => {
    setFailedThumbnailSrc((current) => {
      if (current.has(src)) return current;
      return new Set(current).add(src);
    });
  };
  const mode =
    requestedMode === 'wipe' &&
    (!a || !b || failedSrc.has(a.src) || failedSrc.has(b.src))
      ? 'compare'
      : requestedMode;
  const reset = () => {
    drag.current = null;
    roiDrag.current = null;
    setRoi(null);
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
    if (roiDrag.current) {
      const { owner, start, viewport } = roiDrag.current;
      const point = imagePoint(event, viewport);
      if (!point) return;
      setRoi({
        owner,
        bounds: {
          left: Math.min(start.x, point.x),
          top: Math.min(start.y, point.y),
          right: Math.max(start.x, point.x),
          bottom: Math.max(start.y, point.y),
        },
      });
      return;
    }
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
  const imagePoint = (
    event: PointerEvent<HTMLDivElement>,
    viewport: HTMLDivElement,
  ) => {
    const image = viewport.querySelector('img');
    if (!image || !image.naturalWidth || !image.naturalHeight) return null;
    const imageRect = image.getBoundingClientRect();
    const scale = Math.min(
      imageRect.width / image.naturalWidth,
      imageRect.height / image.naturalHeight,
    );
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    const left = imageRect.left + (imageRect.width - width) / 2;
    const top = imageRect.top + (imageRect.height - height) / 2;
    return {
      inside:
        event.clientX >= left &&
        event.clientX <= left + width &&
        event.clientY >= top &&
        event.clientY <= top + height,
      x: Math.max(0, Math.min(100, ((event.clientX - left) / width) * 100)),
      y: Math.max(0, Math.min(100, ((event.clientY - top) / height) * 100)),
    };
  };
  const pane = (row: FabRow | undefined, label: 'A' | 'B') => {
    const record = row && semRecord(workspace, row.lotId, row.waferId);
    const owner = label;
    return (
      <figure key={owner}>
        <div
          className="sem-image-viewport"
          style={{
            cursor:
              tool === 'roi' && zoom === 1
                ? 'crosshair'
                : zoom > 1
                  ? 'grab'
                  : 'zoom-in',
            touchAction: zoom > 1 || tool === 'roi' ? 'none' : 'auto',
          }}
          onDoubleClick={() => {
            setZoom(zoom > 1 ? 1 : 2);
            setPan({ x: 0, y: 0 });
            setTool(zoom > 1 ? 'roi' : 'pan');
          }}
          onPointerDown={(event) => {
            if (
              tool === 'roi' &&
              zoom === 1 &&
              record &&
              !failedSrc.has(record.src)
            ) {
              const point = imagePoint(event, event.currentTarget);
              if (!point?.inside) return;
              event.preventDefault();
              roiDrag.current = {
                owner,
                start: { x: point.x, y: point.y },
                viewport: event.currentTarget,
              };
              setRoi({
                owner,
                bounds: {
                  left: point.x,
                  top: point.y,
                  right: point.x,
                  bottom: point.y,
                },
              });
              event.currentTarget.setPointerCapture(event.pointerId);
              return;
            }
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
          onPointerUp={(event) => {
            drag.current = null;
            roiDrag.current = null;
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
          }}
          onPointerCancel={() => {
            drag.current = null;
            roiDrag.current = null;
          }}
          onLostPointerCapture={() => {
            drag.current = null;
            roiDrag.current = null;
          }}
        >
          {record && !failedSrc.has(record.src) ? (
            <img
              key={`${record.src}:${retryBySrc[record.src] || 0}`}
              draggable={false}
              style={imageStyle}
              src={record.src}
              alt={`${label} ${record.lotId}/${record.waferId} · ${record.description} · 합성`}
              onLoad={(event) => {
                const image = event.currentTarget;
                setAspectBySrc((previous) => ({
                  ...previous,
                  [record.src]: image.naturalWidth / image.naturalHeight,
                }));
                markLoaded(record.src);
              }}
              onError={() => markFailed(record.src)}
            />
          ) : record ? (
            <div className="sem-missing">
              <Image size={20} />
              <span>SEM 로드 실패</span>
              <button
                className="icon-button"
                title="SEM 다시 시도"
                aria-label="SEM 다시 시도"
                onClick={() => retry(record.src)}
              >
                <RotateCcw size={13} />
              </button>
            </div>
          ) : (
            <div className="sem-missing">
              <Image size={20} />
              <span>{row ? 'SEM 미등록' : '선택 없음'}</span>
            </div>
          )}
          {roi?.owner === owner &&
            zoom === 1 &&
            record &&
            !failedSrc.has(record.src) &&
            aspectBySrc[record.src] && (
              <div
                className="sem-roi-frame"
                style={{
                  width: `min(100cqw, ${aspectBySrc[record.src] * 100}cqh)`,
                  height: `min(100cqh, ${100 / aspectBySrc[record.src]}cqw)`,
                }}
              >
                <div
                  className="sem-roi-box"
                  style={{
                    left: `${roi.bounds.left}%`,
                    top: `${roi.bounds.top}%`,
                    width: `${roi.bounds.right - roi.bounds.left}%`,
                    height: `${roi.bounds.bottom - roi.bounds.top}%`,
                  }}
                  aria-label={`SEM ${owner} ROI ${roi.bounds.left.toFixed(1)}%,${roi.bounds.top.toFixed(1)}% - ${roi.bounds.right.toFixed(1)}%,${roi.bounds.bottom.toFixed(1)}%`}
                />
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
            const nextZoom = +e.target.value;
            setZoom(nextZoom);
            setPan({ x: 0, y: 0 });
            if (nextZoom > 1) setTool('pan');
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
      <div className="sem-tool-modes" role="group" aria-label="SEM 도구">
        <button
          className="icon-button"
          title="SEM 이미지 이동"
          aria-label="SEM 이미지 이동"
          aria-pressed={tool === 'pan'}
          onClick={() => setTool('pan')}
        >
          <Hand size={13} />
        </button>
        <button
          className="icon-button"
          title={
            mode === 'wipe'
              ? 'Wipe 비교에서는 ROI 선택을 사용할 수 없음'
              : zoom > 1
                ? 'ROI 선택은 1배율에서만 사용 가능'
                : 'SEM ROI 선택'
          }
          aria-label="SEM ROI 선택"
          aria-pressed={tool === 'roi'}
          disabled={zoom > 1 || mode === 'wipe'}
          onClick={() => setTool('roi')}
        >
          <Scan size={13} />
        </button>
      </div>
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
      {mode === 'wipe' &&
      a &&
      b &&
      !failedSrc.has(a.src) &&
      !failedSrc.has(b.src) ? (
        <figure>
          <div className="sem-wipe">
            <img
              key={`${a.src}:${retryBySrc[a.src] || 0}`}
              style={imageStyle}
              src={a.src}
              alt="SEM A 합성"
              onLoad={() => markLoaded(a.src)}
              onError={() => markFailed(a.src)}
            />
            <div
              className="sem-wipe-b"
              style={{ clipPath: `inset(0 0 0 ${wipe}%)` }}
            >
              <img
                key={`${b.src}:${retryBySrc[b.src] || 0}`}
                style={imageStyle}
                src={b.src}
                alt="SEM B 합성"
                onLoad={() => markLoaded(b.src)}
                onError={() => markFailed(b.src)}
              />
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
          { id: 'wipe', title: 'SEM A B 경계 비교', Icon: Scan },
        ] as const
      ).map(({ id, title, Icon }) => (
        <button
          key={id}
          className="icon-button"
          title={title}
          aria-pressed={mode === id}
          disabled={
            id === 'wipe' &&
            (!a || !b || failedSrc.has(a.src) || failedSrc.has(b.src))
          }
          onClick={() => {
            setMode(id);
            if (id === 'wipe') {
              setTool('pan');
              setRoi(null);
            }
          }}
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
      <section className="board-image-findings" aria-label="SEM 분석 내용">
        <p>
          A{' '}
          {(() => {
            const record =
              focused && semRecord(workspace, focused.lotId, focused.waferId);
            return !record || !record.src
              ? '미등록'
              : failedSrc.has(record.src)
                ? '로드 실패'
                : record.description;
          })()}{' '}
          · B{' '}
          {(() => {
            const record =
              compare && semRecord(workspace, compare.lotId, compare.waferId);
            return !record || !record.src
              ? '미등록'
              : failedSrc.has(record.src)
                ? '로드 실패'
                : record.description;
          })()}
        </p>
        <small>합성 자료 설명 · 모델 판정 미연결</small>
        <p className="sem-roi-coordinates" aria-live="polite">
          {roi && (
            <>
              ROI {roi.owner}: {roi.bounds.left.toFixed(1)}%,{' '}
              {roi.bounds.top.toFixed(1)}% - {roi.bounds.right.toFixed(1)}%,{' '}
              {roi.bounds.bottom.toFixed(1)}%
            </>
          )}
        </p>
      </section>
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
              {record && !failedThumbnailSrc.has(record.src) ? (
                <img
                  src={record.src}
                  alt=""
                  onLoad={() => clearThumbnailFailure(record.src)}
                  onError={() => markThumbnailFailed(record.src)}
                />
              ) : (
                <Image size={14} />
              )}
              <span>{row.waferId}</span>
            </button>
          );
        })}
      </div>
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
