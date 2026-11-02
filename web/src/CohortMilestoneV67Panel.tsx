import './CohortMilestoneV67Panel.css';

type PriorProof = { id: string; status: string; sha256: string; file: string };
type PriorMilestone = {
  schema_id: string; status: string; synthetic: boolean; production: boolean; proof_count: number;
  proofs: PriorProof[];
  fresh_trend: {
    charts: number; raw_points: number; calibration_normal_charts: number; confirmation_charts: number;
    primary_model: string; primary_ap: number; old_threshold_fpr: number; old_threshold_recall: number;
    fresh_threshold_fpr: number; fresh_threshold_recall: number; fixed05_fpr: number; fixed05_recall: number;
    upper_95_fpr: number; limits: string[];
  };
  v10_partial: { actual_LLM_returns: number; tool_calls: number; history_query_word_occurrences: number; history_query_word_limit: number; new_actions: number; whole_question_satisfied: boolean };
  capacity: { input_tokens: number; output_tokens: number; numerical_prefill_only: boolean; generation_or_quality_validated: boolean };
  current_serving_world: string; corrected_V4_integrated: boolean; platform_complete: boolean;
};
type RootReviews = {
  fullworld_evidence_v11: { status: string; llm_returns: number; tool_calls: number; evidence_facts: number; answer_executed: boolean; new_actions: number; finding: string; whole_question_satisfied: boolean; general_llm_quality_established: boolean };
  metrology_v2: { status: string; llm_returns: number; output_tokens: number; json_parse_error: string; requests: number; new_intents: number; new_audit_events: number; measurements_completed: boolean; whole_task_satisfied: boolean };
  groupedq1_v5: { status: string; numerical_gate_pass: boolean; speed_gate_pass: boolean; numerical_fail_steps: number; candidate_promoted: boolean; active_backend_unchanged: string };
};
export type ResearchMilestoneV67 = {
  schema_id: string; status: string; synthetic: boolean; production: boolean;
  prior_v66: PriorMilestone; trend_raw_points_scope: string; reviews: RootReviews; limits: string[];
};

const n = (value: number) => value.toLocaleString('ko-KR');
const pct = (value: number) => `${(value * 100).toFixed(2)}%`;

