# 반도체 품질 Agent — 현재 설계와 실행 계획

이 문서는 목표 설계다. 구현된 부분은 사고/Lot 독립 데모, 배열 집계 데모, Skill 컴파일/검증, 화면 시안이다. 나머지는 아래 단계별 통과 조건을 만족한 뒤 운영 기능으로 표시한다. 기존 자원 계획은 원본 문서를 유지하며 여기서 GPU 수량이나 모델 사양을 새로 가정하지 않는다.

사고명 검색과 별도 Lot/Wafer 테이블의 최신 구현은 [INCIDENT_LOT_WAFER.md](INCIDENT_LOT_WAFER.md)를 참고한다.

## 1. 요청 처리 아키텍처

LLM 세 역할의 입력/출력과 물리 모델 서버 참조는 [LLM_PLACEMENT.md](LLM_PLACEMENT.md)를 따른다. 현재 같은 text 모델을 역할별로 호출하는 설정이며 실제 서버 연결은 비활성이다.

| 위에서 아래 순서 | 처리 내용 |
|---|---|
| 사용자 질문 / 이미지 / Trend 의뢰 | 원문, 첨부 자료, 사고명/번호, 도시, 라인, 기간, 대상 제품을 받는다. |
| ↓ | |
| **Router LLM** | 질문의 요구사항, 논리 검색 조건, 필요한 Tool과 Skill을 결정한다. |
| ↓ | |
| **1계층: 사고 DB 우선 조회** | 정형 사고 검색 또는 SQL 집계를 실행하고 사고 범위와 조회 상태를 기록한다. |
| ↓ | |
| **2계층: 필요한 추가 Tool 조회** | Lot/Wafer, 사고문서, 사내문서, Eng’r Inform Note, 이미지, Trend, 기간시스템을 필요한 만큼 조회한다. |
| ↓ | |
| **Judge LLM** | 원문 질문에 답할 근거가 충분한지, 사고 범위가 맞는지, 누락/모순이 있는지 검토한다. |
| ↓ | 검토 통과 후 진행한다. 근거 부족이나 사고 오류는 맨 위 Router로 돌린다. |
| **Answer LLM** | 검토된 근거로 최종 답변을 작성한다. 마지막 LLM이다. |
| ↓ | |
| **최종 결과 표시** | 답변, 조회 상태, 확정된 사고 범위, Lot/Wafer 목록, 문서 출처와 이미지, 미확인 항목을 표시한다. |

Router는 위의 한 노드만 사용하고 Judge 재조회도 그 Router로 복귀한다. 추가 Tool은 Lot/Wafer, 문서 RAG, 이미지, Trend, 기간시스템이며 불필요하면 생략한다. 사고 DB 우선 조회/범위 검증은 실행 코드에서 검사한다. Answer 아래에는 검증된 조회 상태와 사고 범위를 최종 표시한다.

인증, 파일 형식 검사, 논리 스키마/동의어 조회는 사전 준비다. 사고 관련 최초 **업무 데이터** 조회는 사고 DB다. 이미지/Trend 단독 의뢰도 사용자가 제공한 메타데이터로 사고 DB를 먼저 조회한다. 유효한 조건이 없으면 필요한 메타데이터를 요청한다. DB에 기존 사고가 없다는 확인 뒤 이상탐지로 새 관측을 생성할 수 있으며 이를 등록 사고로 단정하지 않는다. 향후 상시 탐지 작업은 별도 스케줄러에서 관측을 만들고 이 조사 흐름에 전달한다.

“사고 내용을 다 찾는다”는 전체 DB를 읽는다는 뜻이 아니다. 질문의 사고 후보, 필터, 필요한 컬럼, 페이지 범위가 확정되고 완전성/제한이 기록된 시점이다. 사고가 식별되지 않았으면 제목만으로 다른 사고의 문서를 붙이지 않는다. DB 장애는 0건이 아니며 허용되지 않은 우회 경로로 진행하지 않는다.

상태에는 request_id, actor/ACL, 원문·정규화 필터, scope_id, selected_incident_ids, as_of, 페이지 cursor, tool_budget, evidence IDs, skill release/hash를 저장한다. ReAct식 반복은 Tool 결과로 다음 조회를 결정하는 유한 루프로 구현한다. 자유로운 내부 추론은 저장·표시하지 않고 Tool 이름·조건·짧은 선택 근거·결과 상태를 기록한다. 재시도와 추가 조회 예산은 운영 설정으로 제한한다.

## 2. Tool 인터페이스과 호출 기준

