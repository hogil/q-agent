# 기능 참조

기준: 2026-11-02. 이 문서는 `app/agent.py`, `app/incident_tools.py`, `app/platform_tools.py`, `app/image_tools.py`, `app/meeting_tools.py`, `app/enterprise_tools.py`, `app/mes_reference_contract.py`, Router Tool catalog 및 `config/config.yaml`의 현재 계약을 요약한다. 구현 경로의 존재, 합성 데이터 실행, 사내 연결 검증을 서로 다른 상태로 표시한다. 기본 설정은 demo이며 text/image/trend 모델, 내부문서·Eng’r Inform callback, 회의록, MES 기준정보, enterprise source, FBM 검색, action planner는 대체로 비활성이다.

## 상태 읽기

| 상태 | 의미 |
|---|---|
| 코드 경로 | Q-Agent 본체에 Tool/adapter 호출 경로가 있다. 설정에 따라 비활성일 수 있다. |
| 합성 전용/합성 확인 | 로컬 fixture 또는 synthetic SQLite에서 제한된 계약을 확인한다. 사내 값·성능·ACL의 확인을 뜻하지 않는다. |
| callback 계약 | 신뢰된 호출자가 callback을 주입하면 실행할 수 있는 인터페이스가 있다. 기본 CLI가 실제 site RAG를 연결하지 않는다. |
| 미구현/미연결 | 전용 Tool, adapter 또는 검증된 운영 연결이 없다. 비슷한 Tool의 원자료 출력만으로 기능이 구현됐다고 간주하지 않는다. |

## Tool 카탈로그

사고 요청의 최초 업무 조회는 코드가 `find_incidents` 또는 `summarize_incidents`로 제한한다. Router 지침만으로 강제하는 것이 아니다. 선택 전의 후속 조회는 실행되지 않으며, 복수 사고 후보는 명시 선택이 필요하다.

