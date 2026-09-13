# 품질 AI Agent — 사내 설치 및 Skill 기반 역할 관리

이 패키지는 사내 서비스 구축용 소스 초안이다. 개인 ChatGPT에 Skill을 설치하거나 사내 시스템에 접속하지 않았다. 모든 데이터와 물리 스키마 이름은 가상이다. 실제 LLM 호출 및 운영 성능 평가도 아직 수행하지 않았다.

최신 배포 설정은 [CONFIGURATION.md](CONFIGURATION.md), 전체 19개 Skill과 53개 컬럼 명세는 [SKILLS.md](SKILLS.md)를 기준으로 읽는다. 아래 mapping.example.json과 demo.py 설명은 이전 독립 Lot 회귀 예제다. 새 실행 경로는 config/default.toml + site overlay → generate_dummy.py / query_demo.py / skill_loader.py다.

## 1. 이번 변경과 이전 설계의 유지

현재 설계는 ARCHITECTURE_AND_PLAN.md를 참조한다. 제품세대는 기존 배열을 유지하며, 사내문서와 Eng’r Inform Note는 기존 chunk의 BM25 + vector similarity Hybrid RAG를 연결한다. 이 문서의 구현 범위는 별도 Lot 테이블 연결과 Router/Answer/Judge의 Skill 소스 관리다. 모든 기능이 통합된 운영 앱은 아니다.

사용자: “INC-001의 사고 내용과 사고 Lot 목록까지 보여줘.”
흐름: Router가 사고+Lot 의도를 분류 → 사고 조회로 내부키/표시번호 확보 → scope_id 생성 → Lot Tool이 설정된 관계로 lot_list 조회 → 코드가 중복/건수/페이지/완전성 검사 → Judge 근거 검토 → 부족하면 Router로 재조회 → 검토 통과 후 Answer가 최종 답변.

후속 질문 “그 사고 랏도 보여줘”는 대화의 선택 사고를 사용한다. 선택 사고가 여러 개면 어느 사고인지 확인하거나 명시된 전체 집합을 사용한다. 마지막 메시지의 사고명을 근거 없이 다시 추정하지 않는다.

## 2. LLM 역할과 Tool 실행의 구분

| 구성 | 책임 | 수행하지 않는 일 |
|---|---|---|
| Router LLM | 의도, 논리 필터, Tool 순서와 필요한 Skill 선택 | 물리 SQL/테이블명 생성, 조회 결과 예상 |
| Orchestrator 코드 | 상태, 허용 Tool, 우선 조회 Gate, 권한/범위, 재시도 | 근거 없는 원인 생성 |
| Tool Adapter | 물리 매핑으로 쿼리, 건수/페이지 반환 | 권한을 LLM에게 위임 |
| Answer LLM | 확인 결과와 출처를 사용자 요청에 맞게 설명 | Lot ID/수치/조치 결과 창작 |
| Judge LLM | 답변 전 근거 충분성, 질문 충족, 범위/누락 검토 | 정답 창작, 코드 FAIL 무효화, 실행 승인 |
| Deterministic Checks | ID 집합, 합계, 페이지, 계약, ACL 상태 검증 | 자연어 의미 판단 대체 |

호출 순서는 Router → Tool → Judge → Answer로 고정한다. Judge는 근거를 검토하고 부족하면 Router로 되돌린다. Answer가 마지막 LLM이다. 기존 max_answer_revisions=2는 예약 설정이며 이 흐름의 Answer-Judge 반복을 의미하지 않는다. 전체 Orchestrator와 예산 집행은 아직 미구현이다.

## 3. 논리 이름과 사내 물리 이름

시스템의 논리 이름은 유지하고 사내 물리 이름만 매핑 설정에서 교체한다. LLM의 Skill에는 논리 의미를 넣고 물리 접속정보/비밀번호를 넣지 않는다.

| 논리 항목 | 예시 물리 값 | 사내 교체 사항 |
|---|---|---|
| incident 테이블 | demo_incident | 실제 사고 테이블 또는 읽기 View |
| incident.incident_id | accident_pk | 사고 내부 고유키 |
| incident.incident_number | accident_no | 사용자에게 보여주는 사고번호 |
| incident.title | accident_title | 사고명 |
| incident.city | city_name | 도시/위치 |
| incident.line | line_name | 라인 또는 표시 View |
| incident.expected_lot_count | registered_lot_count | 같은 의미의 등록 Lot 수; 없으면 View의 NULL |
| lot_list 테이블 | demo_lot_list | 실제 lot_list 또는 다른 이름의 테이블/View |
| lot_list.incident_ref | accident_ref | 사고를 참조하는 키 |
| lot_list.lot_id | lot_no | Lot ID |
| lot_list.product_code | product_name | 실제 제품 코드(명칭이면 논리 정의도 수정) |
| lot_list.status | lot_state | Lot 상태와 그 시점 정의 |

