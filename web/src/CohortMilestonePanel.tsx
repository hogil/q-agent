import type { ReactNode } from 'react';

export type ResearchMilestone = {
  created_at_utc: string; proof_count: number;
  actual_llm: {
    status: string; model_calls: number; tool_calls: number; limits: string[];
    facts: { current_wafers: number; past_reference_wafers: number; independent_event_wafers: number; current_down_exposed_wafers: number; current_event_intersection: number; current_outcome_queries: number; current_unobserved_steps: string[] };
    dummy_mes: { receipt_replays: number; new_actions: number; ledger_counts: { holds: number; dispatch_blocks: number; metrology_requests: number } };
  };
  multimodal_tools: { tool_calls: number; llm_calls: number; schema_status: string; limits: string[]; image_expert_results: { view: string; expert: string; scores: { target: string; scope: string; score: number; validation_threshold: number }[] }[] };
  image_benchmark: { context_local_ap: number; context_repeated_ap: number; chip_crop_local_ap: number; chip_crop_repeated_ap: number; hard_chip_crop_local_ap: number; hard_chip_crop_local_positive_count: number; limits: string[] };
  public_numeric_patch: { dataset: string; test_records: number; macro_normalized_mae: { selected_checkpoint: number; train_input_mean: number; locf: number }; limits: string[] };
  forecast_pool: { status: string; macro_normalized_validation_mae: { primary_v1_all_heads: number; v4_fixed_hybrid_v1_yield_v3_signatures: number; v5_locked_yield_and_selected_signatures: number }; fresh_cf4_worlds_generated: number; serving_changed: boolean; limits: string[] };
  integrated_pilot: { counts: { wafer: number; wafer_chip: number }; nominal_complete_rule_overlap_0_to_6: Record<string, number>; full_96week_world_created: boolean; images_generated: boolean; models_trained: boolean; limits: string[] };
  pending: string[];
};
const n = (value: number | undefined) => value == null ? '미확인' : value.toLocaleString('ko-KR');
const metric = (value: number | undefined) => value == null ? '미확인' : value.toFixed(4);
function Card({ title, children }: { title: string; children: ReactNode }) {
  return <article className="cohort-milestone-card"><h3>{title}</h3>{children}</article>;
}
const Limits = ({ values }: { values: string[] }) => <ul className="cohort-milestone-limits">{values.map((text) => <li key={text}>{text}</li>)}</ul>;

