---
name: cohort-claim-slots-v8
description: Interpret qualified multimodal cohort evidence through typed claim slots, while code owns source attribution, scope, numerical facts and read-only execution truth.
---

사내 접근 없는 offline 합성 profile이다. 기준시점은2026-10-26 KST다. 기존 V6/V7 역할·실패 출력·source/model/config/DB를 보존한다. Main active 채팅 역할을 교체하지 않는다. 공유 근거는 `docs/current/COHORT_CLAIM_SLOTS_V8_CURRENT.md`다. 이 Skill·공유 참조·prompt/schema/config를 구현 전에 freeze하며 온라인 자기 수정은 하지 않는다.

- [Router](references/router.md) → 사고 DB → 실제 선택 Tool → [Judge](references/judge.md) → [Answer](references/answer.md) 순서다. 재조회는 같은 Router, Answer가 마지막 LLM이다.
- 최초 질문 원문·incident-first·as_of·scope·선택 expert만 실제 실행하는 경계는 V7과 같다. 고질 cohort와 급성 Wafer/설비 노출은 별도이고 공존할 수 있다.
- LLM은 modality별 가설 상태와 chronic 근거의 support/caution 역할을 선택한다. 출처 F ID와 수치·threshold 결과·실행 사실은 코드가 소유한다. 소스 attribution을 코드가 보장한 결과를 자유 인용 LLM 정확도라고 주장하지 않는다.
- Chronic current/reference/prediction은 별도 typed slot이다. Image는 자체 threshold 양성인 view만 pattern support가 될 수 있다. Gallery는 과거 참조/주의다. Numeric Trend는 실제 숫자 요약이며 이번 profile에 learned FAB anomaly 모델은 없다. 미래 OUT 예측이 Trend 실측 근거로 바뀔 수 없다.
- History의 S slot은 실제 읽은 source의 한정된 catalog다. 과거 정상 후보도 현재 정상 증명이 아니다. Schema ambiguity·이미지 지식 시점/ROI·sampling/미계측·불확실한 예측은 모두 유지한다.
- 새 raw slot 출력과 코드가 구성한 citation plan을 별도 보존한다. V7 실패를 보정해서 새 성공으로 표시하지 않는다. 새 실제 LLM 실행의 판단 의미를 수동 검토한다. 구조 통과는 일반/사내 품질 검증이 아니다.
- 모든 경로·모델·Tool·한도는 config/config.yaml + overlay다. 이 profile은 읽기 전용으로 MES/RELEASE/외부 API를 실행하지 않는다.
