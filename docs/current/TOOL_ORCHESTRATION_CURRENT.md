# 현재 Tool 연결 설계와 실제 실행

후속 실행은 [통합 모델 분석 런타임 v2](D:/project/q-agent/docs/current/UNIFIED_RUNTIME_CURRENT.md)를 따른다. 앱의 별도 모델 분석 API/UI, live forecast, wide Measure SQL, 더미 MES 실행이 추가됐다. 아래는 보존한 Tool graph v1의 계약·범위다.

기준 2026-10-25. 사용자 요청에 따라 app runtime, known-cnn, unknown-contrastive, mapviewer, fail-map, 새 cohort/모델/RDB/RAG, 기존 조치 모듈의 관련 진입점과 계약을 점검했다. 실제 사내 DB/이미지·비공개 설정·생산계·LLM endpoint를 전수 확인한 것이 아니다. 이 문서의 새 연결은 **더미 데이터 lab Tool graph**이며 기존 app의 Tool registry/role 동작은 변경하지 않았다.

## Unknown의 역할부터 분리

| 기능 | 질문 | 출력 | 혼동하면 안 되는 것 |
|---|---|---|---|
| Known 이미지 분류 | 지원하는 패턴인가? | 학습 label별 확률/reject | 이미지 검색 순위·원인 확률이 아님 |
| 유사 이미지 검색 | 이 관측과 비슷한 과거 이미지가 있나? | image/wafer/chip ID, rank, embedding similarity | Unknown/정상 확정이 아님. Known 결과와 무관하게 검색 가능 |
| Unknown 이미지 군집 | 미정의 관측들끼리 반복되는 모양이 있나? | cluster/noise, 묶인 image IDs, model/index version | 과거 사고 DB와의 연결은 별도. cluster ID는 불량 code가 아님 |
| Tabular novelty | 측정 vector가 기준 분포에서 벗어났나? | 거리/novelty score | 이미지 retrieval의 AP/Recall@K와 다른 실험 |
| 파일 검색 | 어떤 Lot/경로의 파일인가? | path/asset reference | 눈으로 비슷한 이미지를 찾는 검색이 아님 |

이전 Unknown AP 약0.20은 `refresh_analysis`의 **tabular 거리 기반 novelty** 결과다. `unknown-contrastive` 이미지 검색 성능을 측정한 수치가 아니다. 이 차이를 기존 답변에서 더 분명히 구분했어야 했다.

현재 `unknown-contrastive` 배포 코드는 image pool 준비/cache/embedding/HDBSCAN grouping의 CLI다. 현재 Q-Agent의 온라인 query→gallery API와 image→사고 join이 이미 구현됐다고 볼 근거는 없었다. 새로 연결한 검색은 기존 합성 spatial-CNN feature cache를 이용한 lab 검색이다. unknown-contrastive의 원래 embedding/checkpoint를 붙인 재현·검색 품질 검증과는 구분한다.

## 단일 주 흐름

| 순서 | 주체 | 호출·책임 |
|---:|---|---|
| 0 | 질문/이미지/METRO/OUT 입력 | 입력 stage, 관측 cutoff, 현재 asset/Lot/Wafer/Chip scope 확인 |
| 1 | Router | 입력 유형에 맞는 계획. 후속 조회도 같은 Router가 관리 |
| 2 | 사고 DB | 최초 업무 Tool로 사고 후보/집계. 과거 후보를 현재 사고로 자동 선택하지 않음 |
| 3 | 후속 Tool | 현재 scope/공정/설비 → 모달리티 분석·검색 → 과거 ID 정합 → RDB/원문 → 적용 조건/반례 비교 |
| 4 | Judge | source ID·시점·좌표·단위·정답/예측 구분·반증·누락 검토. 부족하면 Router로 재조회 |
| 5 | 코드 ActionExecutor | 별도 권한/current MES 상태/조건/revision 검증 후에만 실행. 이번 lab에서는 제안만 생성 |
| 6 | Answer | 마지막 LLM이 근거·예측·가설·미확인·실행 상태를 구분해 답변 |
| 7 | 최종 조회 상태 | 현재 scope와 과거 참조, missing input, 미실행 조치와 남은 조건 표시 |

