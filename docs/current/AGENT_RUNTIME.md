# ReAct 실행

## 실제 호출 흐름

| 순서 | 파일 | 동작 |
|---|---|---|
| 진입 | app/run_agent.py | 사내 config/Skill 검증, run 인자 확인 |
| 시작 | app/agent.py | 질문, 호출자, 요청 범위, 예산과 근거 상태 생성 |
| Router | app/skill_loader.py → app/llm_client.py | Router Skill 조립 후 설정된 모델 호출 |
| 사고 DB | app/agent.py의 invoke → app/runtime_factory.py → app/incident_tools.py | 필요 시 값·컬럼 후보 조회 후 find_incidents 실행, 읽기 전용 연결과 scope 발급 |
| 후속 Tool | 같은 실행기 → incident_tools.py | 같은 scope의 Lot, 이후 Wafer 조회 |
| Judge | skill_loader.py → llm_client.py | 조회 근거의 ID와 요구사항을 검토 |
| Answer | skill_loader.py → llm_client.py | Judge pass/abstain 후 최종 JSON 생성 |
| 최종 표시 | run_agent.py | 답변·조회 상태·사고 scope·근거·이벤트 출력 |

Judge의 need_evidence/revise는 같은 Router로 돌아간다. revise는 기존 scope와 근거를
무효화하고 새 사고 조회를 요구한다. Answer 이후 Router나 Judge를 다시 호출하지 않는다.

## Function calling

