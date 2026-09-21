import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import {
  ArrowLeftRight,
  ImageOff,
  Link2,
  Minus,
  Plus,
  RefreshCcw,
  Unlink2,
} from 'lucide-react';
import type { Workspace } from './api';
import type { FabRow } from './engineeringData';
import { pairKey } from './engineeringAnalysis';
import { semRecord } from './investigationData';
import './boardSem.css';

type Owner = 'A' | 'B';
type ViewState = { zoom: number; pan: { x: number; y: number } };
type ViewByOwner = Record<Owner, ViewState>;

const emptyView = (): ViewState => ({ zoom: 1, pan: { x: 0, y: 0 } });
const emptyViews = (): ViewByOwner => ({ A: emptyView(), B: emptyView() });

const shortTime = (timestamp: string) => {
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime())
    ? timestamp
    : `${parsed.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
};

export default function BoardSem({
  workspace,
  focused,
  compare,
  options,
}: {
  workspace: Workspace;
  focused?: FabRow;
  compare?: FabRow;
  options: FabRow[];
}) {
  const rows = useMemo(() => {
    const byKey = new Map<string, FabRow>();
    options.forEach((row) => {
      if (!byKey.has(pairKey(row))) byKey.set(pairKey(row), row);
    });
    return [...byKey.values()];
  }, [options]);
  const records = useMemo(
    () =>
      new Map(
        rows.flatMap((row) => {
          const record = semRecord(workspace, row.lotId, row.waferId);
          return record ? [[pairKey(row), record] as const] : [];
        }),
      ),
    [rows, workspace],
  );
  const focusedKey = focused ? pairKey(focused) : '';
  const compareKey = compare ? pairKey(compare) : '';
  const [selection, setSelection] = useState({
    focusedKey,
    compareKey,
    aKey: focusedKey,
    bKey: compareKey,
  });
  const rowFor = (key: string) => rows.find((row) => pairKey(row) === key);
  const requestedA =
    focusedKey !== selection.focusedKey && rowFor(focusedKey)
      ? focusedKey
      : selection.aKey;
  const requestedB =
    compareKey !== selection.compareKey && rowFor(compareKey)
      ? compareKey
      : selection.bKey;
  const aRow = rowFor(requestedA) || rowFor(focusedKey) || rows[0];
  const aKey = aRow ? pairKey(aRow) : '';
  const bOptions = rows.filter((row) => pairKey(row) !== aKey);
  const bRow =
    bOptions.find((row) => pairKey(row) === requestedB) ||
    bOptions.find((row) => pairKey(row) === compareKey) ||
    bOptions[0];
  const bKey = bRow ? pairKey(bRow) : '';

  // Consume changed parent keys and discard stale scope keys before rendering panes.
  if (
    selection.focusedKey !== focusedKey ||
    selection.compareKey !== compareKey ||
    selection.aKey !== aKey ||
    selection.bKey !== bKey
  ) {
    setSelection({ focusedKey, compareKey, aKey, bKey });
  }
  const [views, setViews] = useState<ViewByOwner>(emptyViews);
  const [sync, setSync] = useState(true);
  const [activeOwner, setActiveOwner] = useState<Owner>('A');
  const [failedSrc, setFailedSrc] = useState<Set<string>>(() => new Set());
  const drag = useRef<{
    owner: Owner;
    x: number;
    y: number;
    pan: { x: number; y: number };
  } | null>(null);

  useEffect(() => {
    setViews(emptyViews());
    drag.current = null;
  }, [aKey, bKey]);

  const updateView = (owner: Owner, next: Partial<ViewState>) => {
    setViews((current) => {
      const updated = { ...current[owner], ...next };
      return sync
        ? { A: { ...updated }, B: { ...updated } }
        : { ...current, [owner]: updated };
    });
  };
  const resetView = () => setViews(emptyViews());
  const adjustZoom = (delta: number) => {
    const owners: Owner[] = sync ? ['A', 'B'] : [activeOwner];
    setViews((current) => {
      const next = { ...current };
      owners.forEach((owner) => {
        const zoom = Math.max(
          1,
          Math.min(5, +(current[owner].zoom + delta).toFixed(2)),
        );
        next[owner] = {
          zoom,
          pan: zoom === 1 ? { x: 0, y: 0 } : current[owner].pan,
        };
      });
      return next;
    });
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const { owner, x, y, pan } = drag.current;
    const rect = event.currentTarget.getBoundingClientRect();
    const zoom = views[owner].zoom;
    const limit = Math.max(0, (zoom - 1) * 50);
    const clamp = (value: number) => Math.max(-limit, Math.min(limit, value));
    updateView(owner, {
      pan: {
        x: clamp(pan.x + ((event.clientX - x) / Math.max(1, rect.width)) * 100),
        y: clamp(
          pan.y + ((event.clientY - y) / Math.max(1, rect.height)) * 100,
        ),
      },
    });
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const selectA = (key: string) => {
    const row = rowFor(key);
    if (!row) return;
    setSelection((current) => ({
      ...current,
      aKey: key,
      bKey: key === bKey ? aKey : bKey,
    }));
  };
  const selectB = (key: string) => {
    const row = rowFor(key);
    if (!row || key === aKey) return;
    setSelection((current) => ({ ...current, aKey, bKey: key }));
  };

  const selectControl = (owner: Owner, row: FabRow | undefined) => (
    <label className="sem-select-field">
      <span className={`sem-owner sem-owner-${owner}`}>{owner}</span>
      <select
        aria-label={`SEM ${owner} 선택`}
        title={
          row
            ? `${row.lotId} / ${row.waferId} · ${row.equipment} · ${shortTime(row.timestamp)}`
            : '선택 없음'
        }
        value={row ? pairKey(row) : ''}
        onFocus={() => setActiveOwner(owner)}
        onChange={(event) =>
          owner === 'A'
            ? selectA(event.target.value)
            : selectB(event.target.value)
        }
      >
        {!row && (
          <option value="">
            {rows.length ? '비교 대상 없음' : '범위 내 Wafer 없음'}
          </option>
        )}
        {(owner === 'A' ? rows : bOptions).map((item) => {
          const record = records.get(pairKey(item));
          return (
            <option key={pairKey(item)} value={pairKey(item)}>
              {item.lotId} / {item.waferId} · {item.equipment} ·{' '}
              {shortTime(item.timestamp)} · {record ? 'SEM 등록' : 'SEM 미등록'}
            </option>
          );
        })}
      </select>
    </label>
  );

  const pane = (owner: Owner, row: FabRow | undefined) => {
    const record = row && records.get(pairKey(row));
    const view = views[owner];
    const detail = row
      ? `${row.equipment} · ${shortTime(row.timestamp)} · ${record?.description || 'SEM 미등록'}`
      : '선택 없음';
    return (
      <figure
        className={`sem-pane${!sync && activeOwner === owner ? ' sem-pane-active' : ''}`}
        key={owner}
      >
        <figcaption>{selectControl(owner, row)}</figcaption>
        <div
          className="sem-canvas"
          role="img"
          aria-label={`SEM ${owner} 검사 영역`}
          style={{ cursor: view.zoom > 1 ? 'grab' : 'default' }}
          onPointerDown={(event) => {
            setActiveOwner(owner);
            if (view.zoom <= 1) return;
            event.preventDefault();
            drag.current = {
              owner,
              x: event.clientX,
              y: event.clientY,
              pan: view.pan,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={move}
          onPointerUp={endDrag}
          onPointerCancel={() => {
            drag.current = null;
          }}
          onLostPointerCapture={() => {
            drag.current = null;
          }}
        >
          {record && !failedSrc.has(record.src) ? (
            <img
              src={record.src}
              alt={`${owner} ${row?.lotId}/${row?.waferId} SEM · ${record.description}`}
              draggable={false}
              style={{
                transform: `translate(${view.pan.x}%, ${view.pan.y}%) scale(${view.zoom})`,
              }}
              onError={() =>
                setFailedSrc((current) => new Set(current).add(record.src))
              }
              onLoad={() =>
                setFailedSrc((current) => {
                  if (!current.has(record.src)) return current;
                  const next = new Set(current);
                  next.delete(record.src);
                  return next;
                })
              }
            />
          ) : (
            <div className="sem-missing">
              <ImageOff size={18} />
              <span>
                {row
                  ? record
                    ? 'SEM 이미지를 불러올 수 없습니다'
                    : 'SEM 미등록'
                  : rows.length
                    ? '비교 대상 Wafer 없음'
                    : '범위 내 Wafer 없음'}
              </span>
              <small>다른 Lot/Wafer를 선택해 비교하세요</small>
            </div>
          )}
        </div>
        <small className="sem-pane-detail" title={detail}>
          {detail}
        </small>
      </figure>
    );
  };

  return (
    <div className="sem-viewer">
      <header className="sem-viewer-header">
        <h2>SEM 비교 검사</h2>
        <div className="sem-toolbar" role="toolbar" aria-label="SEM 검사 도구">
          <button
            className="icon-button"
            title="축소"
            aria-label="축소"
            onClick={() => adjustZoom(-0.25)}
          >
            <Minus size={13} />
          </button>
          <output
            aria-label={sync ? 'SEM A/B 배율' : `SEM ${activeOwner} 배율`}
            title={sync ? 'A/B 함께 검사' : `${activeOwner} 검사 중`}
          >
            {!sync && `${activeOwner} `}
            {(sync ? views.A.zoom : views[activeOwner].zoom).toFixed(2)}×
          </output>
          <button
            className="icon-button"
            title="확대"
            aria-label="확대"
            onClick={() => adjustZoom(0.25)}
          >
            <Plus size={13} />
          </button>
          <button
            className="icon-button"
            title="배율·위치 초기화"
            aria-label="배율·위치 초기화"
            onClick={resetView}
          >
            <RefreshCcw size={13} />
          </button>
          <label className="sem-sync-toggle" title="배율·이동 동기화">
            <input
              type="checkbox"
              aria-label="배율·이동 동기화"
              checked={sync}
              onChange={(event) => setSync(event.target.checked)}
            />
            {sync ? (
              <Link2 size={13} aria-hidden="true" />
            ) : (
              <Unlink2 size={13} aria-hidden="true" />
            )}
          </label>
          <button
            className="icon-button"
            title="A와 B 바꾸기"
            aria-label="A와 B 바꾸기"
            disabled={!aRow || !bRow}
            onClick={() => {
              if (!aRow || !bRow) return;
              setSelection((current) => ({
                ...current,
                aKey: bKey,
                bKey: aKey,
              }));
            }}
          >
            <ArrowLeftRight size={14} />
          </button>
        </div>
      </header>
      <div className="sem-panes">
        {pane('A', aRow)}
        {pane('B', bRow)}
      </div>
      <footer className="sem-viewer-footer">
        <span>합성 SEM · 실측 아님 · 이미지 모델 미연결</span>
        <span>
          전체 {rows.length} Wafers · SEM 등록{' '}
          {rows.filter((row) => records.has(pairKey(row))).length}
        </span>
      </footer>
    </div>
  );
}
