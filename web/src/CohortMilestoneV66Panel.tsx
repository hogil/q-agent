import './CohortMilestoneV66Panel.css';

type Proof = { id: string; status: string; sha256: string; file: string };
type PendingStudy = { id: string; status: string; summary: string; result: null };
export type ResearchMilestoneV66 = {
  schema_id: string;
  status: string;
  created_at_utc: string;
  synthetic: boolean;
  production: boolean;
  proof_count: number;
  proofs: Proof[];
  fresh_trend: {
    charts: number; raw_points: number; calibration_normal_charts: number; confirmation_charts: number;
    primary_model: string; primary_ap: number; old_threshold_fpr: number; old_threshold_recall: number;
    fresh_threshold_fpr: number; fresh_threshold_recall: number; fixed05_fpr: number; fixed05_recall: number;
    upper_95_fpr: number; fixed05_same_as_fresh_decisions: boolean; old_csv_reproduction: boolean;
    automatic_promotion: boolean; limits: string[];
  };
  v10_partial: {
    elapsed_seconds: number; actual_LLM_returns: number; tool_calls: number; history_retrieved: boolean;
    history_query_word_occurrences: number; history_query_word_limit: number; E5_loaded: boolean;
    forecast_executed: boolean; forecast_Judge_approved: boolean; new_actions: number;
    root_manual_findings: string[]; whole_question_satisfied: boolean; general_LLM_quality_established: boolean;
  };
  capacity: { input_tokens: number; output_tokens: number; numerical_prefill_only: boolean; generation_or_quality_validated: boolean; limits: string[] };
  pending_studies: PendingStudy[];
  current_serving_world: string;
  corrected_V4_integrated: boolean;
  platform_complete: boolean;
  limits: string[];
};

const n = (value: number) => value.toLocaleString('ko-KR');
const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
const metric = (value: number) => value.toFixed(4);

const pendingLabel = (study: PendingStudy) => {
  if (study.id === 'fullworld_evidence_v11') return '실패 · ROOT capsule 대기';
  if (study.id === 'metrology_v2') return '실패 · ROOT capsule 대기';
  return 'ROOT capsule 대기';
};
const pendingDescription = (study: PendingStudy) => {
  if (study.id === 'fullworld_evidence_v11') return 'Router requery 불일치로 실패했다는 ROOT 상태 보고가 있습니다. 제한 수용 capsule와 검토된 지표는 대기 중입니다.';
  if (study.id === 'metrology_v2') return '첫 LLM raw가 malformed였고 후속 request는 0건이라는 ROOT 상태 보고가 있습니다. 제한 수용 capsule와 검토된 지표는 대기 중입니다.';
  return 'ROOT가 제한 수용 capsule를 제공하기 전까지 결과와 점수는 표시하지 않습니다.';
};