| Tool | 목적, 입력 및 범위 | 출력과 제한 | 활성화 조건 및 구현 상태 |
|---|---|---|---|
| `match_incident_values` | 사고 질문의 도시·부서·라인·세대·불량코드 등 정형 값 후보를 찾는다. 질문은 자연어이며 설정된 필드에서만 매칭한다. | 후보/매칭 상태를 반환한다. 전체 distinct 값 목록을 모델에 주지 않는다. 권한/ACL 기능이 아니다. | `value_matching.enabled`, 필드 허용목록 및 read-only incident DB 필요. 코드 경로 있음. |
| `find_incidents` | 사고번호, 제목 exact/contains, 도시, 라인 및 논리 필터로 사고를 검색한다. cohort 조회도 필터에 한정된다. | 후보 사고와 scope 발급 근거를 반환한다. 다중 후보를 자동 확정하지 않는다. | Router catalog 활성. 실제 runtime은 read-only SQLite/demo adapter 기준이며 사내 DB driver 및 ACL은 별도 미구현/미검증. |
| `summarize_incidents` | 필수 filters, 선택 group_by(최대 3개), 비교 기간, top_k로 사고 테이블을 SQL 집계한다. 그룹 예: 부문·도시·라인·제품세대·FAB OUT 불량코드. | 전체 조건 집계 수와 표시용 상위 그룹을 반환한다. 제품세대 배열은 세대를 펼친 뒤 distinct 사고를 세므로 세대별 합계가 고유 사고 수보다 클 수 있다. | 기본 catalog 활성, read-only DB 및 유효한 논리 매핑 필요. site SQL adapter/운영 DB 연결은 확인되지 않음. |
| `list_incident_lots` | 선택된 scope의 Lot membership을 `page_size`, `offset`으로 페이지 조회한다. | Lot, 상태, total/next offset 및 coverage/completeness metadata. 페이지 chain 완료는 source completeness 증명이 아니다. | 선택된 사고와 DB adapter가 필요. 합성/demo 경로 구현. |
| `list_incident_wafers` | 선택 scope의 Wafer를 페이지 조회하고 필요 시 `lot_ids`로 좁힌다. runtime이 Lot membership과 교차 검증한다. | 사고-Lot-Wafer 관계와 `wafer_scope`, completeness를 반환한다. `lot_inventory`를 사고 영향 Wafer로 간주하지 않는다. | 사고 scope 및 Lot 조회 완료 필요. 합성/demo adapter 구현; 실제 영향관계 mapping 미확인. |
| `get_platform_evidence` | 이미 확정한 사고 scope에 대해 선택한 합성 source(`mes`, `test`, `measure`, `failbit`, `sem`, `trend`, `inform`)와 제한된 행/Measure feature를 조회한다. `actor`, scope, incident IDs, as_of는 코드가 바인딩한다. | 범위가 제한된 source 행과 시간·출처 정보. 원인 확정이나 DB snapshot이 아니다. | config `platform.enabled` 및 source 데이터 필요. code/demo 경로 있음. MES DOWN/상태, Measure, Trend, Inform은 synthetic evidence 예시일 수 있음. |
| `search_platform_history` | 정확히 한 건 선택 사고의 합성 platform 과거 참조를 top-k 조회한다. | historical candidate이며 현재 영향범위가 아니다. 유사도는 원인 확률이 아니다. | platform/history 설정 및 선택 사고 필요. 합성 전용 경로. |
| `search_related_incidents` | 선택 사고 기준 검색어 1~6개로 관련 사고 후보를 조회한다. | 과거 후보 및 출처 메타데이터. 현재 사고로 자동 귀속하지 않는다. | 사고 scope, related-search 설정/DB 필요. 후보 retrieval 코드 있음, site 데이터 미검증. |
| `search_meeting_minutes` | `query`, 선택 `top_k`로 회의록 기존 chunk를 검색한다. independent 범위에서도 허용되는 문서 Tool이다. | 회의일/version/chunk/locator/가용시점과 검색 상태. 0건은 전체 자료 부재를 뜻하지 않는다. | `meetings.enabled`와 SQLite FTS5 또는 설정된 service가 필요. 기본 false; local lexical demo 경로와 remote 계약 존재, site 연결 미확인. |
| `search_engineer_notes` | `query`, `top_k`로 기존 Eng’r Inform Note/엔지니어 노트 검색 callback을 호출한다. 선택 사고의 현재/역사 scope 및 cutoff는 Orchestrator가 전달한다. | 기존 chunk의 문서/버전/locator/available_at 등 evidence. 후보는 원인/적용 확정이 아니다. | retrieval source enabled, 유효한 status allowlist, caller 주입 `document_query` callable 모두 필요. 기존 Hybrid BM25+vector chunk 연결을 전제하는 callback 계약; 기본 CLI는 callback을 주입하지 않음. |
| `search_internal_documents` | 내부문서의 기존 chunk를 `query`, `top_k`로 검색한다. PDF/PPTX/DOCX 등의 문서에서 OCR/수집된 기존 chunk도 이 검색 계약에 해당한다. | 문서 ID/version/chunk/locator/available_at 및 scope relation. 검색 후보 수나 `truncated=false`도 전체 저장소 전수검색을 보증하지 않는다. | internal retrieval enabled + status allowlist + trusted `document_query` 필요. 기존 BM25+vector 검색 재사용 계약. 사내 연결/ACL, 저장소 완전성은 미확인. |
| `search_mes_reference` | 사고 scope 확인 후 허용된 `kind`와 `query`, 선택 `top_k` 및 설정 허용 논리 키에 대한 exact filters로 기준정보를 찾는다. scope/actor/as_of는 코드 바인딩. | `available_at`, effective window, applicability, `scope_relation`, truncation을 보존한다. `catalog_candidate`는 사고 적용 근거가 아니며 시간상 active만으로 적용을 확정하지 않는다. | `mes_reference.enabled`, allowed kind, 유효한 callback 필요. Workbench/CLI는 synthetic SQLite reader를 자동 구성할 수 있으나 합성 전용. 사내 MES adapter·ACL 미구현/미검증. |
| `list_comparison_assets` | 현재 Item과 `sem` 또는 `overlay` modality에 대한 비교 자산 목록 조회. | asset ID/revision/시점/범위와 사용 가능한 자산. 자산 목록만으로 비교 분석이 아니다. | 각 image_tools modality 설정과 image registry 필요. local/demo 경로 구현, specialist endpoint 기본 disabled. |
| `compare_sem_images` | 같은 Item의 명시 asset ID를 SEM 비교 service에 전달한다. | 모델/버전/관측 결과/findings와 정렬·비교 제한. 좌표 미확인 또는 `INCOMPARABLE`은 통과가 아니다. | SEM service 활성 및 callable endpoint, 등록 자산 필요. 코드 계약/로컬 합성 확인; 운영 모델·서비스는 기본 disabled. |
| `compare_overlay_maps` | 같은 Item의 명시 asset ID를 Overlay 비교 service에 전달한다. | 중첩/차이 관측 및 alignment 제한. 통계 시각화는 모델 추론과 다르다. | Overlay service 활성 및 callable endpoint 필요. 운영 서비스 기본 disabled. |
| `plan_synthetic_action_evidence` | 사용자가 명시적으로 판단 보조를 요청했을 때, 선택 사고 및 완전한 영향 Wafer scope의 synthetic snapshot에 대해 가설/검사 추천을 구성한다. Tool 인자는 없고 trusted callback/lease가 입력 범위를 공급한다. | 합성 hypothesis/검사 추천. HOLD/RELEASE 실행, 생산 ACL, 실제 검사 권한 또는 인과 증명이 아니다. | 기본 false. 설정 외에도 snapshot lease/provider 등 trusted runtime 연결과 완전성 gate가 필요. 본체 실행 경로는 조건부이며 생산 action executor는 없음. |