export default function CohortMilestonePanel({ milestone: m, historical = false }: { milestone: ResearchMilestone; historical?: boolean }) {
  const llm = m.actual_llm, f = llm.facts, mes = llm.dummy_mes, multi = m.multimodal_tools;
  const image = m.image_benchmark, patch = m.public_numeric_patch, pool = m.forecast_pool, pilot = m.integrated_pilot;
  return <section className="cohort-section cohort-milestone" aria-labelledby="cohort-milestone-title">
    <div className="cohort-section-heading"><div><span className="model-lab-kicker">{historical ? '보존 이력 · MILESTONE V5.1' : 'LATEST · MILESTONE V5'}</span><h2 id="cohort-milestone-title">{historical ? '이전 연구 결과 · 당시 저장 상태' : '최신 연구 결과 · 제한된 합성 시연'}</h2></div><span className="cohort-chip">저장된 결과 · 새 실행 없음</span></div>
    <p className="cohort-caption">Chronic skip-rule cohort와 acute 설비/chamber/time 노출은 함께 존재할 수 있습니다. 독립 event와 현재 물량의 실제 교집합을 구분합니다. 일반 LLM 품질과 실제 site 성능은 미검증입니다.</p>
    <div className="cohort-milestone-grid">
      <Card title="V6 실제 Router → Judge → Answer"><p><strong>{n(llm.tool_calls)} Tools + {n(llm.model_calls)} LLM calls</strong></p><p>{llm.status} · 단일 사례 수동 검토 시연</p><p>현재 {n(f.current_wafers)} · reference {n(f.past_reference_wafers)} · 독립 event {n(f.independent_event_wafers)} Wafer</p><p>현재 DOWN {n(f.current_down_exposed_wafers)} · event 교집합 {n(f.current_event_intersection)} Wafer · 현재 OUT 조회 {n(f.current_outcome_queries)}</p></Card>
      <Card title="별도 multimodal Tool bundle"><p><strong>{n(multi.tool_calls)} Tools + {n(multi.llm_calls)} LLM calls</strong></p><p>이미지 2 views · 같은 view gallery top5 · numeric Trend · schema lookup</p><p>실제 LLM role 미연결 · schema {multi.schema_status}</p><p>V6의 3회 LLM graph와 별도 실행입니다.</p></Card>
    </div>
    <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>주 흐름</th><th>저장된 상태</th></tr></thead><tbody>
      <tr><th>Router</th><td>V6 실제 호출</td></tr><tr><th>사고 DB</th><td>최초 업무 Tool 조회</td></tr><tr><th>후속 Tool</th><td>V6 base {n(llm.tool_calls)}회 전체 업무 Tool에 포함</td></tr><tr><th>Judge</th><td>제한을 유지한 단일 사례 검토</td></tr><tr><th>Answer</th><td>{llm.status}</td></tr>
    </tbody></table></div>
    <p className="cohort-final-scope"><strong>최종 조회 상태</strong> · 현재 {n(f.current_wafers)} / reference {n(f.past_reference_wafers)} / 독립 event {n(f.independent_event_wafers)} Wafer · OUT 조회 {n(f.current_outcome_queries)} · 미계측 {f.current_unobserved_steps.join(', ')} · 미계측은 정상 0이 아닙니다.</p>
    <Card title="실제 synthetic MES receipt · replay"><p>기존 receipt 재표시 {n(mes.receipt_replays)}건 · 새 조치 {n(mes.new_actions)}건</p><p>기존 ledger: HOLD {n(mes.ledger_counts.holds)} Wafer · BLOCK_DISPATCH {n(mes.ledger_counts.dispatch_blocks)} exact route keys · 계측 요청 {n(mes.ledger_counts.metrology_requests)}건</p><p>모두 기존 상태입니다. 계측 REQUESTED는 PASS가 아니며 production 실행은 없습니다.</p></Card>
    <div className="cohort-milestone-grid">
      <Card title="Synthetic image · scene / ROI 별도 target"><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>View / expert</th><th>Target scope</th><th>Score / threshold</th></tr></thead><tbody>{multi.image_expert_results.flatMap((view) => view.scores.map((score) => <tr key={`${view.view}-${score.target}`}><th>{view.view}<br />{view.expert}</th><td>{score.target}<br />{score.scope}</td><td>{metric(score.score)} / {metric(score.validation_threshold)}</td></tr>))}</tbody></table></div><p>합성 test AP: scene local {metric(image.context_local_ap)} / repeated {metric(image.context_repeated_ap)} · crop local {metric(image.chip_crop_local_ap)} / repeated {metric(image.chip_crop_repeated_ap)}</p><p>약한 hard crop-local AP {metric(image.hard_chip_crop_local_ap)} · 양성 {n(image.hard_chip_crop_local_positive_count)}개</p><Limits values={image.limits} /><Limits values={multi.limits} /></Card>
      <Card title="Public medical numeric Patch · FAB 성능 아님"><p>{patch.dataset} · test {n(patch.test_records)} records</p><p>Normalized MAE: selected {metric(patch.macro_normalized_mae.selected_checkpoint)} · LOCF {metric(patch.macro_normalized_mae.locf)} · train mean {metric(patch.macro_normalized_mae.train_input_mean)}</p><p>Numeric values + mask 입력입니다. FAB numeric Trend는 조회만 실행했고 호환 모델 inference는 실행하지 않았습니다.</p><Limits values={patch.limits} /></Card>
      <Card title="Forecast pool · validation으로 선택"><p>{pool.status}</p><p>Validation normalized MAE: v1 {metric(pool.macro_normalized_validation_mae.primary_v1_all_heads)} · v4 {metric(pool.macro_normalized_validation_mae.v4_fixed_hybrid_v1_yield_v3_signatures)} · pool {metric(pool.macro_normalized_validation_mae.v5_locked_yield_and_selected_signatures)}</p><p>Fresh confirmation world {n(pool.fresh_cf4_worlds_generated)}개 · serving 변경 {pool.serving_changed ? '예' : '아니오'}</p><Limits values={pool.limits} /></Card>
      <Card title="Integrated stress / nominal pilot · training only"><p>{n(pilot.counts.wafer)} Wafer · {n(pilot.counts.wafer_chip)} Chip</p><p>Nominal 규칙 중복 0~6: {Object.entries(pilot.nominal_complete_rule_overlap_0_to_6).map(([overlap, count]) => `${overlap}개=${n(count)}`).join(' · ')}</p><p>96주 전체 생성 {pilot.full_96week_world_created ? '예' : '아니오'} · image 생성 {pilot.images_generated ? '예' : '아니오'} · 모델 학습 {pilot.models_trained ? '예' : '아니오'}</p><Limits values={pilot.limits} /></Card>
    </div>
    <details className="cohort-milestone-pending"><summary>남은 검증과 연결 작업</summary><Limits values={llm.limits} /><Limits values={m.pending} /></details>
    <p className="cohort-caption">스냅샷 {m.created_at_utc} · 고정 proof pin {n(m.proof_count)}개 · source hash는 아래 provenance에서 확인합니다.</p>
  </section>;
}
