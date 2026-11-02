# Q-Agent

Q-Agent은 반도체 품질 사고를 조사하는 bounded Agent와 합성 데이터 분석 Workbench를 포함합니다. 사고 관련 요청은 사고 DB를 먼저 조회하고, 코드가 발급·검증한 사고 scope 안에서 후속 Tool을 실행합니다. Workbench의 공개 데모 데이터와 연구용 산출물은 합성 데이터이며 실제 사내 품질 판정이나 생산 조치를 뜻하지 않습니다.

## 현재 구성

| 구성 | 용도 | 현재 경계 |
|---|---|---|
| Agent CLI | Router, 사고/후속 Tool, Judge, Answer 실행 | 기본 설정의 LLM과 사내 source는 비활성. 실행에는 명시적 demo 또는 site 설정이 필요 |
| Workbench UI | 합성 사례 조회, 저장 분석·대화, 모델 분석 화면 | `config/workbench.yaml`이 별도로 지정하는 화면/데이터 경로. CLI의 site 설정을 대신하지 않음 |
| 플랫폼·모델 lab | 합성 공정·계측·이미지·Trend cohort 분석 및 research worker bridge | 별도 `q-agent-models` 환경의 worker/데이터와 연결되며 app의 생산 adapter 또는 live LLM이 아님 |
| OCR·FBM 검색 연구 | 합성 OCR retrieval, FBM 표현 retrieval, callback 계약 연구 | 합성 smoke와 설계 수준. 사내 RAG/ACL, 실물 FBM source·검색 연결은 확인되지 않음 |

## Agent 흐름과 scope

사고 관련 질문에서 Orchestrator가 사고 DB 우선 조회와 scope 검증을 강제합니다. 프롬프트는 권한 경계가 아닙니다.

| 순서 | 단계 | 동작 |
|---:|---|---|
| 1 | Router | 질문에 맞는 단일 조회 계획과 등록 topic을 선택 |
| 2 | 사고 DB | 우선 검색·집계. 모호한 복수 사고는 자동 선택하지 않고 선택을 요구 |
| 3 | 후속 Tool | 검증된 scope 안에서 Lot을 조회하고, 필요할 때 해당 Lot의 Wafer를 조회하거나 사용 가능한 문서·회의록·이미지·Trend·MES reference Tool을 호출 |
| 4 | Judge | evidence ID, 조회 범위, 시점과 요청 충족 여부를 검토. 근거가 부족하면 같은 Router로 재조회 |
| 5 | Answer | Judge 승인 뒤 마지막 역할 호출로 근거, 한계와 조회 상태를 답변 |

| 규칙 | 처리 |
|---|---|
| Judge의 `need_evidence` 또는 `revise` | 같은 Router로 반환. revise는 기존 scope와 evidence를 무효화하고 재조회 요구 |
| 독립 요청 | 신뢰 경계에서 `request_scope=independent`로 지정한 경우 사고 DB를 열지 않음. 자연어 자동 분류 정확도는 검증되지 않음 |
| 복수 사고 후보 | 사용자 선택 전 Lot/Wafer 상세 조회를 차단 |
| Wafer 조회 | 선택한 사고와 Lot 범위를 함께 확인. `lot_inventory`는 사고 영향 Wafer라는 증거가 아니며 미확인 completeness는 unknown으로 유지 |
| 기존 답변 | 조회 evidence로 재사용하지 않음. 현재 실행에서 등록된 evidence만 검토 |

사고 통계는 제품 세대 배열을 펼친 뒤 distinct 사고 수를 계산합니다. 통계를 세대별로 균등 분할하지 않습니다. 실제 DB에서 이 의미와 mapping이 맞는지는 site 자료로 확인해야 합니다.

## Tool과 연결 상태

Router Tool catalog는 [tools.json](app/skills/roles/router/references/tools.json)에 있습니다. 등록 상태는 호출 가능 계약을 뜻하며, 각 source가 기본 환경에서 연결·활성화되어 있다는 뜻은 아닙니다.

