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

## 검색과 근거

- DB: SQL 매개변수 바인딩과 논리 컬럼 매핑. 질문 단어의 컬럼 후보는 제한된 DISTINCT 조회로 찾는다. 후보를 정답 필터로 자동 확정하지 않는다.
- 사고-Lot-Wafer: 기존 관계 조회를 유지한다. Wafer는 Lot 확인 뒤 조회하며, 등록 목록의 완전성 unknown은 그대로 전달한다.
- 회의록: 승인 상태, as_of, 사고 범위를 **top-k 전에** 적용한다. 빈 사고 집합을 전체 문서 검색으로 바꾸지 않는다.
- 더미 검색: SQLite FTS5 BM25. 전체 검색어 일치가 0건이고 사고 scope가 있을 때만 일부 검색어로 한 번 재검색한다. 같은 날짜·승인·사고 필터와 timeout을 유지한다. 독립 검색은 넓히지 않는다. 한국어 형태소 분석·벡터 검색은 아니다.
- `query_match.strategy=scoped_any_terms`는 부분 검색어 일치다. Judge에 그대로 전달하며 질문의 모든 조건을 만족했다는 뜻은 아니다. 추가 LLM 호출 없이 최대 SQL 조회 한 번이 늘어난다. 기존 일치 결과가 있으면 부분 일치로 채우지 않는다.
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
retrieval의 `--query-source annotated`는 지정 검색어, `--query-source question`은 질문 원문으로 회의록을 검색한다. 두 모드 모두 사고번호·scope는 annotation을 사용하므로 Router·Judge·Answer 성능 평가가 아니다.
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

## 다음 개선

1. train/dev에 독립 문서의 표현 변형·동의어와 무관한 문서 반례를 추가하고, 기존 생성물은 보존한 채 새 data_root로 생성한다. scope·날짜·승인 제한은 고정한다.
2. 승인된 실제 모델을 연결해 Router의 검색어 구성과 Judge 재조회 행동을 확인한다. shared meeting 지침이나 해당 역할의 필요한 조각만 수정하며 정답 문구를 넣지 않는다.
3. 같은 모델·dev·예산에서 추가 few-shot on/off를 비교한다. 호출 수·실제 근거·답변 정확도를 함께 검토한다. 이번에 본 test 질문은 계속 튜닝에 쓰지 않고 새 holdout도 준비한다.

사내 전문가 golden 확보, 한국어 Hybrid 검색 품질, 실제 모델 비교, 권한/ACL, 서버 DB Adapter, 버전별 DB snapshot이 남아 있다.
이미지·Trend·조치 실행과 웹 원격 채팅도 이번 DB/회의록 구현 범위에는 없다.
자동 주기 실행이나 무인 프롬프트 배포는 설정하지 않았다. 검증 근거 없는 변경을 반복하지 않는다.
