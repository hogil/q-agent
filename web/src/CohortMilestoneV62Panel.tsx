import { displayCount } from './CohortMilestoneV6Panel';
import { displayMetric } from './CohortMilestoneV61Panel';

type Comparison = { comparison: string; role: string; difference: number; ci95: number[]; regressing_targets: number };
export type ResearchMilestoneV62 = {
  schema_id: string; created_at_utc: string; accepted_at_utc: string; proof_count: number;
  population: { synthetic_worlds: number; calendar_weeks: number; cohort_views: number; targets: number; whole_cohort_unknown_rows: number };
  methods: { family: string; balanced_normalized_mae: number; task_normalized_mae: number[]; raw_yield_fraction_MAE: number }[];
  primary: Comparison; comparisons: Comparison[]; MLP_regressing_targets_vs_mean: number;
  sql_audit_scope: { selected_cohorts: number; unique_Wafers: number; Chips: number };
  limits: string[];
};
const names: Record<string, string> = { 'MLP-full': 'MLP · full history', 'NumericPatch-cross-item': 'Patch · mean readout', 'NumericPatch-current-token': 'Patch · current readout', 'CatBoost-summary': 'CatBoost · summary', 'train-mean': 'Train-mean baseline' };
export const displaySigned = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${displayMetric(value)}` : '미확인';
export default function CohortMilestoneV62Panel({ milestone: m }: { milestone: ResearchMilestoneV62 }) {
  const p = m.population, primary = m.primary, audit = m.sql_audit_scope;
  return <section className="cohort-section cohort-milestone cohort-milestone-v62" aria-labelledby="cohort-milestone-v62-title">
    <div className="cohort-section-heading"><div><span className="model-lab-kicker">LATEST · MILESTONE V6.2</span><h2 id="cohort-milestone-v62-title">첫 confirmation · 산술과 일부 source SQL 검토 수용</h2></div><span className="cohort-chip">합성 연구 · 새 조치 0</span></div>
    <div className="cohort-v6-summary"><strong>모델 선택은 validation MLP로 고정 · primary ablation은 악화</strong><p>ROOT 수용 {m.accepted_at_utc} · 저장 snapshot {m.created_at_utc}. 실시간 실행 상태나 production 승인 표시가 아닙니다.</p><p>신규 세계의 end-to-end Router / LLM / MES 연결, site·OOD·일반 LLM 품질은 미확립입니다. 기존 old-world V8 20 Tools + 3 LLM 사례는 아래의 별도 이력입니다.</p></div>
    <article className="cohort-milestone-card cohort-v6-caution"><h3>Prespecified primary · current-token − mean-Patch</h3><p><strong>Balanced norm MAE 차이 {displaySigned(primary.difference)} · B4 CI95 [{displaySigned(primary.ci95[0])}, {displaySigned(primary.ci95[1])}]</strong></p><p>오차는 낮을수록 좋습니다. 차이와 CI가 양수이므로 current-token readout이 더 나빴습니다. {displayCount(primary.regressing_targets)} / 135 targets에서 악화했습니다. Confirmation을 보고 모델을 다시 선택하거나 튜닝·자동 승격하지 않았습니다.</p><p>Calendar week 전체의 모든 context·anchor views를 함께 재표집한 circular block bootstrap: B4 primary, B3/6/8 sensitivity, 2,000 draws. CI는 unadjusted descriptive이며 독립 세계의 재현성·site 성능을 보장하지 않습니다.</p></article>
    <article className="cohort-milestone-card"><h3>고정 5 predictors · confirmation 성능</h3><p>{displayCount(p.synthetic_worlds)} synthetic world · {displayCount(p.calendar_weeks)} calendar weeks (78..95) · {displayCount(p.cohort_views)} cohort views · {displayCount(p.targets)} targets, 각 target 3,456 observed rows. 같은 Wafer의 여러 anchor·context views를 독립 표본으로 세지 않습니다.</p><p>예측 단위는 weekly anchor/context cohort의 Yield + 6 overlapping Rule fractions + 128 Measure 평균입니다. 개별 Chip의 미래 예측이나 현재 관측 Chip Rule 모사와 다릅니다.</p>
      <div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>고정 predictor</th><th>Balanced norm MAE</th><th>Yield norm</th><th>6 signatures norm</th><th>128 Measures norm</th><th>Yield raw MAE (fraction)</th></tr></thead><tbody>{m.methods.map((row) => <tr key={row.family}><th>{names[row.family]}{row.family === 'MLP-full' ? ' · validation 선택 유지' : ''}</th><td>{displayMetric(row.balanced_normalized_mae)}</td>{row.task_normalized_mae.map((value, i) => <td key={i}>{displayMetric(value, 6)}</td>)}<td>{displayMetric(row.raw_yield_fraction_MAE)}</td></tr>)}</tbody></table></div>
      <p>고정 train scale과 동등한 3-task 가중치를 사용합니다. MLP의 aggregate 오차는 train-mean보다 낮지만 {displayCount(m.MLP_regressing_targets_vs_mean)} / 135 targets에서 악화했습니다. 모든 135 raw/normalized errors·분모·per-week 결과와 bootstrap arrays는 원본 proof에 보존됩니다.</p>
    </article>
    <div className="cohort-milestone-grid">
      <article className="cohort-milestone-card"><h3>두 독립 검토의 범위</h3><p>저장 예측·label을 이용한 cached 산술 재검산과 별도 source SQL 검토가 각각 PASS했습니다.</p><p>Source SQL은 미리 선택한 {displayCount(audit.selected_cohorts)} cohorts / {displayCount(audit.unique_Wafers)} unique Wafers / {displayCount(audit.Chips)} Chips의 135 targets를 재계산했습니다. 전체 3,456 cohorts를 독립 SQL로 다시 확인한 것은 아닙니다.</p><p>8 checkpoints / 4 ensembles original-backend replay와 모든 5 prediction 저장·ROOT gate가 label 단계보다 먼저였습니다. CPU v1 strict replay 실패는 아래 이력에 보존되며 정확한 operator 차이는 미확인입니다.</p></article>
      <article className="cohort-milestone-card cohort-v6-caution"><h3>v3 first-point residual 결함 · 수정 v4는 별도 연구</h3><p>v3 METRO generator는 13 sites에 첫 point residual을 재사용했습니다. 이 첫 confirmation은 그 기존 v3 데이터의 한계를 포함합니다.</p><p>원본과 실패·성능 기록을 보존했습니다. 수정된 신규 v4-1 세계는 별도 데이터·새 연구이며 이 v3 결과로 수정 세계의 성능을 주장하지 않습니다. Train-median 등 추가 robust reference도 이 고정 연구에서 검토하지 않았습니다.</p></article>
    </div>
    <details className="cohort-milestone-pending"><summary>모든 고정 비교와 target 회귀 수 · secondary descriptive 포함</summary><div className="cohort-table-wrap"><table className="cohort-table"><thead><tr><th>비교</th><th>구분</th><th>Balanced Δ</th><th>B4 descriptive CI95</th><th>악화 targets / 135</th></tr></thead><tbody>{m.comparisons.map((row) => <tr key={row.comparison}><th>{row.comparison.replace('_minus_', ' − ')}</th><td>{row.role === 'primary_prespecified_ablation' ? 'Primary' : 'Secondary descriptive'}</td><td>{displaySigned(row.difference)}</td><td>[{displaySigned(row.ci95[0])}, {displaySigned(row.ci95[1])}]</td><td>{displayCount(row.regressing_targets)}</td></tr>)}</tbody></table></div></details>
    <details className="cohort-milestone-pending"><summary>ROOT acceptance의 한계 원문</summary><ul className="cohort-milestone-limits">{m.limits.map((text) => <li key={text}>{text}</li>)}</ul></details>
    <p className="cohort-caption">Proof pins {displayCount(m.proof_count)}개 · 기존 관측 Chip 14 fits와 validation 8 fits, V6.1 score-pending snapshot, V6/V5.1/13-source 이력은 아래에 그대로 보존합니다. 이 게시 작업의 새 DB/model/LLM/GPU 호출은 0입니다.</p>
  </section>;
}
