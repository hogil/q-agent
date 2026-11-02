# MES 기준정보 참조 런타임 현황

기준일 2026-10-29. 아래는 현재 코드와 설정에서 확인한 경계다. 합성 callback 실행 가능한 구조와 실제 운영 연결은 구분한다. 이 문서는 1000시간 완료나 이 문서 작성 과정에서 검증하지 않은 테스트를 주장하지 않는다.

## 런타임 계약

- 사고 요청의 후속 Tool인 `search_mes_reference`는 incident scope 확정 뒤에만 사용할 수 있다. 최초 업무 Tool은 사고 DB 조회/집계다. 기본 `config/config.yaml`은 `mes_reference.enabled: false`, `allowed_kinds: []`로 설정해 비활성이다. 활성화하려면 설정된 허용 kind와 callable `mes_reference_query`가 모두 있어야 한다.
- Router에는 `kind`, `query`, `top_k`만 허용한다. 런타임이 actor, 선택 scope의 incident ID 목록, 요청 `as_of`를 callback에 바인딩한다. 사용자가 전달한 identity/scope 인자는 거부한다. kind는 설정 allowlist에 있어야 하며 top_k는 설정 cap 이하 1..100이다.
- `app/mes_reference_sqlite.py`는 매핑된 논리 컬럼을 사용하는 합성 SQLite용 read-only callback 예다. 절대경로 SQLite를 `mode=ro`와 `query_only`로 열고, 식별자를 검증하며, 요청값을 parameter로 전달한다. 고정 candidate scan cap은 1000행이다. 이 구현은 site adapter, 생산 DB 연결 또는 ACL을 제공하지 않는다.
- `available_at`은 필수이고 설정 timezone의 `as_of` 날짜 다음 날 자정이라는 exclusive cutoff 전에 있어야 한다. 기준일 이후 공개된 행은 제외한다. `effective_from`과 `effective_to`는 nullable이며 반개구간 `[from, to)`로 해석한다. 둘 다 null이면 시간 유효성은 `unknown`; `time_status=active`도 시간상 유효성만 뜻한다.
- 적용성은 별도 `applicability` (`confirmed`, `candidate`, `unknown`) 및 `scope_relation` (`current_scope`, `catalog_candidate`)로 표현한다. 시간상 active라는 사실이 현재 제품/사고에 적용된다는 증거는 아니다. scope relation은 adapter assertion이며 출처 인증이나 ACL 증거가 아니다.
- 응답은 status, 기준일, incident 범위, 허용 kind, item 수, `truncated`와 `candidate_count` 관계를 검사한다. top_k에 따른 잘림 또는 고정 scan cap 초과 가능성이 있어 반환 항목을 전체 후보로 간주할 수 없다. truncation은 evidence limitation으로 남고 답변에서도 일부 결과임을 밝혀야 한다.
- MES callback/응답 검증 실패는 `MES_REFERENCE_RETRIEVAL_FAILED`로 처리하고 실패한 동일 Tool·인자·scope 요청 fingerprint를 기록한다. 같은 요청의 중복 차단은 이 실패 요청에 한해 재시도를 허용한다. 성공 완료 요청의 반복은 계속 차단된다.

## 인접 자료 경계

- `search_internal_documents`와 engineer notes는 기존 Hybrid RAG callback(`document_query`) 경로 및 기존 chunk/provenance 계약을 사용한다. callback과 source 활성화가 필요하며 MES 기준정보 검색이 이 chunk를 대체하거나 재생성하지 않는다.
- Enterprise 설비/Inform 조회는 별도 SQL callback이다. source mapping에 `available_at` 컬럼이 없으면 `AVAILABILITY_TIME_NOT_MAPPED`, null이면 `AVAILABILITY_TIME_NULL`을 남기고 availability를 unknown으로 둔다. 해당 source는 unknown availability 행 때문에 `PARTIAL`이 될 수 있다. 따라서 기준시점 당시 확인 가능한 근거라고 단정하지 않는다.

## 미검증 범위

실제 운영 MES schema/API/connection, site mapping의 의미, 사용자·역할 ACL, 운영 LLM 호출 및 실제 답변 품질은 확인되지 않았다. 합성 read-only adapter나 validator 계약만으로 이 항목들의 연결·검증 완료를 주장하지 않는다.

## 근거 파일

- `D:\project\q-agent\app\agent.py`
- `D:\project\q-agent\app\mes_reference_contract.py`
- `D:\project\q-agent\app\mes_reference_sqlite.py`
- `D:\project\q-agent\app\evidence_review.py`
- `D:\project\q-agent\app\enterprise_tools.py`
- `D:\project\q-agent\config\config.yaml`
- `D:\project\q-agent\docs\current\DOCUMENT_AND_EQUIPMENT_RUNTIME_20261029_ROOT_v1.md`
