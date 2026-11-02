---
name: cohort-multimodal-evidence-v7
description: Route optional image, train-gallery, numeric Trend and schema Tools into receipt-bound chronic and acute synthetic cohort investigations, preserving source qualification and missing evidence.
---

별도 offline 더미 profile의 역할 계약이다. 기존 active 채팅 역할이나 V6 원본을 교체하지 않는다. 기준시점은 2026-10-26 KST다. 사내 데이터/생산 검증은 없으며 DB·모델·경로·Tool 범위는 config와 site overlay에서 읽는다.

변경 근거는 실제 V6 parent 검토와 별도 20-Tool 실행이다. 상세 출처·해시·변경 범위는 `docs/current/COHORT_MULTIMODAL_V7_CURRENT.md`에 있다. 이 Skill, 공유 참조, 역할 prompt/schema/config를 구현 전에 freeze한다. 온라인 자기 수정은 하지 않는다.

- [Router](references/router.md) → 사고 DB → 후속 Tool → [Judge](references/judge.md) → [Answer](references/answer.md) 순서다. Judge 재조회는 같은 Router다. Answer가 마지막 LLM이다.
- 고질 skip-rule cohort와 급성 설비/Wafer 노출은 별도이며 공존할 수 있다. 미계측을 정상으로 바꾸거나 독립 event 전체를 현재 영향 물량으로 확장하지 않는다.
- Router가 설정에 제공된 optional expert만 선택한다. 선택한 expert만 실제 실행한다. 미선택/불가/미관측은 서로 구분한다. Gallery는 image와 함께 선택하며 재조회에서 expert를 몰래 추가하지 않는다.
- 이미지 expert의 threshold signal은 해당 asset/view/ROI에 대한 합성 모델 출력이다. 다른 ROI의 낮은 score는 Wafer 전체 반증이 아니다. Annotation/모델 지식의 역사적 available_at이 미검증이면 그 제약을 유지한다.
- Train-only gallery는 유사 참조다. 불량 label·원인·현재 영향 scope·정상 예외로 복사하지 않는다. 검색 품질/Unknown 검증을 했다고 표시하지 않는다.
- 숫자 Trend는 실제 관측 시간/단위/legend/coverage를 가진다. 공간13 point를 시간13 step으로 바꾸지 않는다. 이번 profile에는 호환 FAB 숫자 모델이 없어 기술통계이며 모델 이상 판정을 생성하지 않는다.
- Schema/value의 복수 후보는 ambiguity다. 학습 unique profile은 현재 물량 값의 전수 목록이 아니다. RCS alias는 recess 뜻이며 물리 기준면/단위를 증명하지 않는다. SQL/Join/현재 OUT 권한은 생성하지 않는다.
- 실제 조회·hash·scope·원문 인용과 숫자는 코드 renderer가 보존한다. Judge와 Answer의 근거 선택은 raw 출력으로 별도 기록하고 실제 의미 검토를 받는다. 구조 통과를 일반 LLM 품질로 주장하지 않는다.
- 이 V7 profile은 읽기 전용이다. MES 실행·RELEASE·외부 API는 비활성이다. DOWN 정책 근거 검토는 실행 권한이 아니며 actions_executed=false를 유지한다.
