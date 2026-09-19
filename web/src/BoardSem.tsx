import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Columns2, Image, Layers, Maximize2, X } from 'lucide-react';
import type { Workspace } from './api';
import type { FabRow } from './engineeringData';
import { pairKey } from './engineeringAnalysis';
import { semRecord } from './investigationData';

export default function BoardSem({
  workspace,
  focused,
  selected,
  onFocus,
  overlay,
}: {
  workspace: Workspace;
  focused?: FabRow;
  selected: FabRow[];
  onFocus: (row: FabRow) => void;
  overlay: ReactNode;
}) {
  const [mode, setMode] = useState('single');
  const [compareKey, setCompareKey] = useState('');
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (expanded) dialog.current?.showModal();
  }, [expanded]);
  const options = selected.filter(
    (row) => !focused || pairKey(row) !== pairKey(focused),
  );
  const compare =
    options.find((row) => pairKey(row) === compareKey) || options[0];
  const renderImage = (row?: FabRow) => {
    const record = row && semRecord(workspace, row.lotId, row.waferId);
    return (
      <figure>
        {record ? (
          <img
            src={record.src}
            alt={`${record.lotId} / ${record.waferId} · ${record.provenance}`}
          />
        ) : (
          <div className="sem-missing">
            <Image size={23} />
            <span>{row ? 'SEM 미등록' : '선택 없음'}</span>
          </div>
        )}
        <figcaption>
          {row ? `${row.lotId} / ${row.waferId}` : '비교 대상 없음'}
          <small>{record ? record.provenance : '이미지 원본 미연결'}</small>
        </figcaption>
      </figure>
    );
  };
  const content = (
    <div className={`sem-preview ${mode === 'compare' ? 'comparison' : ''}`}>
      {mode === 'overlay' ? (
        overlay
      ) : (
        <>
          {renderImage(focused)}
          {mode === 'compare' && renderImage(compare)}
        </>
      )}
    </div>
  );
  return (
    <>
      <header>
        <h2>SEM · Overlay</h2>
        <div className="sem-modes" role="group" aria-label="SEM 표시 방식">
          {[
            ['single', '선택 SEM', Image],
            ['compare', 'SEM 두 개 비교', Columns2],
            ['overlay', '선택 Map Overlay', Layers],
          ].map(([id, title, Icon]: any) => (
            <button
              key={id}
              className="icon-button"
              title={title}
              aria-pressed={mode === id}
              onClick={() => setMode(id)}
            >
              <Icon size={14} />
            </button>
          ))}
        </div>
        <button
          className="icon-button"
          title="SEM 확대"
          onClick={() => setExpanded(true)}
        >
          <Maximize2 size={14} />
        </button>
      </header>
      {mode === 'compare' && (
        <select
          aria-label="SEM 비교 Wafer"
          value={compare ? pairKey(compare) : ''}
          onChange={(event) => setCompareKey(event.target.value)}
          disabled={!options.length}
        >
          {options.length ? (
            options.map((row) => (
              <option key={pairKey(row)} value={pairKey(row)}>
                {row.lotId} / {row.waferId}
              </option>
            ))
          ) : (
            <option value="">선택된 비교 Wafer 없음</option>
          )}
        </select>
      )}
      {content}
      <div className="sem-thumbnails" aria-label="선택 Wafer SEM 목록">
        {selected.map((row) => {
          const record = semRecord(workspace, row.lotId, row.waferId);
          return (
            <button
              key={pairKey(row)}
              title={`${row.lotId} / ${row.waferId} SEM${record ? ' · 합성' : ' · 미등록'}`}
              aria-pressed={!!focused && pairKey(row) === pairKey(focused)}
              onClick={() => onFocus(row)}
            >
              {record ? <img src={record.src} alt="" /> : <Image size={15} />}
              <span>{row.waferId}</span>
            </button>
          );
        })}
      </div>
      <footer>{selected.length}개 선택 · 실측 / 좌표 정렬 미연결</footer>
      {expanded && (
        <dialog
          className="sem-dialog"
          ref={dialog}
          onCancel={() => setExpanded(false)}
          onClose={() => setExpanded(false)}
        >
          <header>
            <h2>
              SEM ·{' '}
              {mode === 'compare'
                ? '비교'
                : mode === 'overlay'
                  ? 'Overlay'
                  : '선택 이미지'}
            </h2>
            <button
              className="icon-button"
              title="SEM 확대 닫기"
              onClick={() => setExpanded(false)}
            >
              <X size={18} />
            </button>
          </header>
          {content}
        </dialog>
      )}
    </>
  );
}
