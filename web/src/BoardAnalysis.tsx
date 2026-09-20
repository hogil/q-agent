import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Download, Loader2, Play, Send, X } from 'lucide-react';
import {
  api,
  download,
  type Attachment,
  type Room,
  type RoomSummary,
} from './api';

const sourceOptions = [
  ['incident', '사고 DB'],
  ['trend', 'Trend'],
  ['correlation', 'Fab × EDS'],
  ['maps', 'Map'],
  ['sem', 'SEM'],
  ['production', '재공 / 다운'],
  ['inform', 'Eng’r Inform'],
  ['meetings', '회의록'],
  ['changes', '변경 이력'],
] as const;
export type AnalysisContext = {
  incident_number: string;
  item: string;
  step: string;
  equipment: string;
  from: string;
  to: string;
  wafers: { lot_id: string; wafer_id: string }[];
};
type Analysis = {
  mode: 'demo';
  llm_connected: false;
  sources: string[];
  context: AnalysisContext;
  steps: {
    source: string;
    status: 'completed' | 'unavailable';
    detail: string;
  }[];
};
type Response = {
  messages: Room['messages'];
  room: RoomSummary;
  analysis: Analysis;
};

export default function BoardAnalysis({
  roomId,
  context,
  onChange,
  attachments = [],
  notes = '',
  onNotes = () => undefined,
  onRemoveAttachment = () => undefined,
  onOpenAttachment = () => undefined,
}: {
  roomId: string;
  context: AnalysisContext;
  onChange: () => void;
  attachments?: Attachment[];
  notes?: string;
  onNotes?: (value: string) => void;
  onRemoveAttachment?: (item: Attachment) => void;
  onOpenAttachment?: (item: Attachment) => void;
}) {
  const [sources, setSources] = useState<string[]>(
    sourceOptions.map(([id]) => id),
  );
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [messages, setMessages] = useState<Room['messages']>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [panelTab, setPanelTab] = useState<'results' | 'review'>('results');
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(true);
  const roomRef = useRef(roomId);
  roomRef.current = roomId;
  const pinned = attachments.slice(0, 8);
  const tabBase = `board-analysis-${roomId}`;
  const resultsTabId = `${tabBase}-results-tab`;
  const reviewTabId = `${tabBase}-review-tab`;
  const resultsPanelId = `${tabBase}-results-panel`;
  const reviewPanelId = `${tabBase}-review-panel`;
  useEffect(() => {
    mounted.current = true;
    let active = true;
    api<{ analysis: Analysis | null }>(`/rooms/${roomId}/analysis`)
      .then((result) => {
        if (!active) return;
        setAnalysis(result.analysis);
        if (result.analysis) setSources(result.analysis.sources);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    api<Room>(`/rooms/${roomId}`)
      .then((result) => {
        if (active) setMessages(result.messages);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      mounted.current = false;
    };
  }, [roomId]);
  useEffect(() => {
    if (expanded) dialog.current?.showModal();
  }, [expanded]);
  const sameContext = (a: AnalysisContext, b: AnalysisContext) =>
    ['incident_number', 'item', 'step', 'equipment', 'from', 'to'].every(
      (key) =>
        a[key as keyof AnalysisContext] === b[key as keyof AnalysisContext],
    ) &&
    JSON.stringify(a.wafers.map((w) => [w.lot_id, w.wafer_id]).sort()) ===
      JSON.stringify(b.wafers.map((w) => [w.lot_id, w.wafer_id]).sort());
  const stale =
    !!analysis &&
    (!sameContext(analysis.context, context) ||
      [...analysis.sources].sort().join() !== [...sources].sort().join());
  const latest = messages
    .filter((message) => message.role === 'assistant')
    .at(-1);
  async function run(followup = false) {
    if (busy || (followup && (!draft.trim() || !analysis || stale))) return;
    const runRoomId = roomId;
    setBusy(true);
    setError('');
    try {
      const result = await api<Response>(
        `/rooms/${roomId}/analysis`,
        'POST',
        followup
          ? { content: draft.trim() }
          : {
              content: `${context.item} / ${context.step} / ${context.equipment || '전체 설비'} 선택 자료 분석`,
              sources,
              context,
            },
      );
      if (!mounted.current || roomRef.current !== runRoomId) return;
      setAnalysis(result.analysis);
      setMessages((previous) => [...previous, ...result.messages]);
      setDraft('');
      onChange();
    } catch (e) {
      if (mounted.current && roomRef.current === runRoomId)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && roomRef.current === runRoomId) setBusy(false);
    }
  }
  function downloadManualReview() {
    download(
      `${context.incident_number}-manual-review.json`,
      JSON.stringify(
        {
          synthetic: true,
          review_type: 'manual_notes_not_agent_verdict',
          context_snapshot: context,
          current_notes: notes,
          refs: pinned,
        },
        null,
        2,
      ),
      'application/json',
    );
  }
  const compose = (
    <form
      className="board-chat-compose"
      onSubmit={(event) => {
        event.preventDefault();
        void run(true);
      }}
    >
      <input
        aria-label="분석 후 추가 질문"
        placeholder={
          stale ? '조건 변경 · 다시 분석 필요' : '같은 분석에 추가 질문'
        }
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        maxLength={12000}
        disabled={busy || !analysis || stale}
      />
      <button
        className="icon-button"
        title="추가 질문 보내기"
        disabled={busy || !draft.trim() || !analysis || stale}
      >
        <Send size={14} />
      </button>
    </form>
  );
  return (
    <>
      <header>
        <h2>에이전트 분석 · 채팅</h2>
        <span>LLM 미연결</span>
        <button
          className="icon-button"
          title="분석 대화 전체 보기"
          onClick={() => setExpanded(true)}
        >
          <ArrowUpRight size={14} />
        </button>
      </header>
      {panelTab === 'results' && (
        <>
          <fieldset className="board-source-checks" disabled={busy}>
            <legend className="sr-only">분석에 포함할 자료</legend>
            {sourceOptions.map(([id, label]) => (
              <label key={id}>
                <input
                  type="checkbox"
                  checked={sources.includes(id)}
                  disabled={id === 'incident'}
                  onChange={(event) =>
                    setSources((previous) =>
                      event.target.checked
                        ? [...previous, id]
                        : previous.filter((source) => source !== id),
                    )
                  }
                />
                {label}
              </label>
            ))}
          </fieldset>
          <div className="board-run-row">
            <span>
              {context.item} · {context.wafers.length} Wafers
            </span>
            <button
              className="board-run"
              onClick={() => void run()}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="spin" size={12} />
              ) : (
                <Play size={12} />
              )}
              {busy ? '조회 중' : stale ? '현재 조건 분석' : '분석 실행'}
            </button>
          </div>
        </>
      )}
      <nav
        className="board-analysis-tabs"
        role="tablist"
        aria-label="분석 패널"
        onKeyDown={(event) => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key))
            return;
          event.preventDefault();
          const next =
            event.key === 'Home'
              ? 'results'
              : event.key === 'End'
                ? 'review'
                : panelTab === 'results'
                  ? 'review'
                  : 'results';
          setPanelTab(next);
          event.currentTarget
            .querySelectorAll('button')
            [next === 'results' ? 0 : 1]?.focus();
        }}
      >
        <button
          id={resultsTabId}
          role="tab"
          aria-selected={panelTab === 'results'}
          aria-controls={resultsPanelId}
          tabIndex={panelTab === 'results' ? 0 : -1}
          className={panelTab === 'results' ? 'active' : ''}
          onClick={() => setPanelTab('results')}
        >
          조회 결과
        </button>
        <button
          id={reviewTabId}
          role="tab"
          aria-selected={panelTab === 'review'}
          aria-controls={reviewPanelId}
          tabIndex={panelTab === 'review' ? 0 : -1}
          className={panelTab === 'review' ? 'active' : ''}
          onClick={() => setPanelTab('review')}
        >
          엔지니어 검토{' '}
          <span className="board-review-tab-badge">{pinned.length}</span>
        </button>
      </nav>
      {panelTab === 'results' ? (
        <div
          id={resultsPanelId}
          role="tabpanel"
          aria-labelledby={resultsTabId}
          tabIndex={0}
          className="board-analysis-output"
          aria-live="polite"
        >
          {error ? (
            <p role="alert">{error}</p>
          ) : busy ? (
            <p role="status">선택 범위 검증 및 합성 DB 조회 중</p>
          ) : analysis ? (
            <>
              <div className="board-analysis-status">
                {stale ? '이전 조건 결과' : '조회 완료'} ·{' '}
                {
                  analysis.steps.filter((step) => step.status === 'completed')
                    .length
                }
                개 조회 ·{' '}
                {
                  analysis.steps.filter((step) => step.status === 'unavailable')
                    .length
                }
                개 미연결
              </div>
              <p>{latest?.content}</p>
            </>
          ) : (
            <p>분석 대기 · 실제 LLM 추론 미연결</p>
          )}
        </div>
      ) : (
        <section
          id={reviewPanelId}
          role="tabpanel"
          aria-labelledby={reviewTabId}
          tabIndex={0}
          className="board-engineer-review"
          aria-label="엔지니어 검토"
        >
          <header className="board-review-header">
            <span>고정 참조 {pinned.length}/8</span>
            <button
              className="icon-button"
              title="수동 검토 JSON 다운로드"
              aria-label="수동 검토 JSON 다운로드"
              onClick={downloadManualReview}
            >
              <Download size={14} />
            </button>
          </header>
          {pinned.length ? (
            <ul className="board-review-list">
              {pinned.map((item) => (
                <li
                  key={`${item.kind}:${item.id}`}
                  className="board-review-item"
                >
                  <span className="board-review-ref">
                    <strong>{item.kind}</strong>
                    <span>{item.label}</span>
                  </span>
                  <span className="board-review-actions">
                    <button
                      className="icon-button"
                      title={`${item.label} 열기`}
                      aria-label={`${item.label} 열기`}
                      onClick={() => onOpenAttachment(item)}
                    >
                      <ArrowUpRight size={14} />
                    </button>
                    <button
                      className="icon-button"
                      title={`${item.label} 고정 해제`}
                      aria-label={`${item.label} 고정 해제`}
                      onClick={() => onRemoveAttachment(item)}
                    >
                      <X size={14} />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="board-review-empty">고정 참조 없음</p>
          )}
          <label className="board-review-notes">
            엔지니어 검토 메모
            <textarea
              aria-label="엔지니어 검토 메모"
              value={notes}
              maxLength={8000}
              onChange={(event) => onNotes(event.target.value)}
            />
            <span>{notes.length}/8000 · 수동 메모이며 AI 판정이 아닙니다.</span>
          </label>
        </section>
      )}
      {panelTab === 'results' && compose}
      {expanded && (
        <dialog
          className="analysis-dialog"
          ref={dialog}
          onCancel={() => setExpanded(false)}
          onClose={() => setExpanded(false)}
        >
          <header>
            <h2>분석 대화</h2>
            <span>{context.incident_number} · 합성 DB / LLM 미연결</span>
            <button
              className="icon-button"
              title="분석 대화 닫기"
              onClick={() => setExpanded(false)}
            >
              <X size={18} />
            </button>
          </header>
          {analysis && (
            <div className="analysis-trace">
              {analysis.steps.map((step) => (
                <div key={step.source}>
                  <strong>
                    {sourceOptions.find(([id]) => id === step.source)?.[1] ||
                      step.source}
                  </strong>
                  <span>
                    {step.status === 'completed' ? '조회 완료' : '미연결'}
                  </span>
                  <p>{step.detail}</p>
                </div>
              ))}
            </div>
          )}
          <div className="analysis-chat-log">
            {messages.map((message) => (
              <article key={message.id} className={message.role}>
                <strong>
                  {message.role === 'user' ? '질문' : '합성 DB 조회 결과'}
                </strong>
                <p>{message.content}</p>
              </article>
            ))}
          </div>
          {error && <p role="alert">{error}</p>}
          {panelTab === 'results' && compose}
        </dialog>
      )}
    </>
  );
}
