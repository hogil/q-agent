import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowDownToLine, CircleAlert, Loader2, Play, RefreshCw } from 'lucide-react';
import { api, download } from './api';
import './ModelLabView.css';

type LabCase = {
  id: string;
  cohort: string;
  row_id: number;
  input_kind: string;
  as_of: string;
  label: string;
  wafer_id: string;
  chip_id: string;
  stage: string;
};
type Catalog = {
  synthetic: true;
  cases: LabCase[];
  training: {
    state: string;
    selected_model: string;
    validation_AP: number | null;
    baseline_validation_AP: number | null;
    report?: object;
  };
  notice: string;
};
type ActionName = 'HOLD' | 'BLOCK_DISPATCH' | 'ADDITIONAL_METRO' | 'RELEASE';
type ActionState = {
  revision: number;
  status: string;
  dispatch_blocked: boolean;
  target?: {
    wafer_count?: number;
    lot_count?: number;
    rules?: { eqp?: string; chamber?: string; recipe?: string; step_name?: string }[];
  };
};
type Run = {
  synthetic: true;
  run_id: string;
  status: string;
  scope: Record<string, unknown>;
  summary: string;
  findings: { task: string; model: string; kind: string; scores: { name: string; score: number; threshold: number | null }[] }[];
  trace: { tool: string; status: string; milliseconds: number }[];
  sources: { id: string; title: string; text: string; scope_role: string }[];
  actions: { state: ActionState; proposals: { action: ActionName; reason: string; allowed: boolean }[] };
  performance: { elapsed_ms: number; cache_hit: boolean };
  limitations: string[];
  inputs: {
    image_data_url: string | null;
    current_note?: string | null;
    trend: { values: number[][]; observed: boolean[][]; domain: 'METRO' } | null;
    caption: string;
  };
  service_llm_calls: 0;
  report_url?: string;
};
type Progress = { running: boolean; events: { tool: string; status: string; milliseconds: number }[]; case_id?: string };
type ActionResult = {
  synthetic: true;
  status: string;
  action: ActionName;
  state: ActionState;
  receipt_id: string;
  reason?: string;
  proposals?: { action: ActionName; reason: string; allowed: boolean }[];
};
type ActionPayload = { run_id: string; action: ActionName; expected_revision: number; request_id: string };
type ActionStatus = { status: 'RECORDED' | 'NOT_RECORDED'; run_id: string; request_id: string; outcome: ActionResult | null; run_available: boolean; synthetic_only: true };
type PendingAction = { payload: ActionPayload; caseId: string; uncertain: boolean };
type RecoveredAction = { pending: PendingAction; outcome: ActionResult; runAvailable: boolean };
const pendingActionKey = 'qagent.synthetic-model-lab.pending-action.v1';

function restorePendingAction(): PendingAction | null {
  try {
    const stored = JSON.parse(sessionStorage.getItem(pendingActionKey) || 'null');
    const payload = stored?.payload;
    if (typeof stored?.caseId === 'string' && typeof payload?.run_id === 'string'
      && /^[a-f0-9]{32}$/.test(payload.run_id) && typeof payload.action === 'string'
      && Object.hasOwn(actionLabels, payload.action) && Number.isInteger(payload.expected_revision)
      && payload.expected_revision >= 0 && typeof payload.request_id === 'string'
      && payload.request_id.length > 0 && payload.request_id.length <= 100) {
      return { payload, caseId: stored.caseId, uncertain: true };
    }
  } catch {
    // A new action requires successful persistence before its POST is sent.
  }
  return null;
}

const actionLabels: Record<ActionName, string> = {
  HOLD: 'HOLD',
  BLOCK_DISPATCH: 'BLOCK DISPATCH',
  ADDITIONAL_METRO: '추가 METRO',
  RELEASE: 'RELEASE',
};
const show = (value: unknown) => value == null || value === '' ? '—' : String(value);
const score = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
const duration = (value: number) => `${value.toFixed(1)} ms`;