| 영역 | 등록 Tool | 현재 구현·연결 경계 |
|---|---|---|
| 사고 DB | `match_incident_values`, `find_incidents`, `summarize_incidents` | 설정 mapping을 사용하는 읽기 전용 SQLite Adapter 경로. 비 SQLite 사고 DB는 별도 Adapter 필요 |
| 사고 scope | `list_incident_lots`, `list_incident_wafers` | 사고 scope와 Lot 관계를 검사. Wafer source completeness 기본값은 unknown |
| 문서·회의 | `search_engineer_notes`, `search_internal_documents`, `search_meeting_minutes`, `search_related_incidents` | 문서 Tool은 주입형 callback 계약과 evidence 검증이 있음. 기본 설정은 꺼져 있고 site Hybrid RAG callback/ACL은 확인되지 않음. Eng’r Inform과 문서는 기존 BM25+vector Hybrid RAG 및 기존 chunk를 연결 대상으로 함 |
| MES·Engineering | `get_engineering_snapshot`, `search_mes_reference` | Engineering snapshot과 합성 SQLite MES reference 경로가 있음. 실제 사내 MES 연결은 아님 |
| 플랫폼 합성 자료 | `get_platform_evidence`, `search_platform_history` | Workbench 플랫폼 overlay가 활성화한 합성 데모 경로. 128-feature wide 데이터의 126개 채널은 더미이며 실측 feature coverage가 아님 |
| 이미지 비교 | `list_comparison_assets`, `compare_sem_images`, `compare_overlay_maps` | metadata 및 callback/service 경계가 있음. specialist endpoint 기본 비활성. 이미지 비교를 실제 이미지 이해 모델이나 인과 증거로 해석하지 않음 |
| FBM 유사 검색 | `search_similar_fbm` | 명시적 callback이 필요한 후속 retrieval. 기본 비활성·callback 미연결. synthetic catalog 연구는 운영 gallery/ACL/실물 연결 증거가 아님 |
| 생산 조치 | `plan_synthetic_action_evidence` | catalog에는 비활성 상태로 등록. 실제 생산 HOLD/RELEASE 실행 권한·Adapter는 제공하지 않음 |

설정이 존재하는 것과 Adapter가 실제 source에 연결된 것은 구분됩니다. 기본 `config/config.yaml`은 사고 DB를 SQLite로 지정하고, Router/Judge/Answer 모델·문서 검색·FBM 검색·조치 관련 서비스는 비활성입니다. `actor` 값도 사용자 식별용 문자열일 뿐 인증이나 ACL이 아닙니다.

## 문서 OCR 및 FBM 연구 경계

문서 callback 계약은 scope, source kind, status, `as_of`, locator와 completeness metadata를 검사할 수 있습니다. OCR marker 및 파생 시점 계약도 있으나 기본 retrieval source는 꺼져 있고, 실제 OCR engine·사내 원문·ACL·Hybrid RAG 서비스는 연결 검증되지 않았습니다. 2026-10-30 OCR retrieval 결과는 작은 합성 fixture의 탐색 결과입니다. 이미지 OCR 내용, image embedding, 원문 ACL을 검증한 것으로 볼 수 없습니다.

`search_similar_fbm`은 사고 DB 및 사고/Lot/Wafer scope 확인 뒤 실행되는 후속 Tool입니다. raw FBM과 `object_id_yield_fbm`은 별도 표현으로 취급하며 결과를 서로 대체하거나 점수를 섞지 않습니다. 2026-10-30 표현 비교는 소규모 합성 wafer 자료에 대한 연구 관측입니다. 실측 FBM, object ID/yield의 실제 의미, 운영 gallery, source ranking, 물리적 lineage와 ACL은 미확인입니다.

