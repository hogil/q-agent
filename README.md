# Q-Agent

질문을 받아 DB를 조회하고, 근거를 검토한 뒤 답하는 Agent입니다.

## 먼저 볼 곳은 세 군데

| 할 일 | 볼 곳 |
|---|---|
| 실행하기 | [app/run_agent.py](app/run_agent.py) |
| 폴더·DB·모델 설정 바꾸기 | [config/config.yaml](config/config.yaml) |
| LLM 지시문 바꾸기 | [app/skills/roles](app/skills/roles) |

## Skill 폴더

- **roles**: Router(조회 계획), Judge(근거 검토), Answer(답변).
- **schema**: 사고·Lot·Wafer 등 테이블 설명과 해당 조회·통계·문서 규칙.
- **rules**: 용어 해석·조치 경계·오프라인 Skill 관리.
- **core**: 모든 역할이 따르는 공통 규칙.

## 실행 흐름

| 순서 | 하는 일 |
|---|---|
| Router | 무엇을 조회할지 결정 |
| 사고 DB | 사고를 찾고 조회 범위 확인 |
| 후속 Tool | 필요한 Lot·Wafer·회의록 조회 |
| Judge | 근거 확인. 부족하면 Router로 돌아감 |
| Answer | 최종 답변과 조회 범위·한계 표시 |

전체 흐름을 구현한 코드는 [app/agent.py](app/agent.py)입니다.
`models.text.structured_outputs: true`이면 Router도 JSON Schema로 계획을 제출합니다. `false`이면 네이티브 `submit_plan` 함수 호출을 사용합니다. 두 방식 모두 같은 Tool 인자·사고 범위 검증을 거치며, 일반 텍스트를 실행 계획으로 추측하지 않습니다. 로컬 Qwen의 함수 호출 누락에 대응하며 [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)를 사용합니다.
회의록만 묻는 독립 질문은 Router가 independent로 분류해 사고 DB를 열지 않습니다.
나머지 Python 파일은 설정 로딩·모델 통신·조회·검사를 맡는 내부 모듈입니다.

## 실행 준비

Python 3.11+에서 `python -m pip install -r requirements.txt`를 실행합니다.
사내 config·Skill·모델 API 키는 별도로 준비해야 합니다.
[사내 실행 방법](docs/current/ONPREM_RUN.md)에 따라 `--mode run`으로 실행합니다.
기본 `check` 모드는 설정 확인만 합니다. Skill 수정 후에는 검토하고 명시적으로 freeze합니다.

전체 설계·합성 실행·golden 개선 절차는 [현재 설계](docs/current/PROJECT_DESIGN.md)에 정리했습니다.

현재 연결된 Tool은 SQLite 사고·Lot·Wafer와 회의록 검색입니다.
도시·부서·세대 등의 값이 어느 컬럼에 속하는지 DB 값 후보 조회로 확인할 수 있습니다.
회의록은 로컬 FTS5 데모와 사내 Hybrid RAG HTTP 연결을 구분합니다. 사내 서비스는 미검증입니다.
golden 기반 검증과 개선 제안은 오프라인이며, 원본 Skill을 자동 수정하지 않습니다.
실제 모델·데이터 검증, 서버 DB·이미지·조치 Tool과 운영 인증은 아직 남아 있습니다.

## 분석 UI

분석 작업실에는 선택 자료 분석과 후속 질문 입력란이 있으며, 같은 대화방의 전체 채팅도 별도 화면에서 볼 수 있습니다.

