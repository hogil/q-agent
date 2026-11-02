# Q-Agent capability coverage for requested fab workflows

현재 연결·학습·실행 상태: [UNIFIED_RUNTIME_CURRENT.md](D:/project/q-agent/docs/current/UNIFIED_RUNTIME_CURRENT.md). 아래 감사 표는 구현 전 시점의 자료로 보존한다. 문서 검색 및 MES 기준정보 Tool의 후속 runtime 연결 상태는 아래 `2026-10-30 runtime 보완`을 참조한다.

후속 구현과 실제 실행은 [TOOL_ORCHESTRATION_CURRENT.md](TOOL_ORCHESTRATION_CURRENT.md)를 따른다. 아래 표는 구현 전 targeted audit 시점의 app/source 상태이며 새 lab graph를 app 배포 완료로 해석하지 않는다.

Checked: 2026-10-25 (Asia/Seoul), static targeted source/config inspection. Scope: current app Tool catalog, called adapters/functions, documented rule contracts and public base/demo config only. No local overlays, secrets, databases, endpoints, model/API calls or execution checks were read or used.

Status meanings: `connected_app_demo` means a callable app path exists for demo/synthetic operation; it does not mean site connectivity or production readiness. `lab_only` means development work outside the runtime catalog. `design_missing` means offline analysis exists but no Q-Agent runtime Tool was found. `design_missing` means no implemented app Tool/flow was found for the requested capability. `deferred` is an explicit hold. Configured flags are defaults/examples, not live service health.