OpenAI Python SDK의 Chat Completions를 사용한다. 사내 모델 서버는 해당 호환 프로토콜의
function calling과 JSON object 응답을 지원해야 한다. Responses API 전용 서버는 지원하지 않는다.
참고: [공식 Function calling 문서](https://developers.openai.com/api/docs/guides/function-calling).

Router의 native tool_call 이름은 `submit_plan`이다. 그 arguments에는 기존 Router JSON
전체가 들어간다. 실제 업무 Tool은 JSON 안의 plan에 지정한다. 각 DB 함수를 모델 SDK에
직접 등록한 방식이 아니라, 검증 가능한 계획 제출 함수를 통해 실행하는 방식이다.

```json
{
  "intents": ["search"], "filters": {},
  "plan": [{"tool": "find_incidents", "arguments": {"incident_number": "USER_SUPPLIED_NUMBER"}, "depends_on": [], "reason": "질문에 명시된 사고 조회"}],
  "needs_skills": [], "clarification": null,
  "decision": "execute", "stage": "incident", "search_mode": "sql_exact", "limitations": []
}
```

위 번호는 실행 예시용 placeholder다. 실제 입력에서 얻은 번호를 사용한다.
Tool 실행 결과는 원래 tool_call_id와 연결한 role=tool 메시지로 다음 Router 호출에 전달한다.
사고 조회는 한 단계에 한 Tool만 실행한다. scope 검증 후 현재 활성화된 독립적인 후속 Tool은
최대 4개를 한 계획에 묶는다. 전체 인자를 먼저 검사하고 순차 실행하며, 실패하면 나머지를
중단한다. 같은 계획의 앞 Tool이 반환할 ID를 미리 가정할 수 없다. 실제 SQL이나 actor/scope_id를 모델이 지정할 수 없다.

find_incidents는 fields에 지정한 매핑된 논리 컬럼을 기본 요약 목록에 추가할 수 있다.
원인·조치 질문에만 필요한 상세 컬럼을 요청한다. 생략하면 기존 목록 크기를 유지하며,
미매핑·잘못된 컬럼은 거부한다. 별도 RAG/Hybrid 검색 구현을 의미하지 않는다.

match_incident_values는 arguments={}로 호출하며 원문 질문은 코드가 바인딩한다.
설정한 사고 컬럼의 unique value에서 질문에 등장한 값만 candidates로 반환한다.
배열은 원소별로 비교하고, 같은 표현이 여러 컬럼/값에 걸리면 ambiguous로 표시한다.
후보 발견은 포함/제외/인용 문맥의 판단이나 사고 검색을 대신하지 않는다. 이 Tool은
scope와 incident_checked를 발급하지 않으며, 실제 검색은 find_incidents로 수행한다.
현재는 정확한 정규화 일치와 제한된 한국어 조사 처리를 지원한다. 사전 별칭·퍼지 검색·
영속 값 인덱스는 연결하지 않았다. 후보 조회도 Tool 예산과 DB timeout을 사용한다.

Router history에는 이전 함수 호출과 결과만 보관한다. 전체 상태·근거 payload는 최신
user 메시지로 한 번만 전달하며, 과거 payload를 매번 누적하지 않는다. 이전 Tool 결과가
history에 남아 있어도 현재 evidence_ids와 유효 scope에 없는 근거는 재사용하지 않는다.
컨텍스트 제한, Tool 인자·scope 검사와 호출 전 릴리스 해시 검사는 유지한다.
명시적 requested_tools 워크플로에서는 완료된 Engineering/회의록/이미지 결과를 Router용
조회 상태로 축약한다. 실제 원문 근거는 폐기하지 않고 Judge/Answer에 전달한다.
`structured_outputs: true`에서는 역할 JSON 계약을 response_format으로 검증하되, 의미 이해를
위해 시스템 프롬프트에도 계약을 유지한다. 스키마 제거는 로컬 Qwen에서 빈 계획 회귀를 보였다.
`llm_output.metrics`에 호출 시간·입출력 토큰을 기록한다. 출력 한도 초과는 MODEL_OUTPUT_LIMIT로
구분하며 잘린 JSON을 성공 답변으로 복구하지 않는다.

## 역할별 Skill 관리

- 각 API 호출 전에 공통 Skill + 선택 topic + 역할 Skill + config 매핑을 조립한다.
- 실행 전체의 topic은 역할별 허용 목록으로 분리한다. loaded_topics는 해당 역할이 실제로 읽은 topic이다. 알 수 없는 topic과 온라인 비허용 topic은 거부한다.
- 세 역할의 모델/temperature/출력 한도는 roles와 models 설정에서 읽는다.
- output.schema.json과 tools.json도 같은 사내 skills_root에서 읽는다.
- Skill·사전·실행 코드의 릴리스 해시를 확인하며 변경되면 중단한다.
- Lot/Wafer 실행에 필요한 Schema topic을 추가 로딩한다. Router도 등록된 topic을 load_skills로 요청할 수 있다.
- 새 topic은 세 역할에서 사전 검사하지만, 이미 로딩한 topic은 페이지마다 같은 사전 검사를 반복하지 않는다. 각 모델 호출 직전의 해시 검사는 유지한다.
- 파일을 온라인으로 생성/수정/freeze하지 않는다. 사내 릴리스에는 신규 react.md와 tools.json 및 코드 해시를 반영해야 한다.
- llm_start 이벤트에 실제 loaded_files와 prompt_sha256을 기록한다. 모델 키는 입력/이벤트에 넣지 않는다.

## 실행 설정

run 모드는 모든 역할에 enabled=true, mode=api, 실제 served_model과 base_url이 필요하다.
각 api_key_env가 가리키는 환경변수도 있어야 한다. 무인증 로컬 모델 서버도 별도의 비밀이
아닌 로컬 토큰 값을 그 환경변수에 명시한다. 인증 없는 사내 공개 엔드포인트를 권장하는 의미는 아니다.

runtime.max_tool_calls는 Tool 호출 한도, max_agent_steps는 전체 LLM 호출 한도다.
max_retries는 API 전송 재시도 및 연속 실행/출력 오류의 재시도 한도다.
출력 계약 오류는 기존 조회 근거를 무효화하지 않으므로 정상 출력으로 교정할 수 있다.
실제 Tool 실패의 code_gate는 성공한 Tool 조회 전까지 FAIL로 유지한다.
max_answer_revisions는 Judge가 Router로 돌려보내는 횟수 한도다.
max_context_characters 초과 시 근거를 조용히 잘라내지 않고 중단한다. 문자 수는 token 수와 다르다.
Tool 실행은 순차적이며 max_parallel_tools는 아직 사용하지 않는다.

## 범위와 한계

독립 요청은 --request-scope independent로 지정한다. 현재 DB Tool을 전혀 노출하지 않으며,
사용자 제공 내용을 출처가 확인되지 않은 입력 근거로 구분한다. 자동 범위 분류기는 없다.
복수 사고는 사용자 선택을 요구하며 --select-incident로 지정한 ID만 현재 검색 범위에서 검증한다.
오류·모호함·조회 한도 도달 시 unavailable/needs_selection/needs_clarification을 반환한다.

현재 Tool에는 사고/값 후보/Lot/Wafer, 회의록, Engineering snapshot, SEM/Overlay 비교,
관련 사고 텍스트 검색이 있다. Workbench의 사내 SQL 선택은 snapshot에 시스템별 조회 결과를
추가한다. SQL은 설정한 View/컬럼과 설비·Step·기간·Lot 값만 사용하며 LLM SQL은 실행하지 않는다.
SQLite 연결은 로컬 DB로 검증했다. 서버 SQL은 ODBC 드라이버/읽기 전용 계정과 실제 스키마
검증이 필요하다. 사고 DB 주 Adapter 자체는 여전히 SQLite이며 사내 SQL 연결과 별개다.
관련 사고 후보는 현재 scope를 변경하지 않고 텍스트 일치만 반환한다. CD/Bin/Failbit 모델,
이미지 기반 사고 검색, 생산 조치, 운영 ACL은 없다. actor는 호출자 구분이며 인증이 아니다.
배포 전에 사내 모델의 판단 품질, 실제 데이터/스키마, DB 권한과 전송 보안을 검증해야 한다.
로컬 모의 HTTP 서버로 프로토콜 연결을 확인한 것은 실제 LLM 성능 검증이 아니다.
