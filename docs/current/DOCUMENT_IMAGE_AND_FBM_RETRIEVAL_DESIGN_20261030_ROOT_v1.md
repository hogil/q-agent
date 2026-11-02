# 문서 이미지 추출과 FBM 유사 검색 설계 (2026-10-30)

## 목적과 상태

이 문서는 Eng’r Inform Note 및 사내 공용 저장소 문서의 이미지 내용을 검색 가능하게 만들고, 불량 FBM map을 별도 image-retrieval 경로로 탐색하기 위한 설계 초안이다. 구현, 실데이터 검증, 실험 실행을 기록하는 문서가 아니다. 실제 사내 문서·ACL·schema·OCR 환경과 FBM source 계약은 확인되지 않았다.

요청 범위는 두 검색 경로다.

1. 문서 이미지에서 OCR 텍스트, 표 구조, 그림 설명을 추출해 기존 BM25+vector Hybrid RAG의 문서/chunk와 연결한다.
2. 불량 FBM map 원본 및 파생 표현을 별도 보존하고, image embedding 기반 유사 사례 검색을 제공한다.

두 경로는 동일한 원본 보존·provenance·권한 원칙을 공유할 수 있지만 인덱스, 검색 단위, 평가 기준은 분리한다. 문서 이미지 추출은 문서 chunk 검색을 보강하며 FBM 유사도 결과는 원인 판정이 아니다.

## 현재 확인된 지원과 제안의 구분

| 구분 | 확인된 현재 상태 | 이번 문서의 제안 |
|---|---|---|
| 사내문서/Eng’r Inform 검색 | Workbench에 `search_engineer_notes`, `search_internal_documents` 경로와 기존 Hybrid RAG callback 계약이 있다. 합성 callback은 실제 BM25+vector 검색을 수행하지 않으며 실 문서 연결도 확인되지 않았다. Eng’r Inform snapshot의 합성 참조와 원문 검색은 별개다. | 이미지에서 추출한 파생 텍스트/표/캡션을 문서의 기존 chunk 또는 문서 검색 인덱스에 provenance를 보존해 연결한다. 현재 chunk를 임의 재생성하거나 교체하지 않는다. |
| FBM retrieval | 기존 Q-Agent는 일부 image evidence Tool을 보유하지만, 이는 이 설계에서 요구하는 범용 FBM map embedding gallery 또는 문서 이미지 OCR 경로가 아님을 전제로 한다. 기존 multimodal 구현의 상태·제한은 `MULTIMODAL_PROJECT_BOUNDARY_20261028.md` 참조. | FBM 전용 sidecar 저장·embedding·similarity retrieval과 검토 UI/API를 별도 설계하고, 기존 사고 DB 우선 조회 및 scope 검증 뒤 후속 Tool로 연결한다. |
| 데이터·권한 | 운영 ACL, 실제 사내 source/schema, 보존 정책, 실제 image access는 검증되지 않았다. | ACL 상속을 검색 단계 전체에서 fail-closed로 적용하고, 권한 검증 없는 원본/파생물/메타데이터 노출을 거부한다. |

Workbench의 문서 검색 계약과 현재 미연결 범위는 [WORKBENCH_RETRIEVAL_SOURCES_20261030_ROOT_v1.md](D:/project/q-agent/docs/current/WORKBENCH_RETRIEVAL_SOURCES_20261030_ROOT_v1.md)에 기록되어 있다. 아래 항목은 모두 제안이며 실제 사내 자료에서 검증된 계약이 아니다.

## 공통 저장·provenance 원칙