| Requested category | Source / proven function | Actual app Tool name | Status | Next adapter/key / scope limit |
|---|---|---|---|---|
| 사고 검색 / 집계 | `incident_tools.py::find_incidents`, `summarize_incidents`; SQL scope and distinct aggregation. [tools.json:14](</D:/project/q-agent/app/skills/roles/router/references/tools.json:14>) | `find_incidents`, `summarize_incidents` | `connected_app_demo` | Site DB driver/column mapping + production ACL; current runtime factory is SQLite read-only. |
| scope: Lot / Wafer / Chip / 좌표 | `incident_tools.py::list_incident_lots/list_incident_wafers`; `platform_tools.py::evidence` joins incident/Lot/Wafer/Chip keys; map registry preserves coordinate spaces. [tools.json:294](</D:/project/q-agent/app/skills/roles/router/references/tools.json:294>) | `list_incident_lots`, `list_incident_wafers`, `get_platform_evidence` | `connected_app_demo` (bounded) | Site mapping for affected-wafer relation, Lot/Wafer/Chip keys and coordinate transforms; source completeness is `unknown`, and there is no standalone arbitrary chip-coordinate lookup Tool. |
| 모든 step genealogy | `enterprise_tools.py::query` can read configured SQL sources in workbench; no all-step genealogy Tool is in Router catalog. | 없음 | `design_missing` | Map authenticated enterprise genealogy rows: part/lot/wafer/chip, step, equipment, parent-child keys, event time, availability and completeness; current enterprise defaults disabled and sources empty. |
| MES 상태 / 설비코드 DOWN | `platform_tools.py::evidence/summaries` exposes MES status/equipment/step/recipe/hold/queue fields on synthetic source. | `get_platform_evidence` | `connected_app_demo` | Site MES adapter plus authoritative status/code dictionary and equipment/chamber ID mapping; a synthetic DOWN value is not a production finding. |
| METRO numeric Trend / 13-point local | Raw configured `trend_series`; tabular/map analysis support other grains, but no METRO 13-point local pattern function/Tool was found. [platform_tools.py:170](</D:/project/q-agent/app/platform_tools.py:170>) | `get_platform_evidence` (raw Trend only) | `design_missing` | Adapter must supply METRO sites, point IDs, units, wafer/chip coordinates, sampling plan and aligned 13-point window; existing Trend Tool is bounded/time-cutoff data, not this analysis. |
| FAB OUT Yield + 128 Measure / electrical Trend | `platform_tools.py::summaries/trend_series`; `tabular_analysis.py::analyze_platform_case`; demo config sets 128 synthetic features. | `get_platform_evidence` | `connected_app_demo` (synthetic) | Site EDS/FAB OUT stages, tested/failed denominators, feature catalogue/unit/spec and Trend mapping; 128 demo features include synthetic dummy channels and are not validated electrical coverage. |
| FDC | No FDC source, parser, adapter or catalog entry found in inspected runtime. | 없음 | `deferred` | After deferral is lifted: define authorized FDC source, equipment/chamber keys, sensor/unit/sample time and availability/cutoff contract. |
| Known CNN | No Known CNN inference callable or catalog Tool found in Q-Agent app; mentioned as research provenance only; external CLI availability was not checked. | 없음 | `design_missing` | If runtime use is intended, wrap the frozen checkpoint with asset registry, preprocessing/version, provenance and `as_of`; no app connection currently. |
| Unknown image embedding / clustering | No embedding/clustering Tool found in app; `map_analysis.py` uses registered direct-mask overlap for a bounded demo path. | 없음 | `design_missing` | Adapter would need embedding version, normalization, clustering parameters, reject/noise output and image IDs; similarity alone must not assert recurring defect. |
| Query-gallery visual search (new lab) | Parent reports the new lab engine is still being implemented; its callable name/contract is not established in this audit. | 미정 (개발 중) | `lab_only` | Once the lab API is frozen, bridge query/gallery asset IDs, modality, version, score/rank, reject threshold and scope receipt; not an app Tool yet. |
| SEM / 성분분석 EDS vs electrical EDS | SEM image registry/comparison in `image_tools.py`; electrical test-stage summaries in `platform_tools.py`; no EDX/compositional analyzer. | `list_comparison_assets`, `compare_sem_images`; electrical via `get_platform_evidence` | `connected_app_demo` (SEM/electrical only) | Add separate authorized composition/EDX adapter and chemistry schema if required. Keep EDS (Electrical Die Sorting) separate from EDX. SEM specialist service defaults disabled. |
| Wafer-local region vs Chip repeated motif | `map_analysis.py::analyze_demo_case/_analyze_cohort` returns wafer-local regions and registered chip-mask overlap. [analysis-grains.md:8](</D:/project/q-agent/app/skills/rules/platform-analysis/references/analysis-grains.md:8>) | `get_platform_evidence` when synthetic `failbit`/map analysis is enabled | `connected_app_demo` | Site image/position registry, chip crop orientation and coordinate registration; heuristic threshold is not calibrated defect truth. |
| Past image → Wafer → OUT → incident bindings | Image metadata binds incident/Lot/Wafer/stage; platform sources use incident/Lot/Wafer/Chip keys and as-of. No complete historical image→Wafer→FAB OUT→incident provenance chain was verified. | `list_comparison_assets`, `compare_sem_images`, `get_platform_evidence` (partial) | `design_missing` | Stable asset→wafer key, OUT stage/result key, incident lineage, source version/hash and availability time; do not infer image identity from similarity. |
| Hybrid RAG for incident PDF/PPTX/DOCX/MHT and Inform | **2026-10-25 audit snapshot:** `meeting_tools.py::search` supports local FTS5 BM25 or remote hybrid; platform `inform` source returns synthetic rows. Generic existing-chunk BM25+vector was configured but no general document/Inform Router Tool was found. | Snapshot: `search_meeting_minutes` (meetings only). Current runtime callback path: `search_engineer_notes`, `search_internal_documents`; callback supplied by caller. | Snapshot: `design_missing` (partial meeting path). Current: `connected_app_demo` (callback contract only; no site backend verified). | See `2026-10-30 runtime 보완`. Connect existing site BM25+vector indexes/chunks for requested formats and Inform, preserving chunk/document/version/as-of IDs. Base retrieval flags remain off; configured callback contract does not establish site connectivity or ACL. |
| Future IN vs prior OUT | Role guidance distinguishes current/future results from historical results; no dedicated future-IN/prior-OUT paired history Tool or registered data source found. | 없음 | `design_missing` | Add temporal status adapter with current IN expectation, prior OUT event/result, product/recipe/test-stage identity and available-at; never substitute historical OUT for current result. |
| Critical equipment combinations | Synthetic MES/equipment/step/recipe fields exist; no critical-equipment-combination registry/Tool or rule join found. | `get_platform_evidence` (raw scoped MES only) | `design_missing` | Site critical-equipment/chamber combination registry, effective dates, step/recipe and incident/Lot lineage; classify verified combinations separately from heuristic co-occurrence. |
| HOLD / block / metrology / RELEASE actions | `actions` Skill says prepare action draft; no action Tool appears in Router catalog. Public base config has actions disabled and approval required. | 없음 | `design_missing` | Authorized ActionExecutor with target scope, current state, policy checks, approval identity, idempotency key and execution receipt; HOLD/block/metrology/RELEASE are not currently executable. |
| Judge counterevidence and re-query | `agent.py::review` calls Judge and returns to Router for `need_evidence/revise`; Judge contract routes those verdicts to router. | Runtime roles (not business Tool): `judge` → `router` | `connected_app_demo` | Requires evidence IDs and callable source Tools; metadata review is lineage/cutoff, not semantic truth, causal validation or production approval. |
| Answer last | `agent.py::review` calls Answer only after Judge returns `answer`; output contract requires Judge pass/abstain before claims. | Runtime roles: `answer` | `connected_app_demo` | Preserve Router → Tool → Judge → Answer ordering and citations; deployment text model is disabled in base config, so code wiring does not prove a live Answer path. |

## Configuration interpretation

Public `config/config.yaml` has text/image/trend models, SEM/overlay services, internal/engineer retrieval, meetings, enterprise and actions disabled by default. `config/platform-demo.yaml` enables synthetic platform and model fixtures, including `feature_count: 128`; this is an example overlay, not an applied runtime check. No `*.local.*` file was read. No row above establishes full platform readiness.

