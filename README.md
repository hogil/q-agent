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