- 원본 문서와 원본 이미지는 불변 원본으로 보존한다. OCR 텍스트, 표 셀 구조, 캡션/그림 설명, thumbnail, crop, 정규화 이미지, embedding은 별도 파생물로 저장하고 원본을 덮어쓰지 않는다.
- 각 파생물은 `source_document_id`, 원본 version/hash, document status, page, figure/table/region ID, 좌표계와 region 좌표, 원본 chunk ID 또는 연관 chunk ID, 변환기/OCR/caption 모델 및 버전, 생성 시각, `available_at`, 문서 기준일/유효기간을 가리킨다. 없는 값은 추정하지 않고 unknown으로 기록한다.
- ACL·분류등급·보존·삭제 상태는 원본에서 상속한다. 파생물·thumbnail·embedding·검색 결과·캐시·로그에도 동일한 접근 필터를 적용한다. 원본 권한 또는 상속 관계를 확인할 수 없으면 인덱싱/검색 결과 반환을 거부한다. 권한 회수·원본 삭제 시 모든 파생 인덱스와 캐시를 무효화하는 tombstone 및 purge 경로가 필요하다.
- `as_of` 검색은 원본 및 파생물이 해당 시점에 사용 가능했는지 확인한다. 문서 게시일, 이미지 추출일, 원본 유효기간을 혼동하지 않는다. 정정된 문서 버전은 기존 버전과 분리하고 lineage를 유지한다.
- 텍스트 검색 결과는 원문 page/region으로 되돌아갈 수 있어야 한다. 문서에 이미지가 존재하지만 OCR을 못했거나 품질 gate를 통과하지 못한 상태도 명시한다. 이미지의 미추출을 근거가 없다는 뜻으로 해석하지 않는다.

## 문서 이미지와 Hybrid RAG 연결

### 파생 산출물

각 페이지/그림 단위로 다음 중 이용 가능한 산출물을 생성한다.

- OCR text: 원문 언어, 읽기 순서 및 block/line 위치, confidence와 품질 상태를 포함한다.
- 표: 셀 값뿐 아니라 행/열 구조, header 관계, 병합/단위/각주를 보존하고, 렌더링된 표 이미지 region과 연결한다. 구조 복원이 불확실하면 평문으로 강제 변환하지 않는다.
- 그림 설명: 캡션이 있으면 원문 캡션과 자동 생성 설명을 분리한다. 자동 설명은 생성 모델/버전·confidence를 표기하고 사용자 확인 전 사실로 승격하지 않는다.
- region asset: 원본 이미지 참조, page number, figure/table/region identifier, 좌표 및 좌표 frame, crop derivation recipe를 기록한다.

기존 Hybrid RAG의 BM25와 vector 인덱스가 파생 텍스트를 검색 대상으로 받아들일 수 있는지 확인한 뒤, 기존 문서와 연결된 별도 derived text record 또는 기존 chunk 확장 방식 중 하나를 선택한다. 사용자 질의 시 원문 chunk와 이미지 유래 text를 함께 보여주되 각 evidence의 modality와 provenance를 구별한다. 임의 OCR 결과가 기존 chunk를 덮거나 출처 문장을 합쳐 provenance를 잃어서는 안 된다. embedding은 기존 문서 embedding 설정과 호환성을 확인하기 전 새 모델로 혼합하지 않는다.

### 품질·불확실성

OCR confidence는 모델 점수만으로 신뢰도를 보장하지 않는다. 필기, 흐림, 낮은 해상도, 회전, 다국어, 기호/단위, 도면 annotation, 겹친 글자, 작은 표 글꼴별 오류 유형과 검토 가능한 표본을 별도로 기록한다. confidence가 낮거나 레이아웃 검증이 실패한 text/table은 검색 후보로 격리하거나 `uncertain` 상태로 제공하며, 숫자·단위·경보 문구를 확정 근거로 단정하지 않는다. 사용자는 원본 crop을 열어 확인할 수 있어야 하고, 권한이 확인된 경우에만 제공한다.

## FBM map 전용 유사 검색

### 원본과 별도 표현

FBM 인덱스는 문서 RAG 인덱스와 분리한다. 각 map은 원본 파일을 변경 없이 보존하고, 파생 map tensor/preview/thumbnail과 embedding을 버전별로 별도 보관한다. 사용자 결정에 따라 적어도 두 표현을 독립적으로 유지한다.