관련 설계와 연구 기록은 [문서/OCR/FBM retrieval 설계](docs/current/DOCUMENT_IMAGE_AND_FBM_RETRIEVAL_DESIGN_20261030_ROOT_v1.md), [문서 retrieval completeness](docs/current/DOCUMENT_RETRIEVAL_COMPLETENESS_20261030_ROOT_v1.md), [OCR content kind 정책](docs/current/OCR_CONTENT_KIND_SOURCE_POLICY_20261030.md), [FBM Tool 연결 계약](docs/current/FBM_SEARCH_TOOL_INTEGRATION_20261030.md), [합성 OCR·FBM 연구 결과](docs/current/OCR_FBM_RETRIEVAL_RESEARCH_20261030.md)를 참고하세요.

## Workbench와 합성 플랫폼

Workbench는 저장된 합성 분석 결과와 대화 기능을 제공합니다. `config/workbench.yaml`에서 raw/scenario 데이터, conversation SQLite, static build 경로와 포트를 설정합니다. 화면을 시작한다고 실제 사내 DB나 Agent LLM이 연결되는 것은 아닙니다.

`config/platform-demo.yaml`은 플랫폼 데모 overlay 예시입니다. 문서화된 확장 fixture에는 사고·MES·Failbit·SEM·전기 측정·Trend·Inform 자료가 포함되며, 생성 데이터와 고정된 모델 산출물은 생산 측정이 아닙니다. 모델 분석 화면은 별도 `q-agent-models` persistent worker를 사용할 수 있습니다. 해당 runtime은 합성 cohort를 대상으로 하며 서비스 LLM 호출 또는 실 FAB 조치로 표시하지 않습니다. 상세 범위와 실행 근거는 [통합 플랫폼](docs/current/ALL_IN_ONE_PLATFORM.md), [플랫폼 refresh](docs/current/PLATFORM_REFRESH_CURRENT.md), [통합 모델 분석 runtime](docs/current/UNIFIED_RUNTIME_CURRENT.md)를 확인하세요.

## 설치 및 실행

Python 3.11 이상을 준비합니다. UI 빌드에는 Node.js 22 이상이 필요합니다.

```powershell
python -m pip install -r requirements.txt
npm.cmd --prefix web ci
npm.cmd --prefix web run build
python app/workbench.py --port 8787
```

브라우저에서 `http://127.0.0.1:8787/`을 엽니다. 실제 기본 port는 `config/workbench.yaml`에서 확인하고, 이미 사용 중이면 다른 포트를 지정합니다. 공개 localhost 데모용입니다. 별도 플랫폼 runtime과 모델 분석 worker를 실행하는 방법은 [통합 모델 분석 runtime](docs/current/UNIFIED_RUNTIME_CURRENT.md)의 절차를 따릅니다.

## 설정 확인과 CLI

배포 설정의 기준점은 `config/config.yaml`과 명시적인 site overlay입니다. 사내 설정은 Git 제외 대상인 `config/site.local.yaml` 등에 둡니다. `config/site.example.yaml`은 예시이며 실 DB 매핑, 연결 또는 권한을 보증하지 않습니다.

```powershell
# 기본 설정 구조 확인 (네트워크 연결이나 비밀정보 조회 없음)
python app/config_loader.py --config config/config.yaml

# demo 환경에서 config와 세 역할의 Skill/lock 검사
python app/run_agent.py --demo --mode check

# Router Skill 조립 결과 출력
python app/run_agent.py --demo --mode prompt --role router --topics incident_search
```

명시적으로 사내 설정을 지정한 check/prompt 예시는 다음과 같습니다.

```powershell
python app/run_agent.py --site-config config/site.local.yaml --mode check
python app/run_agent.py --site-config config/site.local.yaml --mode prompt --role router --topics incident_search
```

실제 질의는 아래처럼 `run` 모드로 실행합니다. API 모델, 환경변수와 읽기 전용 DB 연결이 먼저 준비되어 있어야 합니다.

```powershell
python app/run_agent.py --site-config config/site.local.yaml --mode run --request-scope incident --actor local-user --question "사고번호에 해당하는 Lot을 조회해"
```

