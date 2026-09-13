# 설정 변경 안내

DB 테이블/컬럼, 폴더, 모델 파일명, API 모델 이름을 바꿀 때 Python 코드를 고치지 않는 것이 목적이다. 기본 파일은 `config/default.toml`, 사용자가 관리할 사내 변경값은 `config/site.local.toml`이다. `site.local.toml`은 Git에서 제외한다. Python 3.11 이상에서 표준 `tomllib`을 사용하며 권장 실행 환경은 기존 계획대로 Python 3.12다.

최신 사고명 → Lot → Wafer 연결과 실행 예시는 [INCIDENT_LOT_WAFER.md](INCIDENT_LOT_WAFER.md)를 참고한다. wafer_list와 relations.wafer_parent_key/wafer_scope가 추가됐다.

## 1. 무엇을 어디서 변경하는가

| 변경 대상 | 설정 위치 | 설명 |
|---|---|---|
| 데이터 기준 폴더 | paths.data_root | image/document/trend/sqlite 기본 경로가 함께 따라간다 |
| 이미지/문서/Trend 폴더 | paths.image_root / document_root / trend_root | 서로 다른 mount에 둘 때 각각 지정 |
| 결과/로그/캐시 | paths.output_root / log_root / cache_root | 실제 서비스별 적용 여부는 아래 표 참조 |
| DB 파일/엔진/schema | database.sqlite_file / dialect / schema | SQLite는 구현됨. 다른 엔진은 Adapter 필요 |
| 사고 테이블 | tables.incident.name | 오른쪽 물리 이름 변경 |
| 사고 컬럼 | tables.incident.columns.<논리키> | 논리키는 유지하고 오른쪽 실제 컬럼명 변경 |
| Lot/문서/chunk/이미지/Trend 테이블 | tables.<entity>.name / columns | 총 7개 논리 엔티티의 매핑 |
| 사고-Lot 연결 | relations.incident_parent_key | 내부키 incident_id, 표시번호 incident_number, 고유성 검증된 title |
| 제품세대 저장 타입 | arrays.product_generations | 기존 배열 유지. native_array/json_array/json_text 구분 |
| 모델 공통 폴더 | paths.model_root | 개별 모델 local_dir의 기준 |
| 개별 모델 폴더 | models.<name>.local_dir | 모델별 독립 경로 가능 |
| 체크포인트 파일명 | models.<name>.checkpoint_file | 파일명만. 폴더는 local_dir에서 변경 |
| tokenizer 폴더 | models.<name>.tokenizer_dir | 모델 폴더와 별도로 지정 가능 |
| 모델 API | models.<name>.base_url / served_model | 접속 URL과 API 요청의 model 값 |
| 역할별 모델 선택 | roles.router/answer/judge.model | models에 정의한 논리 모델 이름 참조 |
| 기존 RAG 연결 | retrieval.internal_documents / engineer_notes | endpoint, index_name, 기존 검색 정책 |
| Storage | storage | local/object 계약. object Adapter는 후속 구현 |
| 기간시스템/조치 | enterprise / actions | 연결 계약만 정의, 현재 호출하지 않음 |
| Skill/사전 파일 위치 | paths.skills_root / dictionary_root / registry_file / skill_lock_file | 내용이 같으면 이동 후에도 동일 프롬프트 해시 |
| 더미 데이터 규모 | demo.incident_count / lots_per_incident / trend_points / seed | 새 대상 폴더에 재현 가능한 데이터 생성 |

## 2. 설정 적용 규칙

1. `--config`가 있으면 해당 파일, 없으면 환경변수 `QAGENT_CONFIG`, 둘 다 없으면 번들 `config/default.toml`을 읽는다.
2. `--overlay`가 있으면 해당 파일, 없으면 `QAGENT_OVERLAY`를 읽어 기본 설정에 덮어쓴다. overlay는 한 파일이며 사용하지 않으면 생략한다.
3. TOML table은 재귀 병합한다. 배열과 단일 값은 교체한다. 수정하지 않은 키는 기본값을 유지한다.
4. **모든 내부 상대경로는 기본 TOML 파일이 있는 폴더 기준이다. overlay 파일의 폴더나 실행한 작업 폴더 기준이 아니다.** `--config`/`--overlay` 인자 자체의 상대경로는 명령 실행 위치 기준이다.
5. `${paths.data_root}/images`처럼 paths 참조만 지원한다. 순환 참조나 없는 키는 오류다. 일반 문자열 환경변수 치환은 하지 않는다.
6. 설정 로딩은 디렉터리 생성, DB 쓰기, 원격 접속을 하지 않는다. 값 검증과 `--check-paths` 검사는 별개다.