| Tool | 데이터·처리 | 호출 조건 / 핵심 반환값 |
|---|---|---|
| find_incidents | 사람이 관리한 정형 사고 DB | 사고 조건, ID/번호, canonical 필터, 기준시각, 페이지·총건수·scope |
| aggregate_incidents | 같은 DB의 승인된 SQL 집계 | count·sum·추이·비교·순위 요청, 집계 단위·분모·미등록·다중값 규칙 |
| list_incident_lots | 별도 lot_list | 유효한 사고 scope 후 Join, 고유 Lot/사고-Lot 관계 수, 페이지·완전성 |
| search_incident_documents | 사고문서 table → 기존 PPT/PDF chunk | DB scope 확정 후 상세 원인/조치 질문, ID 연결·제목 후보 확인·페이지/슬라이드 |
| search_internal_documents | 사내문서 저장소의 기존 Hybrid RAG | BKM·표준·관련 기술 근거, BM25+vector 결과와 문서 provenance |
| search_engineer_notes | Eng’r Inform Note의 기존 Hybrid RAG | 엔지니어 조사 기록, 작성/승인/수정 시점 및 문서 ID |
| query_enterprise_records | 승인된 기간시스템/DW·ODS Adapter | 처리이력·검사·설비이력, 요청/응답 스키마와 기준시각 |
| detect_image_anomaly / detect_trend_anomaly | 사내 검증 모델·룰 서비스 | 관측 결과, 임계값/모델 버전, 대상·시간/좌표·신뢰도 |
| search_similar_images / list_incident_images | 이미지 메타데이터 + Storage | 사고·Lot·Wafer·FAB/EDS 단계로 제한, 권한 검사 후 임시 URL |
| propose_action / execute_approved_action | 조치 제안 / 별도 실행 서비스 | 대상·변경 전후·근거·승인·만료·idempotency key·감사 기록 |

Hybrid RAG 두 소스는 이미 chunking되어 있으므로 초기에는 ingest/chunk 재구축을 하지 않는다. 기존 query API와 인덱스 버전·ACL·BM25 점수·vector metric·top-k·fusion/rerank 계약을 확인한다. 서로 다른 점수를 무작정 더하지 않는다. PostgreSQL ts_rank를 BM25라고 표기하지 않는다. 사고문서 검색도 기존 인덱스가 있다면 재사용하며 ID/문서 버전 관계를 우선 검증한다.

## 3. 논리 데이터 계약과 물리 매핑

실제 DB를 변경하기 전에 읽기 Adapter와 mapping을 만든다. 아래 이름은 논리 이름이며 사내 물리 이름을 강제하지 않는다. 도시와 라인은 별개다. 라인 표시 예: `65L (ABCD)`; 저장/필터는 line_code와 line_alias를 별도로 매핑할 수 있다.

| 논리 필드 | 의미와 규칙 |
|---|---|
| incident_id / incident_number / title | 내부 안정키 / 사용자 사고번호 / 중복 가능한 사고명 |
| occurred_at / status / department | 발생 기준시각 / 상태 / 공식 부서 코드 |
| city / line_code / line_alias | 위치인 도시 / 라인 코드 / 라인 별칭 |
| product_generations | 원본 배열. 예: `{D1a,D1z,D20,FET,V5,V6,V7,V8}`. JSON 출력은 문자열 배열 |
| incident_detail / analysis_detail | 현상·대상·기간·영향 범위 / 비교군·관측·반증·분석 한계 |
| confirmed_cause / cause_status | 확인 원인과 미확정 가설 구분, null은 미확정 가능 |
| affected_lot_count / affected_wafer_count | 단위가 고정된 영향 수량. 실제 Lot 목록 건수와 교차검증 |
| fab_out_failure_codes | FAB Out 시 판정된 불량 코드. 물리 컬럼이 단일/배열/별도 행인지 설정으로 확인 |
| containment / corrective_action | 봉쇄·영향 확산 방지 / 원인 시정 조치 |
| verification / prevention / remaining | 효과 검증 / 재발 방지 / 잔여 불확실성 |

`lot_list`는 별도 테이블이며 사고와 Lot의 관계를 표현한다. 물리 PK인지 사고번호인지 설정으로 선언하고, 동일 Lot가 여러 사고에 속하면 각 관계를 보존한다. 사고명 Join은 기본값으로 사용하지 않는다. Lot ID가 사이트별로 재사용되면 site/line 등 복합 고유키를 정의한다. 여러 세대 배열만으로 각 Lot의 세대를 추정하지 않는다.

사고문서 table은 incident_id 또는 검증된 incident_number, document_id, title, storage_ref, version, approval, ACL, chunk_index_ref를 매핑한다. 사고명만 있으면 도시·라인·발생시점으로 후보를 검증하고 연결 신뢰도를 표시한다. PPT/PDF가 같은 문서 버전이면 같은 근거로 취급한다. 이미지 메타데이터에는 image_id, incident/Lot/Wafer 키, FAB/EDS stage, 좌표계, 촬영시각, 공정/설비, object_key, model version, ACL을 둔다.

