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

분석 작업실과 채팅은 별도 화면입니다. 작업실에서 기능을 열고 근거를 선택한 뒤 같은 대화방의 채팅으로 넘깁니다.

- 작업실: Overview, Trend, Wafer/SEM/Image/Overlay Map, Inform, Production, History, Data, Review.
- 엔지니어 조사: Signals에서 이상 항목 선택 → Trend 드래그/슬라이더 구간 지정 → Fab × EDS 상관분석 → 생산·설비·문서·이미지 → Assessment. 조사 조건은 방·사고별로 보관하며, 선택 근거를 다시 열면 저장 당시 조건을 복원합니다.
- 조사 화면은 설비·Recipe 조건을 공유합니다. 상관분석의 Wafer 상세 패널에서 관측점을 순회하고 Map/SEM/Overlay로 이동합니다. 선택 Wafer는 방·사고별로 저장하며 현재 매칭 범위에 있을 때만 복원합니다. 모바일은 화면 선택 메뉴와 가로 스크롤 없는 감지 목록을 사용합니다.
- Fab/EDS는 합성 측정값을 `Lot + Wafer`로 매칭하고 Recipe·설비·Fab 시각·EDS 시차를 적용합니다. 중복·누락·시차 제외를 별도 집계합니다. Pearson r은 [simple-statistics](https://simple-statistics.github.io/docs/#samplecorrelation)로 계산하며 3쌍 미만 또는 값의 변동이 없으면 N/A입니다. 인과관계나 독립 표본의 통계적 유의성을 판정하지 않습니다.
- Production은 합성 재공 스냅샷(RUN/WAIT/HOLD, Queue, Recipe)과 다운코드를 제공합니다. 다운타임 KPI는 선택 구간과 겹치는 시간의 합계이며, 표의 Duration은 각 이벤트 전체 시간입니다. Assessment는 계산 결과·회의록·미연결 근거를 보여주는 로컬 요약으로, 실제 Judge/Answer 실행 결과가 아닙니다.
- Overview는 사고 DB 기록과 최근 승인 회의록을 분리해 보여줍니다. Review에서 선택 근거의 원문·기준일·버전을 비교하고 사용자 메모와 출처를 JSON으로 내보냅니다. 이 검토는 Judge의 판정이 아닙니다.
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
Eng’r Inform·생산 시스템·LLM은 미연결입니다. 채팅은 결정적 DB 조회 데모이며, 대화 저장이 모델 메모리 연결을 뜻하지 않습니다.
감지 이벤트·Fab/EDS 값·재공 상태·다운코드는 `D:\project\q-agent\web\src\engineeringData.ts`의 결정적 합성 데이터입니다. 등록 Lot/Wafer ID를 재사용해도 실제 생산 상태나 영향 범위가 검증된 것은 아닙니다. 실제 시스템에 적용하려면 서버 측 권한 검증, 원본 Adapter, 단위·시간대·재작업 이력 매칭, Agent Tool 계약이 추가로 필요합니다.
서버는 localhost 전용 단일 사용자 데모입니다. 사내 원격 서비스로 공개하지 마세요.
