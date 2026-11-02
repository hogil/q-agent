import './CohortMilestoneV65Panel.css';

type WorkflowRow = { stage: string; ro6: string; ro7: string };
type ProofRow = { id: string; status: string; sha256: string; file: string };
export type ResearchMilestoneV65 = {
  schema_id: string;
  status: string;
  created_at_utc: string;
  synthetic: boolean;
  production: boolean;
  viewer_actions: number;
  recorded_synthetic_action_commits: number;
  current_serving_world: string;
  corrected_V4_future_model_integrated_in_current_serving: boolean;
  platform_complete: boolean;
  proof_count: number;
  proofs: ProofRow[];
  workflow: WorkflowRow[];
  original_csv_trend: {
    fits: number; selected_model: string; test_rows: number; test_positive: number; unknown: number;
    retrospective: boolean; test_already_exposed: boolean; cnn1d_ap: number;
    model_comparison: { model: string; selected_on_validation: boolean; AP: number; fixed05_F1: number;
      parameters: number; fit_seconds_min: number; fit_seconds_max: number }[];
    fpr1_test: { threshold: number; test_fpr: number; rows: number }; limits: string[];
  };
  spread_trend_v2: {
    fits: number; rows: number; validation_selected_model: string; validation_ap: number;
    confirmation_ap: { A128mean: number; B128spread: number; C512spread: number };
    primary_B_minus_A_delta_ap: number; primary_B_minus_A_ci95: [number, number];
    secondary_C_minus_B_ci95: [number, number]; automatic_promotion: boolean;
    current_fullworld_trend_model_changed: boolean; limits: string[];
  };
  action_v6: {
    root_stages: number; actual_LLM_returns: number; recorded_synthetic_action_commits: number; viewer_actions: number;
    hold_wafers: number; requested_cells: number; qualified_cells: number; recovery_up_pass: number;
    released_wafers: number; allowed_new_progress: number; allowed_replay_new_progress: number;
    denied_new_progress: number; denied_replay_after_release_new_progress: number;
    final_active_holds: number; final_active_blocks: number; final_pass_cells: number;
    final_simulated_progress: number; audit_hash_chain_rows: number; frozen_source_bindings: number;
    production: boolean; source_DB_or_Yield_rewritten: boolean; limits: string[];
  };
  local_RO6: {
    actual_LLM_returns: number; actual_Tool_calls: number; compiled_claims: number;
    forecast_executed: boolean; current_OUT_feature_queries: number; first_business_Tool: string;
    last_LLM: string; task_answer_fully_accepted: boolean; new_actions: number; limits: string[];
  };
  image_RO7: {
    actual_LLM_invocations: number; actual_LLM_returns: number; actual_Tool_results: number;
    image_list_rows: number; imaged_Wafers: number; hits: number; DINO_CPU_queries: number;
    judge_answer_completed: boolean; judge_input_tokens: number; max_input_tokens: number;
    judge_input_over_budget: boolean; new_actions: number; morphology_registered: boolean;
    image_retrieval_quality_established: boolean; limits: string[];
  };
  final_scope_status: {
    current_serving_world: string; corrected_V4_future_model_integrated: boolean; platform_complete: boolean;
    synthetic: boolean; production: boolean; viewer_actions: number; recorded_synthetic_action_commits: number;
  };
  limits: string[];
};

const n = (value: number) => value.toLocaleString('ko-KR');
const metric = (value: number) => value.toFixed(4);
const pct = (value: number) => `${(value * 100).toFixed(2)}%`;