- 기본 화면은 브라우저 폭을 모두 사용하는 통합 분석 격자입니다. 상단은 이상감지 Item 표 → Trend → Fab/EDS Corr, 중단은 Lot/Wafer → 개별 Map → 전체 Map → SEM, 하단은 Box plot → Inform/회의록 → 생산/재공입니다. 분석·채팅은 오른쪽에서 중·하단 두 행 높이를 사용합니다. 메뉴와 분석 계획은 겹쳐 여는 패널이며, 작은 화면은 세로 배치로 전환합니다.
- 데스크톱은 패널 모서리 드래그로 폭·높이를 조절합니다. 인접 패널끼리 공간을 배분하며 분석 패널의 너비 조절은 상단 배치를 바꾸지 않습니다. 방향키 조절, Esc 취소, 상단 잠금·기본 배치 복원을 지원합니다. 크기는 이 브라우저의 `qagent:board-layout:v3`에 저장합니다. 이전 배치 값은 그대로 보존하지만 새 구조에 적용하지 않으며 모바일에서는 자동 배치를 사용합니다.
- 각 패널의 확대 버튼은 같은 내용을 모달로 크게 표시합니다. 닫으면 선택·채팅·배치가 유지됩니다. 개별/전체 Map은 휠·버튼 확대, 이동, XY 영역 선택, 전체 보기 복원을 지원합니다. Hover에는 X/Y/R(mm)와 Chip 좌표를 표시합니다. `D:\project\q-agent\config\workbench.yaml`의 `wafer_geometry`는 합성 300 mm 기준이며 실제 치수 검증이 아닙니다. Geometry가 없으면 mm는 미설정으로 표시하고 측정점의 Chip 좌표는 pitch 기준 계산값으로 구분합니다.
- 감지 대상은 설비로 고정하지 않습니다. `Device + Step + Item`과 `legendAxis`/`highlightedMember`를 구분하며, 원본 `D:\project\anomaly-detection\src\data\schema.py`에 맞춰 Equipment·Recipe·Chamber 축을 지원합니다. Recipe는 Recipe로 Fab을 좁히고 Chamber→Fab 매핑이 없으면 Step 범위임을 표시합니다. 비교 그룹이 원인 판정을 뜻하지는 않습니다.
- 감지 항목을 선택하면 옆의 Trend가 바뀝니다. 드래그/슬라이더로 선택한 시간과 설비·Recipe 조건에 맞는 Fab Wafer를 표시합니다. 합성 포함 체크박스로 같은 Die 좌표의 Flag 빈도를 다시 계산합니다. 분모는 좌표별 관측 Wafer 수이며, 누락 좌표를 정상으로 세지 않습니다. 서로 다른 grid나 중복 Wafer는 합성을 거부합니다.
- 이상 표는 Device·Step·Item·EQP 검색, 우선순위 필터, 정렬을 지원합니다. Item 버튼에서 위/아래·Home/End 키로 이동합니다. 필터는 조사 대상을 자동 변경하지 않으며 현재 선택이 숨겨지면 표시합니다.
- Trend 상단 통계는 화면에 그린 대상 Raw 표본의 n·중앙값·IQR입니다. 기준 구간은 감지 시점과 선택 시작 중 이른 시각 이전이며 비교군은 제외합니다. 실제 선택 구간과 기준 구간이 각각 3개 이상일 때 중앙값 차이를 표시합니다. 별도 A/B 수치는 시간 집계 비교이며 유의성 검정이나 원인 판정이 아닙니다.
- 변동 시작점과 Recipe/전산 변경 시각은 합성 메타데이터입니다. 시간상 선후 관계를 보여줄 뿐 원인을 판정하지 않습니다. Map과 SEM의 실제 측정·좌표 정렬도 검증하지 않았습니다.
- Trend는 `D:\project\anomaly-detection\src\data\image_renderer.py`의 표시 방식을 참고한 합성 scatter입니다. Fleet, 선택 설비의 정상/이상 구간, 기준선과 변동 시작점을 표시합니다. 원본 실험 데이터는 복사하지 않았습니다.
- Trend의 XY 드래그는 선택을 교체하며 Ctrl/Meta 드래그는 영역을 추가합니다(최대 16개). 마우스를 놓으면 박스는 사라지고 선택 점만 강조됩니다. 떨어진 영역 사이의 빈 구간은 포함하지 않습니다. Trend/Box plot은 같은 Legend 색을 사용합니다. Lot/Wafer 표는 개별 행 또는 체크된 목록을 탭 구분으로 복사합니다.
- 현재 Wafer는 Fab 단계로 EDS 결과를 생성하지 않습니다. Fab/EDS Corr는 같은 Item·Step의 과거 완료 이력에 설비·Recipe 조건을 적용하고, 현재 선택 시작 시각 이후 완료된 기록을 제외합니다. X는 Fab 온도/Queue/가동률 값, Y는 Yield/Bin 3/Bin 4 값인 산점도입니다. Pearson r은 `simple-statistics`로 계산하며 3쌍 미만 또는 변동이 없으면 N/A입니다. 상관관계를 원인으로 해석하지 않습니다.
- 조사 조건과 선택 Wafer는 방·사고별로 저장합니다. 합성 대상 체크는 현재 화면 상태이며 범위 변경 시 초기화됩니다. 예전 Fab/EDS 근거 참조는 조건만 복원하고, 새 과거 비교가 이전 계산 결과의 재현은 아니라는 안내를 표시합니다.
- Production은 합성 재공 스냅샷(RUN/WAIT/HOLD, Queue, Recipe)과 다운코드를 제공합니다. 다운타임 KPI는 선택 구간과 겹치는 시간의 합계이며, 표의 Duration은 각 이벤트 전체 시간입니다. Assessment는 계산 결과·회의록·미연결 근거를 보여주는 로컬 요약으로, 실제 Judge/Answer 실행 결과가 아닙니다.
- 통합 재공 차트는 Y축 제품, X축 Layer입니다. 제품별 Fab 0.0~End 선 위에 Lot 위치를 표시하고, 현재 재공이 있는 구간으로 축을 제한합니다. 중단 SEM은 Lot/Wafer·EQP·시간으로 A/B를 선택하고 동기 확대·이동, 교환, 전체 화면 비교를 지원합니다. 등록된 합성 이미지 두 장만 표시하며 미등록 이미지는 생성하지 않습니다.
- 개별/전체 Map은 CD(기본)·THK·Overlay·Bin 선택을 공유합니다. CD/THK는 nm 단위 측정점과 Delaunay 삼각형 내부 선형 보간값을 구분하며, 측정 범위 밖은 채우지 않습니다. 전체 Map은 선택 Wafer를 공통 좌표로 보간한 뒤 좌표별 평균을 계산하며 미관측 Wafer는 분모에서 제외합니다. 색상 범위는 개별/전체 간 고정합니다. 개별 통계는 측정점, 전체 통계는 평균 Map의 grid 기준입니다. 현재 측정점은 `D:\project\q-agent\web\src\metrologyMap.ts`의 합성 fixture이며 Raw 파일·측정 시스템·Agent Tool 연결은 아직 없습니다. Bin은 선택 기능으로 남기며 현재 Fab의 CD/THK/Overlay와 EDS 결과를 동일 시점 데이터로 취급하지 않습니다.
- Overlay는 측정점별 벡터 화살표로 Raw/Fit/Res를 동시에 표시합니다. Fit은 `dx=a0+a1*x+a2*y`, `dy=b0+b1*x+b2*y`의 6계수 선형 최소제곱 모델이며 Res는 Raw−Fit입니다. 계산은 [ml-matrix QR](https://mljs.github.io/matrix/classes/QrDecomposition.html)을 사용합니다. 세 Map의 화살표 배율은 같으며 단위는 nm입니다. 전체 Overlay의 Raw는 측정 원본이 아닌 보간 벡터의 Wafer 평균입니다. 실제 장비 보정 모델이나 조치 결과를 뜻하지 않습니다.
- Eng’r Inform은 Equipment 감지의 Step·EQP에 일치하는 문서를 최신순 표로 표시합니다. 비설비 축은 Step과 사용자가 지정한 후속 설비로 조회하며 Recipe/Chamber 문서 Join은 검증되지 않았습니다. UTC 날짜/시간을 포함합니다. 클릭하면 새 창에서 전체 합성 문서를 표시합니다. 회의록 링크는 DB에 저장된 전체 chunk를 열며, 회의 전체 문서를 뜻하지 않습니다.
- 이상 항목을 선택하면 자동 분석을 시작하고 `/api/rooms/{id}/analysis/progress`에서 실제 실행 단계를 표시합니다. 실행 중 다른 항목을 선택하면 최신 선택 하나만 대기합니다. 드래그·Wafer 체크 변경은 자동 재호출하지 않으며 수동 재분석합니다. `/api/rooms/{id}/analysis`는 사고 범위와 Wafer 키를 검증합니다. 기본값은 DB 조회 데모이며 명시적인 `agent_overlay`를 설정하면 Router → Tool → Judge → Answer를 실제 호출합니다. 선택하지 않은 회의록과 UI 이미지 모델 호출은 차단합니다. 조건과 역할 실행 기록은 SQLite에 저장하고 후속 질문에서 재사용합니다. 모델 오류를 데모 답변으로 대체하지 않습니다.
- Overview는 사고 DB 기록과 최근 승인 회의록을 분리해 보여줍니다. Review에서 선택 근거의 원문·기준일·버전을 비교하고 사용자 메모와 출처를 JSON으로 내보냅니다. 이 검토는 Judge의 판정이 아닙니다.
- 분석 패널은 답변·부분 조회·실패를 먼저 표시하고 상세 실행 기록은 접어 둡니다. 재실행 중에는 이전 답변을 새 결과로 표시하지 않습니다. 조회/미연결 수는 실제 응답의 자료 상태를 사용합니다.
- 분석 계획: 기능별 체크, 화면 이동, 질문 준비. 선택은 실제 Agent 실행이나 검증 완료를 의미하지 않습니다.
- 채팅: 방별 질문·답변 저장, 이름 변경·삭제, 이전 기록 조회, 근거의 사고 범위 확인.

로컬 합성 데이터 데모 실행 (Python 3.11+, Node.js 22+):

```powershell
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
python app/workbench.py --port 8787
```

브라우저: `http://127.0.0.1:8787/`, 별도 채팅: `http://127.0.0.1:8787/?view=chat`.
8787 포트가 사용 중이면 `--port 8788`처럼 다른 포트를 지정합니다.

설정은 `D:\project\q-agent\config\workbench.yaml`입니다. 기본 DB 설정은 기존 `config.yaml` + `demo.yaml`을 사용합니다.
첫 실행에서 합성 DB가 모두 없을 때만 생성하고, 일부만 있으면 덮어쓰지 않고 중단합니다.
대화는 `D:\project\q-agent\var\data\workbench\conversations.sqlite`에 별도로 저장합니다.
준비한 질문·선택 근거·검토 메모는 대화방과 사고별로 이 브라우저의 localStorage에 저장합니다. 다른 브라우저와 동기화되지 않으며 브라우저 데이터 삭제 시 사라집니다. 문서 원문은 저장하지 않고 조회 시 가져옵니다. 개인정보가 포함된 메모를 공용 PC에 남기지 마세요.

**연결 범위:** 사고·Lot·Wafer·회의록은 합성 DB를 실제 조회합니다. Trend/Map은 합성 데이터, SEM은 AI 생성 이미지입니다.
Eng’r Inform·생산 시스템·이미지/Trend 모델은 미연결입니다. 기본 채팅은 결정적 DB 조회 데모입니다. LLM 모드는 같은 방·사고의 최근 8개 메시지를 각각 600자까지 참고 입력으로 전달하며, 이전 답변을 Tool 근거로 사용하지 않습니다. 무제한 대화 메모리는 아닙니다.
감지 항목·Trend·현재 Fab·재공·다운코드·변경 이력·Inform·SEM 연결은 설정의 `sources.raw_file`에서 읽습니다. 과거 완료 Fab/EDS와 Map은 아직 `D:\project\q-agent\web\src\historicalData.ts`, `D:\project\q-agent\web\src\waferMaps.ts`의 합성 데이터입니다. 등록 Lot/Wafer ID를 재사용해도 실제 생산 상태나 영향 범위가 검증된 것은 아닙니다. 실제 연결에는 서버 측 권한 검증, 원본 Adapter, 단위·시간대·재작업 매칭, Agent Tool 계약이 필요합니다.
서버는 localhost 전용 단일 사용자 데모입니다. 사내 원격 서비스로 공개하지 마세요.

### Raw 데이터와 환경 설정

UI 실행 설정의 진입점은 `D:\project\q-agent\config\workbench.yaml`입니다. Agent 설정은 이 파일이 지정하는 `D:\project\q-agent\config\config.yaml` + overlay를 그대로 사용합니다.

| 설정 | 용도 |
|---|---|
| `server.port` | HTTP 포트 |
| `sources.raw_file` | Raw JSON 파일 |
| `demo.base_config`, `demo.overlay` | Agent 기본/합성 DB 설정 |
| `agent_overlay` | 선택적 LLM 설정 파일 |
| `chat.sqlite_file`, `static_root` | 대화 DB, 빌드된 UI 폴더 |

YAML 안의 상대 경로는 해당 YAML 폴더 기준입니다. CLI/환경변수의 상대 경로는 실행 디렉터리 기준이며 환경변수가 YAML보다 우선합니다. API 키는 기존 `api_key_env`가 가리키는 환경변수로만 전달합니다.

Raw 예제는 `D:\project\q-agent\data\workbench\raw.example.json`입니다. `incidents[사고번호].engineering.signals`가 이상 Raw 목록이며, `trend_fleets`, `comparison_traces`, `inform_notes`, `sem_assets`가 연결 자료입니다. Drift, level shift, spike, variance burst, periodic pattern을 포함합니다. 파일 누락·잘못된 값·참조 불일치는 중단하며 자동 데모 대체는 없습니다. 현재 로더는 **합성 자료만 허용**합니다. 실제 자료 전환 시 `synthetic` 표시를 거짓으로 바꾸는 것만으로 운영 연결이 되지는 않습니다.

Linux 실행 예시(경로는 Linux 배치 위치로 지정):

```bash
QAGENT_WORKBENCH_CONFIG=/srv/q-agent/config/workbench.yaml \
QAGENT_RAW_FILE=/srv/q-agent/data/workbench/raw.example.json \
QAGENT_PORT=8787 PYTHON_BINARY=python3 \
bash /srv/q-agent/start.sh
```

LLM을 켜려면 `QAGENT_LLM_OVERLAY=/srv/q-agent/config/llm.local.yaml`과 설정된 키 환경변수도 함께 전달합니다. Windows는 `D:\project\q-agent\start.ps1`에 같은 환경변수를 사용합니다. 스크립트는 설치·빌드·Skill 수정을 자동 수행하지 않습니다.

예제를 다시 생성할 때는 실행 중인 로컬 합성 서버에 대해 `node --experimental-strip-types D:/project/q-agent/web/scripts/export-workbench-data.mjs --output D:/project/q-agent/var/raw.preview.json`을 사용합니다. 기존 출력 파일은 덮어쓰지 않습니다.

### 로컬 LLM 연결

`D:\project\q-agent\config\workbench.local.yaml`에 기본 workbench 설정과 `agent_overlay: llm.local.yaml`을 지정합니다. `D:\project\q-agent\config\llm.local.yaml`은 `models`, `roles`, `runtime`만 재정의하며 DB 경로 변경은 거부합니다. 두 로컬 파일은 Git에서 제외됩니다.

```yaml
models:
  text:
    enabled: true
    base_url: http://127.0.0.1:11434/v1
    served_model: YOUR_INSTALLED_TOOL_CALLING_MODEL
    api_key_env: QAGENT_LLM_API_KEY
```

```powershell
$env:QAGENT_LLM_API_KEY = 'ollama' # Only for local Ollama; not a real credential.
python D:/project/q-agent/app/workbench.py --config D:/project/q-agent/config/workbench.local.yaml --port 8787
```

OpenAI-compatible endpoint, native `submit_plan` function calling, Judge/Answer JSON 응답이 필요합니다. 긴 Skill 입력이 서버 컨텍스트에서 잘리지 않도록 모델 설정을 확인하세요. 설정됨·실제 응답 확인·검증된 최종 답변은 별개이며, 합성 DB 모델 실행을 사내 데이터 품질 검증으로 해석하지 않습니다.
