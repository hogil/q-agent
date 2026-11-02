import type { ReactNode } from 'react';

type Claim = { id: string; assessment: string; support_fact_ids: string[]; caution_fact_ids: string[] };
export type ResearchMilestoneV6 = {
  schema_id: 'qagent.skip_research_milestone.v6'; created_at_utc: string; proof_count: number;
  actual_v8: {
    status: string; case_dataset: string; model_calls: number; tool_calls: number; source_as_of: string;
    citation_owner: string; number_owner: string; raw_slots_owner: string; receipt_count: number; new_actions: number;
    raw_answer_slots: { id: string; assessment: string }[]; compiled_claims: Claim[];
    scope_counts: { current_wafers: number; past_reference_wafers: number; independent_event_wafers: number; current_down_exposed_wafers: number; current_event_intersection: number; current_outcome_queries: number };
    future_yield_point: number; limits: string[];
    image_views: { id: string; view: string; target_scope: string; targets: string[]; scores: number[]; thresholds: number[]; above: boolean[] }[];
  };
  quality_history: { v7_status: string; v7_tool_calls: number; v7_model_calls: number; v7_issues: string[]; legacy_v6_MES_receipt_replays: number; legacy_v6_new_actions: number };
  full_world: {
    dataset: string; weeks: number; counts: { lots: number; wafers: number; chips: number; feature_rows: number; eligible_rows: number };
    eligible_splits: { train: number; validation: number; confirmation: number; purge: number };
    supervised_rows: { train: number; validation: number }; whole_cohort_unknown_rows: number; target_count: number;
    fit_status: { status: string; status_as_of_utc: string; planned_nonfixture_fits: number; completed_fits: number | null; performance_metrics_published: false };
    limits: string[];
  };
  CF4: { worlds: number; rows: number; target_count: number; normalized_macro_delta: number; normalized_ci95: number[]; regressing_families: string[]; limits: string[] };
  analysis_tracks: { id: string; status: string; text: string }[]; pending: string[];
};
export const displayCount = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ko-KR') : '미확인';
export const displayCitations = (ids: string[] | null | undefined) => ids == null ? '미확인' : ids.length ? ids.join(', ') : '없음';
const fixed = (v: number) => Number.isFinite(v) ? v.toFixed(6) : '미확인';
const signed = (v: number) => Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(6)}` : '미확인';
const titles: Record<string, string> = { chronic: 'Chronic cohort', acute: 'Acute DOWN 노출', history: '과거 기록', image: 'Image pattern', trend: 'Numeric Trend' };
function Card({ title, children, caution = false }: { title: string; children: ReactNode; caution?: boolean }) {
  return <article className={`cohort-milestone-card${caution ? ' cohort-v6-caution' : ''}`}><h3>{title}</h3>{children}</article>;
}
function Limits({ values }: { values: string[] }) {
  return <ul className="cohort-milestone-limits">{values.map((text) => <li key={text}>{text}</li>)}</ul>;
}
export default function CohortMilestoneV6Panel({ milestone: m, historical = false }: { milestone: ResearchMilestoneV6; historical?: boolean }) {
  const v = m.actual_v8, c = v.scope_counts, w = m.full_world, cf = m.CF4, history = m.quality_history;
  return <section className="cohort-section cohort-milestone cohort-milestone-v6" aria-labelledby="cohort-milestone-v6-title">
    <div className="cohort-section-heading"><div><span className="model-lab-kicker">{historical ? '보존 이력 · MILESTONE V6' : 'LATEST · MILESTONE V6'}</span><h2 id="cohort-milestone-v6-title">V8 연결 결과 · 제한된 합성 사례</h2></div><span className="cohort-chip">읽기 전용 · 새 조치 0</span></div>
    {historical ? <p className="cohort-caption">이하는 이전 저장 상태입니다. 00:20 RUNNING 표시는 과거 snapshot이며 최신 standalone 완료 상태는 위 V6.1에 있습니다.</p> : null}
    <div className="cohort-v6-summary"><strong>{displayCount(v.tool_calls)} Tools + {displayCount(v.model_calls)} local LLM calls</strong><p>기존 {v.case_dataset} 사례 · 새 96주 데이터·135-target 학습과 별도입니다.</p><p>일반 LLM 품질 미확립 · production / site 검증 아님</p></div>
    <div className="cohort-v6-ownership"><p><strong>LLM 소유</strong> · 실제 Router / Judge / Answer의 typed assessment slots</p><p><strong>code 소유</strong> · validated catalog의 citation과 deterministic source 숫자. 자유 citation 추론 품질로 해석하지 않습니다.</p></div>
    <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>주 흐름</th><th>저장된 실제 실행</th><th>소유 / 경계</th></tr></thead><tbody>
      <tr><th>Router</th><td>실제 local LLM · image / gallery / numeric / schema 선택</td><td>LLM slots · 원래 사용자 질문은 code가 실행</td></tr>
      <tr><th>사고 DB</th><td>최초 업무 Tool · search_incident_db</td><td>incident-first · 현재 scope 검증</td></tr>
      <tr><th>후속 Tool</th><td>core + 선택 전문가 · 전체 {displayCount(v.tool_calls)} Tools</td><td>실제 source · ROI / 시점 / 분모 유지</td></tr>
      <tr><th>Judge</th><td>실제 local LLM · ready_with_limits</td><td>schema ambiguity / image-time / descriptive-only 한계 유지</td></tr>
      <tr><th>Answer</th><td>실제 local LLM slots → code citations / 숫자</td><td>제한된 단일 사례 검토 · 일반 품질 미확립</td></tr>
    </tbody></table></div>
    <p className="cohort-final-scope"><strong>최종 조회 상태</strong> · 현재 {displayCount(c.current_wafers)} / reference {displayCount(c.past_reference_wafers)} / 독립 event {displayCount(c.independent_event_wafers)} Wafer · 현재 DOWN {displayCount(c.current_down_exposed_wafers)}/{displayCount(c.current_wafers)} · event 교집합 {displayCount(c.current_event_intersection)} Wafer · 현재 OUT 조회 {displayCount(c.current_outcome_queries)}</p>
    <p className="cohort-caption">V8 기준시점 {v.source_as_of} · receipt {displayCount(v.receipt_count)}건 · 새 action {displayCount(v.new_actions)}건. 이전 V6 MES replay와 별개이며 RELEASE/dispatch/MES 실행은 없습니다.</p>
    <div className="cohort-milestone-grid">
      <Card title="실제 LLM assessment slots"><dl className="cohort-v6-slots">{v.raw_answer_slots.map((row) => <div key={row.id}><dt>{titles[row.id]}</dt><dd><code>{row.assessment}</code></dd></div>)}</dl><p>물리 원인 unconfirmed · 정상 반례 not_established</p></Card>
      <Card title="Code가 부여한 근거 citation"><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>Claim</th><th>Support</th><th>Caution</th></tr></thead><tbody>{v.compiled_claims.map((row) => <tr key={row.id}><th>{row.id}</th><td>{displayCitations(row.support_fact_ids)}</td><td>{displayCitations(row.caution_fact_ids)}</td></tr>)}</tbody></table></div><p>F18 scene-positive만 image support입니다. F17 crop과 F19/F20 gallery는 caution입니다. F21/F22는 관측 numeric 요약이며 F6 미래 예측과 다릅니다.</p></Card>
      <Card title="Image view / ROI와 numeric 한계"><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>View / fact</th><th>Target scope</th><th>Score / threshold</th></tr></thead><tbody>{v.image_views.flatMap((view) => view.targets.map((target, i) => <tr key={`${view.id}-${target}`}><th>{view.view} · {view.id}</th><td>{target}<br />{view.target_scope}</td><td>{fixed(view.scores[i])} / {fixed(view.thresholds[i])}<br />{view.above[i] ? '해당 target threshold 이상' : '해당 target threshold 미만'}</td></tr>))}</tbody></table></div><p>Scene과 selected crop ROI target은 다릅니다. 낮은 crop score는 전체 Wafer 정상 보증이 아닙니다. Image knowledge-time은 미확인, gallery는 과거 유사성입니다.</p><p>현재 V8 numeric FAB METRO는 descriptive-only · 호환 numeric anomaly model inference 없음 · RCS schema ambiguity 유지.</p><p>F6 기존-world 미래 Yield point {fixed(v.future_yield_point)}는 관측 OUT이 아니며 새135-target 모델 결과도 아닙니다.</p></Card>
      <Card title="V7 실패도 품질 근거로 보존" caution><p><strong>최종 Answer 거부 · {displayCount(history.v7_tool_calls)} Tools + {displayCount(history.v7_model_calls)} LLM calls</strong></p><p>Raw 자동 수선 없음 · 실패를 성공으로 재분류하지 않습니다.</p><Limits values={history.v7_issues} /></Card>
    </div>
    <div className="cohort-v6-tracks">{m.analysis_tracks.map((track) => <Card key={track.id} title={track.id === 'future_cohort_forecast' ? '1 · 미래 cohort forecast' : track.id === 'observed_chip_diagnosis' ? '2 · 관측 Chip 진단' : '3 · Acute 설비 노출'}><p>{track.text}</p></Card>)}</div>
    <div className="cohort-milestone-grid">
      <Card title="새 full-world · 96주 생성 완료"><p><strong>{displayCount(w.counts.chips)} Chip · {displayCount(w.counts.lots)} Lots · {displayCount(w.counts.wafers)} Wafers</strong></p><p>Feature {displayCount(w.counts.feature_rows)}행 · eligible {displayCount(w.counts.eligible_rows)}행 · 실제 8개 prior observed-week gate 유지</p><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>Split</th><th>Input rows</th><th>135-target valid rows</th><th>Whole-cohort unknown</th></tr></thead><tbody>
        <tr><th>Train</th><td>{displayCount(w.eligible_splits.train)}</td><td>{displayCount(w.supervised_rows.train)}</td><td>{displayCount(w.eligible_splits.train - w.supervised_rows.train)}</td></tr>
        <tr><th>Validation</th><td>{displayCount(w.eligible_splits.validation)}</td><td>{displayCount(w.supervised_rows.validation)}</td><td>{displayCount(w.eligible_splits.validation - w.supervised_rows.validation)}</td></tr>
        <tr><th>Confirmation</th><td>{displayCount(w.eligible_splits.confirmation)}</td><td>봉인 · 미조회</td><td>미조회</td></tr><tr><th>Purge</th><td>{displayCount(w.eligible_splits.purge)}</td><td colSpan={2}>학습 / 선택 제외</td></tr>
      </tbody></table></div><p>{displayCount(w.target_count)} targets = Yield 1 + 중복 signature 6 + electrical Measure 평균 128. 첫7은 cohort fraction, 나머지128은 SYN_SEVERITY입니다.</p><p>전체 {displayCount(w.whole_cohort_unknown_rows)}개 cohort는 전체135 targets unknown. 원래 cutoff·membership을 유지하며 partially mature 평균으로 대체하지 않았습니다.</p><Limits values={w.limits} /></Card>
      <Card title="새135-target 모델 · RUNNING snapshot"><p><strong>계획 {displayCount(w.fit_status.planned_nonfixture_fits)} fits · 완료 / 성능 미게시</strong></p><p>MLP 2 seeds · numeric Patch Transformer 2 seeds · CatBoost summary 2 seeds</p><p>저장된 시작 상태: {w.fit_status.status_as_of_utc}. 실시간 완료 판정이 아닙니다.</p><p>Feature·target 준비 완료와 모델 품질 검증은 별도입니다. Confirmation target은 봉인 상태이며 자동 승격하지 않습니다.</p></Card>
      <Card title="CF4 · 추가 성능 향상 미확립"><p>{displayCount(cf.worlds)} synthetic worlds · {displayCount(cf.rows)} rows · 기존 skip-world 계열 {displayCount(cf.target_count)} rate targets</p><p><strong>v5 − v4 normalized macro Δ {signed(cf.normalized_macro_delta)}</strong></p><p>CI95 [{signed(cf.normalized_ci95[0])}, {signed(cf.normalized_ci95[1])}] · 0 포함</p><p>회귀 family: {cf.regressing_families.join(', ')} · Yield는 정확히 동일합니다.</p><Limits values={cf.limits} /></Card>
      <Card title="이전 V6 MES replay는 별도 이력"><p>이전 receipt replay {displayCount(history.legacy_v6_MES_receipt_replays)}건 · 이전 새 action {displayCount(history.legacy_v6_new_actions)}건</p><p>V8 현재 read-only receipt는 0건입니다. 기존 8 Wafer / 6 route keys / 8 metrology requests를 새 실행으로 표시하지 않습니다.</p><p>불변 V5.1 milestone과 기존 13-source 이력은 아래에 유지합니다.</p></Card>
    </div>
    <details className="cohort-milestone-pending"><summary>현재 결과의 제한과 다음 검증</summary><Limits values={v.limits} /><Limits values={m.pending} /></details>
    <p className="cohort-caption">Milestone snapshot {m.created_at_utc} · 고정 proof pins {displayCount(m.proof_count)}개 · 전체 FAB 자료는 synthetic이며 production validation은 없습니다.</p>
  </section>;
}