1. **Raw FBM:** 원본 fail-bit 값과 observation/validity mask를 lossless하게 보존한다. 클래스 색칠이나 모델 판정으로 값을 치환하지 않는다.
2. **Object-ID + chip-yield FBM:** object/class overlay와 yield/pass-fail 값을 분리해 저장한다. yield의 0/1 의미는 실제 schema 검증 전에는 가정하지 않는다. uninspected, invalid, missing, unknown은 pass/fail과 분리한다.

클래스는 multi-hot을 허용한다. known class 집합, unknown/novel candidate, reject/invalid 및 관측 상태는 독립 필드/채널로 유지한다. 다중 불량을 단일 class로 축약하거나 unknown을 정상으로 취급하지 않는다. object ID가 chip 고유 ID인지 class index인지 source contract로 확인하며, 현재 연구 문서에서 기술한 predicted class overlay를 새 사내 데이터의 정의로 간주하지 않는다.

### Geometry와 lineage 계약

검색 가능한 map record마다 wafer/chip geometry 및 등록 lineage를 보존한다: 제품/세대·layout version, wafer grid/chip 좌표, row/column origin, pitch/ROI, wafer frame, rotation/flip/orientation/notch 상태, 검사 coverage/mask, crop 생성 방식, pixel-to-chip 대응 및 geometry validation 상태. 미확인 geometry는 unknown으로 두고 변환·회전 불변화를 임의 가정하지 않는다.

동일 wafer의 raw/enriched map, 여러 crop, 반복 촬영, 재처리본은 공통 lineage/group ID를 공유한다. map embedding은 모델/architecture/checkpoint hash, preprocessing 및 resize/normalization, embedding dimension, transform version, source representation, 생성일/as-of와 geometry contract에 묶는다. 버전이 다른 embedding을 같은 공간으로 조용히 비교하지 않는다. 원본 map, 파생 image와 embedding은 서로 역참조 가능해야 한다.

### 검색 반환과 해석

유사도 검색 결과에는 similarity score와 그 해석 한계, representation 및 embedding version, wafer/map scope, source/as-of, geometry 상태, thumbnail 또는 원본 접근 locator, known/unknown/status 요약, 권한 판정 및 lineage를 함께 반환한다. `top_k` 후보는 사례 탐색용이다. 유사도는 공정 원인, 불량 확정, Lot 영향, 현재 유효성을 증명하지 않는다. 사고·Lot/wafer 범위는 Orchestrator/Adapter가 검증하고, `lot_inventory`를 영향 Wafer로 간주하지 않는다. 첫 업무 Tool 사고 DB 검색/집계를 유지한 뒤에만 이미지 검색을 수행한다.

## 데이터 계약 및 필수 검증 항목

구현 논의 전에 실제 데이터 소유자와 다음 계약을 문서화한다. 부재·충돌·미확정 항목은 fail-closed 또는 명시적 unknown으로 남긴다.

| 계약 | 확인할 필드·규칙 |
|---|---|
| 문서 식별·버전 | 문서 ID, source repository, version/hash, 승인/초안/폐기 status, page identity, 기준일, 게시·수정·available 시각 및 유효기간 |
| image/region | 이미지 ID, 원본 byte/hash, 문서/page/figure/table 연결, 좌표계, region 좌표, 해상도/rotation, 원본 접근 방법 및 보존 정책 |
| ACL | actor/group/role policy, 상속 규칙, 분류등급, deny precedence, 권한 변경 전파, 감사 로그와 파생물 purge SLA |
| FBM 식별 | dataset/source version, observation/map ID, wafer/Lot/chip key semantics, 제품·세대·layout, event/inspection time, source hash |
| map 값 의미 | raw bit encoding, yield polarity/meaning, object/class ID semantics, multi-hot labels, known/unknown/reject/invalid/uninspected 상태와 label completeness |
| geometry | 좌표 origin, pitch, frame, orientation/notch, chip mask/coverage, crop과 resize 변환, geometry version과 검증 책임자 |
| Measure 연결(선택 arm) | exact same wafer/chip join key, stage/item, event/measurement time, unit, cardinality, coverage, cutoff 및 temporal match rule |
| 임베딩 | 허용 모델/체크포인트, license/배포 위치, 전처리·모델 버전, 거리 함수, dimension, threshold/top-k와 reindex 정책 |