function validActionResult(payload: ActionPayload, result: ActionResult, recordedOnly = false): boolean {
  if (!result || result.synthetic !== true || result.action !== payload.action || !result.state
    || !Number.isInteger(result.state.revision) || result.state.revision < 0
    || typeof result.state.status !== 'string' || typeof result.state.dispatch_blocked !== 'boolean') return false;
  if (result.status === 'executed_in_dummy_db') {
    return result.state.revision === payload.expected_revision + 1
      && typeof result.receipt_id === 'string' && result.receipt_id.startsWith('SYN-ACTION-');
  }
  return !recordedOnly && result.status === 'blocked' && result.receipt_id === ''
    && typeof result.reason === 'string' && result.reason.length > 0;
}

export function LegacyModelLabView() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [caseId, setCaseId] = useState('');
  const [question, setQuestion] = useState('');
  const [run, setRun] = useState<Run | null>(null);
  const [runCaseId, setRunCaseId] = useState('');
  const [progress, setProgress] = useState<Progress | null>(null);
  const [trendChannel, setTrendChannel] = useState(0);
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);
  const [actionResultRunId, setActionResultRunId] = useState('');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [acting, setActing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(restorePendingAction);
  const [recoveredAction, setRecoveredAction] = useState<RecoveredAction | null>(null);
  const [unavailableActionRunId, setUnavailableActionRunId] = useState('');
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const catalogSequence = useRef(0);
  const runSequence = useRef(0);
  const actionSequence = useRef(0);
  const pendingActionRef = useRef<PendingAction | null>(pendingAction);
  const selectedCase = catalog?.cases.find((item) => item.id === caseId);
  const currentRun = run && runCaseId === caseId ? run : null;
  const actionTarget = currentRun?.actions.state.target;
  const uncertainAction = pendingAction?.uncertain ? pendingAction : null;
  const actionResultBelongsToCurrentRun = actionResultRunId === currentRun?.run_id;
  const actionRunUnavailable = unavailableActionRunId === currentRun?.run_id;

  function savePendingAction(value: PendingAction | null) {
    try {
      if (value) sessionStorage.setItem(pendingActionKey, JSON.stringify(value));
      else sessionStorage.removeItem(pendingActionKey);
    } catch {
      throw new Error('조치 요청을 보존할 수 없습니다. 상태 확인이 가능할 때 다시 시도해 주세요.');
    }
    pendingActionRef.current = value;
    setPendingAction(value);
  }

  function applyActionResult(payload: ActionPayload, result: ActionResult) {
    setRun((current) => current?.run_id === payload.run_id ? {
      ...current,
      actions: {
        ...current.actions,
        state: result.state,
        proposals: result.proposals ?? current.actions.proposals,
      },
    } : current);
    setActionResultRunId(payload.run_id);
    if (currentRun?.run_id === payload.run_id) setActionResult(result);
  }

  async function checkActionStatus(pending: PendingAction) {
    const status = await api<ActionStatus>('/model-lab/action-status', 'POST', pending.payload);
    if (status.synthetic_only !== true || status.run_id !== pending.payload.run_id || status.request_id !== pending.payload.request_id) {
      throw new Error('조치 상태 응답이 요청과 일치하지 않습니다.');
    }
    if (status.status === 'RECORDED' && status.outcome) {
      if (!validActionResult(pending.payload, status.outcome, true)) {
        throw new Error('실행 기록의 조치 결과가 요청과 일치하지 않습니다.');
      }
      applyActionResult(pending.payload, status.outcome);
      setRecoveredAction({ pending, outcome: status.outcome, runAvailable: status.run_available });
      setUnavailableActionRunId(status.run_available ? '' : pending.payload.run_id);
      savePendingAction(null);
      setActionError('');
    } else {
      savePendingAction({ ...pending, uncertain: true });
      setActionError('조치 결과를 아직 확인할 수 없습니다. 같은 요청 상태를 다시 확인해 주세요.');
    }
  }

  async function loadCatalog(refresh = false) {
    const request = ++catalogSequence.current;
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError('');
    try {
      const result = await api<Catalog>('/model-lab/catalog');
      if (request !== catalogSequence.current) return;
      setCatalog(result);
      setCaseId((current) => result.cases.some((item) => item.id === current)
        ? current : result.cases[0]?.id || '');
      if (caseId && !result.cases.some((item) => item.id === caseId)) {
        ++runSequence.current;
        ++actionSequence.current;
        setRun(null);
        setRunCaseId('');
        setActionResult(null);
      }
    } catch (reason) {
      if (request === catalogSequence.current)
        setError(reason instanceof Error ? reason.message : '사례 목록을 불러오지 못했습니다.');
    } finally {
      if (request === catalogSequence.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }

  useEffect(() => {
    void loadCatalog();
    return () => {
      ++catalogSequence.current;
      ++runSequence.current;
      ++actionSequence.current;
    };
  }, []);

  useEffect(() => {
    if (!running || !caseId) return;
    let active = true;
    let timer = 0;
    const selectedId = caseId;
    async function poll() {
      try {
        const result = await api<Progress>('/model-lab/progress');
        if (active && selectedId === caseId && (!result.case_id || result.case_id === selectedId))
          setProgress(result);
      } catch {
        // Progress is optional; the analysis request remains authoritative.
      } finally {
        if (active) timer = window.setTimeout(() => void poll(), 800);
      }
    }
    void poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [running, caseId]);

  function selectCase(value: string) {
    setCaseId(value);
    ++runSequence.current;
    ++actionSequence.current;
    setRun(null);
    setRunCaseId('');
    setActionResult(null);
    setProgress(null);
    setActionError('');
    setError('');
    setExpandedSource(null);
  }

  async function analyze(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!caseId || !question.trim() || running || acting || pendingActionRef.current) return;
    const selectedId = caseId;
    const request = ++runSequence.current;
    ++actionSequence.current;
    setRun(null);
    setActionResult(null);
    setProgress({ running: true, events: [], case_id: selectedId });
    setActionError('');
    setError('');
    setRunning(true);
    try {
      const result = await api<Run>('/model-lab/analyze', 'POST', {
        case_id: selectedId,
        question: question.trim(),
      });
      if (request === runSequence.current && selectedId === caseId) {
        setRun(result);
        setRunCaseId(selectedId);
        setUnavailableActionRunId('');
        setProgress(null);
      }
    } catch (reason) {
      if (request === runSequence.current && selectedId === caseId) {
        setError(reason instanceof Error ? reason.message : '분석을 실행하지 못했습니다.');
        setProgress(null);
      }
    } finally {
      if (request === runSequence.current) setRunning(false);
    }
  }

  async function executeAction(action: ActionName) {
    if (!currentRun || acting || pendingActionRef.current || actionRunUnavailable) return;
    const proposal = currentRun.actions.proposals.find((item) => item.action === action && item.allowed);
    if (!proposal) return;
    const selectedId = caseId;
    const runId = currentRun.run_id;
    const request = ++actionSequence.current;
    const state = currentRun.actions.state;
    const payload: ActionPayload = {
      run_id: runId,
      action,
      expected_revision: state.revision,
      request_id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    };
    setActionError('');
    setActionResult(null);
    setActing(true);
    const pending: PendingAction = { payload, caseId: selectedId, uncertain: false };
    let submitted = false;
    try {
      savePendingAction(pending);
      submitted = true;
      const result = await api<ActionResult>('/model-lab/actions', 'POST', payload);
      if (request !== actionSequence.current || caseId !== selectedId) return;
      if (!validActionResult(payload, result)) throw new Error('조치 응답이 요청과 일치하지 않습니다.');
      applyActionResult(payload, result);
      savePendingAction(null);
    } catch (reason) {
      if (request === actionSequence.current) {
        if (submitted) {
          try {
            await checkActionStatus(pending);
          } catch {
            savePendingAction({ ...pending, uncertain: true });
            setActionError('조치 결과를 확인하지 못했습니다. 조치 결과 확인 버튼으로 다시 조회해 주세요.');
          }
        } else if (caseId === selectedId) {
          setActionError(reason instanceof Error ? reason.message : '더미 조치를 완료하지 못했습니다.');
        }
      }
    } finally {
      if (request === actionSequence.current) setActing(false);
    }
  }

  async function retryActionStatus() {
    const pending = pendingActionRef.current;
    if (!pending || acting) return;
    const request = ++actionSequence.current;
    setActing(true);
    setActionError('');
    try {
      await checkActionStatus(pending);
    } catch {
      if (request === actionSequence.current) {
        savePendingAction({ ...pending, uncertain: true });
        setActionError('조치 결과를 확인하지 못했습니다. 잠시 뒤 다시 확인해 주세요.');
      }
    } finally {
      if (request === actionSequence.current) setActing(false);
    }
  }

  async function downloadRun() {
    if (!currentRun || acting) return;
    const runId = currentRun.run_id;
    const request = runSequence.current;
    try {
      const report = await api<Run>(`/model-lab/report?run_id=${encodeURIComponent(runId)}`);
      download(`synthetic-model-lab-${runId}.json`, JSON.stringify(report, null, 2));
    } catch (reason) {
      if (request === runSequence.current)
        setError(reason instanceof Error ? reason.message : '보고서를 내려받지 못했습니다.');
    }
  }

  const training = catalog?.training;
  const delta = training?.validation_AP != null && training.baseline_validation_AP != null
    ? training.validation_AP - training.baseline_validation_AP : null;
  const trend = currentRun?.inputs.trend;
  const channelCount = trend ? Math.min(trend.values.length, trend.observed.length) : 0;
  const activeChannel = channelCount ? Math.min(trendChannel, channelCount - 1) : 0;
  const trendValues = trend?.values[activeChannel] || [];
  const trendMask = trend?.observed[activeChannel] || [];
  const visibleTrend = trendValues.flatMap((value, index) => trendMask[index] && Number.isFinite(value) ? [value] : []);
  const trendMin = visibleTrend.length ? Math.min(...visibleTrend) : 0;
  const trendMax = visibleTrend.length ? Math.max(...visibleTrend) : 1;
  const trendSegments: string[] = [];
  let segment = '';
  trendValues.forEach((value, index) => {
    if (!trendMask[index] || !Number.isFinite(value)) {
      if (segment) trendSegments.push(segment);
      segment = '';
      return;
    }
    const x = trendValues.length <= 1 ? 360 : 48 + (index / (trendValues.length - 1)) * 650;
    const scaled = trendMax === trendMin ? .5 : (value - trendMin) / (trendMax - trendMin);
    const y = 176 - scaled * 145;
    segment += `${segment ? ' L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`;
  });
  if (segment) trendSegments.push(segment);

  return (
    <section className="model-lab" aria-label="Synthetic Model Lab">
      <header className="model-lab-heading">
        <div>
          <p className="model-lab-eyebrow">SYNTHETIC · ISOLATED RUN SCOPE</p>
          <h1>Synthetic Model Lab</h1>
          <p>사례를 선택해 모델 출력, 조회 근거, 제한된 더미 MES 조치를 확인합니다.</p>
        </div>
        <button className="outline-button" onClick={() => void loadCatalog(true)} disabled={refreshing || running || acting}>
          {refreshing ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
          사례 새로고침
        </button>
      </header>

      <div className="model-lab-banner" role="note">
        <strong>합성 lab 전용</strong>
        <span>이 화면의 scope와 조치는 기존 채팅/사고 보고서와 분리됩니다. 실제 생산계 연결이나 원인 확정을 의미하지 않습니다.</span>
      </div>

      {error && <div className="model-lab-error" role="alert"><CircleAlert size={16} />{error}<button className="text-button" onClick={() => void loadCatalog(true)}>다시 시도</button></div>}
      {loading ? <div className="model-lab-empty"><Loader2 className="spin" size={22} />사례 목록을 불러오는 중</div> : (
        <>
          <div className="model-lab-layout">
            <section className="model-lab-card model-lab-case-card">
              <div className="model-lab-card-heading"><div><span>01 / CASE</span><h2>입력 사례</h2></div><span className="model-lab-chip">명시 선택</span></div>
              <label className="model-lab-field">합성 사례
                <select value={caseId} onChange={(event) => selectCase(event.target.value)} disabled={!catalog?.cases.length || running || acting}>
                  {!catalog?.cases.length && <option value="">사례 없음</option>}
                  {catalog?.cases.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.id}</option>)}
                </select>
              </label>
              {selectedCase ? (
                <dl className="model-lab-case-facts">
                  <div><dt>입력 유형</dt><dd>{selectedCase.input_kind} · {selectedCase.stage}</dd></div>
                  <div><dt>기준 시각</dt><dd>{selectedCase.as_of}</dd></div>
                  <div><dt>대상</dt><dd>Wafer {selectedCase.wafer_id} · Chip {selectedCase.chip_id}</dd></div>
                  <div><dt>Cohort / row</dt><dd>{selectedCase.cohort} / {selectedCase.row_id}</dd></div>
                </dl>
              ) : <p className="model-lab-muted">분석할 합성 사례를 선택하세요.</p>}
              <form className="model-lab-question" onSubmit={analyze}>
                <label className="model-lab-field" htmlFor="model-lab-question">분석 질문
                  <textarea id="model-lab-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={2000} placeholder="예: 이 관측에서 확인된 신호와 추가 확인이 필요한 근거를 요약해 주세요." />
                </label>
                <button className="primary-button" type="submit" disabled={!selectedCase || !question.trim() || running || acting || !!uncertainAction}>
                  {running ? <Loader2 className="spin" size={16} /> : <Play size={15} />}{running ? '분석 실행 중' : '합성 분석 실행'}
                </button>
              </form>
            </section>

            <section className="model-lab-card model-lab-training-card">
              <div className="model-lab-card-heading"><div><span>MODEL SNAPSHOT</span><h2>학습 지표 비교</h2></div><span className="model-lab-chip">{show(training?.state)}</span></div>
              {training ? <>
                <p className="model-lab-model-name">선택 모델 <strong>{show(training.selected_model)}</strong></p>
                <div className="model-lab-metrics">
                  <div><span>기준 모델 validation AP</span><strong>{score(training.baseline_validation_AP)}</strong></div>
                  <div><span>선택 모델 validation AP</span><strong>{score(training.validation_AP)}</strong></div>
                  <div><span>차이</span><strong className={delta == null ? '' : delta >= 0 ? 'positive' : 'negative'}>{delta == null ? '—' : `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(2)}%p`}</strong></div>
                </div>
                <p className="model-lab-muted">선택 모델과 기준 모델의 validation 지표입니다. validation AP는 원인 확률이나 생산 품질 보증이 아닙니다.</p>
              </> : <p className="model-lab-muted">학습 지표 정보를 불러오지 못했습니다.</p>}
            </section>
          </div>

          {catalog?.notice && <p className="model-lab-notice">{catalog.notice}</p>}

          {running && <div className="model-lab-running"><Loader2 className="spin" size={18} />선택한 사례의 독립 scope에서 파이프라인을 실행하고 있습니다.</div>}
          {uncertainAction && !currentRun && <div className="model-lab-error" role="status">조치 결과 불명 · 원래 사례 {uncertainAction.caseId}의 조치 상태를 확인해야 합니다. <button className="outline-button" onClick={() => void retryActionStatus()} disabled={acting}>{acting ? '확인 중' : '조치 결과 확인'}</button></div>}
          {recoveredAction && currentRun?.run_id !== recoveredAction.pending.payload.run_id && <section className="model-lab-card model-lab-action-receipt" role="status" aria-label="복구한 이전 조치 기록">
            <strong>확인된 이전 합성 조치</strong>
            <p>사례 {recoveredAction.pending.caseId} · run {recoveredAction.pending.payload.run_id}</p>
            <p>{actionLabels[recoveredAction.outcome.action]} · {recoveredAction.outcome.status} · receipt {recoveredAction.outcome.receipt_id}</p>
            <p>요청 {recoveredAction.pending.payload.request_id} · revision {recoveredAction.pending.payload.expected_revision} → {recoveredAction.outcome.state.revision}</p>
            {(recoveredAction.outcome.state.target?.lot_count != null || recoveredAction.outcome.state.target?.wafer_count != null) && <p>기록된 범위{recoveredAction.outcome.state.target?.lot_count != null ? ` · Lot ${recoveredAction.outcome.state.target.lot_count}` : ''}{recoveredAction.outcome.state.target?.wafer_count != null ? ` · Wafer ${recoveredAction.outcome.state.target.wafer_count}` : ''}</p>}
            {!recoveredAction.runAvailable && <p>후속 조치 전 새 분석이 필요합니다.</p>}
          </section>}
          {running && <section className="model-lab-card model-lab-live-progress" aria-live="polite">
            <div className="model-lab-card-heading"><div><span>LIVE / TOOL PROGRESS</span><h2>실시간 조회 경과</h2></div><span className="model-lab-chip">{progress?.events.length || 0} steps</span></div>
            {progress?.events.length ? <ol className="model-lab-trace">{progress.events.map((item, index) => <li key={`${item.tool}-${index}`}><span className="model-lab-trace-index">{String(index + 1).padStart(2, '0')}</span><strong>{item.tool}</strong><span>{item.status}</span><time>{duration(item.milliseconds)}</time></li>)}</ol> : <p className="model-lab-muted">첫 Tool event를 기다리는 중</p>}
          </section>}
          {!currentRun && !running && !error && <div className="model-lab-empty">사례와 질문을 확인한 뒤 합성 분석을 실행하세요. 이전 실행 결과는 사례를 바꾸면 비워집니다.</div>}

          {currentRun && <div className="model-lab-results" aria-live="polite">
            <section className="model-lab-card model-lab-result-head">
              <div><span className="model-lab-kicker">RUN {currentRun.run_id}</span><h2>{currentRun.summary}</h2><p>상태: {currentRun.status} · 대상: {caseId} · 서비스 LLM 호출: {currentRun.service_llm_calls}</p></div>
              <div className="model-lab-downloads">
                <button className="outline-button" onClick={() => void downloadRun()} disabled={acting}><ArrowDownToLine size={15} />JSON 다운로드</button>
                {currentRun.report_url && <a className="outline-button" href={currentRun.report_url} target="_blank" rel="noreferrer">보고서 열기</a>}
              </div>
            </section>

            <div className="model-lab-result-grid">
              <section className="model-lab-card model-lab-observations">
                <div className="model-lab-card-heading"><div><span>01 / INPUTS</span><h2>선택 scope 관측 미리보기</h2></div><span className="model-lab-chip">합성 관측</span></div>
                {currentRun.inputs.image_data_url && <figure className="model-lab-image-preview"><img src={currentRun.inputs.image_data_url} alt={`${selectedCase?.label || '선택 사례'}의 합성 이미지`} /><figcaption>{currentRun.inputs.caption || '선택 scope의 합성 이미지'}</figcaption></figure>}
                {!currentRun.inputs.image_data_url && <p className="model-lab-muted">이 사례에 표시할 합성 이미지가 없습니다.</p>}
                {currentRun.inputs.current_note && <div className="model-lab-current-note"><h3>현재 공정 · Inform 문맥</h3><p>{currentRun.inputs.current_note}</p></div>}
                {trend && channelCount > 0 && <div className="model-lab-trend-preview">
                  <div className="model-lab-trend-heading"><strong>METRO · numeric input</strong><label>채널 <select value={activeChannel} onChange={(event) => setTrendChannel(Number(event.target.value))}>{Array.from({ length: channelCount }, (_, index) => <option key={index} value={index}>Channel {index + 1}</option>)}</select></label></div>
                  <svg className="model-lab-trend-svg" viewBox="0 0 720 220" role="img" aria-label={`합성 METRO 채널 ${activeChannel + 1}, 관측 구간만 연결한 추세`}>
                    <path d="M48 31V176H698" fill="none" stroke="#dbe3dc" strokeWidth="1" />
                    <path d="M48 103H698" fill="none" stroke="#edf1ed" strokeWidth="1" strokeDasharray="3 4" />
                    {trendSegments.map((path, index) => <path key={index} d={path} fill="none" stroke="#4f8360" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />)}
                    {trendValues.map((value, index) => {
                      if (!trendMask[index] || !Number.isFinite(value)) return null;
                      const x = trendValues.length <= 1 ? 360 : 48 + (index / (trendValues.length - 1)) * 650;
                      const scaled = trendMax === trendMin ? .5 : (value - trendMin) / (trendMax - trendMin);
                      const y = 176 - scaled * 145;
                      return <circle key={index} cx={x} cy={y} r="2.7" fill="#4f8360"><title>{`relative bin ${(trendValues.length <= 1 ? 0 : index / (trendValues.length - 1)).toFixed(3)} · ${value}`}</title></circle>;
                    })}
                    <text x="48" y="198">relative bin 0</text><text x="350" y="198">0.5</text><text x="666" y="198">1.0</text>
                    <text x="49" y="20">{trendMax.toPrecision(4)}</text><text x="49" y="171">{trendMin.toPrecision(4)}</text>
                  </svg>
                  <p className="model-lab-muted">{trend.domain} · raw numeric values preserved · missing observations remain disconnected · {visibleTrend.length}/{trendValues.length} observed</p>
                </div>}
                {trend && channelCount === 0 && <p className="model-lab-muted">METRO Trend 값이 없습니다.</p>}
              </section>
              <section className="model-lab-card">
                <div className="model-lab-card-heading"><div><span>02 / MODEL</span><h2>모델 결과</h2></div><span className="model-lab-chip">{currentRun.performance.cache_hit ? 'model cache hit' : 'model cache miss'} · {duration(currentRun.performance.elapsed_ms)}</span></div>
                {currentRun.findings.map((finding, index) => <article className="model-lab-finding" key={`${finding.task}-${index}`}>
                  <header><strong>{finding.task}</strong><span>{finding.model} · {finding.kind}</span></header>
                  <div className="model-lab-score-list">{finding.scores.map((item) => <div key={item.name}><span>{item.name}</span><strong>{score(item.score)}</strong><small>{item.threshold == null ? 'threshold —' : `기준 ${score(item.threshold)}`}</small></div>)}</div>
                  <small className="model-lab-muted">점수는 모델 출력이며 원인 확률이 아닙니다.</small>
                </article>)}
                {!currentRun.findings.length && <p className="model-lab-muted">표시할 모델 결과가 없습니다.</p>}
              </section>

              <section className="model-lab-card">
                <div className="model-lab-card-heading"><div><span>03 / TRACE</span><h2>{currentRun.performance.cache_hit ? '이전 Tool 실행 기록 · 결과 재사용' : 'Tool 실행 경과'}</h2></div><span className="model-lab-chip">{currentRun.performance.cache_hit ? '재사용 처리' : '총'} {duration(currentRun.performance.elapsed_ms)}</span></div>
                <ol className="model-lab-trace">{currentRun.trace.map((item, index) => <li key={`${item.tool}-${index}`}><span className="model-lab-trace-index">{String(index + 1).padStart(2, '0')}</span><strong>{item.tool}</strong><span>{item.status}</span><time>{duration(item.milliseconds)}</time></li>)}</ol>
                {!currentRun.trace.length && <p className="model-lab-muted">실행 trace가 없습니다.</p>}
              </section>
            </div>

            <section className="model-lab-card">
              <div className="model-lab-card-heading"><div><span>04 / SOURCES</span><h2>Text 근거 원문</h2></div><span className="model-lab-chip">{currentRun.sources.length}건</span></div>
              <div className="model-lab-sources">{currentRun.sources.map((source) => <article key={source.id}>
                <button className="model-lab-source-toggle" aria-expanded={expandedSource === source.id} onClick={() => setExpandedSource((value) => value === source.id ? null : source.id)}><span><strong>{source.title}</strong><small>{source.id} · {source.scope_role}</small></span><span>{expandedSource === source.id ? '접기' : '원문 보기'}</span></button>
                {expandedSource === source.id && <pre>{source.text}</pre>}
              </article>)}</div>
              {!currentRun.sources.length && <p className="model-lab-muted">반환된 text source가 없습니다.</p>}
            </section>

            <section className="model-lab-card model-lab-actions-card">
              <div className="model-lab-card-heading"><div><span>05 / SYNTHETIC MES</span><h2>더미 MES 조치</h2></div><span className="model-lab-chip">revision {currentRun.actions.state.revision}</span></div>
              <div className="model-lab-action-state"><span>현재 상태 <strong>{currentRun.actions.state.status}</strong></span><span>Dispatch 차단 <strong>{currentRun.actions.state.dispatch_blocked ? '예' : '아니오'}</strong></span></div>
              {(actionTarget?.lot_count != null || actionTarget?.wafer_count != null) && <p className="model-lab-action-target">영향 범위{actionTarget?.lot_count != null ? ` · Lot ${actionTarget.lot_count}` : ''}{actionTarget?.wafer_count != null ? ` · Wafer ${actionTarget.wafer_count}` : ''}</p>}
              {!!actionTarget?.rules?.length && <ul className="model-lab-rule-scope">{actionTarget.rules.map((rule, index) => <li key={`${rule.eqp}-${rule.chamber}-${rule.recipe}-${rule.step_name}-${index}`}>{[rule.eqp, rule.chamber, rule.recipe, rule.step_name].filter(Boolean).join(' · ')}</li>)}</ul>}
              <p className="model-lab-muted">실행은 현재 run의 고정 scope와 revision에 묶입니다. 실제 MES에는 전달되지 않습니다.</p>
              {uncertainAction && <div className="model-lab-error" role="status">조치 결과 불명 · {uncertainAction.payload.run_id === currentRun.run_id ? '현재 run' : `원래 run ${uncertainAction.caseId}`} 조치를 확인 중입니다.</div>}
              <div className="model-lab-action-buttons">{currentRun.actions.proposals.filter((item) => item.allowed).map((item) => <button key={item.action} className={item.action === 'RELEASE' ? 'outline-button model-lab-release' : 'outline-button'} onClick={() => void executeAction(item.action)} disabled={acting || !!uncertainAction || actionRunUnavailable} title={item.reason}>{acting ? <Loader2 className="spin" size={14} /> : null}{actionLabels[item.action]}</button>)}</div>
              {uncertainAction && <button className="outline-button" onClick={() => void retryActionStatus()} disabled={acting}>조치 결과 확인</button>}
              {actionRunUnavailable && <p className="model-lab-muted">실행 기록은 확인했습니다. 후속 조치 전 새 분석이 필요합니다.</p>}
              {actionError && <p className="model-lab-error" role="alert">{actionError}</p>}
              {actionResultBelongsToCurrentRun && actionResult && <p className="model-lab-action-receipt" role="status">{actionLabels[actionResult.action]} · {actionResult.status} · receipt {actionResult.receipt_id}{actionResult.reason ? ` · ${actionResult.reason}` : ''}</p>}
            </section>

            <section className="model-lab-limitations"><strong>미확인 사항 및 제한</strong><ul>{currentRun.limitations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></section>
          </div>}
        </>
      )}
    </section>
  );
}

const CohortEvidencePanel = lazy(() => import('./CohortEvidencePanel'));

export default function ModelLabView() {
  const [view, setView] = useState<'cohort' | 'models'>('cohort');
  return (
    <div className="cohort-view-shell">
      <nav className="cohort-view-switcher" role="tablist" aria-label="연구 보기">
        <button type="button" role="tab" aria-selected={view === 'cohort'} onClick={() => setView('cohort')}>공정 물량</button>
        <button type="button" role="tab" aria-selected={view === 'models'} onClick={() => setView('models')}>개별 모델</button>
      </nav>
      {view === 'cohort' ? (
        <Suspense fallback={<section className="model-lab"><div className="model-lab-empty">근거 패널 불러오는 중입니다.</div></section>}>
          <CohortEvidencePanel />
        </Suspense>
      ) : <LegacyModelLabView />}
    </div>
  );
}
