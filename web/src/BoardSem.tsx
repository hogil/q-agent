import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import {
  ArrowLeftRight,
  ChevronDown,
  Check,
  History,
  ImageOff,
  Link2,
  Minus,
  Plus,
  RefreshCcw,
  Unlink2,
  X,
} from 'lucide-react';
import type { Workspace } from './api';
import type { FabRow } from './engineeringData';
import { pairKey } from './engineeringAnalysis';
import { filterSemWafers, semRecord } from './investigationData';
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

function WaferSearch({
  owner,
  row,
  options,
  onSelect,
  onFocus,
}: {
  owner: Owner;
  row?: FabRow;
  options: FabRow[];
  onSelect: (key: string) => void;
  onFocus: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    return () => trigger.current?.focus({ preventScroll: true });
  }, [open]);
  const label = (item: FabRow) => `${item.lotId} / ${item.waferId}`;
  const selected = row ? label(row) : '';
  const matches = filterSemWafers(options, query);
  const choose = (item: FabRow) => {
    onSelect(pairKey(item));
    setOpen(false);
  };
  return (
    <div className="sem-select-field">
      <span className={`sem-owner sem-owner-${owner}`}>{owner}</span>
      <button
        ref={trigger}
        type="button"
        className="sem-wafer-trigger"
        aria-label={`SEM ${owner} Lot/Wafer 검색`}
        aria-haspopup="dialog"
        title={selected || 'Lot / Wafer'}
        disabled={!options.length}
        onFocus={onFocus}
        onClick={() => {
          setQuery('');
          setOpen(true);
        }}
      >
        <span>{selected || 'Wafer 없음'}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <dialog
          ref={dialog}
          className="analysis-dialog sem-wafer-dialog"
          aria-label={`SEM ${owner} Lot/Wafer 선택`}
          onCancel={() => setOpen(false)}
          onClose={() => setOpen(false)}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
          }}
        >
          <header>
            <h2>SEM {owner} · Lot / Wafer</h2>
            <button
              type="button"
              className="icon-button"
              aria-label="SEM Wafer 선택 닫기"
              onClick={() => setOpen(false)}
            >
              <X size={16} />
            </button>
          </header>
          <input
            type="search"
            autoFocus
            aria-label="Lot/Wafer 검색어"
            placeholder="Lot / Wafer"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.nativeEvent.isComposing &&
                matches.length === 1
              ) {
                event.preventDefault();
                event.stopPropagation();
                choose(matches[0]);
              }
            }}
          />
          <div className="sem-wafer-columns">
            <span>Lot</span>
            <span>Wafer</span>
          </div>
          <div className="sem-wafer-results">
            {matches.map((item) => (
              <button
                key={pairKey(item)}
                type="button"
                aria-label={label(item)}
                aria-pressed={!!row && pairKey(item) === pairKey(row)}
                onClick={() => choose(item)}
              >
                <span>{item.lotId}</span>
                <span>{item.waferId}</span>
                {row && pairKey(item) === pairKey(row) && <Check size={13} />}
              </button>
            ))}
            {!matches.length && <p role="status">일치하는 Lot/Wafer 없음</p>}
          </div>
        </dialog>
      )}
    </div>
  );
}