`search_similar_fbm`은 Router catalog에 `enabled:false`로만 정의된 callback 계약이다. 현재 사고 → Lot → Wafer page chain이 끝난 뒤 요청 representation(`raw_fbm` 또는 `object_id_yield_fbm`) 하나씩 조회하도록 설계됐다. `fbm_search.enabled`와 trusted callback이 모두 필요하나 기본 Workbench/CLI의 실제 연결은 확인되지 않았다. 실제 encoder, index/storage, lineage, ACL 및 검색 품질을 확인하지 않았으므로 production FBM 검색 기능으로 취급하지 않는다.

`get_engineering_snapshot`은 Router catalog에서 `enabled:true`인 후속 Tool이지만, `app/agent.py`가 runtime에서 `callable(engineering_query)`일 때만 usable로 광고한다. Workbench가 callback을 enterprise source 경로에서 구성해 주입해야 하며, callback이 없으면 Tool은 unavailable 상태다. callback 결과도 선택 incident IDs와 `as_of` scope 검증을 통과해야 한다. 이 경로는 임의 설비/Trend SQL 기능이나 모든 step genealogy 전수조회 보증이 아니다.

## 주요 업무 영역의 경계

### 문서, Eng’r Inform, OCR

Q-Agent 문서 Tool은 자체 OCR을 실행하는 Tool이 아니라 **기존 Hybrid RAG chunk에 검색을 요청하는 callback**이다. 기존 chunk의 출처·문서/버전·페이지 또는 슬라이드 locator·가용시점을 이어받아야 한다. 이미지에서 OCR을 새로 수행하는 ingestion이나 검색 인덱스 구축이 online `search_internal_documents`에 포함된다고 보장하지 않는다. 검색 결과는 후보이며 문서 사용자별 ACL은 Q-Agent에서 별도 검증하지 않는다. `truncated`/completeness unknown/0건은 검색 범위 한계를 보존한다.

`get_platform_evidence`의 `inform` source 또는 MES 기준정보 후보는 실제 Eng’r Inform 문서 검색을 대체하지 않는다. 기존 BM25+vector chunk/source 연결은 callback과 site 검증이 필요하다.

### FBM 유사 검색