새 lab 실행기는 이 순서를 코드로 묶고 source/cutoff/의존성을 검사한다. LLM Router/Judge/Answer를 호출한 결과는 아니다. 기존 app에는 별도로 Router→Tool→Judge→Answer와 Judge 재조회 경로가 존재하며 base 설정의 배포 모델/서비스 다수는 비활성이다.

## 새 lab에 실제 등록한 16개 Tool

아래 이름은 새 lab catalog의 실제 이름이다. 기존 app에 동일 이름을 만들어 둔 것처럼 사용하면 안 된다.

| Tool | 선행 결과 | 반환/다음 연결 |
|---|---|---|
| `search_incident_db` | typed cutoff | 기존 사고 metadata + 이미지에 직접 연결한 합성 조사 후보. 현재 사고 자동선택 없음 |
| `resolve_current_scope` | 사고 DB 확인 | cohort/row→현재 Wafer/Chip/frame/cutoff receipt |
| `get_process_genealogy` | current scope | snapshot 이전 Wafer×step route. critical step 비교와 model input 범위 |
| `get_equipment_context` | route | 해당 Wafer의 설비 고장 코드/시점. DOWN policy 근거 |
| `get_metro_observations` | route | 일반 13-point Chip/local 위치와 별도의 96-feature dense experimental panel |
| `get_fab_out_results` | current scope | 공개된 Chip Yield/128 Measure만. 미래면 실제 값 조회 없이 `not_observed_yet` |
| `get_numeric_trend` | route | raw 수치 METRO의 mask/statistics/source, eqp/chamber/ppid/reticle 문맥. FDC 대체 금지 |
| `get_model_findings` | route | freeze된 row-bound morphology/Trend/미래 OUT 또는 관측 OUT 결과. score 종류 구분 |
| `search_similar_images` | current asset/scope | 같은 encoder/kind의 과거 이미지 top-k. Known score로 gate하지 않음 |
| `get_historical_references` | 반환된 image ref IDs | 실제 과거 Wafer/Chip/OUT Measure·Yield/critical steps·정확한 사고 attachment. context twin도 다른 scope로 조회 |
| `get_image_spatial_evidence` | current Wafer | 표본/가용 Chip 분모, local/repetition 후보와 native 위치. 미관측 Chip을 정상으로 채우지 않음 |
| `analyze_equipment_combinations` | structure/recipe/critical steps | 과거 관측 OUT의 일치 비교군·검사 분모·장비 조합. 표본 부족/step 독립성 부족 표시 |
| `retrieve_records` | 사고 후보/route/직접 attachment IDs | 사고/Inform/회의 및 직접 연결한 원문의 Hybrid 결과. 공개된 corpus를 scope 후 검색 |
| `compare_applicability` | 과거 참조+문서+현재 scope | 적용 가능한 문맥, 다른 recipe/structure 반례, registration 미확인 구분. OUT가 공개됐으면 공통 관측 Measure item 비교 |
| `read_source_chunks` | 반환된 chunk refs | 선택 원문 1~3개, bounded text, file hash/locator. 문서 지시문 실행 금지 |
| `plan_follow_up` | 설비/반례 검토 | HOLD/block/추가 계측 제안. RELEASE는 current hold reason/state/권한/승인 조건 없이는 실행 불가 |

## 이미지 입력에서 실제로 잇는 ID

1. 현재 asset은 `cohort + row_id + wafer_id + chip_id + native frame + available_at`로 바인딩한다.
2. query descriptor와 gallery가 같은 encoder version/kind인지 확인한다. 현재 gallery는 `synthetic_chip_patch`, source pixel64이며 SEM/FBM/원소분석 EDS와 섞지 않는다.
3. 과거 image ref는 `development:row_id`이고 source image array hash/row, Wafer/Chip을 보존한다. 다른 cohort의 동일 정수 pair ID를 같은 관측으로 취급하지 않는다.
4. index가 반환한 ref만 서버가 과거 RDB로 해석한다. 같은 합성 physical pair의 다른 recipe scenario는 별도 Wafer/Chip scope로 확장하며 검색 rank를 새로 발명하지 않는다.
5. 그 ref에 명시적으로 연결한 `case_id → document_id → chunk_id/path/hash/locator`를 따라 원문을 읽는다. 분류명이나 높은 similarity를 사고번호 대신 join key로 사용하지 않는다.
6. 과거 OUT 값은 그 과거 사례의 공개시점이 지난 경우에만 읽는다. 현재 FAB IN 입력의 미래 OUT을 과거 값으로 채우지 않는다.