Measure는 이 image retrieval의 필수 종속성이 아니다. 별도 multimodal 실험 arm을 제안할 때만 exact key, stage/item, 시간, unit, cardinality, coverage를 검증한다. wafer grid 좌표나 이름이 비슷한 ID만으로 Join하지 않는다.

## 실험 계획 제안

실험은 실제 사내 데이터 사용 권한·ACL 검증·데이터 계약 동결 및 별도 자원 승인을 받은 뒤 범위가 정해진다. 이 문서는 실행을 승인하지 않는다. 모든 실데이터는 승인된 내부 저장소/실행 환경 안에서만 처리하며 외부 API·웹 서비스·외부 SaaS에 고객 이미지, 문서, OCR text, embedding, 식별자 또는 trace를 보내지 않는다.

### A. 문서 이미지 추출 / RAG

1. 권한이 확인된 문서 표본에 대해 source/version/status와 페이지/이미지 수, 언어, 이미지·표 유형을 식별하고, 문서·페이지·원본 이미지 단위로 train/dev/test 또는 calibration/evaluation 그룹을 고정한다. 같은 문서의 재발행본·중복 이미지·파생 crop은 같은 그룹에 둔다.
2. 표본 정답은 접근 통제된 검토 절차로 OCR text, 숫자·단위, table cell/header 관계, figure-caption 연결과 page/region 위치를 채점한다. 샘플링 기준과 검토자 불일치·adjudication을 남긴다. 무검수 자동 caption은 정답으로 사용하지 않는다.
3. OCR/layout 모델과 전처리를 동결한 뒤 CER/WER 또는 언어별 text metric, 핵심 숫자·단위 exactness, table structure/cell accuracy, region localization, abstain/uncertain coverage를 보고한다. 자동 설명은 별도 사람 평가와 provenance 확인을 거친다.
4. 검색은 기존 text-only Hybrid RAG baseline과 image-derived text 추가 arm을 동일 query·문서 corpus·ACL/as-of 조건으로 비교한다. Recall@k/MRR/nDCG 및 근거 region 정합성, 답변 인용의 source/page/region 정확성, 권한 거부·권한 변경·만료 문서 누출을 측정한다. 문서 버전 또는 페이지가 split을 가로지르지 않게 한다.
5. 낮은 해상도, 표/그림 혼동, OCR 오류 숫자, 회전/언어 혼합, 상충 버전, 권한 회수, 원본 누락을 명시적 failure/negative controls로 둔다. ACL leakage는 성능 평균과 별개로 허용 0건이어야 한다.

### B. FBM image embedding retrieval

1. 기존 position-free classifier/retrieval baseline과 geometry/source mapping을 먼저 검증한다. raw FBM과 object-ID-plus-yield map을 서로 다른 표현 arm으로 고정하고, 필요하면 같은 query set에 두 arm을 별도로 검색한다. 학습/인덱스 모델 version과 거리 함수를 사전 지정한다.
2. 평가 split은 Lot 단위로 우선 분리하고, 같은 wafer의 모든 map, chip crop, 재촬영, resize/augmentation, 파생 표현 및 near-duplicate를 동일 split에 묶는다. test query와 동일 wafer/gallery sibling이 학습 또는 gallery에 들어가지 않도록 한다. 제품/세대/layout과 시간 holdout을 별도 평가한다. 중복/near-duplicate 탐지 기준은 split 확정 전에 동결한다.
3. 정답 relevance는 검증된 class multi-hot/status와 필요 시 전문가 adjudication으로 만들고, 불완전 annotation은 unknown으로 유지한다. nearest-neighbor hit를 ground-truth 원인으로 해석하지 않는다.
4. Recall@k, mAP/nDCG, 같은 wafer/다른 wafer 결과 비율, known-class별 및 multi-hot 성능, unknown/reject coverage, geometry/status 하위군, 제품/세대 holdout 성능, duplicate leakage audit를 보고한다. 동일 wafer retrieval이 허용된 운영 시나리오와 cross-wafer 사례 탐색을 구분한다.
5. 변형·회전·flip, orientation 누락/오류, geometry mismatch, raw/enriched mismatch, unknown/invalid/missing, 중복 map 및 ACL/as-of 경계의 negative controls를 둔다. Similarity 결과를 불량 원인·장비·공정 조치로 자동 확장하지 않는다.