`lot_list`는 논리 엔티티 이름이지 반드시 그대로 설치해야 하는 테이블명이 아니다. `mapping.example.json`은 모든 테이블/컬럼/Join과 페이지 제한을 모아 둔다. `mapping.renamed-demo.json`은 물리 이름을 전부 변경한 동작 검증용 설정이다.

기존 원본 테이블을 ALTER하거나 덮어쓸 필요는 없다. 의미 차이가 있으면 읽기 전용 View 또는 Adapter에서 정규화한다. 선택 컬럼이 실제로 없으면 대응하는 NULL과 availability 정보를 제공하고 없는 데이터를 다른 컬럼으로 임의 대체하지 않는다. 새 통합 설정에서 expected_lot_count를 빈 문자열로 두면 Adapter가 NULL을 반환한다.

## 4. 사고와 Lot 연결키

사고 내부키 `PK001`과 표시번호 `INC-001`은 서로 다르다. 기본 설정은 incident.incident_id → lot_list.incident_ref로 Join한다. 실제 Lot 테이블에 사고번호가 저장돼 있다면 `relationships.incident_lots.parent_key`를 `incident_number`로 바꾼다.

연결키 타입, 앞자리 0, 공백, 대소문자, 과거 키 변경, 사이트별 번호 중복을 확인한다. 문자열을 숫자로 바꾸어 앞자리 0을 잃지 않는다. 사고번호가 도시별 중복이면 도시+사고번호 복합키 또는 고유 surrogate key View가 필요하다. 현재 Adapter는 단일 parent key의 고유성을 검사하며 복합키 구현은 별도다.

Lot 자체도 전사 고유인지 확인한다. Lot 번호가 사업부/사이트/기간별 재사용되면 고유 Lot 집계키를 확장한다. 현재 데모는 lot_id 전사 고유를 가정한다. Rework, split/merge, parent/child Lot는 별도 관계로 모델링하며 자동으로 같은 Lot로 합치지 않는다.

## 5. 더미 Lot 결과

INC-001은 LOT-001~LOT-006의 6개 Lot다. 페이지당 3개 설정으로 첫 응답에 3개와 next_offset=3을 반환하고 다음 응답이 나머지 3개를 반환한다. 두 페이지를 모두 받은 후에만 전체 목록이라고 표시한다.

INC-002는 LOT-006~LOT-009의 4개이며 INC-007은 LOT-010의 1개다. 세 사고의 관계 수는 6+4+1=11, 고유 Lot는 LOT-006 중복을 제거해 10개다. 사고별 목록을 합칠 때 사고번호를 유지한다.

INC-009는 등록 기대수 2개지만 연결 테이블에는 행이 없는 누락 사례다. “사고가 없다” 또는 “불량 Lot가 없다”가 아니라 “사고는 조회됐으나 Lot 연결 결과가 등록 기대수와 불일치”로 표현한다.

Lot 상세 결과의 product_code/status는 가상 코드다. 현재 Lot 진행 상태가 필요하면 기간시스템에서 다시 확인해야 한다. 사고 당시 등록 상태와 현재 상태를 같은 컬럼으로 혼용하지 않는다.

## 6. 사내 설치 절차

1. DDL/컬럼 설명/코드 기준정보/익명 표본으로 사고-Lot 관계와 데이터 단위를 확정한다.
2. 읽기 전용 계정과 네트워크·인증 방식을 서비스 설정으로 준비한다. 비밀번호는 비밀정보 관리 또는 환경변수로 주입하고 Skill/매핑/로그에 기록하지 않는다.
3. DB 엔진을 확인한다. 제공 Adapter는 SQLite 전용이다. Oracle/PostgreSQL/SQL Server 등은 드라이버, placeholder, 식별자 quoting, 스키마 검증, pagination, timeout, 날짜 처리, snapshot/transaction Adapter를 구현한다. dialect 값만 바꾼다고 호환되지 않는다.
4. mapping.example.json을 사내 설정으로 복사해 물리 이름과 Join 기준을 교체한다. SQL identifier는 사용자 입력으로 바꾸지 않는다. 현재 예제는 단순 Unicode 이름을 허용한다. schema.table, 공백/한글 이름 등은 해당 DB Adapter의 검증·quoting 또는 표준 View로 처리한다.
5. 허용 도시/라인/제품 등 실제 ACL을 사고 조회와 Lot 조회 모두 서버에서 적용한다. actor-scope 바인딩은 ACL을 대신하지 않는다.
6. source_completeness를 담당자/ETL 보장으로 확인한다. 실제 기간 필터/보관 범위가 일부면 partial/unknown으로 선언한다.
7. 스키마 검증, 기준 SQL 대조, 미등록·오류·중복·불일치, 페이지/권한 테스트를 수행한다.
8. 사내 변경 사항을 관련 Schema Skill/사전/Tool 인터페이스에 반영한 뒤 릴리스 lock을 새 버전으로 빌드한다.
9. 운영에서는 query_scope 만료·사용자·데이터 revision/snapshot을 고정하고 대량 Lot는 keyset pagination 또는 안정적인 서버 export로 처리한다.

