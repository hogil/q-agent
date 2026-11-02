---
name: cohort-claims-evidence-v4
description: Review chronic skip-rule cohorts and acute equipment exposure with receipt-bound facts, structured hypotheses, bounded requery, and an authoritative fact renderer.
---

별도 offline 더미 실험의 역할 계약이다. 기존 active 채팅 역할을 교체하지 않는다. 기준시점은 2026-10-26 KST이며 사내 데이터·생산 권한으로 검증하지 않았다.

변경 근거는 실제 v3/Unicode v2 실행에서 발견한 출처 누락, 근거 없는 부정 단정, 보고 가능성과 원인 확정의 혼동이다. 원본 결과를 보존하고 공유 참조 `docs/current/COHORT_CLAIMS_V4_CURRENT.md`, 이 Skill, 역할 prompt/schema/config를 구현 전에 freeze한다. 온라인 자기 수정은 하지 않는다.

- [Router](references/router.md) → 사고 DB → 후속 Tool → [Judge](references/judge.md) → [Answer](references/answer.md) 순서를 지킨다. Judge 재조회는 같은 Router로 돌아간다.
- 고질 불량은 서로 다른 Lot/Wafer의 skip-rule cohort·strata 비교로, 급성 설비 이상은 시간·설비·Wafer 노출 집합으로 해석한다. 두 경로는 동시에 존재할 수 있다.
- 최초 업무 Tool과 현재 scope/as_of·OUT 미조회·조치 권한은 코드가 강제한다. 과거 사고 후보는 현재 물량이나 실행 권한이 아니다.
- Judge는 제약을 명시한 forward 보고 가능성을 판단한다. 미래 실측, 동일 Wafer pairing, calibrated interval, 물리 원인 확정은 이 보고의 필수 완료 조건이 아니다. 제약은 숨기지 않는다.
- Answer는 마지막 LLM이며 가설 상태·근거·주의 근거·후속 조회를 구조화해 선택한다. 수치·step 이름·문서 locator·실행 건수는 검증된 Tool 결과에서 코드가 별도로 표시한다. 이 표시를 LLM이 생성한 사실성 성능으로 계산하지 않는다.
- raw LLM 출력, 구조 검사, 사실 렌더링, 실제 Adapter receipt를 구분해 보존한다. 구조가 통과해도 실제 답변 품질이나 생산 검증 완료를 주장하지 않는다.
- DOWN은 실제 매칭 subset에 대한 정책 근거이며 물리적 원인 확률이 아니다. 더미 MES Adapter는 scope receipt/CAS/idempotency를 독립 검증한다. 이 실험은 RELEASE를 실행하지 않는다.
