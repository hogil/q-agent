import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  ChevronRight,
  CircleAlert,
  Clock3,
  Download,
  History,
  Loader2,
  Play,
  Send,
  X,
} from 'lucide-react';
import {
  api,
  download,
  type Attachment,
  type Bootstrap,
  type Room,
  type RoomSummary,
} from './api';
import './boardAnalysis.css';

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
  mode: 'demo' | 'llm';
  llm_connected: boolean;
  status?: string;
  trace?: { role: string; model: string; step: number }[];
  sources: string[];
  context: AnalysisContext;
  steps: {
    source: string;
    status: 'completed' | 'unavailable';
    detail: string;
  }[];
};
type ProgressEvent = {
  event: string;
  role?: string;
  model?: string;
  step?: number | string;
  source?: string;
  status?: string;
  error?: string;
  time?: string;
};
type ProgressRun = {
  id: string;
  status: 'running' | 'completed' | 'failed';
  context: AnalysisContext;
  sources: string[];
  events: ProgressEvent[];
  started_at?: string;
  finished_at?: string;
  error?: string;
};
type ProgressResponse = { run: ProgressRun | null };
type Response = {
  messages: Room['messages'];
  room: RoomSummary;
  analysis: Analysis;
};

const sameContext = (a: AnalysisContext, b: AnalysisContext) =>
  ['incident_number', 'item', 'step', 'equipment', 'from', 'to'].every(
    (key) =>
      a[key as keyof AnalysisContext] === b[key as keyof AnalysisContext],
  ) &&
  JSON.stringify(a.wafers.map((w) => [w.lot_id, w.wafer_id]).sort()) ===
    JSON.stringify(b.wafers.map((w) => [w.lot_id, w.wafer_id]).sort());

const sameSources = (a: string[], b: string[]) =>
  [...a].sort().join('|') === [...b].sort().join('|');

const eventText = (event: ProgressEvent) => {
  const name = event.event.replaceAll('_', ' ');
  const role = event.role ? ` · ${event.role}` : '';
  const source = event.source ? ` · ${event.source}` : '';
  return `${name}${role}${source}`;
};

const eventLabel = (event: ProgressEvent) => {
  const labels: Record<string, string> = {
    scope_validated: '분석 범위 확인',
    llm_start: event.role ? `${event.role} 단계 시작` : '모델 단계 시작',
    llm_output: event.role ? `${event.role} 응답 수신` : '모델 응답 수신',
    tool_result: event.source ? `${event.source} 결과 수신` : 'Tool 결과 수신',
    source_result: event.source
      ? `${event.source} 결과 수신`
      : '자료 결과 수신',
    route_selected: '분석 경로 선택',
    validation_or_tool_error: '조회 또는 검증 오류',
    run_error: '실행 오류',
  };
  return labels[event.event] || '분석 진행 중';
};