새 gallery는 train split의 **이미지 가용성 열**을 source warehouse와 대조한 7,076개 feature로 만들었다. 실제 lab 약속은 tabular/image/trend/text 순서의 가용성 매핑이며, 서로 바꾸지 않는다. 단순 row index는 외부 global ID가 아니다.

과거 120개 Wafer의 저장된 검사·계측·route 사실에서 합성 조사 120건과 Markdown 120개/480 chunk를 새로 만들고 7,076개 attachment를 FK로 연결했다. 링크는 우리가 만든 더미 관계다. stored tested=1/Yield=0인 Chip만 `observed_failed_chip`, 나머지는 `investigation_context`다. Wafer inventory 전체를 사고 영향 Chip으로 단정하지 않는다. cause는 모두 unconfirmed다.

## 입력별 실행과 반례

| 입력 | 주 분석 | 추가로 확인할 것 | 실제 실행 확인 |
|---|---|---|---|
| 이상 이미지 | Known/morphology + 유사 이미지 + local/repetition 공간 증거 | 과거 OUT/route/사고 원문·Inform과 현재 recipe 조건 | image inquiry 16 Tool |
| METRO 이상 | 숫자 Trend + step/item·13-point/local 정합 | 관련 공정/설비·text, 필요한 이미지/후속 계측 | METRO inquiry 12 Tool |
| 관측 FAB OUT Measure | tested/128 item 분포 + 과거 IN 역추적 | 유사 과거 **IN** 이미지와 critical step 조합·원문 | reverse inquiry 16 Tool |
| 채팅/설비 질문 | 사고→current scope/route→설비/기록 | DOWN 우선 정책, 필요한 source 원문 | chat/DOWN inquiry 8 Tool |

FAB OUT 이미지 자체를 query하려면 그 FBM/Failbit/SEM 타입용 descriptor/index가 필요하다. 현재 reverse 예시의 이미지 검색은 그 OUT 관측에 대응하는 **이전 IN 이미지**를 사용하는 것이며, OUT bitmap encoder가 구현됐다는 뜻이 아니다.

같은 이미지가 다른 recipe/Inform 조건에서 나온 사례는 제거하지 않는다. 직접 link된 양쪽 과거 결과를 유지하고 현재 적용 조건을 비교한다. text의 가설/반박/승인 조건은 section 별로 해석한다. source에 rejected 대안이 있다는 이유만으로 문서 전체를 반례로 분류하지 않는다. 일반 point 번호는 sampling plan/revision ID가 아니다.

Wafer 내 local 후보와 Chip 내부 반복 모양도 구분한다. intrachip repetition classifier가 여러 Chip에서 높아도 여러 Chip의 동일 local motif registration까지 증명한 것은 아니다. 해당 분석에는 별도 ROI/local-pixel descriptor와 방향·scale·bit/CAD mapping이 필요하다.

## Judge가 Router로 돌려야 하는 조건

| 조건 | 재조회/중단 |
|---|---|
| 현재 이미지 또는 수치 Trend가 없음 | `need_current_image` / `need_numeric_trend`. 다른 modality를 해당 입력처럼 대체하지 않음 |
| OUT 아직 미공개 또는 미검사 | `need_observed_out_evidence`; 미래 예측은 별도 task로만 제안 |
| 이미지 유사하지만 recipe/구조가 다름 | 비교군의 다른 조건과 같은 조건 사례를 함께 읽고 반례 유지 |
| 원문이 가설/미확인뿐임 | 원문 section/다른 사고·Inform·실제 공정 관측 추가 조회; 원인 확정 보류 |
| 좌표/측정 plan/단위 등록 불명확 | 수치/공간 join 보류, source 변환 정의 조회. 정성적 이미지 검색은 별도 유지 |
| schema/데이터 버전이 다름 | 명시적 mapping Adapter 없으면 합치지 않음. old FAB combo/action DB와 새 warehouse의 정수 ID를 동일시하지 않음 |
| 장비 조합의 비교군/독립 변동이 부족함 | `insufficient_support`; 연관을 원인·정책 실행 근거로 단정하지 않음 |
| 같은 실패 반복 또는 예산 소진 | 같은 Router에서 최대 재조회/Tool 예산을 적용하고 한계를 보고 |

