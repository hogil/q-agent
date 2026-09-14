# Agent 파일 구성

## 현재 실행 코드

run_agent.py의 run 모드가 agent.py의 ReAct 루프를 실행한다. llm_client.py가 설정된
Router/Judge/Answer 모델 API를 호출한다. 실제 사내 모델·DB 검증과 운영 인증은 별도다.

| 순서 | 담당 파일 | 하는 일 |
|---|---|---|
| 설정 | config/config.yaml + site overlay | DB/폴더/모델/Tool 설정의 시작점 |
| 설정 로딩 | app/config_loader.py | YAML 병합, 타입/경로 검사, 논리 컬럼을 물리 컬럼으로 매핑 |
| 사내 실행 진입점 | scripts/run_onprem.sh, scripts/run_onprem.ps1 → app/run_agent.py | check/prompt/run 모드 선택 |
| ReAct 루프 | app/agent.py | Router → Tool → Judge → Answer, 재조회·근거·범위·예산 관리 |
| 모델 API | app/llm_client.py | 역할별 설정으로 OpenAI 호환 SDK 호출, Router 함수 호출과 JSON 응답 처리 |
| 프롬프트 조립 | app/skill_loader.py | 공통 Skill + topic + 역할 Skill을 읽고 해시/문자 제한 확인 |
| Router | app/skills/roles/router/SKILL.md | 질문 조건과 다음 Tool 계획에 대한 시스템 지침 |
| 출력 검사 | app/prompt_contracts.py | Router/Judge/Answer JSON 형식, 단계, scope, 근거 ID 검사 |
| Tool 실행 | app/agent.py의 invoke | 검사된 단일 Tool을 호출하고 scope·근거·예산 갱신 |
| DB 연결 | app/runtime_factory.py | 설정된 SQLite에 읽기 전용 연결, timeout 적용, 연결 종료 |
| 사고/Lot/Wafer Tool | app/incident_tools.py | 값·컬럼 후보 조회, 검색, 사고 선택, scope 발급, 관계/수량/페이지 조회 |
| 검색 조건 | app/incident_filters.py | 허용된 필터를 SQL 조건과 바인딩 값으로 변환 |
| Judge | app/skills/roles/judge/SKILL.md | 근거 부족/충돌/범위 오류를 검토하는 시스템 지침 |
| Answer | app/skills/roles/answer/SKILL.md | 검토한 근거로 최종 답변을 작성하는 시스템 지침 |

Judge가 추가 근거를 요구하면 같은 Router로 돌아가고 Answer는 마지막에 배치한다.
agent.py가 호출 순서, 단일 Tool 실행과 종료 한도를 함께 제어한다.

## Skill 구성

- app/skill_registry.json: 역할별 Skill과 허용 topic 등록.
- app/release.lock.json: 배포할 Skill/실행 코드의 해시.
- app/skills/core: 모든 역할에 적용할 규칙과 업무 태도.
- app/skills/roles/router, judge, answer: 역할별 지시문.
- 각 역할의 references/output.schema.json: 출력 JSON 형식.
- 각 역할의 references/conditions.md: 모델이 참고할 조건별 행동 예시.
- schema 아래 7개 Skill: 논리 컬럼 설명과 해당 검색/조회/통계/문서 규칙.
- rules 아래 3개 Skill: terminology, actions, skill-maintenance.

Skill 파일이 있다는 사실은 해당 RAG/통계/조치 Tool이 운영 환경에 연결됐다는 뜻이 아니다.

## 실제 실행 진입점

scripts/run_onprem.sh 또는 scripts/run_onprem.ps1 → app/run_agent.py →
app/config_loader.py → app/skill_loader.py 순서로 실행한다.
check/prompt는 설정 확인과 프롬프트 출력만 한다. run은 agent.py → llm_client.py 및
agent.py의 invoke → runtime_factory.py → incident_tools.py로 이어진다.

app/query_demo.py는 기존 SQLite를 직접 조회하는 개발용 CLI다. runtime_factory와
incident_tools를 호출하며 운영 인증이나 LLM을 거치지 않는다.
app/terminology.py의 match_values는 DB 값과 질문 표현을 비교해 컬럼·값 후보를 만든다.
기존 라벨 입력 사전 정규화 코드는 별도로 남아 있으며 Agent의 사전 조회로 연결되지는 않았다.
합성 데이터 생성기와 합성 사전은 제거했다. 사내 사전은 별도로 준비한다.

## Tool 호출 연결

agent.py는 등록된 Tool 이름, 단일 계획, 인자 schema와 Python 시그니처를 검사한 뒤
invoke(name, **arguments)를 호출한다. 사용자 정보와 검증된 scope는 코드가 바인딩한다.
출력 JSON이 임의 함수를 실행하지는 않는다.

request_scope=incident이면 사고 DB 조회와 scope 규칙을 적용한다.
request_scope=independent이면 사고 검색을 거부하고 독립 Tool 또는 무조회 경로만 허용한다.
request_scope를 정하는 운영 분류기, 인증과 Adapter별 권한 검사는 별도 연결 대상이다.

## 생성된 프롬프트

`config/config.yaml`의 `database`에 host/port/name/schema/sqlite_file을,
`tables`에 실제 테이블/컬럼명을 관리한다. 서버 DB 접속은 아직 미구현이다.

컬럼 설명은 테이블별로 분리되어 있다.

| 테이블 | 설명 파일 |
|---|---|
| 사고 | app/skills/schema/incident-schema/references/logical-schema.json |
| Lot | app/skills/schema/lot-schema/references/columns.json |
| Wafer | app/skills/schema/wafer-schema/references/columns.json |
| 사고 문서 | app/skills/schema/incident-document-schema/references/columns.json |
| 문서 chunk | app/skills/schema/document-chunk-schema/references/columns.json |
| 이미지 | app/skills/schema/image-metadata-schema/references/columns.json |
| Trend | app/skills/schema/trend-metadata-schema/references/columns.json |

조립 순서는 공통 규칙 + 선택 topic의 Skill/컬럼 설명 + 역할 지침 + config의 선택 테이블 매핑이다.
`incident_search`는 사고 설명을 포함하고, `wafers`는 사고/Lot/Wafer 설명을 함께 로딩한다.
접속 주소/포트/DB 이름/인증정보는 프롬프트에 넣지 않는다. 실제 매핑은
`[runtime/schema-mapping]` 블록에서 확인할 수 있다. 설명은 합성 데이터 기반 초안이며
사내 스키마 검증 완료를 의미하지 않는다.

app/export_system_prompts.py는 필요할 때 설정된 output_root 아래에 프롬프트 파일과
manifest를 생성하는 도구다. 저장소에 생성 결과는 포함하지 않는다.
수정할 원본은 app/skills이며 run_agent.py --mode prompt는 파일 쓰기 없이 출력한다.

평가 스크립트/정답 세트/평가 보고서는 삭제했다. prompt_contracts.py와
config_loader.py의 검사는 실제 실행 경로를 보호하므로 유지한다.