복수 사고 후보는 결과의 선택 ID를 `--select-incident`로 명시합니다. `--trace`는 질의·내부 조회 자료를 포함할 수 있는 이벤트를 stderr에 남기므로 승인된 내부 환경에서만 사용합니다. 기본 check/prompt는 모델 API를 호출하지 않습니다. config check 성공은 설정 구조의 유효성만 뜻합니다.

```powershell
# 선택한 역할의 Skill 컴파일 검사
python app/skill_loader.py router --topics incident_search

# 사내 실행 wrapper (Linux/Windows)
& '.\scripts\run_onprem.ps1' --site-config 'config/site.local.yaml'
```

`app/run_agent.py`에는 demo 데이터 준비 및 제한된 retrieval evaluation/proposal/compare 모드도 존재합니다. 이 모드들은 별도 입력·출력 경로를 사용하는 연구/검증 CLI이며 기본 실행 확인으로 취급하지 않습니다. 포괄적인 Q-Agent 답변 정답 질문 세트는 복원되어 있지 않습니다. 사용자가 별도로 요청한 NL2SQL 합성 데이터 연구와 일반 Agent의 실제 LLM 답변 검증은 서로 다른 범위입니다.

## 개발 및 변경 경계

| 목적 | 진입점 |
|---|---|
| Agent Orchestration / CLI | [app/agent.py](app/agent.py), [app/run_agent.py](app/run_agent.py) |
| 사고 DB Runtime Adapter | [app/runtime_factory.py](app/runtime_factory.py), [app/incident_tools.py](app/incident_tools.py) |
| 설정과 site overlay | [config/config.yaml](config/config.yaml), [docs/current/CONFIGURATION.md](docs/current/CONFIGURATION.md) |
| Router/Answer/Judge 및 Schema Skill | [app/skills](app/skills), [app/skill_registry.json](app/skill_registry.json) |
| Workbench server/UI | [app/workbench.py](app/workbench.py), [web/src](web/src) |
| 현재 요청·scope 설계 | [요청별 사고 DB 필요성](docs/current/REQUEST_ROUTING.md), [Agent runtime](docs/current/AGENT_RUNTIME.md), [사고·Lot·Wafer](docs/current/INCIDENT_LOT_WAFER.md) |
| Adapter/Tool 연결 범위 | [설정](docs/current/CONFIGURATION.md), [Tool 연결 설계](docs/current/TOOL_ORCHESTRATION_CURRENT.md), [Tool capability 기록](docs/current/TOOL_CAPABILITY_COVERAGE.md) |
| 실행 가이드 | [사내 실행 방법](docs/current/ONPREM_RUN.md), [Workbench/플랫폼](docs/current/ALL_IN_ONE_PLATFORM.md) |
| 기능 카탈로그 | [기능 참조](docs/current/FUNCTION_REFERENCE.md): Tool별 구현 경로, 설정 상태와 검증 범위를 요약합니다. |
| 운영 점검 | [운영 및 로컬 검증](docs/current/OPERATIONS_AND_VALIDATION.md): 설정·Skill 검사와 합성 조회의 실행 절차 및 한계를 설명합니다. |
| 확장 개발 도구 | [현재 확장 목록](docs/current/EXTENSIONS_CURRENT.md) |

사내 테이블·컬럼·관계는 mapping과 source Adapter에서 연결합니다. 현재 사고 DB Adapter는 SQLite read-only 구현입니다. PostgreSQL/Oracle/SQL Server 설정값을 넣는 것만으로 동작하는 Adapter가 생기지 않습니다. 사내 site API, 실제 Hybrid RAG, OCR/FBM source, 운영 ACL, 생산계 조치, 이미지·Trend 모델을 구현·검증 완료로 간주하지 마세요. 비밀정보, 실제 Lot/이미지/문서, 로컬 `*.local.yaml`·`*.local.toml`, `var/` 데이터와 전체 결과는 Git에 올리지 않습니다.
