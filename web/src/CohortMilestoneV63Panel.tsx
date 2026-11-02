import './CohortMilestoneV63Panel.css';

type WorkflowRow = { stage: string; status: string; first_business_tool?: string };
type ProofRef = { id: string; status: string; sha256: string; file: string };
export type ResearchMilestoneV63 = {
  schema_id: string;
  status: string;
  synthetic: boolean;
  production: boolean;
  new_actions: number;
  new_full_local_agent_run_completed: boolean;
  proof_count: number;
  proofs: ProofRef[];
  workflow: WorkflowRow[];
  workflow_status: string;
  qwen_role_replay: {
    completed_returns: number;
    baseline_returns: number;
    bounded_returns: number;
    baseline_answer_completed: boolean;
    bounded_text_and_tokens_identical: boolean;
    bounded_peak_reserved_gib: number;
    baseline_first_cap_crossing_observed_gib: number;
    new_tool_calls: number;
    new_actions: number;
    instrumented_common_role_latency: Record<string, { baseline_seconds: number; bounded_seconds: number }>;
    limits: string[];
  };
  tools_mes: {
    dispatches: number;
    tool_name_count: number;
    first_business_tool: string;
    llm_calls: number;
    hold_wafer_count: number;
    release_wafer_count: number;
    active_holds_after_release: number;
    active_blocks_after_release: number;
    transactions: number;
    qualification_pass_basis: string;
    dispatch_admission_controller_verified: boolean;
    production: boolean;
    limits: string[];
  };
  bloodmnist: {
    public_dataset: string;
    selected_arm: string;
    test_rows: number;
    metrics: Record<string, { macro_auc: number; accuracy: number }>;
    independent_arithmetic_audit: boolean;
    production: boolean;
    FAB_validation: boolean;
    clinical_validation: boolean;
    limits: string[];
  };
  sem_v2: {
    confirmation_rows: number;
    confirmation_wafers: number;
    planned_sites: number;
    unobserved_chips_per_wafer: number;
    families: string[];
    seeds: number[];
    local_ap_min: number;
    local_ap_max: number;
    threshold: number;
    fixed_threshold_errors_present: boolean;
    local_mark_validation_rows: number;
    local_mark_control_positive_rate: number;
    serving_registered: boolean;
    limits: string[];
  };
  qwen_load_mode: {
    mode: string;
    peak_allocated_gib: Record<string, number>;
    postload_allocated_gib: Record<string, number>;
    process_peak_rss_gib: Record<string, number>;
    comparison_claim: string;
    inference_quality_established: boolean;
    limits: string[];
  };
  limits: string[];
};

