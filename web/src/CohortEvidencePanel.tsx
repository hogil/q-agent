import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { api } from './api';
import './CohortEvidencePanel.css';
import CohortMilestonePanel, { type ResearchMilestone } from './CohortMilestonePanel';
import CohortMilestoneV6Panel, { type ResearchMilestoneV6 } from './CohortMilestoneV6Panel';
import CohortMilestoneV61Panel, { type ResearchMilestoneV61 } from './CohortMilestoneV61Panel';
import CohortMilestoneV62Panel, { type ResearchMilestoneV62 } from './CohortMilestoneV62Panel';
import CohortMilestoneV63Panel, { type ResearchMilestoneV63 } from './CohortMilestoneV63Panel';
import CohortMilestoneV64Panel, { type ResearchMilestoneV64 } from './CohortMilestoneV64Panel';
import CohortMilestoneV65Panel, { type ResearchMilestoneV65 } from './CohortMilestoneV65Panel';
import CohortMilestoneV66Panel, { type ResearchMilestoneV66 } from './CohortMilestoneV66Panel';
import CohortMilestoneV67Panel, { type ResearchMilestoneV67 } from './CohortMilestoneV67Panel';
import CohortMilestoneV68DraftPanel from './CohortMilestoneV68DraftPanel';
import type { ResearchMilestoneV68 } from './v68EvidenceSnapshot';
import CohortMilestoneV69DraftPanel from './CohortMilestoneV69DraftPanel';
import type { ResearchMilestoneV69 } from './v69EvidenceSnapshot';

