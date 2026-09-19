import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Loader2, Play, Send, X } from 'lucide-react';
import { api, type Room, type RoomSummary } from './api';

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
}: {
  roomId: string;
  context: AnalysisContext;
  onChange: () => void;
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
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(true);
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
      if (!mounted.current) return;
      setAnalysis(result.analysis);
      setMessages((previous) => [...previous, ...result.messages]);
      setDraft('');
      onChange();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
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
          {busy ? <Loader2 className="spin" size={12} /> : <Play size={12} />}
          {busy ? '조회 중' : stale ? '현재 조건 분석' : '분석 실행'}
        </button>
      </div>
      <div className="board-analysis-output" aria-live="polite">
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
      {compose}
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
          {compose}
        </dialog>
      )}
    </>
  );
}