const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
const fixed = (value: number, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : '미확인';
const runLabels: Record<string, string> = {
  'async0-baseline-01': 'Async load · 0',
  'async1-sequential-01': 'Sequential load · 1',
};

export default function CohortMilestoneV63Panel({ milestone: m, historical = false }: { milestone: ResearchMilestoneV63; historical?: boolean }) {
  const cnn = m.bloodmnist.metrics.CNN;
  const dino = m.bloodmnist.metrics.DINO;
  return <section className="cohort-section cohort-milestone cohort-milestone-v63" aria-labelledby="cohort-milestone-v63-title">
    <div className="cohort-section-heading">
      <div><span className="model-lab-kicker">{historical ? '보존 이력 · MILESTONE V6.3' : 'LATEST · MILESTONE V6.3'}</span><h2 id="cohort-milestone-v63-title">ROOT 제한 수용 · Tool/MES, 모델 자원, 공개 이미지 근거</h2></div>
      <span className="cohort-chip">{historical ? 'V6.3 저장 상태 · 합성 연구 · 새 조치 0 · production 아님' : '합성 연구 · 새 조치 0 · production 아님'}</span>
    </div>

    <div className="cohort-v63-intro">
      <strong>{historical ? 'V6.3 당시에는 새로운 full local Router → Answer 실행이 아직 없었습니다.' : '새로운 full local Router → Answer 실행은 아직 없습니다.'}</strong>
      <p>아래 25회는 LLM 없이 실행한 scripted Tool run이고, Qwen의 5회 완료는 과거 trace replay의 두 resource 설정을 합한 수입니다. 서로 다른 실험입니다.</p>
    </div>

    <div className="cohort-table-wrap">
      <table className="cohort-table cohort-v63-workflow">
        <thead><tr><th>순서</th><th>단계</th><th>V6.3 proof의 상태</th></tr></thead>
        <tbody>{m.workflow.map((row, index) => <tr key={row.stage}>
          <td>{index + 1}</td><th scope="row">{row.stage}</th>
          <td>{row.first_business_tool ? `${row.status} · ${row.first_business_tool}` : row.status}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="cohort-v63-workflow-status" role="status">{historical ? 'V6.3 당시 상태:' : '현재 상태:'} {m.workflow_status}</p>

    <div className="cohort-milestone-grid cohort-v63-grid">
      <article className="cohort-milestone-card">
        <h3>Scripted synthetic Tools + dummy MES</h3>
        <div className="cohort-v63-statline"><strong>{m.tools_mes.dispatches}</strong><span>typed dispatches · {m.tools_mes.tool_name_count} Tool names · LLM {m.tools_mes.llm_calls}</span></div>
        <p>첫 업무 Tool은 <code>{m.tools_mes.first_business_tool}</code>. Dummy HOLD {m.tools_mes.hold_wafer_count} Wafer → RELEASE {m.tools_mes.release_wafer_count} Wafer. 종료 상태: active HOLD {m.tools_mes.active_holds_after_release}, dispatch block {m.tools_mes.active_blocks_after_release}.</p>
        <p>Qualification PASS는 {m.tools_mes.qualification_pass_basis}. Dispatch admission controller 확인 여부: {m.tools_mes.dispatch_admission_controller_verified ? '확인' : '미확인'}. 실제 MES/production 실행은 없습니다.</p>
        <ul className="cohort-milestone-limits">{m.tools_mes.limits.map((item) => <li key={item}>{item}</li>)}</ul>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Qwen historical role replay · memory</h3>
        <p>완료된 return {m.qwen_role_replay.completed_returns}: baseline {m.qwen_role_replay.baseline_returns}, bounded {m.qwen_role_replay.bounded_returns}. Bounded 3개 답변은 보존 trace와 text/token이 같았습니다. Baseline은 cap 초과 첫 관측에서 끝나 Answer가 미완료입니다.</p>
        <p>Observed reserved memory: baseline cap crossing {fixed(m.qwen_role_replay.baseline_first_cap_crossing_observed_gib)} GiB, bounded peak {fixed(m.qwen_role_replay.bounded_peak_reserved_gib)} GiB. 공통 Router/Judge 처리시간은 bounded가 더 길었습니다. 속도 향상이나 일반 답변 품질 pass를 뜻하지 않습니다.</p>
        <h4>Load-only flag probe</h4>
        <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>실행</th><th>Peak allocated</th><th>Post-load allocated</th><th>Process peak RSS</th></tr></thead>
          <tbody>{Object.entries(m.qwen_load_mode.peak_allocated_gib).map(([run, peak]) => <tr key={run}><th scope="row">{runLabels[run] || run}</th><td>{fixed(peak)} GiB</td><td>{fixed(m.qwen_load_mode.postload_allocated_gib[run])} GiB</td><td>{fixed(m.qwen_load_mode.process_peak_rss_gib[run])} GiB</td></tr>)}</tbody>
        </table></div>
        <p>{m.qwen_load_mode.comparison_claim}. Load-only result; no forward, inference-quality or 14B capacity claim.</p>
      </article>

      <article className="cohort-milestone-card">
        <h3>Public {m.bloodmnist.public_dataset} · fixed benchmark</h3>
        <p>Validation-only arm selection: <strong>{m.bloodmnist.selected_arm}</strong>. Independent arithmetic review covered {m.bloodmnist.test_rows.toLocaleString()} official test rows.</p>
        <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>Arm</th><th>Macro AUC</th><th>Accuracy</th></tr></thead><tbody>
          <tr><th scope="row">CNN · selected</th><td>{fixed(cnn.macro_auc, 4)}</td><td>{pct(cnn.accuracy)}</td></tr>
          <tr><th scope="row">DINO</th><td>{fixed(dino.macro_auc, 4)}</td><td>{pct(dino.accuracy)}</td></tr>
        </tbody></table></div>
        <p>This is a public image benchmark, not semiconductor or clinical validation. Donor grouping is unverified; architectures also used different pretraining, resolution and compute.</p>
        <ul className="cohort-milestone-limits">{m.bloodmnist.limits.map((item) => <li key={item}>{item}</li>)}</ul>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>SEM v2 procedural proxy · confirmation + local-mark control</h3>
        <p>{m.sem_v2.confirmation_rows.toLocaleString()} crops / {m.sem_v2.confirmation_wafers} Wafers · {m.sem_v2.planned_sites} planned sites per Wafer; the other {m.sem_v2.unobserved_chips_per_wafer} Chips remain unknown.</p>
        <p>Local AP range {fixed(m.sem_v2.local_ap_min, 4)}–{fixed(m.sem_v2.local_ap_max, 4)}. At fixed {fixed(m.sem_v2.threshold)} threshold, some models have false positives or false negatives. This toy proxy score does not validate real SEM defects.</p>
        <p>Local-mark removal changed model input responses in {m.sem_v2.local_mark_validation_rows.toLocaleString()} validation crops; control positive rate at the same threshold was {pct(m.sem_v2.local_mark_control_positive_rate)}. This is procedural input-dependence evidence, not physical-cause evidence. Selected all13 candidate is registered: {m.sem_v2.serving_registered ? 'yes' : 'no'}.</p>
        <ul className="cohort-milestone-limits">{m.sem_v2.limits.map((item) => <li key={item}>{item}</li>)}</ul>
      </article>
    </div>

    <details className="cohort-milestone-pending cohort-v63-proofs">
      <summary>ROOT acceptance proofs · {m.proof_count} capsule hashes</summary>
      <ul>{m.proofs.map((proof) => <li key={proof.id}><strong>{proof.id}</strong> · {proof.status} · <code>{proof.file}</code><br /><code>{proof.sha256}</code></li>)}</ul>
    </details>
    <details className="cohort-milestone-pending"><summary>Bundle limitations</summary><ul className="cohort-milestone-limits">{m.limits.map((item) => <li key={item}>{item}</li>)}</ul></details>
  </section>;
}