export default function CohortMilestoneV67Panel({ milestone: m }: { milestone: ResearchMilestoneV67 }) {
  const prior = m.prior_v66;
  const trend = prior.fresh_trend;
  const v10 = prior.v10_partial;
  const v11 = m.reviews.fullworld_evidence_v11;
  const metrology = m.reviews.metrology_v2;
  const grouped = m.reviews.groupedq1_v5;

  return <section className="cohort-section cohort-v67" aria-labelledby="cohort-v67-title">
    <div className="cohort-section-heading cohort-v67-heading">
      <div><span className="model-lab-kicker">LATEST · MILESTONE V6.7</span><h2 id="cohort-v67-title">ROOT 검토 합성 연구 기록</h2></div>
      <span className="cohort-chip">표시 초안 · ROOT-reviewed source records</span>
    </div>
    <p className="cohort-v67-intro">서로 다른 합성 연구 실행 기록입니다. 각 상태를 분리해 표시하며, 플랫폼 완료나 production 검증을 뜻하지 않습니다.</p>

    <div className="cohort-v67-grid">
      <article className="cohort-milestone-card cohort-v6-caution">
        <h3>Fresh Trend · normal calibration</h3>
        <p>{n(trend.calibration_normal_charts)}개 normal calibration chart와 {n(trend.confirmation_charts)}개 confirmation chart를 사용했습니다.</p>
        <p><strong>{n(trend.raw_points)}개 raw point는 calibration과 confirmation을 합한 전체 {n(trend.charts)}개 chart의 합계입니다.</strong></p>
        <p>모델 {trend.primary_model} · AP {trend.primary_ap.toFixed(4)}. Raw-point 총수는 confirmation 구간만의 수가 아닙니다.</p>
        <div className="cohort-v67-pair"><span>이전 validation FPR1 운영점</span><strong>FPR {pct(trend.old_threshold_fpr)} · recall {pct(trend.old_threshold_recall)}</strong></div>
        <div className="cohort-v67-pair"><span>새 normal calibration 운영점</span><strong>FPR {pct(trend.fresh_threshold_fpr)} · recall {pct(trend.fresh_threshold_recall)}</strong></div>
        <div className="cohort-v67-pair"><span>고정 threshold 0.5</span><strong>FPR {pct(trend.fixed05_fpr)} · recall {pct(trend.fixed05_recall)}</strong></div>
        <div className="cohort-v67-pair"><span>새 운영점의 one-sided 95% FPR upper bound</span><strong>{pct(trend.upper_95_fpr)} · 1% 초과</strong></div>
        <small>고정 threshold 0.5는 새 calibration과 같은 판단이었습니다. 과거 CSV 재현이나 생산 분포 검증은 아닙니다.</small>
      </article>

      <article className="cohort-milestone-card">
        <h3>Fullworld V10 · partial</h3>
        <p>{v10.actual_LLM_returns} LLM returns · {v10.tool_calls} Tool calls · history query {v10.history_query_word_occurrences}/{v10.history_query_word_limit} word occurrences.</p>
        <p>History 검색은 제한 초과로 실행되지 않았습니다. Forecast Tool은 실행됐지만 Judge가 승인하지 않았고 Answer에는 포함되지 않았습니다.</p>
        <strong>질문 미충족 · 신규 action {v10.new_actions}건</strong>
      </article>

      <article className="cohort-milestone-card">
        <h3>Qwen 8192-token numerical prefill</h3>
        <p>입력 {n(prior.capacity.input_tokens)} / 출력 한도 {n(prior.capacity.output_tokens)} tokens.</p>
        <p>수치형 prefill 범위만 확인했습니다. Decode, 업무 도구 흐름, 답변 품질은 검증하지 않았습니다.</p>
      </article>

      <article className="cohort-milestone-card cohort-v67-failed">
        <h3>Fullworld V11 · ROOT partial failure</h3>
        <p>{v11.llm_returns} LLM returns · {v11.tool_calls} Tool calls · {v11.evidence_facts} evidence facts.</p>
        <p>{v11.finding}</p>
        <strong>Answer 미실행 · 신규 action {v11.new_actions}건 · 질문 미충족</strong>
      </article>

      <article className="cohort-milestone-card cohort-v67-failed">
        <h3>Metrology V2 · ROOT failure</h3>
        <p>첫 LLM 반환 {metrology.llm_returns}회 · {metrology.output_tokens} output tokens · malformed JSON.</p>
        <p>후속 request {metrology.requests}건 · intent {metrology.new_intents}건 · audit event {metrology.new_audit_events}건.</p>
        <strong>계측 실행 및 측정 완료 없음</strong>
      </article>

      <article className="cohort-milestone-card cohort-v67-failed">
        <h3>GroupedQ V5 · ROOT rejected</h3>
        <p>Cached-logit numerical gate 실패: 5개 확인 중 {grouped.numerical_fail_steps}개가 고정 허용 범위를 벗어났습니다. BF16 speed gate도 실패했습니다.</p>
        <strong>후보 승격 안 됨 · 기존 backend 유지: {grouped.active_backend_unchanged}</strong>
      </article>
    </div>

    <details className="cohort-v67-history">
      <summary>V6.6의 별도 ROOT proof 3건과 기존 한계 보기</summary>
      <ul>{prior.proofs.map((proof) => <li key={proof.id}><strong>{proof.id}</strong> · {proof.status}</li>)}</ul>
    </details>

    <div className="cohort-v67-final">
      <span>현재 serving</span><strong>{prior.current_serving_world}</strong>
      <span>Corrected V4 통합</span><strong>{prior.corrected_V4_integrated ? '예' : '아니오'}</strong>
      <span>플랫폼 완료</span><strong>{prior.platform_complete ? '예' : '아니오'}</strong>
    </div>
  </section>;
}