Linux 경로는 `/appdata/qagent/models`, Windows 경로는 TOML 리터럴 문자열 `model_root = 'D:\models'` 또는 `D:/models`로 적는다. Windows 경로를 Linux에서 사용하면 오류로 처리한다. 네트워크 Storage URI는 local path에 넣지 않고 storage 설정을 사용한다.

## 3. 사내 설정 시작

저장소 루트에서 실행한다.

```bash
cp config/site.example.toml config/site.local.toml
nano config/site.local.toml
python app/config_loader.py --overlay config/site.local.toml
python app/config_loader.py --overlay config/site.local.toml --show
```

`site.example.toml`은 실제 사내 접속정보가 아니다. YOUR_/SET_ 값과 기본값에서 상속된 나머지 컬럼까지 직접 확인해야 한다. `CONFIG_VALID`는 설정 구조 통과이며 실제 DB나 API 연결 성공을 뜻하지 않는다. `--show`는 실제 비밀정보를 읽지 않지만 내부 경로와 호스트명은 출력할 수 있다.

매번 인자를 쓰지 않으려면 다음을 사용한다.

```bash
export QAGENT_OVERLAY=/appdata/qagent/config/site.local.toml
python app/config_loader.py --check-paths
```

DB 비밀번호와 API 토큰은 TOML 값에 넣지 않는다. `dsn_env`, `api_key_env`, `credential_env`에는 환경변수 이름만 적는다. 현재 Loader는 비밀값을 읽지 않는다. 실제 인증값 주입과 검증은 후속 연결 Adapter가 담당한다.

## 4. 사용자가 자주 수정할 예

```toml
[paths]
data_root = "/appdata/quality/data_v2"
model_root = "/appdata/models"
image_root = "/storage/quality/failure_images"

[tables.incident]
name = "QUALITY_INCIDENT_MASTER"
[tables.incident.columns]
incident_id = "INCIDENT_PK"
incident_number = "INCIDENT_NO"
title = "INCIDENT_NAME"
expected_lot_count = "" # 원본에 없는 선택 컬럼은 비워두고 사용 불가로 처리

[tables.lot_list]
name = "QUALITY_INCIDENT_LOTS"
[tables.lot_list.columns]
incident_ref = "INCIDENT_PK"
lot_id = "LOT_ID"

[models.text]
base_url = "http://127.0.0.1:8001/v1"
served_model = "quality-text-model"
local_dir = "${paths.model_root}/text-model-v2"
tokenizer_dir = "${paths.model_root}/text-model-v2"
checkpoint_file = "" # 디렉터리형 모델

[models.image]
local_dir = "${paths.model_root}/wafer-classifier"
checkpoint_file = "best_epoch_24.pt"
```

이 예는 변경 위치를 설명한다. 나머지 실제 컬럼과 API의 served model을 확인한 완성 사내 설정은 아니다. 한글 테이블명과 컬럼명도 단순 identifier이면 SQLite Adapter에서 사용할 수 있다. schema와 table은 분리하며 복잡한 이름은 해당 DB용 quoting/Adapter 구현이 필요하다.

사고의 incident_id/incident_number/title/city/line과 Lot의 4개 필드는 현재 조회 Adapter의 필수값이다. 나머지 선택 컬럼은 `""`로 비워서 매핑에서 제외할 수 있다. expected_lot_count가 없으면 NULL로 반환하고 완전성을 확정하지 않는다. 논리 필드 뜻이나 Join 관계가 바뀌면 이름만 바꾸는 작업이 아니므로 Catalog와 관련 코드를 함께 검토한다.

모델 `local_dir + checkpoint_file`과 API `served_model`은 서로 다르다. API 모드는 이미 실행 중인 서버를 대상으로 한다. 폴더명을 바꿨다고 원격 서버의 모델이 교체되지 않는다. 이 저장소는 vLLM이나 학습 모델을 자동 실행하지 않는다. `enabled=true`도 아직 API 접속이나 모델 로딩을 실행하지 않는다.

## 5. 더미 데이터 계속 생성하기

```bash
python app/generate_dummy.py
python app/query_demo.py --incident-number SYN-2026-0001 --all-pages
python app/generate_dummy.py --overlay config/demo.batch.toml
python app/query_demo.py --overlay config/demo.batch.toml --all-pages
```

기본 세트는 사고 24건, 사고-Lot 관계 96건, 고유 Lot 84개, 사고-Wafer 관계 1,920건, 합성 문서 72개, chunk 216개, SVG 48개, Trend CSV 24개다. batch 설정은 사고 100건, 관계 400건, 고유 Lot 350개, 사고-Wafer 관계 8,000건, 문서 300개, chunk 900개, SVG 200개, Trend CSV 100개다.

