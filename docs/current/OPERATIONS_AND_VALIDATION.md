# 운영 및 로컬 검증

기준: 2026-11-02. 이 문서는 저장소 안에서 확인 가능한 설정/Skill 검사, 합성 조회의 실행 경계 및 문제 진단을 설명한다. 실행 결과가 `CONFIG_AND_SKILLS_VALID`이어도 사내 DB/API/ACL/모델 연결이나 실제 답변 품질이 검증된 것은 아니다. 평가 스크립트와 광범위 Q-Agent 정답 질문 세트는 복원하지 않는다.

## 실행 환경과 설정 선택

Python 3.11 이상을 사용한다. 의존성은 저장소 `requirements.txt`에 정의되어 있으나 loader 검사만을 위해 자동 설치할 필요는 없다. 본체 배포 설정의 단일 진입점은 `config/config.yaml`과 필요 시 site overlay다. 두 파일은 재귀 mapping 병합되며 배열과 scalar는 overlay 값으로 교체된다. 설정 내부 상대경로는 overlay 폴더가 아니라 기본 `config/config.yaml` 위치를 기준으로 해석된다.

`app/config_loader.py`는 YAML 형식, 키/타입/값 및 선택적 경로 존재를 확인한다. 설정 로딩은 디렉터리 생성, DB 쓰기, 원격 접속, secret 읽기를 하지 않는다. `--show`는 비밀값을 읽지 않지만 내부 경로/호스트를 출력할 수 있다.

`app/run_agent.py`는 실행 환경을 반드시 명시한다.

- `--demo`: 번들 base + `config/demo.yaml`의 합성 환경. 선택적 `--demo-overlay`를 추가할 수 있다.
- `--site-config <파일>`: `environment: onprem`, database와 7개 테이블의 명시적 mapping, Skill registry/lock/dictionary 경로와 무결성 검증 등 site 요구조건을 검사한다. 누락된 site 파일을 자동 생성하지 않는다.
- demo 선택을 site fallback으로 사용하지 않는다. `run_agent.py`에서 site 모드는 `--site-config`를 통해 들어가므로 환경변수 overlay만으로 site를 암묵 적용하지 않는다.

## 권장 안전 점검

아래 명령은 저장소 루트 `D:\project\q-agent`에서 실행한다. `config_loader`는 base 설정을 읽고 `skill_loader router`는 기본 설정에 연결된 Router Skill을 compile한다. `run_agent --demo --mode check`는 Router/Judge/Answer의 설정 및 Skill release integrity를 확인하고 네트워크 호출을 하지 않는다.

```powershell
python app/config_loader.py
python app/config_loader.py --check-paths
python app/skill_loader.py router --topics incident_search
python app/run_agent.py --demo --mode check
```

site 파일이 이미 있고 담당자가 검토한 경우에만 별도 구조 검사를 할 수 있다.

```powershell
python app/config_loader.py --overlay config/site.local.yaml
python app/config_loader.py --overlay config/site.local.yaml --check-paths
```

`CONFIG_VALID`는 loader 구조 통과이며 실제 소스 접속 결과가 아니다. site 운영 전용 엄격 검사는 별도 `scripts/run_onprem.ps1` 또는 Linux 스크립트 계약을 참조한다. 경로와 접근 권한, 사내 schema/data semantics, source ACL은 해당 환경 소유자가 확인해야 한다. secret은 YAML에 기록하지 않고 설정이 가리키는 환경변수 이름을 사용한다.

## 조회 CLI와 위험 경계

`app/run_agent.py --mode run`은 API를 활성화한 설정이면 Router → Tool → Judge → Answer를 실제 호출할 수 있다. 외부 API나 site 데이터 접근 전에 실행 대상, 설정, 질문, actor 및 `--trace` 내용 노출을 검토한다. `--trace`는 진행 이벤트/내부 조회 데이터를 stderr에 쓸 수 있다. actor는 인증이나 ACL이 아니다. 여기 문서의 검사 명령은 `--mode run`을 실행하지 않는다.

합성 fixture를 별도 연구 작업으로 준비할 때의 격리 overlay 경로 키는 다음과 같다. 모든 경로는 기본 `config/config.yaml`을 기준으로 resolve된다.