type Scope = {
  status?: string | null;
  scope_id?: string | null;
  relation?: string | null;
  wafer_count?: number | null;
  lot_count?: number | null;
  anchor_run_count?: number | null;
  window?: Record<string, unknown> | null;
} | null;
type Metrics = { macro_ap?: number | null; macro_f1?: number | null; seed?: number | null } | null;
type LatestResearchRecord = {
  id: string;
  title: string;
  status: string;
  status_label: string;
  execution_started_utc?: string | null;
  execution_ended_utc?: string | null;
  root_reviewed_utc?: string | null;
  summary?: string;
  limitations?: string[];
  metrics?: {
    baseline_tst_ap?: number | null;
    channel_tst_ap?: number | null;
    mean_tst_ap?: number | null;
    max_tst_ap?: number | null;
    mean_tst_recall?: number | null;
    max_tst_recall?: number | null;
    mean_tst_fpr?: number | null;
    max_tst_fpr?: number | null;
    cnn_recall_at_max_fpr?: number | null;
    support?: number | null;
    cpu_smoke_runs?: number | null;
    llm_calls?: number | null;
    tool_calls?: number | null;
    wall_seconds?: number | null;
    section_chars?: number | null;
    quality_gap_count?: number | null;
    observed_wall_reduction_fraction?: number | null;
    observed_generation_reduction_fraction?: number | null;
    same_output_tokens?: number | null;
    matched_call_count?: number | null;
    quality_failure_count?: number | null;
    output_tokens?: number | null;
    child_exit_code_available?: boolean;
    systems?: Record<string, { 'macro_recall@10'?: number | null; 'macro_recall@100'?: number | null; 'ndcg@10'?: number | null }>;
    input_tokens?: number | null;
    selected_tables?: number | null;
    checked_cells?: number | null;
    derived_operand_count?: number | null;
    new_mes_calls?: number | null;
    external_api_calls?: number | null;
    raw_patch_k3_ap?: number | null;
    raw_patch_k3_auc?: number | null;
    raw_patch_k3_standardized_pauc_max_fpr0_01?: number | null;
    raw_patch_k3_tp?: number | null;
    raw_patch_k3_fp?: number | null;
    paano_mean17_29_ap?: number | null;
    paano_mean17_29_auc?: number | null;
    paano_mean17_29_standardized_pauc_max_fpr0_01?: number | null;
    paano_mean17_29_tp?: number | null;
    paano_mean17_29_fp?: number | null;
  } | null;
};
type LatestResearchStatus = { status: string; created_at_utc?: string | null; records: LatestResearchRecord[] };
type Snapshot = {
  milestone?: ResearchMilestone | null;
  current_milestone?: ResearchMilestoneV6 | null;
  completion_milestone?: ResearchMilestoneV61 | null;
  confirmation_milestone?: ResearchMilestoneV62 | null;
  publication_milestone?: ResearchMilestoneV63 | null;
  publication_milestone_v64?: ResearchMilestoneV64 | null;
  publication_milestone_v65?: ResearchMilestoneV65 | null;
  publication_milestone_v66?: ResearchMilestoneV66 | null;
  publication_milestone_v67?: ResearchMilestoneV67 | null;
  publication_milestone_v68?: ResearchMilestoneV68 | null;
  publication_milestone_v69?: ResearchMilestoneV69 | null;
  latest_research_status?: LatestResearchStatus | null;
  schema_id: string;
  synthetic: boolean | null;
  status: string | null;
  source_as_of: string | null;
  scopes?: {
    current?: Scope;
    reference?: Scope;
    event?: Scope;
    intersection?: { wafer_count?: number | null; current_denominator?: number | null } | null;
    current_down_matched?: { matched_n?: number | null; denominator?: number | null } | null;
    risk_floor?: number | null;
    step_sampling?: { step: string; observed_n: number | null; total_n: number | null; coverage: number | null }[] | null;
    future_cohort_yield?: { point?: number | null; unit?: string | null; outcome_observed?: boolean | null; calibrated_interval?: boolean | null; outcome_queries?: number | null } | null;
    future_signature_rates?: { target?: string; point?: number | null; unit?: string | null }[] | null;
    outcome_queries?: number | null;
    first_business_tool?: string | null;
    tool_call_count?: number | null;
  };
  llm?: {
    status?: string | null;
    model_calls?: number | null;
    judge_decision?: string | null;
    router_requested_tools?: string[] | null;
    requested_tools?: string[] | null;
    summary?: string | null;
    limitations?: string[] | null;
    manual_review_status?: Record<string, string> | null;
    manual_findings?: { severity?: string | null; finding?: string | null }[] | null;
    accepted_for_demo?: boolean | null;
    role_traces?: { role?: string; input_tokens?: number | null; output_tokens?: number | null; elapsed_ms?: number | null }[] | null;
    budget_stop?: { status?: string; return_to?: string; requested_tools?: string[]; new_data_queried?: boolean; reason?: string } | null;
    cause_status?: string | null;
  };
  action_execution?: { status?: string | null; receipt_count?: number | null; new_actions_executed?: boolean | null; actions_recorded?: boolean | null; production_execution?: boolean | null } | null;
  independent_mes?: {
    counts?: Record<string, number | null> | null;
    unaffected_wafer_count?: number | null;
    source_warehouse_unchanged?: boolean | null;
    experiment_label?: string | null;
    synthetic?: boolean | null;
    production_actions_executed?: boolean | null;
  } | null;
  forecast?: {
    raw_mae?: { v1?: number | null; v4?: number | null } | null;
    normalized_mae?: { v1?: number | null; v4?: number | null } | null;
    delta_ci95?: [number, number] | null;
    yield_exact?: boolean | null;
    family3_regressed?: boolean | null;
    prior_holdout_informed?: boolean | null;
    limits?: string[] | null;
  } | null;
  public_benchmarks?: {
    cnn?: { macro_ap?: number | null; macro_f1?: number | null; reported_reference_loss?: string } | null;
    dino?: { linear?: Metrics; finetuned?: Metrics; public_dataset?: boolean; site_validation?: boolean } | null;
    same_test_seen?: boolean | null;
    site_validation?: boolean | null;
  };
  numeric_trend?: {
    status?: string | null;
    model_inference_executed?: boolean | null;
    outcome_queries?: number | null;
    current_scope?: Scope;
    reference_scope?: Scope;
    series?: Record<string, { step?: string; item?: string; status?: string; groups?: number; timepoints?: number; unit?: string }[] | null>;
    llm_calls?: number | null;
  } | null;
  document_review?: { status?: string | null; issues?: string[] | null; accepted_for_demo?: boolean | null } | null;
  accepted_document_review?: {
    status?: string | null;
    accepted_for_descriptive_synthetic_rag?: boolean | null;
    distinct_case_count?: number | null;
    document_count?: number | null;
    format_corpus_counts?: Record<string, number> | null;
    manifest_sha256?: string | null;
    individually_reviewed_page_count?: number | null;
    review_findings?: string[] | null;
    visual_review_limits?: string[] | null;
  } | null;
  provenance?: { artifacts?: { name: string; sha256?: string | null; availability?: string }[] };
};

const value = (item: unknown) => item == null || item === '' ? '확인 대기' : String(item);
const count = (item: number | null | undefined) => item == null ? '확인 대기' : item.toLocaleString('ko-KR');
const percent = (item: number | null | undefined) => item == null ? '확인 대기' : `${(item * 100).toFixed(1)}%`;
const metric = (item: number | null | undefined) => item == null ? '확인 대기' : item.toFixed(4);
const boolLabel = (item: boolean | null | undefined) => item == null ? '확인 대기' : item ? '예' : '아니오';
const scopeDescription = (scope: Scope) => {
  if (!scope) return '범위 정보 대기';
  const window = scope.window || {};
  const fields = [window.step, window.eqp, window.product, window.start, window.end].filter(Boolean).map(String);
  return fields.length ? fields.join(' · ') : value(scope.relation);
};

