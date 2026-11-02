import './CohortMilestoneV68DraftPanel.css';
import type { ResearchMilestoneV68 } from './v68EvidenceSnapshot';

const n = (value: number) => value.toLocaleString('ko-KR');

export default function CohortMilestoneV68DraftPanel({ milestone: m }: { milestone: ResearchMilestoneV68 }) {
  const proof = (id: string) => m.proofs.find((item) => item.id === id);
  const records = [
    {
      id: 'native_phase_a', title: 'Native Phase A · metadata / mask', record: m.native_phase_a,
      statusLabel: '제한 검토 · metadata/mask only',
      summary: `${n(m.native_phase_a.samples)} samples · ${n(m.native_phase_a.contexts)} contexts · ${n(m.native_phase_a.point_records)} point records · 독립 SQL ${m.native_phase_a.sql_references_passed}/12 PASS`,
      caveat: 'Phase A ROOT review 시점에는 메타데이터·sampling mask·고정 SQL 참조만 확인했습니다. 그 범위에서는 관측 수치/OUT 값 조회, synthetic label, 모델 학습·보정이 없었습니다.',
      details: [...m.native_phase_a.limits, '이 카드는 Phase A 검토 시점의 역사적 승인 범위만 담으며 이후 Native METRO 결과는 포함하지 않습니다.'],
    },
    {
      id: 'mht_standalone', title: 'MHT source.read · standalone MiniLM adapter', record: m.mht_standalone,
      statusLabel: '제한 검토 · standalone MiniLM',
      summary: `기본 검색 ${m.mht_standalone.default_cases_exact}개 case / ${n(m.mht_standalone.default_matches_compared)}개 match 동일 · 명시 형식 query ${m.mht_standalone.mht_queries}개 · source.read ${m.mht_standalone.source_read_calls}회 · 서로 다른 MHT 문서 ${m.mht_standalone.distinct_mht_documents}개`,
      caveat: '별도 oldbank MiniLM 흐름에서만 확인했습니다. 활성 E5 federated all-in-one에 등록되지 않았고, MHT 첫 HTML MIME body 범위입니다.',
      details: [...m.mht_standalone.limits, `활성 E5 federation 연결: ${m.mht_standalone.e5_federation_connected ? '예' : '아니오'}.`],
    },
    {
      id: 'evidence_v15_1', title: 'Fullworld Evidence V15.1 · partial trace', record: m.evidence_v15_1,
      statusLabel: '부분 실행 · 답변 미충족',
      summary: `${m.evidence_v15_1.llm_returns} LLM returns · ${m.evidence_v15_1.tool_calls} Tool calls · Answer ${m.evidence_v15_1.answer_last ? '마지막' : '순서 미확인'} · 신규 action ${m.evidence_v15_1.new_actions}`,
      caveat: 'forecast 조회는 실행됐지만 Judge가 답변에서 제외했습니다. 최종 Korean narrative에는 Hangul이 없었으며 전체 질문은 충족하지 못했습니다.',
      details: [...m.evidence_v15_1.limits, `최종 forecast 포함: ${m.evidence_v15_1.forecast_included ? '예' : '아니오'}; narrative_ko Hangul 문자: ${n(m.evidence_v15_1.hangul_characters)}개.`],
    },
    {
      id: 'metrology_policy_v5', title: 'Metrology policy V5 · denied flow', record: m.metrology_policy_v5,
      statusLabel: '거부 · Judge 사유 불일치',
      summary: `${m.metrology_policy_v5.llm_returns} LLM returns · fact 승인 표시 ${m.metrology_policy_v5.approved_fact_count}/7 · 새 request ${m.metrology_policy_v5.new_request_cells + m.metrology_policy_v5.new_request_wafers} · 새 action ${m.metrology_policy_v5.new_actions}`,
      caveat: 'Judge는 존재하지 않는 historical factory policy 필수조건을 근거로 거부했습니다. 승인된 plan은 없으며 거부를 우회하지 않았습니다.',
      details: [...m.metrology_policy_v5.limits, `ROOT 검토 finding: ${m.metrology_policy_v5.finding}`],
    },
  ];

  return <section className="cohort-v68-draft" aria-labelledby="cohort-v68-title">
    <header className="cohort-v68-heading">
      <div><span className="cohort-v68-kicker">RESEARCH SNAPSHOT · V6.8 DRAFT</span><h2 id="cohort-v68-title">ROOT 검토 합성 연구 기록</h2></div>
      <span className="cohort-v68-badge">합성 연구 · 한정 검토 기록</span>
    </header>
    <p className="cohort-v68-intro">서로 독립적인 저장 연구 기록입니다. 일부는 제한 승인, 일부는 부분 실행 또는 거부이며 production 동작이나 일반 모델 품질을 입증하지 않습니다.</p>
    <div className="cohort-v68-grid">
      {records.map((record) => <article className="cohort-v68-card" key={record.id}>
        <div className="cohort-v68-card-top"><h3>{record.title}</h3><span>{record.statusLabel}</span></div>
        <p className="cohort-v68-summary">{record.summary}</p>
        <p>{record.caveat}</p>
        <details>
          <summary>근거 파일과 범위</summary>
          <dl><dt>Review capsule</dt><dd className="cohort-v68-path">{proof(record.id)?.path}</dd><dt>SHA-256</dt><dd className="cohort-v68-hash">{proof(record.id)?.sha256}</dd></dl>
          <ul><li>ROOT status: {record.record.status}</li>{record.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>
        </details>
      </article>)}
    </div>
    <footer className="cohort-v68-footer">
      <strong>범위 경계</strong>
      <span>{m.synthetic ? '합성 연구 전용' : '합성 범위 미확인'} · production {m.production ? '검증' : '미검증'} · 일반 LLM 품질 {m.general_LLM_quality_established ? '확립' : '미확립'}</span>
      <span>V16 결과는 이 스냅샷의 검토 대상에서 제외했습니다.</span>
    </footer>
  </section>;
}