```yaml
paths:
  data_root: ../var/data/manual-synthetic-isolated
  golden_file: ${paths.data_root}/golden.jsonl
database:
  sqlite_file: ${paths.data_root}/quality_demo.sqlite
meetings:
  sqlite_file: ${paths.data_root}/meetings.sqlite
```

이는 경로 예시일 뿐 실행 지시가 아니다. `app/run_agent.py --mode prepare-demo`에는 출력 디렉터리 인자가 없다. 경로는 설정의 `paths.data_root`, `database.sqlite_file`, `meetings.sqlite_file`, `paths.golden_file`로 정해지며 `app/demo_data.py::generate`는 기본 `include_goldens=True`로 합성 golden 질문 세트도 쓴다. 따라서 이 CLI를 안전한 조회 점검 명령으로 제시하지 않는다. 사용자 규칙에 따라 평가/golden 생성은 실행하지 않는다. `app/workbench.py`가 처음 시작할 때 호출하는 내부 생성 경로는 코드상 `include_goldens=False`지만, 별도 서버 실행 및 설정 경로가 필요하므로 단순 loader 확인 대체 명령으로 취급하지 않는다. 격리 경로를 검토할 때는 overlay의 `paths.data_root`와 DB 경로들이 모두 새 `var/` 하위로 resolve되는지 먼저 확인한다. 이 경로 변경만으로 `prepare-demo`의 golden 쓰기가 허용된다고 해석하지 않는다. 조회 요청은 실제 사고번호를 포함하지 않는 synthetic fixture에서만 수행한다. base config만으로 demo DB가 준비돼 있거나 live 조회가 성공한다고 가정하지 않는다.

읽기 전용 기준은 `config/config.yaml`의 demo SQLite 계약과 runtime adapter다. 운영 DB 연결은 SQLite 외 adapter가 필요한데 현재 site DB driver가 완성된 상태가 아니다. DB를 직접 수정하는 SQL, 쓰기 권한, 생산 action 실행은 이 운영 절차에 포함하지 않는다.

## 기능 활성화 조건 점검

설정에서 `enabled: true`만 바꿔도 backend가 생기지 않는다. 다음 조건을 모두 확인해야 한다.

| 기능군 | 필요한 요소 |
|---|---|
| 사고/통계/Lot/Wafer | 지원 adapter, 명시 logical table/column/Join mapping, read-only connection, scope/completeness 계약 |
| text LLM | Router/Judge/Answer 모델 설정과 실행 중인 호환 endpoint, credential 환경변수, JSON/function-call 지원 |
| 이미지 비교 | asset metadata와 retrieval 경로, modality별 specialist endpoint 및 모델 버전/정렬 확인 |
| 내부문서/Eng’r Inform | 기존 chunk/index source, caller 주입 `document_query`, source 활성화와 허용 status, source provenance 및 ACL 검토 |
| 회의록 | 활성 backend와 실제 index/table; 로컬 SQLite FTS는 합성/lexical demo일 수 있음 |
| MES 기준정보 | allowed kinds, mapped logical columns, synthetic SQLite 또는 trusted site callback, `available_at`/effective window/적용성 확인 |
| FBM | 동일 incident-Lot-Wafer tuple 조회, representation별 별도 callback, model/preprocess/checkpoint provenance, `as_of`/completeness 계약 |
| 합성 action evidence | 명시 사용자 요청, 선택 사고, 완전한 영향 Wafer scope, trusted snapshot lease와 합성 callback |

site ACL, 생산 action executor, source 의미 검증 및 실제 모델 검증은 별도 구현/운영 요건이다. 설정 flag나 callback response schema만으로 충족했다고 표시하지 않는다.

## 실패 진단

