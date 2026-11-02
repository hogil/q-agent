---
name: platform-analysis
description: 사고 범위에서 MES·이미지·Trend·전기검사·Inform을 함께 검토하는 Tool 흐름.
---

출처: 로컬 Adapter·합성 생성/조회 코드, 2026-10-24. 사내 미검증 설계/합성 초안이다.
Tabular/local/형상/반복성의 판단 경계는 references/analysis-grains.md를 따른다.
find_incidents → list_incident_lots 후 get_platform_evidence로 필요한 sources를 선택한다.
actor/scope/사고 ID/as_of/SQL은 코드가 관리한다. sources는 mes/test/measure/failbit/sem/trend/inform이다.
동일 사고/Lot/Wafer/Chip 키와 unit, 검사 stage를 보존한다. EDS는 Electrical Die Sorting이며 EDX가 아니다.
Chip 전기 Measure·Failbit bit·SEM pixel 좌표는 물리 정합 없이 겹치지 않는다. MES 상태는 조치 완료가 아니다.
관측 시각과 available_at을 업무 timezone의 as_of로 제한하되 과거 DB snapshot으로 주장하지 않는다.
count/summary는 전체 조회 범위, rows는 제한된 샘플이다. 재조회한 동일 record_id를 독립 근거로 세지 않는다.
LLM에는 전체 범위 집계와 source coverage, 근거 ID, 제한된 예시만 전달한다. prompt_sampled는 원본 삭제가
아니며 샘플 행만으로 분포·공간 반복성을 추정하지 않는다. 원본 Tool 결과는 UI/추적에 보존한다.
Measure의 물리 컬럼 수와 item별 전기 feature 수를 구분한다. 식별자/좌표/규격/시각은 feature 수가 아니다.
EDS tabular 이상, wafer local 영역, chip 내부 형상, chip 간 반복성은 별도 근거다. 해당 분석 결과가 없으면
미분석으로 표시한다. SEM/Trend 분류나 유사 사고 검색만으로 FBM 반복성을 판정하지 않는다.
tabular_analysis는 feature catalogue 순서의 chip wide vector 분석이다. 기존 long Measure 2항목과 확장
더미 feature 수를 혼동하지 않는다. train-normal 전처리/threshold와 시간·사고 group holdout을 확인한다.
특정 전기 컬럼을 요구하면 get_platform_evidence.measure_features에 확인된 catalogue name을 최대 8개
지정한다. unknown feature는 임의 대체하지 않는다. selected_values는 제한된 chip 표본이며 전체 분포가 아니다.
map_analysis의 wafer local 후보, chip morphology, registered chip 간 직접 mask 겹침을 따로 해석한다.
cross_modal_alignment의 같은 chip 교집합은 동시 관측이며 인과 확정이 아니다. source별 관측 grain이 다르면
chip/wafer/bit 분모를 합치지 않는다. 미등록 실제 reference 이미지를 합성 사고의 측정 근거로 넣지 않는다.
Inform은 버전·공개 시점·가설/반대 근거를 구분한다. 합성 SQL/FTS는 사내 BM25+vector Hybrid RAG가 아니며
기존 chunk를 바꾸지 않는다. training_label을 제외하고 합성 모델의 추론 관측만 검토한다.
search_platform_history는 과거 참조를 별도로 찾는다. 공통 modality와 cosine 방법을 인용하고 원인 확률로
쓰거나 현재 영향 scope에 합치지 않는다. evidence_review의 시점·lineage 검토는 인과 검증이 아니다.
Judge는 미수신/모순/비교 불가를 같은 Router로 돌린다. Answer는 Judge 이후 관측·가설·미확인·다음 점검을
구분한다. 학습 데이터보다 이른 as_of에는 모델 추론을 보류한다. 생산 조치·실측 성능 완료를 주장하지 않는다.

2026-10-24 실제 로컬 Qwen에서 chip 불량 수를 wafer 불량 수로 바꾼 오류를 확인했다.
platform_facts는 원본 Tool의 전체 집계에서 코드가 만든 수량·단위·분모 계약이다. Answer는
selected_fact_ids로 fact를 선택하고 코드는 원본 text/evidence_ids를 렌더링한다. 수치를 재작성하거나
표본 한 행을 모집단으로 쓰지 않는다.
Answer.answer는 고정 표제다. 코드는 선택된 ID로 원본 fact와 Skill 계획을 렌더링하고,
claims의 완전 일치·후보 누락·중복·근거 ID를 검사한다. 이 검사는 의미/인과 검증의 대체가 아니다.
관측은 fact 표로 표시한다. investigation-recipes.json은 실제 관측 조건으로 후보를 제한하는
오프라인 검토 가설·반증 조건·다음 점검이다. 코드가 조건을 검증하고, Answer는 후보 ID의 우선순위만
선택한다. 생성된 자유 서술을 검증된 분석처럼 표시하지 않는다. 수량/단위와 계획 문구는 원본에서
렌더링하고 모든 source 근거 ID를 보존한다. 미관측 source가 다른 modality의 이상을 취소하지 않는다.
