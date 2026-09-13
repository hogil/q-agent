# 전체 Skill 목록과 컬럼 설명 관리

현재 14개 application Skill이 있다. 개인 ChatGPT에 설치하는 Skill이 아니며 `app/skill_registry.json`과 `app/skill_loader.py`가 필요한 소스를 조합한다. LLM API 호출은 연결되어 있으나 실제 사내 모델·데이터 검증은 아직 하지 않았다.

| 구분 | Skill | 책임 |
|---|---|---|
| 공통 | core | 사고 DB 우선, 근거/가설 구분, 데이터와 지시문 경계 |
| 역할 | router | 의도/조건/Tool 계획과 필요한 공유 Skill 선택 |
| 역할 | answer | Judge 검토 후 최종 답변과 주장-근거 연결 |
| 역할 | judge | 답변 전 조회 근거의 충분성, 범위, 누락 검토 |
| 용어 | terminology | 공식값/동의어/오타/조직 범위 해석 |
| Schema | incident-schema | 사고 테이블 21개 논리 컬럼과 검색·통계 규칙 |
| Schema | lot-schema | 사고-Lot 관계 4개 논리 컬럼과 Lot 조회 |
| Schema | wafer-schema | 별도 Wafer 목록 4개 논리 컬럼과 Wafer 조회 |
| Schema | incident-document-schema | 사고문서 7개 논리 컬럼과 문서 근거 검토 |
| Schema | document-chunk-schema | 기존 문서 chunk 4개 논리 컬럼 |
| Schema | image-metadata-schema | 이미지 메타데이터 7개 논리 컬럼 |
| Schema | trend-metadata-schema | Trend 메타데이터 6개 논리 컬럼 |
| 조치 | actions | 조치 제안, 승인, 실행과 결과 구분 |
| 개발/관리 | skill-maintenance | 수정 범위 판별, 회귀 평가, 릴리스 관리 |

Schema Skill 7개에 총 53개 논리 컬럼 정의가 있다. `SKILL.md`는 해석 규칙을, 각 `references/*.json`은 상세 컬럼 Catalog를 가진다. config_loader.py가 실행 설정을 검사하고, 각 Schema Skill이 컬럼 의미를 설명한다.

## 컬럼별 필수 설명

description(의미), type(논리 타입), nullable, null_meaning, unit, allowed_operations, synthetic_example을 기록한다. 엔티티 수준에는 grain, identity, physical_mapping, 미매핑 처리 규칙을 둔다. 예시는 합성값이며 사내 공식 코드 목록을 대신하지 않는다. 허용 연산은 의미 계약이며 해당 Tool 구현 완료의 표시가 아니다.

예: product_generations의 논리 타입은 array[string]이고 기존 원본 배열을 유지한다. contains_any/contains_all/set_equals를 구분하며 세대별 집계는 원소별 고유 사고다. NULL/빈 배열을 정상 또는 미영향으로 해석하지 않는다. 원본 값으로 세대별 Wafer 수를 추정하지 않는다.

물리 컬럼명을 바꾸려면 config의 tables.incident.columns.product_generations를 수정한다. 컬럼 의미 자체가 바뀌면 incident-schema의 reference를 수정한다. 원본 DB에서 이 컬럼이 없는 경우 사용 불가로 표시하며 LLM이 대체값을 만들지 않는다.

## 공유와 로딩

- 모든 역할: core + 자신의 role Skill.
- 사고 검색: incident_search.
- Lot 질문: incident-schema + lot-schema.
- Wafer 질문: incident-schema + lot-schema + wafer-schema.
- 문서 질문: incident-document-schema + document-chunk-schema.
- 통계 질문: incident-schema; Lot 통계면 Lot 관련 Skill 추가.
- 이미지/Trend 메타데이터 질문: image-metadata-schema / trend-metadata-schema.
- 용어 해석: terminology와 조회한 사전 항목.
- maintenance는 온라인 Router/Answer/Judge에 허용하지 않는다.

공유는 같은 소스/버전을 읽는다는 의미다. 모델 간 컨텍스트가 자동 공유되는 것은 아니다. 현재 compiler는 선택 topic의 reference 전체를 읽으며 JSON은 공백만 축약한다. 대규모 사내 Catalog의 컬럼별 선택 로딩과 실제 tokenizer 예산 계산은 후속 작업이다. 예산 초과 시 규칙을 임의로 자르지 않는다.

이미지/Trend 분석 알고리즘별 workflow Skill, 기간시스템별 상세 조회 Skill은 아직 별도로 작성하지 않았다. 현재 이미지/Trend Skill은 메타데이터 컬럼 설명이다. 이 구분을 구현 상태 보고에 유지한다.

## 모든 Skill의 변경 전 확인

14개 SKILL.md에 실제 원본/대표 데이터, 출처, 기준시점, 변경 근거를 확인하는 규칙을 직접 명시했다. 실제 자료에 접근하지 못하면 미확인으로 표시하고 설계/더미 초안만 관리한다. 상세 확인 대상과 LLM별 배치는 [LLM_PLACEMENT.md](LLM_PLACEMENT.md)를 참고한다. 이 문구가 존재한다고 실제 데이터 확인이 수행됐다는 뜻은 아니다.

quality-demo-0.11에서 terminology에 컬럼/값 별칭 구분, 미확인 필터 보존, 식별자 오보정 방지를 추가했다. 합성 사전 전체를 프롬프트에 넣지 않고 정규화 Tool에서 필요한 결과를 반환한다. 합성 사전과 평가 자료는 제거했으며 사내 사전은 별도로 준비한다.

quality-demo-0.12의 역할 본문, 조건별 예시와 출력 형식 v2는 [SYSTEM_PROMPTS.md](SYSTEM_PROMPTS.md)를 기준으로 한다.

## 구조 정리 기준

2026-09-14 기준 저장소의 Skill 원본과 registry, compiler를 확인했다. 짧은 조회 규칙 5개는 해당 Schema Skill 본문에 통합했다. 기존 topic 이름은 유지하며 동일 Skill은 한 번만 로딩한다. 역할별 조건 예시와 출력 JSON 계약, 테이블별 컬럼 JSON은 목적이 달라 분리 유지한다. 사내 원본 접근이 없어 내용은 미확인 설계 초안이며 이번 변경은 실제 데이터 검증이 아니다.