## 4. 동의어와 스키마 사전

`PHOTO`, `photo`, `Photo`는 Unicode/공백 정리와 대소문자 정규화 후 공식값 PHOTO로 맞춘다. `포토`와 `p기술팀`은 사람이 승인한 부서 alias 사전으로 연결한다. 도시/라인/조직 개편 기간에 따라 뜻이 달라질 수 있어 scope와 유효기간을 둔다. `노광`은 공정명 EXPOSURE일 수 있으므로 항상 부서 PHOTO로 바꾸지 않는다. 문맥상 부서 의미가 확인되거나 해당 alias가 승인된 경우만 부서 필터로 사용한다. 오타의 fuzzy 후보는 제안값이며 모호하면 확인한다.

컬럼 설명은 미리 작성한다. 논리 의미·물리명·type·단위·null 의미·grain·Join 관계·허용 연산·예제·민감도·갱신주기·소유자를 포함한다. DB distinct 값은 허용 범위와 사전 후보를 파악하는 프로파일링 자료이며 의미 정의를 대신하지 않는다. 큰 고유값 컬럼은 상위값/분포와 제한된 샘플만 수집하고 제품 배열은 원소를 펼쳐 프로파일링한다. 원시 Lot ID·비밀정보를 프롬프트 사전에 쌓지 않는다. 신규값/스키마 drift는 검출→담당자 검토→버전 승격 순서로 반영한다.

## 5. 통계 처리

통계는 별도 `aggregate_incidents` Tool을 사용하되 같은 사고 DB와 필터/권한 검사를 공유한다. RAG chunk 빈도로 사고 건수를 계산하지 않는다. LLM은 metric, group_by, time_range, filters를 선언하고 Adapter가 허용된 템플릿·바인딩으로 계산한다. 검색 top-k 결과만으로 전체 통계를 만들지 않는다.

- 사고 건수: `COUNT(DISTINCT incident_id)`. 조회 표본과 전체 모집단을 분리한다.
- 세대별 사고: 배열 원소를 펼치고 `(incident_id, generation)`을 중복 제거한다. 한 사고가 여러 세대에 속하므로 세대별 합계가 고유 사고 수보다 클 수 있다.
- 세대별 Wafer/불량률: 세대별 실제 수량/분모가 없으면 계산 불가다. 사고 전체 수량을 각 세대에 복사하거나 균등 배분하지 않는다.
- Lot 통계: 사고-Lot 관계 건수와 고유 Lot 수를 별도 표기한다. 다대다 Join 후 SUM으로 사고 수량이 부풀지 않도록 먼저 사고 grain에서 집계한다.
- FAB Out: 분류별 포함 사고 집계인지 상호 배타적인 최종판정인지 명시한다. null/빈배열/미등록은 정상으로 간주하지 않는다.
- 기간: 발생일/등록일/종결일 중 어떤 기준인지 명시하고 사내 timezone과 반개구간 `[from,to)`를 사용한다. 0건과 조회 실패를 구분한다.
- 결과에 단위, distinct 규칙, 기준시각, 필터, missing 수, 제한사항, drill-down scope를 반환한다. 표와 차트는 동일 결과를 사용한다.

기존 컬럼이 PostgreSQL text[]인 경우 예시는 `:generation = ANY(product_generations)`와 `CROSS JOIN LATERAL unnest(product_generations)`이다. 실제 DB 종류/배열 타입/driver 바인딩 확인 후 구현한다. 문자열에 LIKE 검색하거나 쉼표로 나누는 방식으로 배열을 흉내 내지 않는다. 이 저장소의 array_demo는 SQLite JSON 배열로 의미를 검증하는 독립 예제다.

## 6. 구체적인 조사 예시

질문: “화성 65L 포토 사고 중 D1a 관련 사고를 찾아 원인과 조치, 사고 랏과 FAB/EDS 이미지도 보여줘.”

1. terminology Skill/사전에서 도시 화성, line_code 65L, 부서 PHOTO, 세대 D1a의 정확 원소 조건을 만든다.
2. 사고 DB를 조회한다. 합성 사례 INC-001의 외곽 Shot EDS Fail, 분석/시정/검증, scope를 확보한다. “유사 패턴”과 “확인 원인”을 구분한다.
3. Lot Tool이 해당 scope의 내부키로 별도 lot_list를 조회한다. 첫 페이지 3개와 다음 페이지 3개를 가져와 고유 Lot 6개, 등록 건수와 일치 여부를 확인한다.
4. 사고문서 table에서 연결 문서를 찾고 질문에 맞는 분석·조치 chunk를 검색한다. BKM 비교가 필요하면 사내문서/Eng’r Inform Note의 기존 Hybrid RAG를 추가 조회한다.
5. 이미지 Tool에서 사고/Lot/단계 메타데이터로 FAB와 EDS 이미지를 조회한다. 같은 Wafer·좌표 대응 여부를 표시한다. 유사도만으로 원인을 확정하지 않는다.
6. 코드가 ID/수량/출처를 검사하고 Judge가 질문에 필요한 근거의 충분성을 검토한다. 부족하면 Router로 재조회하고, 통과하면 Answer가 DB 사실, 문서 근거, 이미지 관측과 한계를 담은 최종 답변을 작성한다.