## Source identity

SHA-256 values below identify the inspected inputs at check time (2026-10-25 Asia/Seoul). They are source provenance hashes, not dataset or deployed artifact hashes.

| Absolute path | SHA-256 |
|---|---|
| `D:\project\q-agent\app\agent.py` | `334E93217970AA55282668173F4BC93606CA39BCCA86F1FAB8ED5252A4D1E166` |
| `D:\project\q-agent\app\incident_tools.py` | `EDDE4FD77C4D45681A03E8B16AE9BF0B34A2213E53860E24E0B84DF3F61C0B66` |
| `D:\project\q-agent\app\platform_tools.py` | `B9B16EEE0802E22499CECBD1AB38F9C5B5E5C4BF9A36868527CD206ABD0A2B51` |
| `D:\project\q-agent\app\platform_models.py` | `671F3A8DBA8D732F1F66CD517530CDA569902EF332F76AD480CFED7F1A540211` |
| `D:\project\q-agent\app\tabular_analysis.py` | `9ACAB9754787E445E71D039EDF78E7081A2EC97A12F2A4CC28AF72CCEA427817` |
| `D:\project\q-agent\app\map_analysis.py` | `7D5F0B0F25080BD1506EDE00A5B1C4E630E6BA7984748C405FB45BE744CB652E` |
| `D:\project\q-agent\app\image_tools.py` | `30B3A183B87C4BD47E190DB9B232E900E6B05A5B35CF5FF6DBB30B491EEC3DFF` |
| `D:\project\q-agent\app\meeting_tools.py` | `3189F1A106490236B1D28E89B9FFEEC6D0A55C3223154A043E1C7B6E0262101A` |
| `D:\project\q-agent\app\enterprise_tools.py` | `7D2E7CE1E05045DAB1736D5B93A210E402DE0ABB5836B37F7D434F7FBB5DF216` |
| `D:\project\q-agent\config\config.yaml` | `695A974D30A4755CFB576C588ADB882FBF3F0DABA9B7DD18C0DB8B2F0151F8B7` |
| `D:\project\q-agent\config\platform-demo.yaml` | `165ADEBFF222E42D42388FC4E18C6B30B6C7D36CC4233A1F89D63C9D63F2CB6F` |
| `D:\project\q-agent\app\skills\roles\router\references\tools.json` | `1C14CD2CFF83E706674E72A1E93C4925DF45DDFD5A2718944867564EC538569B` |
| `D:\project\q-agent\app\skill_registry.json` | `35DA9CB097DDF20208A86864D0E34E6D8BCA5878AB1B8C4D48B797F057310382` |
| `D:\project\q-agent\app\skills\rules\platform-analysis\references\analysis-grains.md` | `467449170DCE27AA0406F1EA0E63D30D47D9993AF8A03F88D54AF002C5F6483C` |
| `D:\project\q-agent\app\skills\roles\judge\SKILL.md` | `E99E47CB9B6B1617D373A3EF31F7317C8FB7A629749AC46629ED5880D90C198D` |
| `D:\project\q-agent\app\skills\rules\actions\SKILL.md` | `6F4068B5D7CC1C4C8A01714734632447930B1D5DC1B01D4E57CB091BB3934263` |

Unverified: live overlay application, endpoint health, production schema/data semantics, external known-CNN/unknown-contrastive CLI availability, and the in-progress lab engine API/name.

## 2026-10-30 runtime 보완

현재 코드에서는 `app/agent.py::run`이 `search_engineer_notes` 및 `search_internal_documents`를 Tool로 등록·호출하며, `app/workbench.py`가 요청 source를 이 Tool 이름에 연결한다. 활성화에는 source 설정, 유효한 status allowlist 및 호출자가 주입한 callable `document_query`가 필요하다. 코드에는 문서 callback 계약·scope 검증 경로가 있으나 `Workbench`/CLI는 기본적으로 이 callback을 주입하지 않는다. 합성 테스트 fixture는 계약 경로를 확인할 뿐 실제 BM25/vector 검색을 수행하지 않는다. 따라서 `design_missing`이라는 과거 행은 현재 Tool/계약의 부재를 뜻하지 않으며, 실제 site Hybrid RAG 연결은 미확인 상태다.

`search_mes_reference`도 현재 `app/agent.py` runtime Tool 집합과 Workbench source routing에 연결되어 있다. demo 환경에서 설정한 `mes_reference.synthetic_sqlite`가 활성이고 DB 파일이 유효하면 Workbench 및 CLI가 합성 SQLite reader를 자동 구성한다. 이는 테스트/합성 기준정보 조회 경로이며 사내 MES Adapter, 데이터, ACL 또는 생산 접속을 의미하지 않는다. 기본 `config/config.yaml`의 문서 retrieval 및 MES reference는 비활성이다.