문서 재조회 cache key는 Tool명/arguments뿐 아니라 선행 fact IDs도 포함한다. 새로운 retrieval 결과가 생겼는데 예전 비교 결과를 재사용하지 않는다. 기본 Tool 예산 18, 재조회 예산 2이며 원문 text budget은 별도로 제한한다. 캐시된 model 결과를 재사용해 Tool 16회가 LLM 16회나 GPU 16회가 되지 않게 한다. 현재 CLI는 단계별 순차 실행이며 독립 Tool의 병렬 실행은 별도 제품 최적화 대상이다.

## 원래 프로젝트와 현재 연결의 경계

- app의 실제 Router catalog는 13개다. `find_incidents`, `summarize_incidents`, `get_platform_evidence`, `get_engineering_snapshot`, `search_platform_history`, `list_comparison_assets`, `compare_sem_images` 등과 새 lab 이름을 혼동하지 않는다.
- known-cnn/unknown-contrastive의 batch/CLI inference를 온라인 Tool로 쓰려면 asset mapping, model/index version, queue/resource lock, callable adapter가 필요하다. 원본 프로젝트를 수정하거나 실제 이미지로 새 학습하지 않았다.
- MapViewer의 파일/경로 탐색과 fail-map의 key mapping은 asset locator/geometry 근거다. visual similarity 점수로 표시하지 않는다.
- SEM, 원소분석 EDS, 전기검사 EDS, FAB OUT Failbit/FBM을 각각 다른 modality/grain으로 관리한다. 현재 합성 chip patch 검색을 이들 전부의 검색으로 표시하지 않는다.
- 기존 사내 BM25+vector/chunk는 그대로 연결 대상이다. 현재 두 더미 corpus의 TF-IDF+로컬 MiniLM RRF를 사내 서비스 교체 완료라고 표시하지 않는다.
- 장비 조합은 source cohort에서 critical step 진행 설비의 독립 변동이 부족한 한계가 있다. 기존 별도 조합 분석기는 그 source DB에서만 실행한다.
- 기존 더미 HOLD/RELEASE simulator도 별도 equipment schema다. 새 graph는 MES current-state Adapter가 없으므로 실행하지 않는다. 이미지가 비슷하고 양품 사례가 있어도 RELEASE하지 않는다.
- FDC 검출기는 계속 보류다. 컬럼 unique/profile·alias/오타 매칭은 기존 helper/Schema Skill과 configured catalog로 수행하고 unique 값만으로 실제 물리 의미를 발명하지 않는다.

전체 category/source/status 표는 [TOOL_CAPABILITY_COVERAGE.md](TOOL_CAPABILITY_COVERAGE.md)에 있다. 이미지 검색 품질은 향후 query-gallery Recall@K/nDCG/동일 패턴 precision과 recipe 반례 분리로 검증해야 한다. 지금 검색이 실행됐다는 사실만으로 높은 검색 품질을 주장하지 않는다.

## 실행 artifact

- 현재 config: `D:\project\q-agent-models\config\config.yaml` + `D:\project\q-agent-models\config\tool-orchestration-v5.yaml`
- 고정 Tool catalog: `D:\project\q-agent-models\var\output\tool-orchestration-v1\tool-contract-v4.json`
- 실행 코드: `D:\project\q-agent-models\src\qmodels\tool_orchestrator.py`
- 이미지 조사: `D:\project\q-agent-models\var\output\tool-orchestration-v1\image-run.json`
- METRO 조사: `D:\project\q-agent-models\var\output\tool-orchestration-v1\metro-run.json`
- OUT 역추적: `D:\project\q-agent-models\var\output\tool-orchestration-v1\out-run.json`
- 채팅/DOWN: `D:\project\q-agent-models\var\output\tool-orchestration-v1\chat-down-run.json`
- 실행/차단 확인: `D:\project\q-agent-models\var\output\tool-orchestration-v1\execution-checks.json`

이 graph는 실제 더미 자료와 동결된 모델 결과를 호출해 만든 보고서다. 서비스 LLM 답변 품질, 생산 권한, MES 실행 검증은 별도다.
