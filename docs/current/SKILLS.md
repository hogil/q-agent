# 전체 Skill 목록과 컬럼 설명 관리

현재 18개 application Skill이 있다. 개인 ChatGPT에 설치하는 Skill이 아니며 `app/skill_registry.json`과 `app/skill_loader.py`가 필요한 소스를 조합한다. 아직 실제 LLM 호출 서비스가 통합된 것은 아니다.

| 구분 | Skill | 책임 |
|---|---|---|
| 공통 | quality-core | 사고 DB 우선, 근거/가설 구분, 데이터와 지시문 경계 |
| 역할 | quality-router | 의도/조건/Tool 계획과 필요한 공유 Skill 선택 |
| 역할 | quality-answer | 질문에 맞는 결과 설명과 주장-근거 연결 |
| 역할 | quality-judge | 답변의 근거, 누락, 과장 검토 |
| 용어 | quality-terminology | 공식값/동의어/오타/조직 범위 해석 |
| Schema | quality-incident-schema | 사고 원장 21개 논리 컬럼 |
| Schema | quality-lot-schema | 사고-Lot 관계 4개 논리 컬럼 |
| Schema | quality-wafer-schema | 별도 Wafer 목록 4개 논리 컬럼 |
| Schema | quality-incident-document-schema | 사고문서 7개 논리 컬럼 |
| Schema | quality-document-chunk-schema | 기존 문서 chunk 4개 논리 컬럼 |
| Schema | quality-image-metadata-schema | 이미지 메타데이터 7개 논리 컬럼 |
| Schema | quality-trend-metadata-schema | Trend 메타데이터 6개 논리 컬럼 |
| 조회 절차 | quality-lot-retrieval | 사고 선조회 후 Lot 연결/중복/페이지/완전성 처리 |
| 조회 절차 | quality-wafer-retrieval | 사고명 확정 → Lot 범위 → 별도 Wafer 목록, 영향/구성 구분 |
| 통계 | quality-statistics | 사고/세대/FAB Out/Lot 집계, grain, 분모, 중복 |
| 문서 근거 | quality-document-evidence | 사고문서 연결, 기존 사내문서/Eng’r Inform Note Hybrid RAG 근거/버전/인용 |
| 조치 | quality-actions | 조치 제안, 승인, 실행과 결과 구분 |
| 개발/관리 | quality-skill-maintenance | 수정 범위 판별, 회귀 평가, 릴리스 관리 |

Schema Skill 7개에 총 53개 논리 컬럼 정의가 있다. `SKILL.md`는 해석 규칙을, 각 `references/*.json`은 상세 컬럼 Catalog를 가진다. `check_config.py`가 config에 정의된 컬럼 목록과 Catalog 목록의 완전 일치를 검사한다.

## 컬럼별 필수 설명

description(의미), type(논리 타입), nullable, null_meaning, unit, allowed_operations, synthetic_example을 기록한다. 엔티티 수준에는 grain, identity, physical_mapping, 미매핑 처리 규칙을 둔다. 예시는 합성값이며 사내 공식 코드 목록을 대신하지 않는다. 허용 연산은 의미 계약이며 해당 Tool 구현 완료의 표시가 아니다.

예: product_generations의 논리 타입은 array[string]이고 기존 원본 배열을 유지한다. contains_any/contains_all/set_equals를 구분하며 세대별 집계는 원소별 고유 사고다. NULL/빈 배열을 정상 또는 미영향으로 해석하지 않는다. 원본 값으로 세대별 Wafer 수를 추정하지 않는다.

물리 컬럼명을 바꾸려면 config의 tables.incident.columns.product_generations를 수정한다. 컬럼 의미 자체가 바뀌면 quality-incident-schema의 reference를 수정한다. 원본 DB에서 이 컬럼이 없는 경우 사용 불가로 표시하며 LLM이 대체값을 만들지 않는다.

## 공유와 로딩

- 모든 역할: core + 자신의 role Skill.
- Lot 질문: incident-schema + lot-schema + lot-retrieval.
- Wafer 질문: incident-schema + lot-schema + wafer-schema + lot-retrieval + wafer-retrieval.
- 문서 질문: incident-document-schema + document-chunk-schema + document-evidence.
- 통계 질문: incident-schema + statistics; Lot 통계면 Lot 관련 Skill 추가.
- 이미지/Trend 메타데이터 질문: image-metadata-schema / trend-metadata-schema.
- 용어 해석: terminology와 조회한 사전 항목.
- maintenance는 온라인 Router/Answer/Judge에 허용하지 않는다.

공유는 같은 소스/버전을 읽는다는 의미다. 모델 간 컨텍스트가 자동 공유되는 것은 아니다. 현재 compiler는 선택 topic의 reference 전체를 읽으며 JSON은 공백만 축약한다. 대규모 사내 Catalog의 컬럼별 선택 로딩과 실제 tokenizer 예산 계산은 후속 작업이다. 예산 초과 시 규칙을 임의로 자르지 않는다.

이미지/Trend 분석 알고리즘별 workflow Skill, 기간시스템별 상세 조회 Skill은 아직 별도로 작성하지 않았다. 현재 이미지/Trend Skill은 메타데이터 컬럼 설명이다. 이 구분을 구현 상태 보고에 유지한다.

## 모든 Skill의 변경 전 확인

18개 SKILL.md에 실제 원본/대표 데이터, 출처, 기준시점, 변경 근거를 확인하는 규칙을 직접 명시했다. 실제 자료에 접근하지 못하면 미확인으로 표시하고 설계/더미 초안만 관리한다. 상세 확인 대상과 LLM별 배치는 [LLM_PLACEMENT.md](LLM_PLACEMENT.md)를 참고한다. 이 문구가 존재한다고 실제 데이터 확인이 수행됐다는 뜻은 아니다.