const elapsedText = (run: ProgressRun) => {
  const started = Date.parse(
    run.started_at || run.events.find((event) => event.time)?.time || '',
  );
  if (!Number.isFinite(started)) return '';
  const finished =
    run.status === 'running'
      ? Date.now()
      : Date.parse(run.finished_at || '') || Date.now();
  const seconds = Math.max(0, Math.round((finished - started) / 1000));
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}분 ${remainder}초` : `${minutes}분`;
};

export default function BoardAnalysis({
  roomId,
  autoKey,
  context,
  onChange,
  attachments = [],
  notes = '',
  onNotes = () => undefined,
  onRemoveAttachment = () => undefined,
  onOpenAttachment = () => undefined,
}: {
  roomId: string;
  autoKey: string;
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
  const [runtime, setRuntime] = useState<Bootstrap | null>(null);
  const [messages, setMessages] = useState<Room['messages']>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ProgressRun | null>(null);
  const [loadedRoom, setLoadedRoom] = useState('');
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [panelTab, setPanelTab] = useState<'results' | 'review'>('results');
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(true);
  const roomRef = useRef(roomId);
  const autoKeyRef = useRef(autoKey);
  const contextRef = useRef(context);
  const sourcesRef = useRef(sources);
  const busyRef = useRef(false);
  const progressRef = useRef<ProgressRun | null>(null);
  const generationRef = useRef(0);
  const requestRef = useRef(0);
  const autoStartedRef = useRef(new Set<string>());
  roomRef.current = roomId;
  autoKeyRef.current = autoKey;
  contextRef.current = context;
  sourcesRef.current = sources;
  const pinned = attachments.slice(0, 8);
  const tabBase = `board-analysis-${roomId}`;
  const resultsTabId = `${tabBase}-results-tab`;
  const reviewTabId = `${tabBase}-review-tab`;
  const resultsPanelId = `${tabBase}-results-panel`;
  const reviewPanelId = `${tabBase}-review-panel`;
  useEffect(() => {
    mounted.current = true;
    ++generationRef.current;
    let active = true;
    setLoadedRoom('');
    setBusy(false);
    busyRef.current = false;
    progressRef.current = null;
    setProgress(null);
    setAnalysis(null);
    setMessages([]);
    setError('');
    autoStartedRef.current.clear();
    api<Bootstrap>('/bootstrap')
      .then((result) => {
        if (active) setRuntime(result);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    Promise.all([
      api<{ analysis: Analysis | null }>(`/rooms/${roomId}/analysis`),
      api<ProgressResponse>(`/rooms/${roomId}/analysis/progress`),
      api<Room>(`/rooms/${roomId}`),
    ])
      .then(([analysisResult, progressResult, roomResult]) => {
        if (!active) return;
        setAnalysis(analysisResult.analysis);
        if (analysisResult.analysis)
          setSources(analysisResult.analysis.sources);
        progressRef.current = progressResult.run;
        setProgress(progressResult.run);
        setMessages(roomResult.messages);
        setLoadedRoom(roomId);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      ++generationRef.current;
      busyRef.current = false;
      mounted.current = false;
    };
  }, [roomId]);
  useEffect(() => {
    if (expanded) dialog.current?.showModal();
  }, [expanded]);
  const stale =
    !!analysis &&
    (!sameContext(analysis.context, context) ||
      [...analysis.sources].sort().join() !== [...sources].sort().join());
  const latest = messages
    .filter((message) => message.role === 'assistant')
    .at(-1);
  const currentProgress =
    progress &&
    sameContext(progress.context, context) &&
    sameSources(progress.sources, sources)
      ? progress
      : null;
  const remoteBusy = progress?.status === 'running';
  const effectiveBusy = busy || remoteBusy;
  const otherContextBusy = remoteBusy && !currentProgress;
  const failedCurrentRun = currentProgress?.status === 'failed';
  const latestProgressEvent = currentProgress?.events.at(-1);
  const progressError =
    currentProgress?.error ||
    [...(currentProgress?.events || [])].reverse().find((event) => event.error)
      ?.error ||
    '';
  const completedStepCount =
    analysis?.steps.filter((step) => step.status === 'completed').length || 0;
  const unavailableStepCount =
    analysis?.steps.filter((step) => step.status === 'unavailable').length || 0;
  const llmLabel = runtime?.llm_configured
    ? `${runtime.models?.router || 'LLM'} · ${effectiveBusy ? '분석 중' : analysis?.llm_connected || runtime.llm_connected ? '응답 확인' : '연결 확인 전'}`
    : 'LLM 미연결';

  async function refreshProgress() {
    const generation = generationRef.current;
    const request = requestRef.current;
    const isCurrent = () =>
      mounted.current &&
      roomRef.current === roomId &&
      generationRef.current === generation &&
      requestRef.current === request;
    try {
      const result = await api<ProgressResponse>(
        `/rooms/${roomId}/analysis/progress`,
      );
      if (!isCurrent()) return;
      const next = result.run;
      if (next?.status === 'completed') {
        const [stored, room] = await Promise.all([
          api<{ analysis: Analysis | null }>(`/rooms/${roomId}/analysis`),
          api<Room>(`/rooms/${roomId}`),
        ]);
        if (!isCurrent()) return;
        if (
          stored.analysis &&
          sameContext(stored.analysis.context, next.context) &&
          sameContext(stored.analysis.context, contextRef.current) &&
          sameSources(stored.analysis.sources, sourcesRef.current)
        ) {
          setAnalysis(stored.analysis);
          setMessages(room.messages);
          onChange();
        }
      }
      progressRef.current = next;
      setProgress(next);
      return next;
    } catch (e) {
      if (isCurrent()) setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (loadedRoom !== roomId || !effectiveBusy) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(async () => {
      if (!active || polling) return;
      polling = true;
      await refreshProgress();
      polling = false;
    }, 700);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [loadedRoom, roomId, effectiveBusy]);

  async function execute(request: {
    followup: boolean;
    key: string;
    requestContext: AnalysisContext;
    requestSources: string[];
    content?: string;
  }) {
    if (busyRef.current || progressRef.current?.status === 'running') return;
    const runRoomId = roomId;
    const generation = generationRef.current;
    const isCurrent = () =>
      mounted.current &&
      roomRef.current === runRoomId &&
      generationRef.current === generation;
    ++requestRef.current;
    autoStartedRef.current.add(`${roomId}:${request.key}`);
    busyRef.current = true;
    setBusy(true);
    setError('');
    progressRef.current = null;
    setProgress(null);
    try {
      const result = await api<Response>(
        `/rooms/${roomId}/analysis`,
        'POST',
        request.followup
          ? { content: request.content || '' }
          : {
              content:
                `현재 선택된 이상 항목 ${request.requestContext.item}을 분석해줘. ` +
                `범위: ${request.requestContext.step} / ${request.requestContext.equipment || '전체 설비'}. ` +
                '선택 자료를 조회하고 근거, 원인 후보, 다음 확인 항목을 구분해 답해줘.',
              sources: request.requestSources,
              context: request.requestContext,
            },
      );
      if (!isCurrent()) return;
      if (
        request.key === autoKeyRef.current &&
        sameContext(result.analysis.context, contextRef.current)
      ) {
        setAnalysis(result.analysis);
        setSources(result.analysis.sources);
      }
      setMessages((previous) => [
        ...previous.filter(
          (message) => !result.messages.some((next) => next.id === message.id),
        ),
        ...result.messages,
      ]);
      if (request.followup) setDraft('');
      onChange();
    } catch (e) {
      if (isCurrent() && request.key === autoKeyRef.current)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (isCurrent()) {
        await refreshProgress();
        if (isCurrent()) {
          busyRef.current = false;
          setBusy(false);
        }
      }
    }
  }

  function run(followup = false) {
    if (effectiveBusy || (followup && (!draft.trim() || !analysis || stale)))
      return;
    void execute({
      followup,
      key: autoKey,
      requestContext: context,
      requestSources: sources,
      content: followup ? draft.trim() : undefined,
    });
  }

  useEffect(() => {
    autoStartedRef.current.clear();
  }, [roomId, autoKey]);

  useEffect(() => {
    // The latest selection waits here while any run in this room is active.
    if (loadedRoom !== roomId || effectiveBusy) return;
    const selectionKey = `${roomId}:${autoKey}`;
    if (autoStartedRef.current.has(selectionKey)) return;
    if (
      (analysis &&
        sameContext(analysis.context, context) &&
        sameSources(analysis.sources, sources)) ||
      currentProgress?.status === 'failed'
    ) {
      autoStartedRef.current.add(selectionKey);
      return;
    }
    const timer = window.setTimeout(() => {
      if (
        !mounted.current ||
        roomRef.current !== roomId ||
        autoKeyRef.current !== autoKey
      )
        return;
      void execute({
        followup: false,
        key: autoKey,
        requestContext: contextRef.current,
        requestSources: sourcesRef.current,
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [loadedRoom, roomId, autoKey, effectiveBusy]);

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
        disabled={effectiveBusy || !analysis || stale}
      />
      <button
        className="icon-button"
        title="추가 질문 보내기"
        disabled={effectiveBusy || !draft.trim() || !analysis || stale}
      >
        <Send size={14} />
      </button>
    </form>
  );
  return (
    <>
      <header>
        <h2>에이전트 분석 · 채팅</h2>
        <span title={llmLabel}>{llmLabel}</span>
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
          <fieldset className="board-source-checks" disabled={effectiveBusy}>
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
        </>
      )}
      <div className="board-analysis-controls">
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
        {panelTab === 'results' && (
          <button
            className="board-run"
            title={`${context.item} · ${context.wafers.length} Wafers`}
            onClick={() => void run()}
            disabled={effectiveBusy}
          >
            {effectiveBusy ? (
              <Loader2 className="spin" size={12} />
            ) : (
              <Play size={12} />
            )}
            {effectiveBusy ? '분석 중' : stale ? '현재 조건 분석' : '분석 실행'}
          </button>
        )}
      </div>
      {panelTab === 'results' ? (
        <div
          id={resultsPanelId}
          role="tabpanel"
          aria-labelledby={resultsTabId}
          tabIndex={0}
          className="board-analysis-output"
          aria-live="polite"
        >
          {error && !failedCurrentRun && <p role="alert">{error}</p>}
          {(effectiveBusy || failedCurrentRun) && (
            <section
              className={`board-analysis-operation-row ${
                currentProgress?.status || (effectiveBusy ? 'running' : '')
              }`}
              aria-label="분석 상태"
              aria-live="polite"
            >
              <span
                className="board-analysis-operation-icon"
                aria-hidden="true"
              >
                {failedCurrentRun ? (
                  <CircleAlert size={14} />
                ) : (
                  <Loader2 className="spin" size={14} />
                )}
              </span>
              <span className="board-analysis-operation-copy">
                <strong>
                  {otherContextBusy
                    ? '이전 선택 분석 중'
                    : failedCurrentRun
                      ? '분석 실패'
                      : '분석 중'}
                </strong>
                {latestProgressEvent && !otherContextBusy && (
                  <span title={latestProgressEvent.event}>
                    {eventLabel(latestProgressEvent)}
                  </span>
                )}
              </span>
              <span className="board-analysis-operation-duration">
                <Clock3 size={12} aria-hidden="true" />
                {currentProgress ? elapsedText(currentProgress) : '진행 중'}
              </span>
            </section>
          )}
          {failedCurrentRun ? (
            <p className="board-analysis-failure" role="alert">
              {progressError || error || '분석이 완료되지 않았습니다.'}
            </p>
          ) : effectiveBusy || error ? null : analysis ? (
            <>
              <div className="board-analysis-status">
                {stale
                  ? '이전 조건 결과 · 현재 선택과 불일치'
                  : analysis.status === 'partial'
                    ? '부분 답변'
                    : '분석 완료'}{' '}
                · {completedStepCount}개 조회 · {unavailableStepCount}개 미연결
              </div>
              {!stale && (
                <p className="board-analysis-answer">{latest?.content}</p>
              )}
            </>
          ) : (
            <p>
              {runtime?.llm_configured
                ? '분석 대기 · 합성 DB'
                : '분석 대기 · LLM 미연결'}
            </p>
          )}
          {currentProgress && (
            <details
              className={`board-analysis-event-details ${currentProgress.status}`}
            >
              <summary>
                <ChevronRight
                  className="board-details-chevron"
                  size={12}
                  aria-hidden="true"
                />
                <History size={12} aria-hidden="true" />
                전체 진행 기록
                <span>
                  {currentProgress.events.length}개 ·{' '}
                  {elapsedText(currentProgress)}
                </span>
              </summary>
              <section
                className="board-analysis-progress"
                aria-label="전체 분석 진행 기록"
              >
                <ol className="board-analysis-timeline">
                  {currentProgress.events.map((event, index) => (
                    <li
                      key={`${event.time || event.event}-${index}`}
                      className={
                        event.error || event.status === 'error' ? 'error' : ''
                      }
                    >
                      <span
                        className="board-analysis-timeline-dot"
                        aria-hidden="true"
                      />
                      <div>
                        <strong title={event.event}>{eventText(event)}</strong>
                        {event.status && <span>{event.status}</span>}
                        {event.model && <small>{event.model}</small>}
                        {event.error && <p>{event.error}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
                {progressError && (
                  <p className="board-analysis-progress-error" role="alert">
                    {progressError}
                  </p>
                )}
              </section>
            </details>
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
          className="analysis-dialog board-analysis-dialog"
          ref={dialog}
          onCancel={() => setExpanded(false)}
          onClose={() => setExpanded(false)}
        >
          <header>
            <h2>분석 대화</h2>
            <span>
              {context.incident_number} · 합성 DB / {llmLabel}
            </span>
            <button
              className="icon-button"
              title="분석 대화 닫기"
              onClick={() => setExpanded(false)}
            >
              <X size={18} />
            </button>
          </header>
          {currentProgress && (
            <details className="board-analysis-dialog-details">
              <summary>
                <ChevronRight
                  className="board-details-chevron"
                  size={12}
                  aria-hidden="true"
                />
                <History size={12} aria-hidden="true" />
                실행 기록
                <span>
                  {currentProgress.events.length}개 ·{' '}
                  {elapsedText(currentProgress)}
                </span>
              </summary>
              <div className="analysis-trace board-analysis-trace board-analysis-dialog-progress">
                {currentProgress.events.map((event, index) => (
                  <div key={`progress-${event.time || event.event}-${index}`}>
                    <strong title={event.event}>{eventText(event)}</strong>
                    <span>{event.status || currentProgress.status}</span>
                    {event.error && <p>{event.error}</p>}
                  </div>
                ))}
              </div>
            </details>
          )}
          {analysis &&
            !stale &&
            !failedCurrentRun &&
            !effectiveBusy &&
            !error && (
              <details className="board-analysis-dialog-details">
                <summary>
                  <ChevronRight
                    className="board-details-chevron"
                    size={12}
                    aria-hidden="true"
                  />
                  <History size={12} aria-hidden="true" />
                  분석 구성
                  <span>
                    {analysis.steps.length}개 자료 ·{' '}
                    {analysis.trace?.length || 0}개 단계
                  </span>
                </summary>
                <div className="analysis-trace board-analysis-trace">
                  {analysis.trace?.map((event) => (
                    <div key={`llm-${event.step}`}>
                      <strong>{event.role}</strong>
                      <span>{event.model}</span>
                    </div>
                  ))}
                  {analysis.steps.map((step) => (
                    <div key={step.source}>
                      <strong>
                        {sourceOptions.find(
                          ([id]) => id === step.source,
                        )?.[1] || step.source}
                      </strong>
                      <span>
                        {step.status === 'completed' ? '조회 완료' : '미연결'}
                      </span>
                      <p>{step.detail}</p>
                    </div>
                  ))}
                </div>
              </details>
            )}
          {failedCurrentRun && (
            <p className="board-analysis-dialog-failure" role="alert">
              이번 실행 실패 · 아래 대화는 이전 기록입니다.
            </p>
          )}
          <div className="analysis-chat-log board-analysis-chat-log">
            {messages.map((message) => (
              <article key={message.id} className={message.role}>
                <strong>{message.role === 'user' ? '질문' : '답변'}</strong>
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