| 증상 | 확인할 내용 |
|---|---|
| `CONFIG_ERROR` 또는 알 수 없는 키/타입 | base와 overlay 버전, YAML 중복 키, `config_loader.py --show`; 임의 키 추가 대신 `SPEC` 허용 스키마와 비교 |
| 경로 검사 실패 | 경로 기준은 base YAML 위치인지 확인하고, 실제 디렉터리/파일을 확인. overlay 위치 기준으로 상대경로를 옮기지 않음 |
| `Skill release mismatch` 또는 prompt compile 실패 | `skill_loader router` 또는 `run_agent --demo --mode check`로 원인 범주를 확인. 현재 운영 Skill/config의 출처를 대조하고 허가된 release 절차 없이 lock/freeze를 덮지 않음 |
| site 실행에서 `environment`, mapping, dictionary 오류 | 명시 `environment: onprem`, database connection fields, 7개 table 이름과 모든 logical columns, site dictionary `synthetic: false`, registry/lock/resource 경로 존재 확인 |
| `search_internal_documents`/`search_engineer_notes` unavailable | source flag 외에 유효 status allowlist와 callable `document_query`가 실제 runtime에 주입됐는지 확인. CLI 설정만으로 BM25/vector source가 생기지 않음 |
| `search_mes_reference` unavailable 또는 실패 | 기능 flag, allowed kind, 설정된 synthetic DB의 파일 존재/읽기 전용 접근, 논리컬럼 매핑, callback 응답 및 cutoff metadata 확인. 합성 adapter를 site MES로 오인하지 않음 |
| 사고 후속 Tool이 실행되지 않음 | incident 검색 status, 복수 후보 명시 선택, scope 만료, 사고 DB evidence 검증, Lot 조회 chain 및 Tool budget 확인 |
| 페이지 조회 후 전체목록/원인 주장에 부족 | page chain과 `source_completeness`, `wafer_scope`, coverage를 따로 확인. `unknown`/`partial`은 그대로 유지. `lot_inventory`를 영향 Wafer로 승격하지 않음 |
| 모델 비교가 `INCOMPARABLE`/unavailable | specialist endpoint enabled/연결 여부, asset ID·revision·Item 일치, alignment/model version/시간 metadata 확인. 그 상태를 성공 비교로 바꾸지 않음 |

`run_agent.py` 오류 출력은 민감 경로/입력을 줄이기 위해 일부 예외를 유형만 표시할 수 있다. 원격 호출 없이 loader와 Skill CLI의 구조적 진단부터 확인한다. 실패를 0건 결과, 빈 scope 또는 정상 근거로 바꾸지 않는다.

## 저장소·데이터 보호

- `config/*local.yaml`, `*.local.toml`, secret, 실제 사내 Lot/이미지/문서와 DB를 합성 예제·Git에 넣지 않는다.
- `var/` 생성 DB, 전체 결과 및 출력 산출물은 Git에 올리지 않는다.
- 합성 입력은 식별자/내용이 실제와 무관하도록 생성한다. 사내 문서나 실제 Lot 값을 예제에 복사하지 않는다.
- `docs/current/RESOURCE_PRESERVATION.json`의 보존 대상 GPU, 서버, VM, DB 용량, 스토리지, 예산, ROI 자료는 삭제/수정/이동하지 않는다. 원본 경로와 Git blob hash를 유지해야 한다.
- 평가 스크립트나 포괄적인 LLM 정답 질문 세트를 복원하지 않는다. 사용자 요청이 있는 제한된 연구용 NL2SQL synthetic set과 포괄 Q-Agent answer evaluation은 서로 다른 목적이다.

## 구현 및 미확인 범위

Loader/skill compiler 검사 성공은 파일 형식·설정 계약·Skill release consistency를 확인할 뿐, 실제 LLM Router/Judge/Answer 실행, 사내 DB schema/data, 사용자 ACL, RAG 검색 완전성, 생산계 조치를 증명하지 않는다. 기본 `models.text.enabled`, 이미지/Trend model, RAG, meetings, enterprise, MES reference, FBM, actions 및 synthetic action planner는 config에서 false다. 일부 Tool은 Workbench에 코드 경로 또는 synthetic callback 계약이 있어도 기본 CLI에서 실제 backend가 연결되지 않는다.

## 참조

- [설정 명세](CONFIGURATION.md)
- [사내 실행 계약](ONPREM_RUN.md)
- [Skill 목록](SKILLS.md)
- [현재 Tool coverage](TOOL_CAPABILITY_COVERAGE.md)
- [자원 보존 manifest](RESOURCE_PRESERVATION.json)