export default function CohortMilestoneV65Panel({ milestone: m }: { milestone: ResearchMilestoneV65 }) {
  return <section className="cohort-section cohort-milestone cohort-milestone-v65" aria-labelledby="cohort-milestone-v65-title">
    <div className="cohort-section-heading cohort-v65-heading">
      <div><span className="model-lab-kicker">LATEST · MILESTONE V6.5</span><h2 id="cohort-milestone-v65-title">최신 검증 결과</h2></div>
      <span className="cohort-chip">제한 수용 · 독립 evidence 5개</span>
    </div>

    <div className="cohort-v65-intro">
      <strong>서로 다른 합성 연구 실행 기록입니다. 수치는 run별로 분리되어 있습니다.</strong>
      <p>Viewer action {m.viewer_actions}회와 별도 synthetic ledger commit {m.recorded_synthetic_action_commits}건은 다른 범위입니다. production 검증이나 전체 플랫폼 완료를 의미하지 않습니다.</p>
    </div>

    <div className="cohort-milestone-grid cohort-v65-grid">
      <article className="cohort-milestone-card cohort-v6-caution cohort-v65-csv-card">
        <h3>Original CSV Trend · retrospective test</h3>
        <p>{m.original_csv_trend.fits} fits · validation에서 {m.original_csv_trend.selected_model} 선택 · test {n(m.original_csv_trend.test_rows)} rows.</p>
        <p>아래 AP와 F1은 과거 test 결과이며, F1은 사전 지정 보고 기준인 threshold 0.5입니다. 파라미터 수와 seed별 학습시간도 함께 표시합니다.</p>
        <div className="cohort-table-wrap cohort-v65-model-table-wrap">
          <table className="cohort-table cohort-v65-model-table">
            <thead><tr><th>모델</th><th>AP</th><th>F1 @ 0.5</th><th>파라미터</th><th>Seed 학습시간 (초)</th></tr></thead>
            <tbody>{m.original_csv_trend.model_comparison.map((row) => <tr key={row.model}>
              <th scope="row">{row.model}{row.selected_on_validation ? <small>validation 선택</small> : null}</th>
              <td>{metric(row.AP)}</td><td>{metric(row.fixed05_F1)}</td><td>{n(row.parameters)}</td>
              <td>{metric(row.fit_seconds_min)}–{metric(row.fit_seconds_max)}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <p>Validation-calibrated FPR1 threshold의 test FPR은 {pct(m.original_csv_trend.fpr1_test.test_fpr)}입니다. 이 synthetic test는 과거 노출이 있어 새 blinded confirmation이 아닙니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Spread Trend V2 · 별도 confirmation</h3>
        <p>{m.spread_trend_v2.fits} fits · validation 선택 {m.spread_trend_v2.validation_selected_model} · validation AP {metric(m.spread_trend_v2.validation_ap)}.</p>
        <p>Confirmation AP: A128mean {metric(m.spread_trend_v2.confirmation_ap.A128mean)}, B128spread {metric(m.spread_trend_v2.confirmation_ap.B128spread)}, C512spread {metric(m.spread_trend_v2.confirmation_ap.C512spread)}. B−A Δ {metric(m.spread_trend_v2.primary_B_minus_A_delta_ap)} · 95% CI [{m.spread_trend_v2.primary_B_minus_A_ci95.map(metric).join(', ')}].</p>
        <p>C−B interval [{m.spread_trend_v2.secondary_C_minus_B_ci95.map(metric).join(', ')}]에는 0이 포함됩니다. Synthetic input-design 결과이며 현재 Trend serving에는 연결되지 않았습니다.</p>
      </article>

      <article className="cohort-milestone-card">
        <h3>ActionV6 · isolated synthetic ledger</h3>
        <p>{m.action_v6.root_stages} stage · LLM returns {m.action_v6.actual_LLM_returns}. HOLD {m.action_v6.hold_wafers} Wafer → METRO {n(m.action_v6.qualified_cells)}/{n(m.action_v6.requested_cells)} PASS → RELEASE {m.action_v6.released_wafers} Wafer.</p>
        <p>새 admission {m.action_v6.allowed_new_progress} · 동일 요청 replay {m.action_v6.allowed_replay_new_progress} · 최종 active hold/block {m.action_v6.final_active_holds}/{m.action_v6.final_active_blocks} · hash-chain {m.action_v6.audit_hash_chain_rows} rows.</p>
        <p>별도 기록 commit {m.action_v6.recorded_synthetic_action_commits}, Viewer action {m.action_v6.viewer_actions}. 생산 MES와 source DB는 변경되지 않았습니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Local RO6 · task coverage partial</h3>
        <p>LLM returns {m.local_RO6.actual_LLM_returns} · Tool calls {m.local_RO6.actual_Tool_calls} · compiled claims {m.local_RO6.compiled_claims}. 첫 업무 Tool {m.local_RO6.first_business_Tool}.</p>
        <p>Forecast 실행 · current OUT feature query {m.local_RO6.current_OUT_feature_queries}. Answer는 반환됐지만 task 전체 답변은 수용되지 않았습니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Image RO7 · Judge/Answer 미완료</h3>
        <p>LLM invocations {m.image_RO7.actual_LLM_invocations} · returns {m.image_RO7.actual_LLM_returns} · Tool results {m.image_RO7.actual_Tool_results}. Image list {m.image_RO7.image_list_rows} rows · {m.image_RO7.hits} hits.</p>
        <p>Judge 입력 {n(m.image_RO7.judge_input_tokens)} / 한도 {n(m.image_RO7.max_input_tokens)} tokens. Judge와 Answer는 완료되지 않았고 morphology 등록이나 retrieval 품질 확립도 없습니다.</p>
      </article>
    </div>

    <div className="cohort-section-heading cohort-v65-flow-heading">
      <div><span className="model-lab-kicker">RUNS KEPT SEPARATE</span><h3>Router → 사고 DB → Tools → Judge → Answer</h3></div>
      <p>RO6와 RO7은 별도 실행 열에 표시합니다.</p>
    </div>
    <div className="cohort-table-wrap">
      <table className="cohort-table cohort-v65-workflow">
        <thead><tr><th>순서</th><th>단계</th><th>RO6</th><th>RO7</th></tr></thead>
        <tbody>{m.workflow.map((row, index) => <tr key={row.stage}>
          <td>{index + 1}</td><th scope="row">{row.stage}</th><td>{row.ro6}</td><td>{row.ro7}</td>
        </tr>)}</tbody>
      </table>
    </div>

    <section className="cohort-v65-final" aria-label="최종 범위와 상태">
      <div><span>최종 serving scope</span><strong>{m.final_scope_status.current_serving_world}</strong></div>
      <div><span>Corrected V4 future TabM 통합</span><strong>{m.final_scope_status.corrected_V4_future_model_integrated ? '통합' : '미통합'}</strong></div>
      <div><span>Platform status</span><strong>{m.final_scope_status.platform_complete ? '완료' : '미완료'}</strong></div>
      <p>합성 {String(m.final_scope_status.synthetic)} · production {String(m.final_scope_status.production)} · Viewer actions {m.final_scope_status.viewer_actions} · 별도 synthetic commits {m.final_scope_status.recorded_synthetic_action_commits}</p>
    </section>

    <details className="cohort-milestone-pending cohort-v65-details">
      <summary>ROOT 제한 수용 proof · {m.proof_count}개 고정 hash</summary>
      <ul>{m.proofs.map((proof) => <li key={proof.id}><strong>{proof.id}</strong> · {proof.status} · <code>{proof.file}</code><br /><code>{proof.sha256}</code></li>)}</ul>
    </details>
    <details className="cohort-milestone-pending cohort-v65-details">
      <summary>연구 제한</summary>
      <ul>{m.limits.map((item) => <li key={item}>{item}</li>)}</ul>
    </details>
    <p className="cohort-caption">Snapshot {m.created_at_utc} · {m.proof_count} ROOT-accepted proof hashes · synthetic {String(m.synthetic)} · production {String(m.production)}.</p>
  </section>;
}
