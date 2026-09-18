# DB + Meeting RAG Agent

기준: 2026-09-18 로컬 구현과 합성 fixture. 사내 DB·회의록·모델 성능은 미검증이다.
목표는 사고 DB의 사실과 전문가 회의록의 분석을 함께 조회하되, 검색과 프롬프트 개선을 분리하는 것이다.

## 실행 구조

시작 파일: `D:\project\q-agent\app\run_agent.py`.
설정: `D:\project\q-agent\config\config.yaml` + 명시적으로 선택한 site/demo overlay.

| 순서 | 역할 | 구현 |
|---|---|---|
| 사용자 질문 | question, actor, as_of 전달. actor는 인증이 아님 | app/run_agent.py |
| Router | auto에서는 먼저 incident/independent 분류, 이후 한 번에 Tool 하나 선택 | app/agent.py, app/llm_client.py, app/skills/roles/router |
| 사고 DB | 사고 질문만 조회. 필터 검증과 후보 선택으로 scope 생성 | app/incident_tools.py, app/incident_filters.py |
| 후속 Tool | 필요한 Lot·Wafer·회의록 검색. 독립 회의록 질문은 DB 없이 여기로 진행 | app/meeting_tools.py |
| Judge | 근거 충분성, 시점, 가설/확정, 상충 수량 확인 | app/skills/roles/judge |
| Answer | 검토된 사실과 회의록 분석을 구분해 답변 | app/skills/roles/answer |
| 최종 표시 | status, 사고 scope, 근거, 한계, 실행 이벤트 | app/agent.py 반환 JSON |