후속 “세대별 몇 건?”은 기존 조건을 재사용하되 전체 집계 Tool을 호출한다. “그 사고 랏도”는 대화의 선택 scope를 사용한다. 여러 사고가 선택되었거나 scope가 만료되면 범위를 확인/재조회한다. 새 조건을 기존 scope에 조용히 섞지 않는다.

## 7. 화면과 운영 UX

디자인은 조사 워크스페이스다. 좌측은 조사 목록/탐색, 중앙은 Chat과 결과, 우측은 선택 사고 및 근거 패널로 구성한다. 도시와 라인, 부서, 제품세대, 기간 필터를 별도 표시한다. 사용자가 정규화된 PHOTO 필터를 확인·수정할 수 있다.

사고/통계/문서 탭, 사고 상세의 현상·분석·조치·검증, Lot 목록의 페이지·총건수·내보내기 범위, FAB/EDS 비교, 문서 페이지/슬라이드 근거를 제공한다. 조회중/부분결과/권한제한/미등록/실패를 다른 상태로 표시한다. 처리 흐름에는 “사고 DB 조회 완료, Lot 조회 6건” 같은 관측만 보여준다. 조치 UI는 대상·변경·근거·예상영향·승인/실행 상태를 구분한다.

현재 design/workspace-preview.html은 정적 합성 데이터 기반 시안이다. API 연결, 접근성·반응형·브라우저 검증 및 운영 인증은 후속 구현 대상이다.

## 8. 단계별 구현과 통과 조건

| 단계 | 작업·산출물 | 통과 조건 |
|---|---|---|
| 0. 자산 확인 | 보존 문서, 물리 스키마, 권한, 기존 RAG API, 승인 담당자 목록 | GPU/자원 원본 해시 동일; DB/RAG 실제 계약 확인 |
| 1. 정형 조회 | semantic catalog, alias, mapping, 사고 검색/집계/Lot Adapter | 키/컬럼 전면 변경 테스트, 배열·중복·페이지·null·권한 평가 통과 |
| 2. 제어 계층 | Router 계획 schema, 상태 저장, 우선 조회 Gate, Tool budget | 사고 우선 조회 우회·scope 사용자 혼용·무제한 재시도 차단 |
| 3. 근거 연결 | 사고문서, 두 기존 Hybrid RAG, provenance/ACL | ID/버전/페이지 추적, 무권한 chunk 배제, DB-문서 충돌 표시 |
| 4. 멀티모달 | 이미지/Trend Tool Adapter, Storage 링크, 정상/불량 비교 | Wafer/좌표·시각 정합성, 사내 검증셋의 탐지/오탐 목표 충족 |
| 5. 답변·UI | Judge/Answer, 코드 gate, 조사 workspace와 통계 drill-down | 질문-근거 회귀 평가, 누락/불확실성 표시, 브라우저/권한 테스트 |
| 6. 제한 배포 | 관측/감사, 성능·부하, 운영 runbook, 읽기 pilot | 대상 사용자의 승인된 평가 기준과 실제 GPU/자원 부하 확인 |
| 7. 조치 확장 | 제안→승인→재검증→실행→확인, rollback/idempotency | 승인 만료·중복 실행·상태 변경·부분 실패 시나리오 통과 |

일정은 인력·접속 승인·기존 API 상태 확인 후 산정한다. GPU 리소스 문서의 신청/발급/가용 상태는 서로 구분해 운영 담당자와 확인하며 현재 문서의 수치를 임의 변경하지 않는다.

평가셋은 실제 사내 정답을 승인된 환경에서 준비한다. 부서 동의어/오타, 세대 배열, 집계 분모, FAB Out 미등록, 사고명 중복, Lot 중복/누락, 문서 버전 충돌, 권한 거부, 이미지 오탐, Trend 결측·시간대, 조치 재실행을 포함한다. 정확도·근거 적합성·필터 정합성·무근거 주장·오탐/미탐·latency·자원 사용을 별도로 측정한다. 배포 수치 목표는 기준선 평가 후 합의한다.

상세 단계, Judge 복귀 조건, 통계/문서/목록 계약과 구현 순서는 [DETAILED_REQUEST_FLOW.md](DETAILED_REQUEST_FLOW.md)를 따른다. 사용자와 확인한 세로 배치를 유지하도록 주 흐름은 표로 표시한다.
