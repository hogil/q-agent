import './CohortMilestoneV64Panel.css';

type WorkflowRow = { stage: string; status: string; first_business_tool?: string };
type ProofRow = { id: string; status: string; sha256: string; file: string };
export type ResearchMilestoneV64 = {
  schema_id: string;
  status: string;
  created_at_utc: string;
  synthetic: boolean;
  production: boolean;
  new_actions: number;
  platform_complete: boolean;
  current_serving_world: string;
  proof_count: number;
  proofs: ProofRow[];
  workflow: WorkflowRow[];
  workflow_status: string;
  future135: { selected_model: string; confirmation_balanced_normalized_mae: number; MLP_confirmation_balanced_normalized_mae: number; rows: number; calendar_weeks: number; targets: number; worlds: number; integrated_in_current_serving: boolean; limits: string[] };
  numeric_trend: { fits: number; rows: number; patchtsmixer_ap: number; cnn1d_ap: number; fpr1_recall: number; high_performance_established: boolean; limits: string[] };
  image_tools: { tool_sequence: string[]; cpu_forwards: number; hits: number; gallery_rows: number; LLM_calls: number; MES_commits: number; GPU_calls: number; morphology_registered: boolean; limits: string[] };
  qwen_resource_replay: { baseline_returns: number; bounded_returns: number; total_returns: number; new_Tool_calls: number; new_actions: number; external_API_calls: number; limits: string[] };
  local_agent_v5: { LLM_returns: number; Tool_calls: number; first_business_tool: string; last_LLM: string; new_actions: number; compiled_claims: number; task_answer_accepted: boolean; failure: string };
  limits: string[];
};

const n = (value: number) => value.toLocaleString('ko-KR');
const metric = (value: number) => value.toFixed(4);

export default function CohortMilestoneV64Panel({ milestone: m }: { milestone: ResearchMilestoneV64 }) {
  return <section className="cohort-section cohort-milestone cohort-milestone-v64" aria-labelledby="cohort-milestone-v64-title">
    <div className="cohort-section-heading">
      <div><span className="model-lab-kicker">LATEST · MILESTONE V6.4</span><h2 id="cohort-milestone-v64-title">제한 수용된 연구 근거 · 실행 상태와 남은 검증</h2></div>
      <span className="cohort-chip">합성 연구 · 새 조치 0 · production 아님</span>
    </div>

    <div className="cohort-v64-intro">
      <strong>플랫폼은 아직 완료되지 않았습니다. V5 제어 흐름은 끝났지만 최종 task answer는 수용되지 않았습니다.</strong>
      <p>아래 결과는 서로 다른 synthetic/public 실험입니다. corrected V4 TabM 미래예측은 현재 serving world {m.current_serving_world}에 연결되지 않았고, 실제 FAB 또는 production 검증이 아닙니다.</p>
    </div>

    <div className="cohort-table-wrap">
      <table className="cohort-table cohort-v64-workflow">
        <thead><tr><th>순서</th><th>단계</th><th>V5 실제 실행에서 확인된 상태</th></tr></thead>
        <tbody>{m.workflow.map((row, index) => <tr key={row.stage}>
          <td>{index + 1}</td><th scope="row">{row.stage}</th>
          <td>{row.first_business_tool ? `${row.status} · ${row.first_business_tool}` : row.status}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="cohort-v64-workflow-status" role="status">{m.workflow_status}</p>

    <div className="cohort-milestone-grid cohort-v64-grid">
      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Corrected V4 future135 · 별도 confirmation</h3>
        <p>Validation에서 TabM-flat을 선택했습니다. 별도 confirmation balanced normalized MAE는 <strong>{metric(m.future135.confirmation_balanced_normalized_mae)}</strong>; MLP-full {metric(m.future135.MLP_confirmation_balanced_normalized_mae)}입니다. {n(m.future135.rows)} rows · {m.future135.calendar_weeks}주 · {m.future135.targets} targets · {m.future135.worlds} synthetic world.</p>
        <p>이 모델은 현재 serving에 통합되지 않았습니다. 이 결과는 단순 정상/이상 Trend 분류가 아니며, 여섯 target 악화 및 단일 synthetic world라는 제한을 유지합니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Official numeric Trend · confirmation arithmetic</h3>
        <p>9회 fit · {n(m.numeric_trend.rows)} rows. PatchTSMixer AP {metric(m.numeric_trend.patchtsmixer_ap)}; CNN1D {metric(m.numeric_trend.cnn1d_ap)}.</p>
        <p>Validation-calibrated 1% FPR 지점의 recall은 {metric(m.numeric_trend.fpr1_recall)}입니다. 높은 민감도나 우수성은 확립되지 않았습니다.</p>
      </article>

      <article className="cohort-milestone-card">
        <h3>Image evidence Tools · retrieval 실행만</h3>
        <p>{m.image_tools.cpu_forwards}회 CPU DINO forward · {m.image_tools.hits} hits. LLM {m.image_tools.LLM_calls} · MES commit {m.image_tools.MES_commits} · GPU {m.image_tools.GPU_calls}.</p>
        <p><code>{m.image_tools.tool_sequence.join(' → ')}</code> · gallery {n(m.image_tools.gallery_rows)} rows.</p>
        <p>형태·정상 여부·원인·물리 정합은 등록되지 않았습니다. Tool 실행은 retrieval 품질 확인과 다릅니다.</p>
      </article>

      <article className="cohort-milestone-card">
        <h3>Qwen context V3 · cached role replay</h3>
        <p>완료된 return {m.qwen_resource_replay.total_returns}: baseline {m.qwen_resource_replay.baseline_returns}, bounded {m.qwen_resource_replay.bounded_returns}. 신규 Tool {m.qwen_resource_replay.new_Tool_calls} · action {m.qwen_resource_replay.new_actions} · 외부 API {m.qwen_resource_replay.external_API_calls}.</p>
        <p>이전 V2의 5회 기록은 별도 보존하며 여기 합산하지 않습니다. 일반 LLM 답변 품질이나 새 업무 흐름의 성공을 뜻하지 않습니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Full local V5 · task answer 미수용</h3>
        <p>LLM returns {m.local_agent_v5.LLM_returns} · 실제 Tools {m.local_agent_v5.Tool_calls} · 첫 업무 Tool {m.local_agent_v5.first_business_tool}. 마지막 LLM은 {m.local_agent_v5.last_LLM}이지만 task answer는 수용되지 않았습니다.</p>
        <p>새 action {m.local_agent_v5.new_actions} · compiled claims {m.local_agent_v5.compiled_claims}. Judge가 요청한 재조회가 억제되어 미래예측이 빠졌고 답변 서술은 모순되었습니다.</p>
      </article>
    </div>

    <details className="cohort-milestone-pending cohort-v64-proofs">
      <summary>ROOT 제한 수용 proof · {m.proof_count}개 고정 hash</summary>
      <ul>{m.proofs.map((proof) => <li key={proof.id}><strong>{proof.id}</strong> · {proof.status} · <code>{proof.file}</code><br /><code>{proof.sha256}</code></li>)}</ul>
    </details>
    <details className="cohort-milestone-pending"><summary>연구 전체의 제한</summary><ul className="cohort-milestone-limits">{m.limits.map((item) => <li key={item}>{item}</li>)}</ul></details>
    <p className="cohort-caption">Proof pins {m.proof_count}개 · snapshot {m.created_at_utc} · synthetic {String(m.synthetic)} · production {String(m.production)} · 신규 조치 {m.new_actions}.</p>
  </section>;
}