성능 기준, 사용자 검토 효용, 허용 latency/coverage 및 threshold는 source contract와 baseline을 확인한 뒤 사전 등록한다. 지표 기준이 결정되기 전에는 성공/실패를 사후 선택하지 않고 exploratory/inconclusive로 보고한다. 실제 고객 데이터를 포함한 검색·수동 검수 artifact는 승인된 내부 환경에만 보관한다.

## 통합과 안전한 실패 동작

- 기존 Q-Agent 흐름을 유지한다: Router → 사고 DB 검색/집계 및 scope 검증 → 선택된 문서/FBM retrieval Tool → Judge 근거 검토 → Answer. 사고 관련 질의에서 이미지 검색이 첫 업무 Tool이 될 수 없다.
- 문서 OCR/RAG Tool은 source kind, incident scope, actor, `as_of`, status allowlist, chunk/page/region locator를 검증한 evidence만 반환한다. FBM retrieval Tool은 동일 scope 검증과 map/embedding lineage, ACL, representation, model version, geometry/status completeness를 추가 확인한다.
- 권한, 기준일, provenance, mapping, embedding version, geometry 또는 label status 검증이 실패하면 해당 결과를 숨기고 구체적 unavailable/unknown 이유를 남긴다. 누락 상태를 정상으로 대체하거나 가장 가까운 후보를 확정 근거로 승격하지 않는다.
- Judge는 OCR/표 추출의 불확실성과 similarity의 후보 성격을 보존한다. 근거 부족이면 Router로 재조회하거나 Answer에서 제한을 표시한다. Answer는 마지막 LLM이며 similarity만으로 causality, confirmed defect, production action을 주장하지 않는다.
- Router/Tool/Judge 계약 변경은 관련 `app/skills`와 공유 참조를 먼저 수정하고 명시적으로 freeze한 다음 별도 변경으로 진행한다. 이 설계 작업은 Tool, Skill, config, index 또는 UI를 변경하지 않는다.

## 보존 경계 및 미확인 사항

이 문서는 설계만 추가한다. 기존 multimodal 업무·실험·GPU 자원·checkpoint·기존 인덱스/데이터를 수정·삭제하지 않으며, `D:\project\multimodal`도 변경하지 않는다. 새 모델 학습, 고객 자료 복사, 데이터 수집, 외부 전송, production DB/ACL 변경은 수행되지 않았다. 기존 자원 자료와 Git 보존 지침을 따른다.

실제 사내 문서 원본과 공용 저장소 API, image/FBM schema, ACL 상속/삭제 propagation, 허용 OCR/table/caption/image embedding model과 license, 실데이터 품질/규모, 운영 storage·latency·보존 규칙, 문서 chunk 수정 가능 방식, 실제 yield/object ID/unknown semantics, geometry/orientation, Measure Join 가능성은 모두 미확인이다. 이 설계는 이를 확인 완료한 것으로 주장하지 않는다. 먼저 데이터 계약과 내부 처리 경로/권한을 확정하고, 그 뒤 별도 승인된 작은 평가를 계획한다.
