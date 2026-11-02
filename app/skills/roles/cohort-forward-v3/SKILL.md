---
name: cohort-forward-evidence-v3
description: Review a synthetic skip-rule FAB IN cohort and separate acute equipment exposure, using incident-first Tools, receipt-bound historical sources, bounded requery, and a limited forward report.
---

이 Skill은 별도 offline cohort 실험의 Router/Judge/Answer 계약이다. 기존 채팅 역할을 대신하는 active registry 항목이 아니다. 기준시점은 2026-10-26 KST이며 실제 사내 데이터나 생산 권한으로 검증하지 않았다.

실행 설정과 동결 contract에서 source hash, 현재 물량 scope, as_of, 사용 가능한 Tool을 확인한다. 단계별 역할은 [router](references/router.md), [judge](references/judge.md), [answer](references/answer.md)를 사용한다. 변경 근거와 적용 범위는 공유 설계 문서 `docs/current/COHORT_GROUNDED_AGENT_V3_CURRENT.md`에 있다. 이 Skill과 공유 문서, 실제 prompt/schema/config를 명시적으로 freeze한 뒤 실행한다. 온라인 질의로 수정하지 않는다.

- 최초 업무 Tool은 사고 DB 검색이며 코드가 강제한다. 과거 후보와 current material scope는 별개다.
- 고질 불량은 skip-rule의 서로 다른 계측 Lot/Wafer를 cohort 및 strata로 해석한다. 급성 DOWN 노출은 별도의 시간·설비·Wafer 집합이다. 두 경로와 교집합을 구분한다.
- forward에서 미래 OUT을 읽지 않는다. 미래 OUT 부재, unpaired METRO, 불확실한 물리 원인은 제한된 예측 보고에 표시할 제약이다. 관측하지 않은 정답을 얻었다고 쓰지 않는다.
- Judge의 충분성은 요청한 범위의 제한 보고에 대한 판단이다. 예측 정확성 보증이나 물리 원인 확정, 조치 권한이 아니다.
- 재조회는 같은 Router로 돌아간다. 바뀐 검색문 또는 아직 읽지 않은 실제 반환 chunk를 사용해 새 Tool 호출이 성공했을 때만 `new_data_queried`를 기록한다. 불가능한 요청/동일 반복은 capability stop이다.
- 원문 corpus, 파일 형식, location은 서로 다른 필드다. 문서 발췌와 위치를 원문에서 검증하고 과거 사례를 현재 정답으로 복사하지 않는다.
- 허용된 더미 MES 실행은 마지막 Answer 전에 코드 Adapter가 scope receipt/CAS/idempotency를 검증한다. 실제 실행과 추천·replay를 구분한다. RELEASE는 이 실험 allowlist에 없다.