const utcLabel = (started?: string | null, ended?: string | null) =>
  started && ended ? `${started} — ${ended}` : started || ended || '기록 없음';

function LatestResearchStatusPanel({ status }: { status: LatestResearchStatus }) {
  const publicRecord = status.records.find((row) => row.id === 'public_retrieval');
  const systems = publicRecord?.metrics?.systems;
  return (
    <section className="cohort-section cohort-latest-research" aria-labelledby="latest-research-title">
      <div className="cohort-section-heading">
        <div><span className="model-lab-kicker">CURRENT RESEARCH · REVIEWED RECORDS</span><h2 id="latest-research-title">최근 연구 실행·검토 기록</h2></div>
        <p>실행 시각과 ROOT 검토 시각을 분리해 표시합니다. 합성 환경 또는 공개 데이터 실험의 제한된 기록입니다.</p>
      </div>
      {status.status !== 'available' && <p className="cohort-latest-unavailable" role="status">일부 최신 근거를 확인할 수 없습니다. 확인된 항목만 표시하며 이전 기록으로 대체하지 않았습니다.</p>}
      <div className="cohort-latest-grid">
        {status.records.map((row) => (
          <article className={`cohort-latest-card${row.status === 'unavailable' ? ' cohort-latest-card-unavailable' : ''}`} key={row.id}>
            <div className="cohort-latest-card-heading"><h3>{row.title}</h3><span>{row.status_label}</span></div>
            <dl>
              <div><dt>실행 UTC</dt><dd>{utcLabel(row.execution_started_utc, row.execution_ended_utc)}</dd></div>
              <div><dt>ROOT 검토 UTC</dt><dd>{row.root_reviewed_utc || '기록 없음'}</dd></div>
            </dl>
            {row.summary && <p>{row.summary}</p>}
            {row.id === 'native_architecture_no_gain' && row.metrics && <small>Baseline TST AP {metric(row.metrics.baseline_tst_ap)} · Channel TST AP {metric(row.metrics.channel_tst_ap)} · 승격 없음</small>}
            {row.id === 'native_maxpool_tradeoff' && row.metrics && <small>Max/mean TST AP {metric(row.metrics.max_tst_ap)} / {metric(row.metrics.mean_tst_ap)} · recall {metric(row.metrics.max_tst_recall)} / {metric(row.metrics.mean_tst_recall)} · FPR {metric(row.metrics.max_tst_fpr)} / {metric(row.metrics.mean_tst_fpr)} · support {count(row.metrics.support)} · 같은 FPR CNN recall {metric(row.metrics.cnn_recall_at_max_fpr)}</small>}
            {row.id === 'e5_service_smoke' && row.metrics && <small>CPU smoke {count(row.metrics.cpu_smoke_runs)}회 · LLM {count(row.metrics.llm_calls)}회 · 실제 Tool 통합 아님</small>}
            {row.id === 'v18_partial_quality' && row.metrics && <small>LLM {count(row.metrics.llm_calls)}회 · Tool {count(row.metrics.tool_calls)}회 · 품질 일부 미충족</small>}
            {row.id === 'v6_runtime_reuse' && row.metrics && <small>{count(row.metrics.matched_call_count)}회 호출에서 입력 bytes와 생성 text 동일 · 단일 사례 시간 차이: 전체 {percent(row.metrics.observed_wall_reduction_fraction)} · 생성 {percent(row.metrics.observed_generation_reduction_fraction)} · 답변 품질은 부분 충족 유지</small>}
            {row.id === 'v19_quality_failed' && row.metrics && <small>LLM {count(row.metrics.llm_calls)}회 · {count(row.metrics.section_chars)}자 · 품질 실패</small>}
            {row.id === 'same_evidence_14b_quality_failed' && row.metrics && <small>단일 Answer · Tool {count(row.metrics.tool_calls)}회 · {metric(row.metrics.wall_seconds)}초 · {count(row.metrics.output_tokens)} tokens · 오류 {count(row.metrics.quality_failure_count)}건</small>}
            {row.id === 'public_retrieval' && <small>영문 BEIR SciFact 고정 test · retrieval only · child exit code 기록 없음</small>}
            {row.id === 'v23_answer_plan_partial' && row.metrics && <small>입력 {count(row.metrics.input_tokens)} tokens · {count(row.metrics.selected_tables)} tables · {count(row.metrics.checked_cells)} cells · 파생 operand {count(row.metrics.derived_operand_count)}개 · Tool {count(row.metrics.tool_calls)}회</small>}
            {row.id === 'workbench_c_partial_stopped' && row.metrics && <small>{metric(row.metrics.wall_seconds)}초 · LLM {count(row.metrics.llm_calls)}회 / Tool {count(row.metrics.tool_calls)}회 · MES {count(row.metrics.new_mes_calls)}회 · service stopped</small>}
            {row.id === 'public_nab_nativeconv_tradeoff' && row.metrics && <small>raw/Paano mean AP {metric(row.metrics.raw_patch_k3_ap)} / {metric(row.metrics.paano_mean17_29_ap)} · pAUC@.01 {metric(row.metrics.raw_patch_k3_standardized_pauc_max_fpr0_01)} / {metric(row.metrics.paano_mean17_29_standardized_pauc_max_fpr0_01)} · FP {count(row.metrics.raw_patch_k3_fp)} / {count(row.metrics.paano_mean17_29_fp)} · no promotion</small>}
            {row.limitations?.map((limitation) => <small className="cohort-latest-limit" key={limitation}>{limitation}</small>)}
          </article>
        ))}
      </div>
      {systems && (
        <div className="cohort-table-wrap cohort-latest-table-wrap">
          <table className="cohort-table"><caption>공개 SciFact retrieval 비교 · 모델/LLM 답변 품질을 나타내지 않음</caption>
            <thead><tr><th>지표</th><th>BM25</th><th>E5</th><th>RRF c=60</th></tr></thead>
            <tbody>{([
              ['Recall@10', 'macro_recall@10'], ['Recall@100', 'macro_recall@100'], ['nDCG@10', 'ndcg@10'],
            ] as [string, 'macro_recall@10' | 'macro_recall@100' | 'ndcg@10'][]).map(([label, key]) => (
              <tr key={key}><th scope="row">{label}</th><td>{metric(systems.BM25?.[key])}</td><td>{metric(systems.E5?.[key])}</td><td>{metric(systems['RRF c=60']?.[key])}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function CohortEvidencePanel() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(refreshKey === 0);
      setRefreshing(refreshKey > 0);
      setError('');
      try {
        const result = await api<Snapshot>('/cohort-research');
        if (active) setSnapshot(result);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : '저장된 근거 스냅샷을 불러오지 못했습니다.');
      } finally {
        if (active) { setLoading(false); setRefreshing(false); }
      }
    }
    void load();
    return () => { active = false; };
  }, [refreshKey]);

  const scopes = snapshot?.scopes;
  const llm = snapshot?.llm;
  const review = snapshot?.document_review;
  const acceptedReview = snapshot?.accepted_document_review;
  const mes = snapshot?.independent_mes;
  const forecast = snapshot?.forecast;
  const publicResults = snapshot?.public_benchmarks;
  const workflowRows = [
    { name: 'Router', detail: llm?.router_requested_tools?.join(', ') || '요청 도구 대기', trace: llm?.role_traces?.filter((row) => row.role?.startsWith('router')) || [] },
    { name: '사고 DB', detail: scopes?.first_business_tool || '사고 DB 검색 상태 대기', trace: [] },
    { name: '후속 Tool', detail: scopes?.tool_call_count == null ? 'Tool 호출 수 대기' : `${count(Math.max(0, scopes.tool_call_count - 1))}회`, trace: [] },
    { name: 'Judge', detail: `판정: ${value(llm?.judge_decision)}`, trace: llm?.role_traces?.filter((row) => row.role === 'judge') || [] },
    { name: 'Answer', detail: `원인 상태: ${value(llm?.cause_status)}`, trace: llm?.role_traces?.filter((row) => row.role === 'answer') || [] },
  ];

  return (
    <section className="model-lab cohort-research" aria-labelledby="cohort-research-title">
      <header className="model-lab-heading cohort-research-heading">
        <div>
          <span className="model-lab-eyebrow">SAVED RESEARCH SNAPSHOT</span>
          <h1 id="cohort-research-title">공정 물량 · cohort 근거</h1>
          <p>저장된 합성 연구 결과를 읽기 전용으로 표시합니다. 새 분석이나 조치는 실행하지 않습니다.</p>
        </div>
        <button className="outline-button cohort-refresh" type="button" onClick={() => setRefreshKey((key) => key + 1)} disabled={refreshing}>
          <RefreshCw size={15} aria-hidden="true" /> {refreshing ? '새로 읽는 중' : '스냅샷 새로고침'}
        </button>
      </header>

      {error && <div className="cohort-alert" role="alert"><AlertTriangle size={16} />{error}</div>}
      {loading && !snapshot && <div className="model-lab-empty" role="status">저장된 근거를 불러오는 중입니다.</div>}
      {!loading && !snapshot && !error && <div className="model-lab-empty">표시할 스냅샷이 없습니다.</div>}

      {snapshot && (
        <>
          {snapshot.latest_research_status && <LatestResearchStatusPanel status={snapshot.latest_research_status} />}
          {snapshot.publication_milestone_v69
            ? <CohortMilestoneV69DraftPanel milestone={snapshot.publication_milestone_v69} />
            : snapshot.publication_milestone_v68
            ? <CohortMilestoneV68DraftPanel milestone={snapshot.publication_milestone_v68} />
            : snapshot.publication_milestone_v67
            ? <CohortMilestoneV67Panel milestone={snapshot.publication_milestone_v67} />
            : snapshot.publication_milestone_v66
              ? <CohortMilestoneV66Panel milestone={snapshot.publication_milestone_v66} />
            : snapshot.publication_milestone_v65
              ? <CohortMilestoneV65Panel milestone={snapshot.publication_milestone_v65} />
              : null}
          <details className="cohort-v5-history cohort-v65-history">
            <summary>{snapshot.publication_milestone_v69 ? '이전 실행 기록 · V6.8, V6.7, V6.6과 기존 저장 연구' : snapshot.publication_milestone_v68 ? '이전 실행 기록 · V6.7, V6.6, V6.5와 기존 저장 연구' : snapshot.publication_milestone_v67 ? '이전 실행 기록 · V6.6, V6.5와 기존 저장 연구' : snapshot.publication_milestone_v66 ? '이전 실행 기록 · V6.5와 기존 저장 연구' : '이전 실행 기록 · V6.4와 기존 저장 연구'}</summary>
          {snapshot.publication_milestone_v69 && snapshot.publication_milestone_v68 ? <CohortMilestoneV68DraftPanel milestone={snapshot.publication_milestone_v68} /> : null}
          {snapshot.publication_milestone_v68 && snapshot.publication_milestone_v67 ? <CohortMilestoneV67Panel milestone={snapshot.publication_milestone_v67} /> : null}
          {snapshot.publication_milestone_v66 && snapshot.publication_milestone_v65 ? <CohortMilestoneV65Panel milestone={snapshot.publication_milestone_v65} /> : null}
          {snapshot.publication_milestone_v64 ? <CohortMilestoneV64Panel milestone={snapshot.publication_milestone_v64} /> : null}
          {snapshot.publication_milestone ? (snapshot.publication_milestone_v64 ? <details className="cohort-v5-history" open><summary>보존된 V6.3 publication snapshot · V6.4에 대한 이전 근거</summary><CohortMilestoneV63Panel milestone={snapshot.publication_milestone} historical /></details> : <CohortMilestoneV63Panel milestone={snapshot.publication_milestone} />) : null}
          {snapshot.confirmation_milestone ? <CohortMilestoneV62Panel milestone={snapshot.confirmation_milestone} /> : null}
          {snapshot.completion_milestone ? (snapshot.confirmation_milestone ? <details className="cohort-v5-history" open><summary>보존된 V6.1 milestone · validation 완료와 confirmation score 대기 시점</summary><CohortMilestoneV61Panel milestone={snapshot.completion_milestone} historical /></details> : <CohortMilestoneV61Panel milestone={snapshot.completion_milestone} />) : null}
          {snapshot.current_milestone ? (snapshot.completion_milestone ? <details className="cohort-v5-history" open><summary>보존된 V6 milestone · 이전 시작 상태와 V8 단일 사례</summary><CohortMilestoneV6Panel milestone={snapshot.current_milestone} historical /></details> : <CohortMilestoneV6Panel milestone={snapshot.current_milestone} />) : null}
          {snapshot.milestone ? (snapshot.current_milestone ? <details className="cohort-v5-history" open><summary>보존된 V5.1 milestone · 이전 V6 / 별도20Tool 실행</summary><CohortMilestonePanel milestone={snapshot.milestone} historical /></details> : <CohortMilestonePanel milestone={snapshot.milestone} />) : null}
          <div className="cohort-legacy-heading"><span className="model-lab-kicker">LEGACY HISTORY · 13 SOURCES</span><h2>이전 저장 run · grounded-v2 / v4 비교 기록</h2><p>아래는 기존 13개 출처의 과거 결과입니다. 이전 need_evidence와 실패 기록은 그대로 보존합니다.</p></div>
      <div className="model-lab-banner cohort-research-banner">
        <strong>{snapshot?.synthetic === true ? '합성 cohort' : '상태 확인 대기'}</strong>
        <span>기준시점 {value(snapshot?.source_as_of)} · 상태 {value(snapshot?.status)} · risk floor는 정책 기준이며 원인 확률이 아닙니다.</span>
      </div>

          <section className="cohort-section" aria-labelledby="cohort-scopes-title">
            <div className="cohort-section-heading"><div><span className="model-lab-kicker">SCOPES</span><h2 id="cohort-scopes-title">현재·과거 기준·event 범위</h2></div></div>
            <div className="cohort-scope-grid">
              {([
                ['현재 물량', scopes?.current], ['과거 reference', scopes?.reference], ['DOWN event', scopes?.event],
              ] as [string, Scope][]).map(([label, scope]) => (
                <article className="cohort-scope-card" key={label}>
                  <span>{label}</span>
                  <strong>{count(scope?.wafer_count)} wafers</strong>
                  <small>{count(scope?.lot_count)} lots · {value(scope?.status)}</small>
                  <p>{scopeDescription(scope)}</p>
                </article>
              ))}
              <article className="cohort-scope-card cohort-scope-highlight">
                <span>현재 × event 교집합</span>
                <strong>{count(scopes?.intersection?.wafer_count)} / {count(scopes?.intersection?.current_denominator)}</strong>
                <small>DOWN 매칭 {count(scopes?.current_down_matched?.matched_n)} / {count(scopes?.current_down_matched?.denominator)}</small>
                <p>Risk floor {percent(scopes?.risk_floor)} · 매칭 subset에 적용된 정책값입니다.</p>
              </article>
            </div>
          </section>

          <section className="cohort-section" aria-labelledby="cohort-metro-title">
            <div className="cohort-section-heading"><div><span className="model-lab-kicker">SPARSE METRO</span><h2 id="cohort-metro-title">현재 cohort step별 계측 물량 비율</h2></div><p>공정별로 계측된 Wafer가 다를 수 있습니다. 측정되지 않은 값은 정상으로 보지 않습니다.</p></div>
            {scopes?.step_sampling?.length ? (
              <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>Step</th><th>계측 Wafer</th><th>현재 물량</th><th>계측 물량 비율</th></tr></thead><tbody>
                {scopes.step_sampling.map((row) => <tr key={row.step}><th scope="row">{row.step}</th><td>{count(row.observed_n)}</td><td>{count(row.total_n)}</td><td>{percent(row.coverage)}</td></tr>)}
              </tbody></table></div>
            ) : <p className="cohort-empty-note">step별 측정 결과가 없습니다.</p>}
            <div className="cohort-forecast-line"><strong>미래 cohort Yield 예측</strong><span>{percent(scopes?.future_cohort_yield?.point)}</span><small>관측 OUT {scopes?.future_cohort_yield?.outcome_observed === false ? '없음' : '확인 대기'} · outcome query {count(scopes?.outcome_queries)}</small></div>
            {scopes?.future_signature_rates?.length ? <>
              <p className="cohort-caption">결함 group별 예측률은 겹칠 수 있으므로 합계 100%로 해석하지 않습니다.</p>
              <div className="cohort-signature-grid">{scopes.future_signature_rates.map((row) => <div key={row.target}><span>{row.target}</span><strong>{percent(row.point)}</strong></div>)}</div>
            </> : null}
          </section>

          <section className="cohort-section" aria-labelledby="cohort-workflow-title">
            <div className="cohort-section-heading"><div><span className="model-lab-kicker">RUN TRACE</span><h2 id="cohort-workflow-title">조회와 검토 순서</h2></div><p>{count(llm?.model_calls)} local model calls · {count(scopes?.tool_call_count)} tool calls</p></div>
            <div className="cohort-table-wrap"><table className="cohort-table cohort-workflow-table"><thead><tr><th>순서</th><th>단계</th><th>저장된 상태</th><th>Token / latency</th></tr></thead><tbody>
              {workflowRows.map((row, index) => <tr key={row.name}><td>{String(index + 1).padStart(2, '0')}</td><th scope="row">{row.name}</th><td>{row.detail}</td><td>{row.trace.length ? row.trace.map((trace, i) => <span className="cohort-trace-chip" key={`${row.name}-${i}`}>{count(trace.input_tokens)} in / {count(trace.output_tokens)} out · {trace.elapsed_ms == null ? '시간 대기' : `${(trace.elapsed_ms / 1000).toFixed(1)} s`}</span>) : '—'}</td></tr>)}
            </tbody></table></div>
            <p className="cohort-final-scope"><strong>최종 조회 상태</strong> · {value(llm?.status)} · 원인 {value(llm?.cause_status)} · 시연 승인 {llm?.accepted_for_demo === false ? '보류' : llm?.accepted_for_demo === true ? '승인' : '대기'}</p>
          </section>

          {llm?.budget_stop && <section className="cohort-section cohort-stop" aria-labelledby="cohort-stop-title"><div className="cohort-section-heading"><div><span className="model-lab-kicker">REQUERY LIMIT</span><h2 id="cohort-stop-title">추가 근거 요청과 budget stop</h2></div></div><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>규칙</th><th>요청</th><th>새 데이터 조회</th><th>상태 및 사유</th></tr></thead><tbody><tr><th scope="row">{value(llm.budget_stop.return_to || '확인 대기')}</th><td>{llm.budget_stop.requested_tools?.join(', ') || '요청 도구 대기'}</td><td>{llm.budget_stop.new_data_queried === false ? '없음' : boolLabel(llm.budget_stop.new_data_queried)}</td><td><strong>{value(llm.budget_stop.status)}</strong><br />{value(llm.budget_stop.reason)}</td></tr></tbody></table></div></section>}

          <section className="cohort-section" aria-labelledby="cohort-answer-title"><div className="cohort-section-heading"><div><span className="model-lab-kicker">SAVED ANSWER</span><h2 id="cohort-answer-title">저장된 Answer</h2></div></div><blockquote className="cohort-answer">{llm?.summary || '저장된 Answer가 없습니다.'}</blockquote><div className="cohort-limitations"><strong>Answer limitations</strong><p>{llm?.limitations?.join(' · ') || '제한사항 정보 대기'}</p></div>
            {llm?.manual_review_status && <div className="cohort-review-note"><strong>Manual review</strong><span>{value(llm.manual_review_status.answer_grounding)} · {value(llm.manual_review_status.workflow)}</span>{llm.manual_findings?.length ? <ul>{llm.manual_findings.map((finding, i) => <li key={i}>{finding.severity ? <strong>{finding.severity}: </strong> : null}{value(finding.finding)}</li>)}</ul> : null}</div>}
          </section>

          <section className="cohort-section" aria-labelledby="cohort-actions-title"><div className="cohort-section-heading"><div><span className="model-lab-kicker">ACTION SEPARATION</span><h2 id="cohort-actions-title">동일 run과 별도 synthetic MES 검증</h2></div></div>
            <div className="cohort-action-grid"><article><h3>현재 LLM run</h3><p>상태 {value(snapshot.action_execution?.status)} · 기록 receipt {count(snapshot.action_execution?.receipt_count)}</p><p>신규 조치 실행 {boolLabel(snapshot.action_execution?.new_actions_executed)} · production 실행 {boolLabel(snapshot.action_execution?.production_execution)}</p></article>
              <article><h3>Adapter 별도 검증</h3><p>{value(mes?.experiment_label)} · synthetic only</p><dl>{Object.entries(mes?.counts || {}).map(([key, n]) => <div key={key}><dt>{key}</dt><dd>{count(n)}</dd></div>)}</dl><p>미영향 wafer {count(mes?.unaffected_wafer_count)} · 원본 warehouse 유지 {mes?.source_warehouse_unchanged === true ? '확인' : '확인 대기'}</p></article></div>
          </section>

          <section className="cohort-section" aria-labelledby="cohort-forecast-title"><div className="cohort-section-heading"><div><span className="model-lab-kicker">FRESH SYNTHETIC CONFIRMATION</span><h2 id="cohort-forecast-title">v1 대비 고정 v4 비교</h2></div></div>
            {forecast ? <><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>지표</th><th>v1</th><th>v4</th></tr></thead><tbody><tr><th scope="row">Macro raw MAE</th><td>{metric(forecast.raw_mae?.v1)}</td><td>{metric(forecast.raw_mae?.v4)}</td></tr><tr><th scope="row">Macro normalized MAE</th><td>{metric(forecast.normalized_mae?.v1)}</td><td>{metric(forecast.normalized_mae?.v4)}</td></tr></tbody></table></div><p className="cohort-ci">Paired Δ v4−v1 95% CI: [{forecast.delta_ci95?.map((x) => x.toFixed(4)).join(', ') || '확인 대기'}]</p><ul className="cohort-flags"><li>Yield predictions exact equality: {forecast.yield_exact == null ? '확인 대기' : forecast.yield_exact ? '예' : '아니오'}</li><li>Family 3 regression preserved: {forecast.family3_regressed == null ? '확인 대기' : forecast.family3_regressed ? '예' : '아니오'}</li><li>Prior holdout metrics informed candidate: {forecast.prior_holdout_informed == null ? '확인 대기' : forecast.prior_holdout_informed ? '예' : '아니오'}</li></ul><p className="cohort-caption">3개 fresh seed의 같은 synthetic generator family를 사용한 조건부 평가입니다. v4는 독립적으로 선택된 모델이 아닙니다.</p></> : <p className="cohort-empty-note">forecast 결과 대기</p>}
          </section>

          <section className="cohort-section" aria-labelledby="cohort-public-title"><div className="cohort-section-heading"><div><span className="model-lab-kicker">PUBLIC BENCHMARKS</span><h2 id="cohort-public-title">공개 ChestMNIST 결과</h2></div><span className="cohort-chip">같은 test split 재사용 · site 검증 아님</span></div>
            <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>모델</th><th>Macro AP</th><th>Macro F1</th><th>구분</th></tr></thead><tbody>
              <tr><th scope="row">Extended CNN (ASL)</th><td>{metric(publicResults?.cnn?.macro_ap)}</td><td>{metric(publicResults?.cnn?.macro_f1)}</td><td>Public · prior split exposure</td></tr>
              <tr><th scope="row">DINO frozen linear</th><td>{metric(publicResults?.dino?.linear?.macro_ap)}</td><td>{metric(publicResults?.dino?.linear?.macro_f1)}</td><td>Public · seed {value(publicResults?.dino?.linear?.seed)}</td></tr>
              <tr><th scope="row">DINO last-two-block fine-tune</th><td>{metric(publicResults?.dino?.finetuned?.macro_ap)}</td><td>{metric(publicResults?.dino?.finetuned?.macro_f1)}</td><td>Public · seed {value(publicResults?.dino?.finetuned?.seed)}</td></tr>
            </tbody></table></div><p className="cohort-caption">환자 단위 분리와 DINO 사전학습 중복은 검증되지 않았습니다. 임상 또는 FAB 성능을 나타내지 않습니다.</p>
          </section>

          <section className="cohort-section" aria-labelledby="cohort-trend-title"><div className="cohort-section-heading"><div><span className="model-lab-kicker">NUMERIC TREND</span><h2 id="cohort-trend-title">별도 numeric trend v2 결과</h2></div></div>
            <p>상태 {value(snapshot.numeric_trend?.status)} · model inference {snapshot.numeric_trend?.model_inference_executed === false ? '실행 안 함' : '확인 대기'} · OUT 조회 {count(snapshot.numeric_trend?.outcome_queries)}</p>
            {(['current', 'past_reference'] as const).map((name) => <div className="cohort-trend-scope" key={name}><strong>{name === 'current' ? 'Current' : 'Past reference'}</strong><span>{snapshot.numeric_trend?.series?.[name]?.map((row) => `${row.step}/${row.item}: ${count(row.timepoints)} points`).join(' · ') || 'series 대기'}</span></div>)}
          </section>

          <section className="cohort-section cohort-doc-review" aria-labelledby="cohort-doc-title">
            <div className="cohort-section-heading"><div><span className="model-lab-kicker">DOCUMENT REVIEW</span><h2 id="cohort-doc-title">합성 문서 corpus review</h2></div></div>
            <article className="cohort-review-note">
              <strong>현재 accepted review · descriptive synthetic RAG 한정</strong>
              <span>{value(acceptedReview?.status)} · {count(acceptedReview?.distinct_case_count)} cases · {count(acceptedReview?.document_count)} documents · 개별 page 검토 {count(acceptedReview?.individually_reviewed_page_count)}</span>
              <p>문서 review 결론: {acceptedReview?.accepted_for_descriptive_synthetic_rag === true ? 'descriptive synthetic RAG 범위에 수용' : '확인 대기'} · 실제 index 구축 완료, 일반 LLM 답변 품질, enterprise source 검증을 승인하는 뜻은 아닙니다.</p>
              {acceptedReview?.format_corpus_counts && <ul>{Object.entries(acceptedReview.format_corpus_counts).map(([key, n]) => <li key={key}>{key}: {count(n)}</li>)}</ul>}
              {acceptedReview?.review_findings?.length ? <ul>{acceptedReview.review_findings.map((item, i) => <li key={`finding-${i}`}>{item}</li>)}</ul> : null}
              {acceptedReview?.visual_review_limits?.length ? <><strong>Visual review limits</strong><ul>{acceptedReview.visual_review_limits.map((item, i) => <li key={`limit-${i}`}>{item}</li>)}</ul></> : null}
              {acceptedReview?.manifest_sha256 && <code>accepted review manifest SHA256 · {acceptedReview.manifest_sha256}</code>}
            </article>
            <article className="cohort-review-note">
              <strong>이전 rejected attempt · 별도 보존</strong>
              <span>{value(review?.status)}</span>
              <p>해당 attempt의 RAG 수용: {review?.accepted_for_demo === false ? '아니오 · 재생성 전 결과' : '확인 대기'} · binary 문서는 승인된 자료로 사용하지 않습니다.</p>
              {review?.issues?.length ? <ul>{review.issues.map((issue, i) => <li key={`rejected-${i}`}>{issue}</li>)}</ul> : <p>이전 검토 항목 대기</p>}
            </article>
          </section>

          <details className="cohort-provenance"><summary>Role trace 및 source hash 보기</summary><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>Role</th><th>Input</th><th>Output</th><th>Elapsed</th></tr></thead><tbody>{llm?.role_traces?.map((row, i) => <tr key={`${row.role}-${i}`}><th scope="row">{value(row.role)}</th><td>{count(row.input_tokens)}</td><td>{count(row.output_tokens)}</td><td>{row.elapsed_ms == null ? '확인 대기' : `${(row.elapsed_ms / 1000).toFixed(1)} s`}</td></tr>)}</tbody></table></div><ul className="cohort-hashes">{snapshot.provenance?.artifacts?.map((entry) => <li key={entry.name}><span>{entry.name} · {value(entry.availability)}</span><code>{entry.sha256 || 'SHA256 대기'}</code></li>)}</ul></details>
          </details>
        </>
      )}
    </section>
  );
}