export default function CohortMilestoneV66Panel({ milestone: m }: { milestone: ResearchMilestoneV66 }) {
  return <section className="cohort-section cohort-milestone cohort-milestone-v66" aria-labelledby="cohort-milestone-v66-title">
    <div className="cohort-section-heading cohort-v66-heading">
      <div><span className="model-lab-kicker">LATEST · MILESTONE V6.6</span><h2 id="cohort-milestone-v66-title">최신 합성 연구 근거</h2></div>
      <span className="cohort-chip">ROOT 검토 대기 · 별도 proof {m.proof_count}개</span>
    </div>

    <div className="cohort-v66-intro">
      <strong>서로 다른 합성 연구 실행 기록입니다.</strong>
      <p>각 연구는 별도로 표시했습니다. 이 요약은 V6.6 capsule 검토 전 준비 상태이며, 전체 플랫폼이나 production 검증 완료를 뜻하지 않습니다.</p>
    </div>

    <div className="cohort-v66-grid">
      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Fresh Trend normal calibration</h3>
        <p>{n(m.fresh_trend.calibration_normal_charts)}개 normal chart로 보정하고, 별도 confirmation {n(m.fresh_trend.confirmation_charts)}개 chart / {n(m.fresh_trend.raw_points)}개 raw point에서 확인했습니다. 이 데이터는 과거 CSV 재현이 아닙니다.</p>
        <div className="cohort-v66-metrics">
          <div><span>기존 validation FPR1 threshold</span><strong>FPR {pct(m.fresh_trend.old_threshold_fpr)} · recall {pct(m.fresh_trend.old_threshold_recall)}</strong></div>
          <div><span>새 normal calibration threshold</span><strong>FPR {pct(m.fresh_trend.fresh_threshold_fpr)} · recall {pct(m.fresh_trend.fresh_threshold_recall)}</strong></div>
          <div><span>고정 threshold 0.5</span><strong>FPR {pct(m.fresh_trend.fixed05_fpr)} · recall {pct(m.fresh_trend.fixed05_recall)}</strong></div>
          <div><span>normal FPR one-sided 95% upper</span><strong>{pct(m.fresh_trend.upper_95_fpr)}</strong></div>
        </div>
        <p>주요 모델 {m.fresh_trend.primary_model} · AP {metric(m.fresh_trend.primary_ap)}. 보정은 threshold만 바꾸며 AP는 바꾸지 않았습니다. 고정 0.5는 새 threshold와 같은 판단이었고, upper bound는 1%를 넘습니다.</p>
        <p className="cohort-v66-caution-note">합성 generator 조건의 calibration 결과이며, 실제 설비나 분포 변화에 대한 보장은 아닙니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Fullworld V10 · partial</h3>
        <p>LLM returns {m.v10_partial.actual_LLM_returns} · Tool calls {m.v10_partial.tool_calls} · {m.v10_partial.elapsed_seconds.toFixed(0)}초.</p>
        <ul className="cohort-v66-findings">
          <li>History query {m.v10_partial.history_query_word_occurrences}개 word occurrence가 {m.v10_partial.history_query_word_limit}개 제한을 넘어 metadata 검색과 E5 전에 실패했습니다.</li>
          <li>Future forecast Tool은 실행됐지만 Judge가 승인하지 않았고 Answer가 포함하지 않았습니다.</li>
          <li>Answer의 ETC_MAIN 표기와 cosine 문구 등은 ROOT가 검토 오류로 기록했습니다.</li>
        </ul>
        <p>질문 전체 충족 및 일반 LLM 품질은 수용되지 않았습니다. 새 action 0건입니다.</p>
      </article>

      <article className="cohort-milestone-card">
        <h3>8192-token numerical prefill</h3>
        <p>입력 {n(m.capacity.input_tokens)} tokens / 출력 한도 {n(m.capacity.output_tokens)} tokens.</p>
        <p>고정 수치형 prefill 용량과 저장 logits parity 범위만 확인했습니다. Text generation, decode, 업무 Tool 또는 답변 품질은 검증하지 않았습니다.</p>
        <p className="cohort-v66-caution-note">이 결과는 Qwen 업무 답변의 성공이나 low-level CUDA kernel dispatch 확인을 의미하지 않습니다.</p>
      </article>
    </div>

    <section className="cohort-section cohort-v66-pending" aria-labelledby="cohort-v66-pending-title">
      <div className="cohort-section-heading"><div><span className="model-lab-kicker">NOT ACCEPTED YET</span><h3 id="cohort-v66-pending-title">추가 연구 상태</h3></div><p>결과는 ROOT capsule가 확인될 때까지 공개 수치로 표시하지 않습니다.</p></div>
      <div className="cohort-v66-pending-grid">{m.pending_studies.map((study) => <article key={study.id}>
        <strong>{study.id === 'fullworld_evidence_v11' ? 'Fullworld V11' : study.id === 'metrology_v2' ? 'Metrology V2' : 'Code performance V5'}</strong>
        <span>{pendingLabel(study)}</span><p>{pendingDescription(study)}</p>
      </article>)}</div>
    </section>

    <div className="cohort-section-heading cohort-v66-flow-heading">
      <div><span className="model-lab-kicker">V10 WORKFLOW · PARTIAL</span><h3>Router → 사고 DB → Tools → Judge → Answer</h3></div>
      <p>이 흐름은 V10 단일 실행만 요약합니다.</p>
    </div>
    <div className="cohort-table-wrap">
      <table className="cohort-table cohort-v66-workflow">
        <thead><tr><th>순서</th><th>단계</th><th>V10 기록</th></tr></thead>
        <tbody>
          <tr><td>1</td><th scope="row">Router</th><td>Router/Judge/Answer 전체 역할 흐름에서 {m.v10_partial.actual_LLM_returns}회 LLM 반환</td></tr>
          <tr><td>2</td><th scope="row">사고 DB</th><td>첫 업무 Tool incidents.search</td></tr>
          <tr><td>3</td><th scope="row">Tools</th><td>{m.v10_partial.tool_calls}회 호출 · History 검색 실패 · forecast 실행</td></tr>
          <tr><td>4</td><th scope="row">Judge</th><td>forecast fact 미승인</td></tr>
          <tr><td>5</td><th scope="row">Answer</th><td>forecast 누락 · ROOT 수동 검토에서 문구 오류 기록</td></tr>
        </tbody>
      </table>
    </div>

    <section className="cohort-v66-final" aria-label="현재 범위와 상태">
      <div><span>현재 serving</span><strong>{m.current_serving_world}</strong></div>
      <div><span>Corrected V4 통합</span><strong>{m.corrected_V4_integrated ? '통합' : '미통합'}</strong></div>
      <div><span>플랫폼 상태</span><strong>{m.platform_complete ? '완료' : '미완료'}</strong></div>
      <p>합성 연구 · production 검증 아님 · capsule status: {m.status}</p>
    </section>

    <details className="cohort-milestone-pending cohort-v66-details">
      <summary>ROOT proof · {m.proof_count}개 hash</summary>
      <ul>{m.proofs.map((proof) => <li key={proof.id}><strong>{proof.id}</strong> · {proof.status} · <code>{proof.file}</code><br /><code>{proof.sha256}</code></li>)}</ul>
    </details>
    <details className="cohort-milestone-pending cohort-v66-details">
      <summary>제한사항</summary>
      <ul>{m.limits.map((item) => <li key={item}>{item}</li>)}</ul>
    </details>
    <p className="cohort-caption">Snapshot {m.created_at_utc} · synthetic {String(m.synthetic)} · production {String(m.production)} · publication ROOT 검토 대기.</p>
  </section>;
}
