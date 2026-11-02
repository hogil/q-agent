# Skill 관리와 상태 기반 프롬프트 조합

기준: 2026-10-28. 사용자가 제공한 전문가상 관련 설명은 설계 참고자료로 사용했다. 사내 경진대회의 최신 공식 심사표와 Skill 인정 범위는 확인하지 않았다. 이 문서는 현재 코드, 합성 구조 검사, 실제 SQL 연구 결과를 구분한다.

Skill은 업무 지침과 참고자료를 관리하는 단위다. 실행 시에는 선택한 Skill을 시스템 프롬프트와 현재 상태로 조합한다. instruction-only Skill도 가능하며, 개발 도구의 개인 Skill과 Q-Agent 서버의 업무 Skill Registry는 별도다. 공식 참고: [OpenAI Build Skills](https://learn.chatgpt.com/docs/build-skills). 특정 API가 SKILL.md를 자동 실행한다고 가정하지 않는다.

## 현재 구현과 적용 범위

| 기능 | 현재 코드와 동작 | 검증 범위 |
|---|---|---|
| 동적 로딩 | 기존 `compile_prompt`/`load_skills`를 유지하고 `skill_graph.py`에서 topic 의존성을 먼저 해석. wafers → lots → incident_search | 실제 registry의 의존성 순서, cycle/unknown/role 거부 |
| 반복별 문맥 | `context_manager.py`가 후속 Router의 typed state, evidence IDs, 최신 Judge/error, 닫힌 호출·응답 이력을 검사 | 조건 충족 시 과거 Router 메시지를 요청에서 제외. 원본 evidence/trace는 보존 |
| 핵심 계약 보존 | core/role/업무 규칙, scope/as_of, Tool 가용성 유지. examples는 선택적으로 제외 | 중복 output schema 제외는 실제 RoleClient가 transport schema를 제공하는 경우에만 허용 |
| 오류별 복구 안내 | `recovery_policy.py`에서 scope, 출력 계약, 설정/schema, transport, action reconciliation, unknown을 분류 | 기존 retry/call budget 안에서 Router 복구 또는 중단. 업무 Tool 자동 재실행·write 재시도는 없음 |
| 관측 | release/prompt hash, 의존성, context phase, 글자 수, role별 시도 수, recovery category | provider가 반환한 usage만 집계. 미반환 token/시간은 null |
| 버전 | Skill 계약을 먼저 변경하고 명시적 freeze 후 runtime 연결, 최종 release `quality-demo-0.81` | 온라인 질의로 Skill 수정하지 않음 |

현재 기본 배포 설정에서는 이력 축약이 꺼져 있다. 새 기능은 `D:\project\q-agent\config\expert-context-v1.yaml` overlay로 선택한다. 과거 로컬 Qwen에서 계약 제거에 따른 빈 계획 회귀가 있었으므로, 이 overlay의 실제 LLM 품질은 확인 전이다. 구조 검사 통과만으로 기본값을 바꾸지 않는다.

## 실행 순서

| 순서 | 계층 | 수행 |
|---|---|---|
| 1 | Router | 사용자 질문·현재 상태·필요 Skill을 조합해 계획 제출 |
| 2 | 사고 DB | 코드가 사고 DB 최초 조회와 scope 검증을 강제 |
| 3 | 후속 Tool | 선택 사고/Lot 범위에서 기존 RDB, Hybrid RAG, 이미지/Trend/Measure Tool 조회 |
| 4 | Judge | 현재 근거·시점·누락·충돌 검토 |
| 5 | Answer | 마지막 LLM으로 근거에 맞는 최종 답변 생성 |
| 6 | 최종 표시 | 실제 조회 상태, 선택 사고/Lot 범위, 제한사항 표시 |

| 재조회 조건 | 처리 |
|---|---|
| Judge need_evidence/revise | 같은 Router로 복귀; 기존 scope 무효화/재취득 규칙을 유지 |
| 출력 계약 오류 | 전체 계약과 해당 오류를 복원해 한도 내 수정 |
| scope/identity 오류 | 명시 선택 또는 허용된 scope 재취득; ID 추측 금지 |
| 설정/schema·transport 문제 | 중단하고 확인된 매핑/연결 진단으로 전달 |
| action commit 상태 불명 | Adapter reconciliation 필요. 이 변경으로 MES Adapter나 생산계 조치를 구현한 것은 아님 |

Skill 의존성은 지식 로딩 순서다. Tool 실행 순서와 권한은 Orchestrator/Adapter가 계속 결정한다. SQL 연구 adapter를 현재 업무 Tool에 연결하지 않았다.

## 실제 구조 측정

`D:\project\q-agent\var\research\expert-skill-20261028\runtime-integration-result-final.json`의 native/structured 합성 control-flow fixture에서, 동일한 wafers 문맥의 full 시스템 프롬프트 29,908자가 continuation 28,357자로 줄었다. 차이는 1,551자다. 같은 시점의 과거 Router 메시지 4개(이력 JSON 908자)도 해당 요청에서 제외했으며 원본에는 6개 메시지가 닫힌 호출·응답 쌍으로 남았다. 로딩 topic이 늘어날 수 있으므로 회차 간 전체 길이가 항상 감소한다는 뜻은 아니다.

- helper 구조 검사 66개, recovery 18개 사례 및 의존성 guards 통과.
- 실제 실행 루프 연결 검사 4개: native, structured, 비활성화, 오류 시 전체 문맥 복구. 네 경우 모두 모델/API/DB 호출 0회.
- config_loader, 세 역할 skill_loader, run_agent check의 기본/overlay 실행 통과.
- 실제 조회 CLI에서 설정된 합성 DB의 사고 1건 → Lot 2건 → Wafer 3건을 조회했다. `D:\project\q-agent\var\research\expert-skill-20261028\final-nonempty-lookup-summary.json`. 이는 연결 목록 조회이며 실제 영향 Wafer 확정이 아니다. 모델 호출은 없었다.
- `RESOURCE_PRESERVATION.json`의 원래 SHA-256 `f8f1a4a1d1a8b100e4e9485f300de4bb8577298ed7671a0b2fc05bdaf57cb528` 유지.

이 수치는 token 절감률, 응답 정확도, provider latency, 생산계 검증 결과가 아니다. 제거된 포괄적 LLM 정답 질문 은행을 복원하지 않았다.

## 출품 설명과 남은 검증

발표에서는 기존 기능인 Skill Registry/동적 로딩/코드 scope gate/Judge와, 이번에 추가한 의존성 검사/조건부 continuation/오류 분류/측정 기록을 구분한다. 학습형 Router, 자동 Skill 수정·배포·롤백, 운영 ACL, 생산 MES 조치는 구현 완료로 표시하지 않는다.

현재 허용된 모델 비교는 별도의 합성 NL2SQL 연구다. 첫 adapter는 JSON/decision 지표를 높였지만 SQL 의미 일치는 5/18에서 5/18로 동일했다. 두 번째 grounded 문맥은 학습 전 기준 모델 0/18로 악화됐고, 자원 probe에서 예상 학습 시간 한도를 넘어 FIT을 보류했다. 따라서 이를 성공 사례로 출품하지 않는다. 상세 결과는 `D:\project\q-agent\docs\current\NL2SQL_GOLDEN_TRAINING_20261028_ROOT_v1.md`에 남긴다.

추가 검증은 실제 배포할 로컬 모델과 명시적으로 허용된 업무에서 같은 질문/도구/모델 조건을 고정한 뒤 수행해야 한다. 정량 기준은 의미가 맞는 실제 조회, 근거 범위 일치, 누락/오류 처리, 실제 provider usage와 실행 시간이다. 짧은 프롬프트나 작은 TRAIN loss만으로 개선을 주장하지 않는다.
