import './CohortMilestoneV69DraftPanel.css';
import type { ResearchMilestoneV69 } from './v69EvidenceSnapshot';

const pct = (value: number) => (value * 100).toFixed(2) + '%';

export default function CohortMilestoneV69DraftPanel({ milestone: m }: { milestone: ResearchMilestoneV69 }) {
  const proof = (id: string) => m.proofs.find((item) => item.id === id);
  const patch = m.native_fixed_four.families.hf_patchtst;
  const cnn = m.native_fixed_four.families.cnn1d;
  return <section className="cohort-v69" aria-labelledby="cohort-v69-title">
    <header className="cohort-v69-heading">
      <div><span className="model-lab-kicker">RESEARCH SNAPSHOT · V6.9</span><h2 id="cohort-v69-title">Native METRO · 고정 4회 합성 연구</h2></div>
      <span className="cohort-v69-badge">합성 연구 · 한정 검토 기록</span>
    </header>
    <p className="cohort-v69-intro">고정된 PatchTST 2회와 CNN 2회 학습 뒤 별도 confirmation 결과를 요약합니다. 합성 자료의 제한된 비교이며, 모델 승격이나 production 성능을 뜻하지 않습니다.</p>
    <div className="cohort-v69-meta">
      <span>128 numeric UTC bins × 20 feature/mask channels</span>
      <span>확인 표본 {m.native_fixed_four.fresh_conf.toLocaleString('ko-KR')} · 지원 {m.native_fixed_four.supported.toLocaleString('ko-KR')}</span>
      <span>지원 양성 {m.native_fixed_four.supported_positive.toLocaleString('ko-KR')} · 지원 정상 {m.native_fixed_four.supported_normal.toLocaleString('ko-KR')}</span>
      <span>이미지 변환 없음</span>
    </div>
    <div className="cohort-v69-table-wrap">
      <table className="cohort-v69-table">
        <thead><tr><th>고정 ensemble</th><th>AP</th><th>선택 recall</th><th>무조건 recall</th><th>FP / 정상 지원</th><th>95% CP 상한</th></tr></thead>
        <tbody>
          <tr><th scope="row">PatchTST</th><td>{patch.average_precision.toFixed(3)}</td><td>{pct(patch.selective_recall)}</td><td>{pct(patch.unconditional_recall)}</td><td>{patch.false_positives} / {patch.normal_supported}</td><td>{pct(patch.one_sided95_cp_upper_selective_fpr)}</td></tr>
          <tr><th scope="row">CNN1D</th><td>{cnn.average_precision.toFixed(3)}</td><td>{pct(cnn.selective_recall)}</td><td>{pct(cnn.unconditional_recall)}</td><td>{cnn.false_positives} / {cnn.normal_supported}</td><td>{pct(cnn.one_sided95_cp_upper_selective_fpr)}</td></tr>
        </tbody>
      </table>
    </div>
    <p className="cohort-v69-footnote">선택 FPR의 one-sided 95% CP 상한 (비율): PatchTST {patch.one_sided95_cp_upper_selective_fpr.toFixed(7)} · CNN {cnn.one_sided95_cp_upper_selective_fpr.toFixed(7)}</p>
    <p className="cohort-v69-callout">CNN AP가 더 높았지만 family나 seed를 승격하지 않았습니다. CNN의 pointwise 95% 상한은 1%를 넘으며, 독립적으로 확인된 ≤1% FPR로 주장할 수 없습니다.</p>
    <div className="cohort-v69-grid">
      <article><h3>고정 Native 비교</h3><p>{m.native_fixed_four.fits}회 fit · 독립 metric audit {m.native_metric_audit.recomputed_exact ? '정확 재계산 확인' : '대기'}</p><p>표본 지지 여부에 따른 조건부 AP/recall입니다. Unknown은 무조건 recall 분모에 남겼습니다.</p><details><summary>근거와 상세 지표</summary><ul>
        <li>PatchTST AUC {patch.auc.toFixed(3)} · CNN AUC {cnn.auc.toFixed(3)}</li>
        {m.native_fixed_four.limits.map((item) => <li key={item}>{item}</li>)}
      </ul>{proof('native_fixed_four') && <p className="cohort-v69-hash">Native capsule: {proof('native_fixed_four')?.path}<br />SHA-256 {proof('native_fixed_four')?.sha256}</p>}{proof('native_metric_audit') && <p className="cohort-v69-hash">Metric audit: {proof('native_metric_audit')?.path}<br />SHA-256 {proof('native_metric_audit')?.sha256}</p>}</details></article>
      <article><h3>관측성 보조 분석</h3><p>{m.native_observability.posthoc_descriptive_only ? '사후 기술 통계 전용' : '상태 확인 대기'}</p><p>별도 관측성 분해는 사전 선언 성능 테스트가 아니며 threshold나 성능 주장을 바꾸지 않습니다.</p><details><summary>범위와 근거</summary><ul>{m.native_observability.limits.map((item) => <li key={item}>{item}</li>)}</ul>{proof('native_observability') && <p className="cohort-v69-hash">Observability: {proof('native_observability')?.path}<br />SHA-256 {proof('native_observability')?.sha256}</p>}</details></article>
      <article><h3>Evidence V16 · no Answer</h3><p>{m.evidence_v16.llm_returns}회 LLM 반환 · {m.evidence_v16.actual_elapsed_seconds.toFixed(1)}초 · Answer raw 반환 없음</p><p>600초 제한이 지난 뒤 종료됐습니다. 짧은 prompt도 품질 성공을 뜻하지 않습니다.</p><details><summary>범위와 근거</summary><ul>{m.evidence_v16.limits.map((item) => <li key={item}>{item}</li>)}</ul>{proof('evidence_v16') && <p className="cohort-v69-hash">V16 capsule: {proof('evidence_v16')?.path}<br />SHA-256 {proof('evidence_v16')?.sha256}</p>}</details></article>
      <article><h3>Weighted V3 · 후속 준비</h3><p>{m.weighted_v3.status} · 학습 완료 아님</p><p>이 스냅샷에는 Weighted V3 fit 결과가 없습니다. Foundation model, live Tool, production 실행 근거도 포함하지 않습니다.</p></article>
    </div>
    <footer className="cohort-v69-footer">합성 연구 전용 · promotion {m.promotion ? '있음' : '없음'} · production 검증 안 됨 · 일반 LLM 품질 미확립</footer>
  </section>;
}