실행 확인용 명령(패키지 폴더에서):

```bash
python demo.py
python check_skills.py
python skill_loader.py router --topics terminology,lots
```

`demo.py`는 메모리 DB를 만들고 패키지 안의 demo.sqlite와 결과 파일을 생성/갱신한다. 원격 DB에 연결하지 않는다. schema_seed.sql은 더미 재현용이며 사내 운영 DB에 실행하지 않는다.

## 7. Skill 구성

| Skill | 로딩 대상 | 내용 |
|---|---|---|
| quality-core | 모든 역할 | 근거/수치/권한/미확정 공통 규칙 |
| quality-router | Router | 의도·필터·Tool 계획 출력 |
| quality-answer | Answer | 결과/목록/출처 설명 |
| quality-judge | Judge | 주장-근거 검토 및 수정 요구 |
| quality-terminology | 용어 해석 필요 역할 | 오타·동의어 후보 선택 규칙 |
| quality-incident-schema | 스키마 관련 역할 | 논리 컬럼·관계 설명 |
| quality-lot-retrieval | Lot 관련 역할 | Join·중복·페이지·완전성 |
| quality-statistics | 통계 관련 역할 | 집계 단위와 중복/분모 |
| quality-document-evidence | 문서 관련 역할 | 사고 연결·버전·Chunk 출처 |
| quality-actions | 조치 관련 역할 | 제안/승인/실행의 구분 |
| quality-skill-maintenance | 개발·개정 작업 | 변경 절차와 회귀·릴리스 |

이는 사내 Application용 Skill 소스다. 개인 ChatGPT Skill UI 설치와는 별도다. 런타임이 SKILL.md를 자동으로 읽는다고 가정하지 않는다. skill_loader.py가 registry에 따라 명시적으로 조합하고, 실제 LLM API의 system 메시지로 전달하는 부분은 사내 Orchestrator에서 구현한다.

## 8. Skill의 분절 및 공유 원칙

역할 Skill에는 역할의 의사결정·출력 규칙만 둔다. 공통 용어/집계 규칙은 복사하지 않고 동일 shared Skill을 로딩한다. 대형 사전은 instructions가 아니라 승인된 data다.

사전은 department/process/failure/generation/equipment/recipe/location 등으로 분할해 인덱스 조회한다. 원문, 후보, 공식값, 도시/라인 범위, 유효기간, 승인상태, dictionary version을 반환한다. 전체 백과사전/모든 컬럼 설명을 매번 system prompt에 넣지 않는다. 사람이 확정한 사전과 검색된 후보는 별도로 표시한다.

공통 Schema Skill은 읽는 방법과 핵심 단위를 설명하고 분야별 상세 Catalog는 검색한다. 작은 이번 예제는 references를 전부 읽어도 작지만 실서비스에서는 요청한 테이블/관계 reference만 선택한다.

권장 조합 예:
- Router + core + terminology + schema + lot-retrieval
- Answer + core + lot-retrieval + 필요 시 statistics/document-evidence
- Judge + core + lot-retrieval + 질문에 필요한 schema/statistics/document-evidence

공유는 같은 소스를 읽는다는 뜻이지 각 LLM의 컨텍스트가 자동 공유된다는 뜻이 아니다. 각 호출에 필요한 조각을 전달한다. 조사 상태와 evidence는 공통 저장소에서 전달한다.

## 9. 프롬프트 조합과 입력 경계

system = 고정 core + 필요한 shared Skill/작은 reference + 역할 Skill.
user/tool = 현재 질문 + 조사 상태 + Tool 결과 + 용어/Schema 검색 데이터 + 문서 근거.
Tool definitions와 출력 JSON Schema는 API가 지원하는 구조화 인터페이스로 전달한다. 실제 사내 모델의 schema/tool calling 준수율을 별도 검증한다.

문서나 사용자 입력을 신뢰된 Skill 텍스트로 합치지 않는다. 승인되지 않은 Skill 경로를 Router가 임의 로드하지 못하도록 registry allowlist를 사용한다. 사전·Catalog의 근거 텍스트에 섞인 지시문도 역할 정책을 바꾸지 못한다.