두 representation은 별도 검색과 별도 결과다. 점수끼리 비교/평균하지 않는다. 동일 query asset/revision self-match 제외 계약 및 응답 metadata 검증은 callback 데이터의 provenance를 증명하지 않는다. 과거 후보는 현재 사고/영향 Wafer/원인으로 승격되지 않으며 similarity는 원인 확률이나 정상 보증이 아니다. 현재 실제 storage·encoder 연결은 미확인이다.

### MES 및 설비 기준정보

`get_platform_evidence`는 사고 scope에서 synthetic MES/equipment event 행을 제공할 수 있다. `search_mes_reference`는 설정된 합성 또는 주입 callback 기준정보 검색이다. 시간상 유효성, scope relation, applicability는 별도이며 adapter가 주장한 범위다. 현재 Tool에 모든 step genealogy 전수조회, FDC, 검증된 critical-equipment 조합, site authoritative equipment code dictionary가 연결된 것으로 해석하지 않는다. 실제 MES/enterprise source·ACL·mapping의 의미는 미검증이다.

### 모델과 action

text 모델과 image specialist service는 base config에서 비활성이다. Known CNN 추론, unknown embedding/clustering, 독립 13-point METRO 분석, 전용 FDC는 현재 Tool catalog에서 확인되지 않는다. Tool wiring, synthetic fixture 또는 별도 model-lab 결과를 본체의 live LLM/model 연결로 보지 않는다. 생산 HOLD/dispatch block/metrology/RELEASE 실행 Tool은 없다.

## 실행 순서와 scope 보장

| 순서 | 주체 | 책임 |
|---:|---|---|
| 1 | 사용자 질문 | 요청 범위와 기준시점을 제공 |
| 2 | Router | 논리 조건과 필요한 업무 Tool을 계획. 최초 사고 업무 조회는 사고 DB Tool만 허용 |
| 3 | 사고 DB | 사고 후보/집계 조회. 후보 선택과 scope 발급은 runtime 코드에서 검증 |
| 4 | 후속 Tool | 확정 scope에 필요한 Lot/Wafer, platform, 이미지, 문서, MES reference 조회 |
| 5 | Judge | 요구사항별 evidence ID, 범위, 시간, 누락/충돌을 검토 |
| 6 | 재조회 | `need_evidence`/`revise`이면 같은 Router로 돌아가고 활성 Tool/예산 내 재조회 |
| 7 | Answer | Judge가 `answer`로 돌려보낸 뒤 마지막 LLM이 확인된 주장과 제한을 작성 |
| 8 | 최종 표시 | 코드가 선택 사고, 조회 상태 및 범위 상태를 구조화해 답에 연결 |

independent 요청은 사고 DB 우선 규칙의 예외이며 독립 자료 검색으로 분류된 경우에만 사용한다. 사고 사실을 다루는 요청은 incident 조회로 scope를 검증한다. `actor`는 로컬 호출자 식별 문자열이며 인증/ACL이 아니다. scope 검증과 사용자별 권한 관리는 별개다. Judge는 코드 metadata·계약 검토와 LLM 근거 판단이 서로 다른 계층이며, 둘 다 causal truth나 생산 승인 권한을 부여하지 않는다.

## 참조 자료

- [상세 요청 흐름](DETAILED_REQUEST_FLOW.md)
- [현재 Tool 실행 구조](TOOL_ORCHESTRATION_CURRENT.md)
- [현재 기능 coverage와 2026-10-30 runtime 보완](TOOL_CAPABILITY_COVERAGE.md)
- [통합 모델 분석 런타임의 합성/LLM 경계](UNIFIED_RUNTIME_CURRENT.md)
- [문서·설비 runtime 제한](DOCUMENT_AND_EQUIPMENT_RUNTIME_20261029_ROOT_v1.md)
- [MES 기준정보 runtime](MES_REFERENCE_RUNTIME_20261029_ROOT_v1.md)
- [FBM Tool integration](FBM_SEARCH_TOOL_INTEGRATION_20261030.md)