export default function BoardSem({
  workspace,
  focused,
  compare,
  options,
  onComparisonChange,
  currentItem,
}: {
  workspace: Workspace;
  focused?: FabRow;
  compare?: FabRow;
  options: FabRow[];
  onComparisonChange?: (wafers: { lot_id: string; wafer_id: string }[]) => void;
  currentItem: string;
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

  useEffect(() => {
    onComparisonChange?.(
      [aRow, bRow].flatMap((row) =>
        row ? [{ lot_id: row.lotId, wafer_id: row.waferId }] : [],
      ),
    );
  }, [aKey, bKey, onComparisonChange]);

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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState('');
  const historyDialog = useRef<HTMLDialogElement>(null);
  const historyTrigger = useRef<HTMLButtonElement>(null);
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

  const historyCandidates = useMemo(() => {
    const currentTime = aRow ? Date.parse(aRow.timestamp) : Number.NaN;
    const step = aRow?.step;
    return (workspace.raw?.image_history ?? [])
      .filter((image) => {
        const occurredAt = Date.parse(image.occurred_at);
        return (
          image.modality === 'sem' &&
          !!image.src &&
          !!step &&
          image.step === step &&
          Number.isFinite(currentTime) &&
          Number.isFinite(occurredAt) &&
          occurredAt < currentTime &&
          image.item === currentItem
        );
      })
      .sort(
        (left, right) =>
          Date.parse(right.occurred_at) - Date.parse(left.occurred_at),
      );
  }, [currentItem, aRow, workspace.raw?.image_history]);

  const selectedHistory =
    historyCandidates.find((image) => image.id === selectedHistoryId) ||
    historyCandidates[0];

  useEffect(() => {
    if (!historyOpen) return;
    historyDialog.current?.showModal();
    setSelectedHistoryId((current) =>
      historyCandidates.some((image) => image.id === current)
        ? current
        : historyCandidates[0]?.id || '',
    );
    return () => historyTrigger.current?.focus({ preventScroll: true });
  }, [historyOpen, historyCandidates]);

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
    <WaferSearch
      owner={owner}
      row={row}
      options={owner === 'A' ? rows : bOptions}
      onSelect={owner === 'A' ? selectA : selectB}
      onFocus={() => setActiveOwner(owner)}
    />
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
          <button
            ref={historyTrigger}
            className="icon-button"
            title="과거 합성 SEM 보기"
            aria-label="과거 합성 SEM 보기"
            disabled={!historyCandidates.length || !aRow}
            onClick={() => setHistoryOpen(true)}
          >
            <History size={14} />
          </button>
        </div>
      </header>
      <div className="sem-panes">
        {pane('A', aRow)}
        {pane('B', bRow)}
      </div>
      <footer className="sem-viewer-footer">
        <span>합성 SEM · 실측 아님 · 정렬 미검증</span>
        <span>
          전체 {rows.length} Wafers · SEM 등록{' '}
          {rows.filter((row) => records.has(pairKey(row))).length}
        </span>
      </footer>
      {historyOpen && (
        <dialog
          ref={historyDialog}
          className="analysis-dialog sem-history-dialog"
          aria-label="과거 합성 SEM 비교"
          onCancel={() => setHistoryOpen(false)}
          onClose={() => setHistoryOpen(false)}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            setHistoryOpen(false);
          }}
        >
          <header>
            <div>
              <h2>과거 합성 SEM 참고</h2>
            </div>
            <button
              type="button"
              className="icon-button"
              aria-label="과거 합성 SEM 닫기"
              onClick={() => setHistoryOpen(false)}
            >
              <X size={16} />
            </button>
          </header>
          {selectedHistory ? (
            <>
              <div className="sem-history-images">
                <figure>
                  <figcaption>현재 A</figcaption>
                  <div className="sem-history-image">
                    {aRow && records.get(aKey)?.src ? (
                      <img src={records.get(aKey)?.src} alt="현재 A SEM" />
                    ) : (
                      <span>현재 A SEM 없음</span>
                    )}
                  </div>
                </figure>
                <figure>
                  <figcaption>과거 참고 · 합성 과거 사고</figcaption>
                  <div className="sem-history-image">
                    <img
                      src={selectedHistory.src}
                      alt={`${selectedHistory.incident_number} 과거 합성 SEM`}
                    />
                  </div>
                </figure>
              </div>
              <div
                className="sem-history-candidates"
                role="listbox"
                aria-label="과거 SEM 참고 이미지"
              >
                {historyCandidates.map((image) => (
                  <button
                    key={image.id}
                    type="button"
                    role="option"
                    aria-selected={image.id === selectedHistory.id}
                    onClick={() => setSelectedHistoryId(image.id)}
                  >
                    <strong>{image.incident_number}</strong>
                    <span>{shortTime(image.occurred_at)}</span>
                    <small>{image.description}</small>
                  </button>
                ))}
              </div>
              <dl className="sem-history-meta">
                <div>
                  <dt>사고번호</dt>
                  <dd>{selectedHistory.incident_number}</dd>
                </div>
                <div>
                  <dt>발생일</dt>
                  <dd>{shortTime(selectedHistory.occurred_at)}</dd>
                </div>
                <div>
                  <dt>설명</dt>
                  <dd>{selectedHistory.description}</dd>
                </div>
                <div>
                  <dt>출처</dt>
                  <dd>{selectedHistory.provenance}</dd>
                </div>
              </dl>
              <p className="sem-history-notice">
                합성 과거 사고 참고 이미지이며, 생산 유사도 또는 원인 판정을
                의미하지 않습니다.
              </p>
            </>
          ) : (
            <p className="sem-history-empty">
              현재 step과 시각 조건에 맞는 과거 SEM 참고 이미지가 없습니다.
            </p>
          )}
        </dialog>
      )}
    </div>
  );
}