Loader는 동일 topic의 중복 shared Skill을 1번만 포함한다. 순서를 고정하고 누락/변경된 파일을 hash로 검사한다. context 예산을 넘으면 지침을 몰래 잘라내지 않고 더 좁은 topic을 선택하게 한다. 현재는 문자 수 상한이며 실제 운영은 해당 모델 tokenizer 기준 token 예산으로 교체한다.

역할간 정책 충돌은 우선순위를 임의 생성하지 않고 릴리스 오류로 취급한다. Registry metadata만 먼저 제공하고 필요한 Skill을 요청하는 2단계 Router 로딩은 향후 Orchestrator 구현 항목이다. 현재 compiler는 topics를 호출자가 명시한다. 새 코드에서는 모델 profile과 경로를 config에서 읽고 JSON reference의 공백만 축약한다.

## 10. 랜덤성과 지속 최적화

Skill 관리가 줄이는 것은 지침의 임의 변경과 누락이다. temperature=0도 하드웨어/병렬 추론/검색 인덱스 변화에 따른 완전한 재현을 보장하지 않는다. 다음을 함께 고정한다.

- role Skill/공통 Skill/reference hash와 release
- 용어/Schema Catalog/물리 mapping 버전
- Tool 인터페이스 및 실행 코드 버전
- 모델 ID/리비전, tokenizer/template, 추론 설정
- 조회 기준시각 및 가능하면 데이터 snapshot
- 검색 인덱스/embedding/reranker 버전과 top-k

현재 release.lock.json은 Skill 소스·사전 예시·registry·Loader/Tool 코드 hash를 고정한다. 배포 매핑·경로·모델 설정은 별도 config_hash로 기록한다. 모델 ID는 config의 models/roles에서 지정하며 아직 운영 모델을 연결하지 않았다. 기존 세션은 같은 lock을 유지하고 새 릴리스가 진행 중 조사에 섞이지 않게 한다.

## 11. 변경 절차

실패 사례 수집 → maintenance Skill과 현재 관련 Skill 읽기 → 실패가 prompt/data/schema/code 어디인지 판별 → 단일 원본 최소 수정 → 단위/통합 검사 → 기존 회귀 + 새로운 실패 사례 → 변경에 사용하지 않은 holdout 평가 → 검토 → 새 release/model profile 고정 → 제한 범위 적용 → 실패 시 이전 릴리스 복구.

운영 중 Router/Answer/Judge가 자신의 Skill을 자동 수정하도록 하지 않는다. Judge는 개선 후보를 만들 수 있지만 독립된 정답 평가를 대체하지 않는다. 여러 프롬프트 변형을 비교할 때 데이터/모델/예산을 맞추고 정답률뿐 아니라 실패 유형·지연·토큰 비용을 본다.

오타를 새로 발견하면 사전 후보에 추가한다. Join 오류면 매핑/Schema/코드 수정이다. 개수 과장 표현이면 Answer Skill과 검증 규칙 수정이다. 무조건 Router/Answer/Judge 세 프롬프트를 동시에 수정하지 않는다.

`python skill_loader.py freeze`는 명시적인 릴리스 빌드 동작이다. runtime은 lock 불일치 때 자동 freeze하지 않는다. 운영 CI에서는 검토/회귀 Gate를 통과한 주체만 릴리스 빌드·배포하도록 설정한다. 현재 명령 자체가 조직 승인 시스템을 구현하는 것은 아니다.

## 12. 현재 검증과 남은 구현

Lot Tool 19개 검사: 우선 조회, PK/표시번호 Join, 중복 제거, 페이지와 전체 ID, 완전성, 다른 사용자 scope, 페이지 상한, 사고 미등록, 기대수 불일치, 여러 사고 고유 Lot, 값/식별자 삽입 방지, 전 테이블/컬럼 교체, 다른 Join 기준, 없는 컬럼, 상충 상태.

Skill 구성 34개 검사: 역할별 동일 프롬프트 hash, 공유 Lot Skill, 불필요 문서 미로딩, 대형 사전 미주입, 공유 Schema 중복 제거, 온라인 Judge의 maintenance 로딩 차단, lock 이후 소스 변경 차단, 19개 Skill metadata.

이 수치는 실제 Router/Answer/Judge LLM 품질 테스트 수가 아니다. 실제 모델 통합, JSON Schema 검증기 연결, Judge/code Gate, 운영 ACL, 동시 데이터 snapshot, 대량 export, 사전 검색 서비스, versioned deployment는 아직 구현하지 않았다.

## 13. 사내 적용 전 필수 확인

실제 사고 테이블/내부 PK/표시번호, lot_list FK, Lot ID 고유 범위, 이력 테이블 여부, 제품/상태의 의미, 예상 Lot 수의 기준, 데이터 완전성/보관기간, DB 엔진과 조회 권한, 실제 사내 모델과 API 계약을 확인한다. 이미 알려진 정보는 재질문하지 않고 해당 설정에 반영한다.