실제 문서 저장소나 BM25/vector 인덱스는 만들거나 변경하지 않는다. 문서는 합성 Markdown이고, chunk는 DB fixture다. SVG는 절차적으로 만든 가상 격자이며 실제 FAB/EDS 계측 이미지가 아니다. Trend는 normal/drift/spike/variance/step/missing 시나리오의 합성 수치다. 생성기에서 이상을 심었다는 정보는 탐지 모델의 정답 성능을 의미하지 않는다.

제품세대 다중 배열, null/빈 배열, 사고 간 공유 Lot를 포함한다. 생성 완료 manifest에는 파일 해시와 연결별 건수를 기록한다. source_completeness는 기본 unknown을 유지한다. 더미 관계가 전부 생성됐다는 확인과 실제 운영 ETL 완전성은 구분한다.

기존 파일이 있으면 생성기는 덮어쓰지 않고 오류를 낸다. 다음 세트를 만들 때 data_root와 output_root를 새 폴더로 바꾸고 seed/count를 변경한다. image/document/trend 경로를 개별 지정했다면 이 경로도 새 폴더로 바꾼다. 생성 중 실패한 경우 일부 더미 파일이 남을 수 있으므로 새 폴더를 사용하거나 manifest/설정으로 확인한 합성 결과만 별도로 정리한다.

## 6. 실제 연결된 설정과 후속 구현 설정

| 범위 | 현재 실행 코드에서 적용 |
|---|---|
| DB/table/column/Join/배열 표현 | 더미 생성기와 읽기 전용 SQLite 사고/Lot 조회에 적용. 다른 엔진 접속은 명시적으로 오류 |
| 입력 템플릿, DB 파일, 문서/이미지/Trend/결과 경로 | 생성과 조회에 적용 |
| 페이지 제한, scope 수/만료, DB timeout | SQLite 조회에 적용. scope는 아직 프로세스 메모리이며 운영 ACL/snapshot은 별도 |
| 모델 파일 경로, API 이름, 역할별 모델 | 모델 profile 생성과 설정/선택 파일 검사에 적용. 실제 LLM/추론 호출 미구현 |
| Skill/registry/dictionary/lock 경로 | Skill compiler에 적용. 파일 내용 무결성 검증 |
| 기존 RAG, object storage, 기간시스템, 조치 | 유효한 설정 구조와 계약만 제공. Adapter 실행 미구현 |
| log/cache 경로, Tool 동시 실행/재시도/수정 예산 | 설정 검증만 적용. 해당 Orchestrator와 logging 서비스 구현 시 소비 |

모델 파일이 있어도 가중치 형식/모델 구조 호환까지 검증한 것은 아니다. 원격 서비스 연결, 권한, 인덱스 실제 이름, 운영 조회 성능은 사내 연결 평가 대상이다.

## 7. Skill과 config 변경의 구분

역할 행동과 공유 업무 지침은 app/skills에서 관리한다. 배포 경로와 모델 선택은 config에서 관리한다. 기존 JSON mapping/RAG 예시는 이전 독립 데모용이며 새 CLI의 설정 원본이 아니다.

Skill 소스는 release.lock.json으로 검증한다. 배포 설정은 별도 config_hash를 만들고 조회/컴파일 결과에 기록한다. 모델 이름이나 폴더만 바꾸면 config_hash는 달라지지만 Skill 내용과 prompt hash는 유지된다. config_hash는 설정 내용의 해시이며 DB 내용이나 모델 가중치 파일의 해시를 대신하지 않는다. 원격 모델 revision/데이터 snapshot 고정은 운영 단계에서 추가해야 한다.

```bash
python app/skill_loader.py router --topics terminology,lots --overlay config/site.local.toml
```

Skill 내용이나 코드 릴리스가 바뀐 경우에만 검토 후 명시적으로 `python app/skill_loader.py freeze`를 수행한다. 설정 파일을 바꿀 때마다 freeze하지 않는다. 프로세스/조사 진행 중 자동 hot reload는 구현하지 않았다. 새 설정으로 새 실행을 시작하고 진행 중 조사에 임의로 섞지 않는다.

## 8. 검증 명령

```bash
python app/check_config.py
python app/demo.py
python app/array_demo.py
python app/check_skills.py
```

설정 회귀는 전체 테이블/컬럼/폴더 변경 후 동일 결과, 실제 생성 파일 연결, 모델 참조, 경로 순환, 오타, 필수값, 읽기 전용 연결, scope 만료, Skill 이동, config와 prompt hash 분리를 검사한다. 기존 GPU/자원 산정 문서는 이번 설정과 별개로 원본 그대로 보존한다.