`app/` 상대 경로의 절대 기준은 `D:\project\q-agent\`이다.
한 Router만 사용하며, 초기 route도 같은 Router 모델의 호출이다. 별도 Planner/Graph DB는 추가하지 않았다.

| 재조회 상황 | 처리 |
|---|---|
| 같은 사고의 문서 근거 부족 | Judge need_evidence → 같은 Router → 기존 scope에서 추가 검색 |
| 사고/필터 오류 | Judge revise → 같은 Router → 기존 근거 폐기 후 사고 DB 재조회 |
| 후보 여러 개 | needs_selection 종료. 사용자 선택을 전달해 재실행 |
| 예산 소진/자료 없음 | abstain 또는 blocked. 부분 확인과 조회 불가 구분 |
| 독립 질문 분류 오류 | 범위를 임의 확대하지 않고 제한을 알린다. incident로 명시해 재실행 |

분류 결과는 업무 경로이지 보안 권한이 아니다. 독립 경로에서 사고 DB 호출은 코드가 차단한다.
사고 경로는 유효한 scope 없이 후속 Tool을 부를 수 없다. 모델이 actor/scope/incident_ids/as_of를 Tool 인자로 덮어쓸 수 없다.

## 로컬 분석 UI

분석 작업실(`/`)과 독립 채팅(`/?view=chat`)은 같은 room ID와 선택 사고를 공유한다.
작업실 오른쪽 분석 계획에서 기능을 선택하고 가운데에서 결과를 검토한다. 선택한 근거와 준비한 질문은 채팅으로 전달한다.
모바일에서는 분석 계획을 본문 다음에 배치한다. 기능 선택 자체로 Agent 실행이나 Judge 통과를 표시하지 않는다.

| 파일 | 역할 |
|---|---|
| `D:\project\q-agent\app\workbench.py` | loopback HTTP API, 합성 DB scope 조회, 별도 SQLite 대화 저장 |
| `D:\project\q-agent\config\workbench.yaml` | demo 설정 경로, 대화 DB, 문서 기준일, 정적 파일 위치 |
| `D:\project\q-agent\web\src\App.tsx` | 작업실/채팅 화면 분리, 방 선택, 질문·근거 전달 |
| `D:\project\q-agent\web\src\modules.ts` | 기능 목록과 분석 계획의 공통 정의 |
| `D:\project\q-agent\web\src\PlanPanel.tsx` | 방별 수동 검토 항목 선택 |
| `D:\project\q-agent\web\src\Views.tsx` | 개요, Trend, Wafer, 회의록, Lot/Wafer 표 |
| `D:\project\q-agent\web\src\Images.tsx` | SEM, Image Map, Overlay 보기 |
| `D:\project\q-agent\web\src\Sources.tsx` | Eng’r Inform, 생산 시스템 연결 상태, 사고 비교 |
| `D:\project\q-agent\web\src\charts.tsx` | ECharts Canvas와 결정적 합성 시각화 데이터 |

- API는 사고 DB를 먼저 조회하고 scope를 만든 뒤 Lot/Wafer/승인 회의록을 조회한다. 실제 사내 DB에 연결되지 않는다.
- 채팅 메시지는 방별로 저장하고 최신 페이지부터 읽는다. 이전 메시지 cursor는 같은 방에 속하는지 검증한다.
- 첨부의 사고 번호를 보존한다. 다른 사고의 근거를 열 때 명시적으로 범위 전환을 확인한다.
- 대화 저장과 LLM 문맥 관리는 다르다. 현재 웹 채팅은 `agent.py`/Router/Judge/Answer에 연결하지 않은 결정적 합성 조회 데모다.
- Trend/Wafer/Overlay 데이터는 화면용 합성값이다. SEM 출처와 생성 기록은 `D:\project\q-agent\web\public\assets\provenance.json`에 있다. 물리적 배율·결함 판정 근거가 아니다.
- Image Map의 Die와 SEM은 실제로 대응되지 않는다. Eng’r Inform과 MES/FDC/SPC/Recipe에는 실데이터 대신 미연결 상태와 필요한 원본 항목을 표시한다.
- 다음 기능은 `modules.ts` 항목과 해당 보기로 추가한다. 범용 플러그인 엔진이나 새로운 Agent 계층은 두지 않는다.
- 사내 배포에는 로그인/ACL, 인증된 사용자와 room 소유권, LLM 스트리밍·취소·승인, 기존 Hybrid RAG 연결과 운영 웹 서버가 필요하다. 현재 서버를 외부에 노출하지 않는다.

## 검색과 근거

- DB: SQL 매개변수 바인딩과 논리 컬럼 매핑. 질문 단어의 컬럼 후보는 제한된 DISTINCT 조회로 찾는다. 후보를 정답 필터로 자동 확정하지 않는다.
- 사고-Lot-Wafer: 기존 관계 조회를 유지한다. Wafer는 Lot 확인 뒤 조회하며, 등록 목록의 완전성 unknown은 그대로 전달한다.
- 회의록: 승인 상태, as_of, 사고 범위를 **top-k 전에** 적용한다. 빈 사고 집합을 전체 문서 검색으로 바꾸지 않는다.
- 더미 검색: SQLite FTS5 BM25. 전체 검색어 일치를 먼저 유지하고, 사고 scope 안에서 남은 top-k 슬롯만 일부 검색어 일치로 채운다. 같은 날짜·승인·사고 필터와 timeout을 유지하며 chunk 중복을 제외한다. 독립 검색은 넓히지 않는다. 한국어 형태소 분석·벡터 검색은 아니다.
- `query_match.strategy=scoped_any_terms`는 전체 검색어 일치가 없는 부분 일치, `scoped_mixed_terms`는 두 종류의 혼합이다. Judge에 그대로 전달하며 질문의 모든 조건을 만족했다는 뜻은 아니다. 추가 LLM 호출 없이 최대 SQL 조회 한 번이 늘어나고 top-k는 증가하지 않는다.
- 사내 검색: `meetings.backend=http`에서 기존 BM25+vector 서비스에 요청한다. 기존 chunk와 source_ref를 보존한다. API 계약은 아래와 같고 실제 서비스 연결은 별도 확인해야 한다.
- 출처: chunk_id, meeting_id, meeting_date, version, incident_ids, source_ref, text. 승인 회의록의 가설도 가설이다. 검색 점수는 정답 확률이 아니다.
- 시점: meeting_date는 해당 버전이 이용 가능해진 기준일로 공급해야 한다. 나중에 수정된 내용을 과거 날짜로 적재하면 안 된다. 현재 사고 DB는 이 cutoff로 과거 snapshot이 되지 않는다. 역사적 DB 질문에는 별도 snapshot/이력 테이블이 필요하다.
- 모든 문서 내용은 데이터다. 인용된 명령으로 Tool 권한·프롬프트·조회 범위를 바꾸지 않는다.

HTTP POST request: `actor, query, incident_ids, as_of, top_k, methods=["bm25","vector_similarity"]`.
Response: `{"retrieval_method":"remote_hybrid","items":[...]}`. 각 item은 위 출처 필드와 `status:"approved", score:number`가 필요하다.
서버는 인증/ACL과 필터 선적용을 보장해야 한다. 클라이언트도 결과의 날짜·범위·중복·크기를 검사하며 오류 시 사용하지 않는다.
인증키는 환경변수, 외부 endpoint는 HTTPS를 사용한다. 이 Adapter가 기존 사내 API와 자동 호환된다고 보장하지 않는다.

## 프롬프트와 예시

공통 규칙 + 요청에 필요한 schema/rules + 역할별 지침/출력 계약으로 조립한다.
원본 위치는 `D:\project\q-agent\app\skills\`, 조립기는 `D:\project\q-agent\app\skill_loader.py`다.
Skill/코드 변경 시 해시가 달라져 실행이 중단된다. 검토 후 명시적으로 freeze해야 한다.

### Router 메모리와 입력 구성

`D:\project\q-agent\app\agent.py`의 `run()` 안에서 state, evidence, history를 관리한다. 별도 `run()` 호출에는 이어지지 않는다. 모델 서버에 대화가 저장된다고 가정하지 않는다.

| 입력 | 현재 전달 방식 |
|---|---|
| 시스템 프롬프트 | 역할별로 조립해 요청마다 한 번 전달. 이전 시스템 메시지를 history에 누적하지 않음 |
| 현재 payload | 질문·scope·예산·Judge 피드백과 전체 유효 evidence |
| Router history | assistant의 submit_plan과 대응 Tool 응답. 성공 조회는 tool/evidence_id/status만 기록 |
| Judge/Answer | 각각 자기 시스템 프롬프트와 현재 payload. Router history는 전달하지 않음 |
| Tool 계약 | Router Skill의 tools.json에 인자 스키마. payload에는 실제 enabled/stage/search_modes만 전달 |

코드의 Tool 인자 검증에는 전체 스키마를 계속 사용한다. 원문은 요약하거나 자르지 않고 evidence와 감사용 events에 보존한다. events는 모델 입력이 아니다.
새 사고 조회·scope 만료·Judge revise는 기존 evidence/history를 무효화한다. 실행 중인 함수 호출은 대응하는 성공/오류 응답까지 남긴다. revise의 issues는 재조회 지침만 유지하고 이전 evidence ID와 coverage는 제거한다. need_evidence는 현재 scope와 근거를 유지한다.

`D:\project\q-agent\app\llm_client.py`는 payload와 함수 인자 JSON의 불필요한 공백을 줄인다. max_context_characters 검사는 Tool 스키마를 포함한 전체 요청에 적용하고 초과 시 전송 전에 중단한다. 문자 수 검사는 모델별 토큰 한도를 보장하지 않으며, 프롬프트 캐시나 실제 비용 절감도 별도 측정해야 한다.

**예시를 넣는 것은 허용한다.** 사고의 정답 암기보다 Tool 선택, 필터 보존, 근거 판정, 답변 표현을 보여준다.
Router/Judge/Answer의 `references/examples.md`에 역할별 예시를 두고 `runtime.prompt_examples`로 추가 로딩을 비교한다.
기존 `conditions.md`는 양쪽에 남으므로 "예시 전혀 없음" 비교가 아니라 "추가 few-shot 없음/있음" 비교다.
기본값은 false다. 실제 모델 dev 비교 전 성능 개선을 주장하지 않는다.

| 넣어도 되는 내용 | 넣지 않을 내용 |
|---|---|
| train의 짧은 질문 → Tool/판정/출처 표시 예시 | dev/test 정답 복사 |
| 확정과 가설이 다른 유사 사례 | 특정 사고 원인을 영구 정답으로 선언 |
| 값·기간·표현이 바뀌는 반례 | 특정 질문 문자열을 if/else로 분기 |
| 검증된 고정 업무 규칙·단위 | 실제 조회 없이 수치·사고 ID 재사용 |

[OpenAI prompting guidance](https://developers.openai.com/api/docs/guides/prompt-engineering)는 few-shot을 설명한다.
실제 효과는 별도 [평가](https://developers.openai.com/api/docs/guides/evaluation-best-practices)로 확인해야 하며 이 프로젝트에서는 아래 절차를 사용한다.

## 개선 흐름

1. 전문가가 회의록에서 질문·답변·근거 chunk·판정 기준을 추출하고 확인한다. 분석 결론만 있고 DB에 근거가 없다면 RAG 근거가 필요하다.
2. 동일 사고의 반복 회의를 같은 group/split으로 묶는다. 시간순 train/dev/test 분리와 사건 간 누수도 확인한다. 독립 문서 역시 동일 문서의 변형 질문을 분리하지 않는다.
3. train만 예시 작성에 사용한다. dev에서 검색 누락/범위/시점/판정/답변 실패를 구분한다.
4. `golden.py propose` 결과를 검토해 코드·설정·해당 Skill 중 원인을 수정한다. 자동 원본 덮어쓰기는 하지 않는다.
5. 같은 dev 데이터·모델·한도에서 baseline/candidate 또는 추가 예시 on/off를 비교한다. 성공률뿐 아니라 호출 수·지연도 본다. 모델 제공 token usage 기반 비용 측정은 아직 없다.
6. 동의어·ID·기간 변경, 근거 없는 질문, 충돌, 미래 문서, 인용 명령을 포함한 회귀 확인을 한다. test는 최종 확인용이며 개선 예시로 재사용하지 않는다.
7. 전문가가 사실 정확도·누락·출처 타당성을 확인한 변경만 별도 site release로 freeze한다. 문제 시 이전 config/Skill/lock 조합으로 돌아간다.

`D:\project\q-agent\app\golden.py`는 검증/보고/개선 제안을 맡는다. 모델 가중치를 학습하거나 운영 Skill을 자동 고치지 않는다.
retrieval의 `--query-source annotated`는 지정 검색어, `--query-source question`은 질문 원문으로 회의록을 검색한다. 두 모드 모두 사고번호 또는 복합 `retrieval.lookup`과 scope는 annotation을 사용하므로 Router·Judge·Answer 성능 평가가 아니다. `lookup`은 `find_incidents` 인자이며 기존 `incident_number`와 동시에 쓰지 않는다. 복수 후보의 `needs_selection` 사례는 후보 집합을 대조하고 회의록 검색 전에 중단한다.
필수 chunk가 있는 사례의 검색 성공과 chunk recall을 전체 계약 통과율과 별도로 표시한다. 필수 chunk 목록은 모든 관련 문서의 목록이 아니므로 precision은 측정하지 않는다.
`--mode compare`는 같은 데이터·DB fingerprint·config·split·query source·case 집합의 version-2 합성 retrieval 보고서만 비교한다. 하나라도 다르면 중단하고, 개선/회귀/남은 실패를 구분한다. 배포를 자동 승인하지 않는다.
live 모드는 실제 모델 경로를 실행하고 아래 Token Recall을 주점수로 보고한다. 기존 answer_fact 문자열 포함 검사는 보조 진단으로 유지한다. 사실 정확도와 근거 적합성은 별도 검토한다.

## 답변 평가 기준

2026-09-18 사용자 결정에 따라 **Token Recall이 제1 기준**이다. 회의록의 질문별 reference_answer를 최소 포함 내용으로 사용하고, 근거를 갖춘 추가 설명은 감점하지 않는다.

`Token Recall = sum(min(reference의 토큰별 횟수, answer의 토큰별 횟수)) / reference 전체 토큰 수`

- 계산 위치: `D:\project\q-agent\app\golden.py`의 `token_recall`. 생성 답변만 채점하고 retrieved context나 출력 JSON 전체를 채점하지 않는다. 정답은 모델 입력에 전달하지 않는다.
- 고정 토큰화 `unicode_word_v1`: Unicode NFC 정규화, casefold, 문자·숫자 연속 구간 분리. 한국어를 보존하며 공백·기호·underscore는 구분자다. 조사·동의어를 합치지 않고 LLM의 subword tokenizer를 사용하지 않는다.
- 결과 범위는 0~1이며 1은 100% 포함이다. 정답을 모두 포함한 짧은 답변과 추가 설명이 있는 답변은 모두 1이다. 같은 단어를 반복해도 정답의 등장 횟수를 넘는 점수는 없다.
- live 보고서의 `primary_metric.name=token_recall`, `aggregate.token_recall`이 질문별 점수의 macro 평균이다. 답변 길이·Precision·F1·비용을 이 점수에 혼합하지 않는다.
- 답변 없음이나 빈 reference는 `null`과 사유를 표시한다. 선택한 모든 사례를 채점하지 못하면 주평균도 `null`이다. 일부 측정 평균 `scored_case_token_recall`과 측정/미측정 건수를 별도로 기록해 실패 사례가 빠진 평균을 전체 성능처럼 표시하지 않는다.
- `passed/failed`는 실행·범위·근거 ID 등 기존 계약 검사다. Token Recall과 별도이며, 높은 Recall이 사실 정확성을 보장하지 않는다. 실제 사실 오류의 자동 의미 판정은 아직 없고 전문가 검토가 필요하다.
- retrieval 모드는 답변을 생성하지 않으므로 Token Recall을 만들지 않는다. 기존 `compare`도 검색 비교 전용이다. live 후보는 동일 golden·tokenizer·모델·예산에서 주점수와 별도 오류를 대조한다.

평가 정책의 Skill 원본은 `D:\project\q-agent\app\skills\rules\skill-maintenance\SKILL.md`다. 점수를 높이려고 dev/test 정답을 runtime Skill에 복사하지 않는다.
Token Recall 추가 후 회귀 테스트 50개와 프롬프트 조합 76개를 확인했다. 합성 채점 예시는 `D:\project\q-agent\var\output\token-recall-contract-20260918.json`에 있다. 실제 모델은 미연결이라 모델 답변의 Recall은 미측정이다.

## 합성 실행

`D:\project\q-agent\app\demo_data.py`가 사고·Lot·Wafer DB, 회의록 FTS DB, JSONL golden 초안을 만든다.
기존 파일은 덮어쓰지 않고 demo/test 설정에서만 실행한다. 결과는 Git에서 제외된 `D:\project\q-agent\var\data\meetings-demo\`에 놓인다.
더미 split은 사고·문서 그룹별 계약 검증용이다. 엄격한 시간순 일반화 성능을 측정하는 데이터는 아니며, 실제 평가에서는 train에 포함된 마지막 회의 버전보다 이후의 dev/test 기간을 별도로 구성해야 한다.

```powershell
python D:\project\q-agent\app\run_agent.py --demo --mode prepare-demo
python D:\project\q-agent\app\run_agent.py --demo --mode check
python D:\project\q-agent\app\run_agent.py --demo --mode evaluate --evaluation-mode retrieval --split dev
python D:\project\q-agent\app\run_agent.py --demo --mode evaluate --evaluation-mode retrieval --split dev --query-source question
python D:\project\q-agent\app\run_agent.py --demo --mode propose --report D:\project\q-agent\var\output\evaluate-ACTUAL_TIMESTAMP.json
```

보고서는 `D:\project\q-agent\var\output\`에 고유 이름으로 생성된다. 위 ACTUAL_TIMESTAMP는 출력된 실제 경로로 대체한다.
합성 실행 회귀 검사는 `python -m unittest discover -s D:\project\q-agent\tests -v`로 실행한다.
테스트의 scripted model 응답은 실행 제어만 검사하며 실제 LLM 품질을 의미하지 않는다.
실제 모델 검증에는 승인된 endpoint, served_model, enabled와 API 환경변수를 설정한 demo-only overlay가 필요하다.
예: `--demo-overlay D:\project\q-agent\config\demo.local.yaml --evaluation-mode live --split dev --with-examples`.
같은 설정에서 `--without-examples`도 실행해 비교한다. 사내 데이터는 승인 없이 외부 모델로 전송하지 않는다.

### Hard 프로필

기본 더미의 사고번호 직접 조회만으로는 복합 WHERE와 유사 사고 혼동을 검증하기 어렵다. `--demo-profile hard`는 생성 모드에서만 지정하고, 별도 overlay로 기존 데이터를 보존한다.

```powershell
python D:\project\q-agent\app\run_agent.py --demo --demo-overlay D:\project\q-agent\config\hard-demo.yaml --mode prepare-demo --demo-profile hard
python D:\project\q-agent\app\run_agent.py --demo --demo-overlay D:\project\q-agent\config\hard-demo.yaml --mode evaluate --split dev
python D:\project\q-agent\app\run_agent.py --demo --demo-overlay D:\project\q-agent\config\hard-demo.yaml --mode evaluate --split dev --query-source question
```

생성 위치는 `D:\project\q-agent\var\data\meetings-hard-v1\`이다. 이미 존재하면 생성이 중단된다. `D:\project\q-agent\tests\test_hard_demo.py`에서 데이터의 결정성, SQL 후보, 근거 메타데이터, Lot/Wafer 연결을 검사한다. 이 검사는 모든 검색 사례가 성공하도록 요구하지 않는다.

사고 192건(48개 유사 사고 그룹), Lot 행 576개, Wafer 행 1,257개, 회의록 chunk 588개, golden 30개(train/dev/test 각 10개)다. 행 수에는 의도한 정확 중복이 포함된다. 6개 도시·4개 부서·4개 라인, 배열 any/all/exact, 시간대와 반개방 기간, 중복/공유 Lot, 누락 Wafer, 수량 불일치를 포함한다. 회의록에는 분리된 가설/확정/조치, 단위가 다른 수량, 미래 버전, 미승인 초안, 다른 사고와의 비교를 넣었다.

## 2026-09-18 개선 실험

기존 더미 DB와 golden 파일을 수정하지 않고 비교했다. 짧은 지정 검색어에서는 17/17이었지만 질문 원문으로는 필수 회의록이 있는 모든 사례에서 검색이 누락됐다. 질문별 정답이나 한국어 조사 제거 규칙을 추가하지 않고 사고 범위 내 lexical 재검색만 바꿨다.

| 질문 원문의 필수 회의록 검색 | baseline | candidate |
|---|---|---|
| train | 0/3 | 2/3 |
| dev | 0/3 | 2/3 |
| test | 0/3 | 1/3 |

이는 각 질문의 필수 chunk를 모두 찾은 건수다. train/dev에서 후보를 결정한 후 test를 확인했으며, 이번 test 결과로 추가 튜닝하지 않았다. 사례가 작고 같은 문서에 대한 질문도 있어 일반화 성능을 주장할 수 없다.
기존 지정 검색어 계약은 17/17 유지, 확인된 회귀와 금지 chunk 반환은 0건이다. 독립 검색과 어휘가 겹치지 않는 질문은 여전히 실패한다. 재검색 결과가 질문에 적합한지와 실제 답변 품질은 별도 검증해야 한다.

비교 보고서 폴더: `D:\project\q-agent\var\output\retrieval-improvement-20260918\`.
예: `D:\project\q-agent\var\output\retrieval-improvement-20260918\comparison-verified-dev-question.json`.

```powershell
python D:\project\q-agent\app\run_agent.py --demo --mode compare --baseline D:\project\q-agent\var\output\retrieval-improvement-20260918\baseline-dev-question.json --report D:\project\q-agent\var\output\retrieval-improvement-20260918\verified-dev-question.json
```

검색 개선 당시 로컬 확인: 회귀 테스트 43개, 역할/topic/추가 예시 조합 76개, Skill 형식 검사 14개와 합성 검색 계약 17개(train 5/dev 7/test 5) 통과.
합성 데이터는 사고 9건, Lot 22건, Wafer 57건, 회의록 chunk 11개다. 검색 계약 실행의 LLM 호출 수는 0이며 모델 답변 정확도 점수가 아니다.
잘못된 검색어를 넣는 대조 테스트에서는 required chunk 누락이 검출되고 프롬프트 정답 암기가 아닌 검색/config 점검으로 제안되는지도 확인했다.

### Hard 검색 개선

release `quality-demo-0.30`에서 요약 하나의 전체 검색어 일치가 후속 근거 검색을 막는 실패를 수정했다. train/dev로 후보를 결정하고 test를 최종 확인했다. 같은 DB·golden·config·top-k=8을 유지했으며 기본 데이터는 변경하지 않았다.

| 필수 chunk recall | baseline | candidate |
|---|---|---|
| train/dev/test 각각, 지정 검색어 | 1/16 (6.25%) | 13/16 (81.25%) |
| train/dev/test 각각, 질문 원문 | 15/16 (93.75%) | 15/16 (93.75%) |

각 split의 지정 검색어 계약 통과는 5/10 → 9/10, 필수 근거가 있는 질문의 완전 검색은 1/6 → 5/6이다. 질문 원문 계약은 9/10을 유지했다. 비교에서 검색 회귀와 금지 chunk 반환은 0건이다. 검색어가 달라지면 기존 OR 재검색의 발동 여부도 달라지므로 두 모드의 점수를 혼합하지 않는다.

남은 실패는 지정 검색어의 동의어/다국어 어휘 불일치와 독립 문서의 질문 원문 검색이다. 범위 안의 추가 문서가 전부 유용하다는 뜻은 아니며 Judge의 사실 귀속 검토가 필요하다. 30개는 같은 생성 규칙의 그룹별 변형으로, 규모 확장과 계약 스트레스 검사이지 사내 난도나 의미 일반화의 증거는 아니다. 실제 모델 미연결로 **답변 Token Recall은 미측정**이다.

보고서: `D:\project\q-agent\var\output\hard-retrieval-20260918\comparison-dev-annotated.json`.
전체 실험 폴더: `D:\project\q-agent\var\output\hard-retrieval-20260918\`.
검증: 회귀 테스트 59개, 192개 사고의 Lot/Wafer 원본 행 대조, 프롬프트 조합 76개(최대 31,842자), Skill 형식 14개, 기존 기본 검색 계약 17/17.

### Router 입력 최적화

release `quality-demo-0.31`은 세 차례 수정·검증했다. 1차는 Tool 결과 이중 전달 제거, 2차는 scope 무효화 처리 통합과 오래된 history 제거, 3차는 Tool 인자 스키마 중복 제거·JSON 압축·전체 요청 길이 검사다. 공통 ReAct Skill도 함께 수정하고 명시적으로 freeze했다.

실제 합성 SQLite Adapter와 RoleClient의 요청 구성을 실행하되 API 응답은 고정 mock으로 대체했다. 아래 값은 모든 역할 호출의 **요청 JSON 직렬화 문자 수 합계**이며 토큰·비용·지연 측정값이 아니다.

| 시나리오 | 변경 전 | 1차 | 2차 | 3차 | 감소 |
|---|---:|---:|---:|---:|---:|
| 사고 → Lot → Wafer → 회의록 | 276,228 | 263,760 | 262,276 | 251,048 | 9.12% |
| 회의록 반복 조회 | 504,344 | 461,965 | 458,421 | 437,168 | 13.32% |
| 다른 사고로 재조회 | 235,300 | 227,787 | 223,679 | 213,591 | 9.23% |
| Judge revise 후 재조회 | 300,281 | 291,168 | 282,849 | 269,978 | 10.09% |

위 네 시나리오의 LLM/Tool 호출 수와 최종 근거 해시는 동일하다. 해시 비교에서는 실행마다 달라지는 scope_id와 임시 경로의 영향을 받는 mapping_version만 제외했다. 큰 회의록을 반복 조회하는 별도 사례는 변경 전 MODEL_CONTEXT_LIMIT으로 중단됐지만 변경 후 전체 흐름이 완료됐다. 완료 작업량이 달라 이 사례의 총량 감소율은 계산하지 않는다.

최종 벤치마크 3회에서 수치·근거 해시가 일치했다. 테스트 78개, 프롬프트 조합 76개(최대 31,900자), Skill 형식 14개가 통과했다. 기본 검색 계약은 17/17, hard 검색은 각 split에서 지정 검색어 13/16·질문 원문 15/16의 필수 chunk recall을 유지했다. 기존 어휘 불일치 실패는 남아 있으며 실제 모델의 답변 Token Recall은 미측정이다. 원문 근거 보존이 모델 행동의 동일성을 보장하지는 않는다.

보고서: `D:\project\q-agent\var\output\router-memory-20260918\summary.json`.
실험 요청·로그: `D:\project\q-agent\var\output\router-memory-20260918\`. 합성 데이터 전용이며 Git에 올리지 않는다.

## 다음 개선

1. hard train/dev의 동의어·독립 문서 실패를 기존 Hybrid 검색 또는 Router 검색어 구성으로 검증한다. 현재 더미의 규칙적 템플릿만 늘리지 않고 전문가가 검토한 새로운 표현과 다중 근거 사례를 확보한다. scope·날짜·승인 제한은 고정한다.
2. 승인된 실제 모델을 연결해 Router의 검색어 구성과 Judge 재조회 행동을 확인한다. shared meeting 지침이나 해당 역할의 필요한 조각만 수정하며 정답 문구를 넣지 않는다.
3. 같은 모델·dev·예산에서 추가 few-shot on/off를 비교한다. 호출 수·실제 근거·답변 정확도를 함께 검토한다. 이번에 본 test 질문은 계속 튜닝에 쓰지 않고 새 holdout도 준비한다.

사내 전문가 golden 확보, 한국어 Hybrid 검색 품질, 실제 모델 비교, 권한/ACL, 서버 DB Adapter, 버전별 DB snapshot이 남아 있다.
이미지·Trend·조치 실행과 웹 원격 채팅도 이번 DB/회의록 구현 범위에는 없다.
자동 주기 실행이나 무인 프롬프트 배포는 설정하지 않았다. 검증 근거 없는 변경을 반복하지 않는다.
