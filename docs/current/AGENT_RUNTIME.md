# ReAct 실행

## 실제 호출 흐름

| 순서 | 파일 | 동작 |
|---|---|---|
| 진입 | app/run_agent.py | 사내 config/Skill 검증, run 인자 확인 |
| 시작 | app/agent.py | 질문, 호출자, 요청 범위, 예산과 근거 상태 생성 |
| Router | app/skill_loader.py → app/llm_client.py | Router Skill 조립 후 설정된 모델 호출 |
| 사고 DB | app/plan_executor.py → app/runtime_factory.py → app/incident_tools.py | 검증된 find_incidents 실행, 읽기 전용 연결과 scope 발급 |
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
한 단계에 한 Tool만 실행한다. 실제 SQL이나 actor/scope_id를 모델이 지정할 수 없다.

## 역할별 Skill 관리

- 각 API 호출 전에 공통 Skill + 선택 topic + 역할 Skill + config 매핑을 조립한다.
- 세 역할의 모델/temperature/출력 한도는 roles와 models 설정에서 읽는다.
- output.schema.json과 tools.json도 같은 사내 skills_root에서 읽는다.
- Skill·사전·실행 코드의 릴리스 해시를 확인하며 변경되면 중단한다.
- Lot/Wafer 실행에 필요한 Schema topic을 추가 로딩한다. Router도 등록된 topic을 load_skills로 요청할 수 있다.
- 파일을 온라인으로 생성/수정/freeze하지 않는다. 사내 릴리스에는 신규 react.md와 tools.json 및 코드 해시를 반영해야 한다.
- llm_start 이벤트에 실제 loaded_files와 prompt_sha256을 기록한다. 모델 키는 입력/이벤트에 넣지 않는다.

## 실행 설정

run 모드는 모든 역할에 enabled=true, mode=api, 실제 served_model과 base_url이 필요하다.
각 api_key_env가 가리키는 환경변수도 있어야 한다. 무인증 로컬 모델 서버도 별도의 비밀이
아닌 로컬 토큰 값을 그 환경변수에 명시한다. 인증 없는 사내 공개 엔드포인트를 권장하는 의미는 아니다.

runtime.max_tool_calls는 Tool 호출 한도, max_agent_steps는 전체 LLM 호출 한도다.
max_retries는 API 전송 재시도 및 연속 실행/출력 오류의 재시도 한도다.
max_answer_revisions는 Judge가 Router로 돌려보내는 횟수 한도다.
max_context_characters 초과 시 근거를 조용히 잘라내지 않고 중단한다. 문자 수는 token 수와 다르다.
Tool 실행은 순차적이며 max_parallel_tools는 아직 사용하지 않는다.

## 범위와 한계

독립 요청은 --request-scope independent로 지정한다. 현재 DB Tool을 전혀 노출하지 않으며,
사용자 제공 내용을 출처가 확인되지 않은 입력 근거로 구분한다. 자동 범위 분류기는 없다.
복수 사고는 사용자 선택을 요구하며 --select-incident로 지정한 ID만 현재 검색 범위에서 검증한다.
오류·모호함·조회 한도 도달 시 unavailable/needs_selection/needs_clarification을 반환한다.

실제 연결된 업무 Tool은 SQLite 사고 검색, Lot 조회, Wafer 조회 3개다. RAG/이미지/Trend/
조치/서버 DB Adapter와 운영 ACL은 아직 없다. actor는 로컬 호출자 구분이며 인증이 아니다.
배포 전에 사내 모델의 판단 품질, 실제 데이터/스키마, DB 권한과 전송 보안을 검증해야 한다.
로컬 모의 HTTP 서버로 프로토콜 연결을 확인한 것은 실제 LLM 성능 검증이 아니다.
