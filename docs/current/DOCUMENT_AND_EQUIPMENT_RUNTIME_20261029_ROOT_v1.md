# 문서 검색 및 설비 기준시점 런타임 확인

2026-10-29 원 기록. 당시 파일 확인에서 문서 검색·증거검토·설비 snapshot 경계와 요청 제공 검증 결과를 기록했다. 아래 `2026-10-30 runtime 상태 보완`은 현재 코드의 후속 callback/MES Tool 연결을 반영한다. 이 기록은 실제 사내 문서/RAG, 사내 ACL, 생산 MES 또는 실제 LLM 응답 품질이 검증되었다는 뜻이 아니다.

## 구현에서 확인한 동작

- `app/agent.py`의 `run()`은 문서 Tool을 `search_engineer_notes` 및 `search_internal_documents`로 등록한다. 각 Tool은 해당 retrieval source의 `enabled: true`, 비어 있지 않은 고유 status allowlist, 호출자가 전달한 callable `document_query`가 모두 있을 때에만 활성화된다. 기본 `config/config.yaml`의 두 retrieval source는 모두 비활성이고 기존 chunk 사용 설정 및 BM25/vector similarity 방식을 선언한다.
- Incident 요청은 문서 Tool을 포함한 후속 Tool을 실행하기 전에 사고 scope를 검증한다. 문서 callback에 전달하는 actor, 현재 incident ID, 기준일 `as_of`, 사고 연관 검색에서 얻은 historical incident ID, query, 제한된 `top_k`는 런타임 코드가 구성한다. Router 인자가 caller identity/scope를 덮어쓰는 것은 거부한다. 요청 `top_k`는 설정 cap 이하이고 1–100 범위여야 하며 초과·잘못된 값은 거부된다.
- `app/document_evidence_contract.py`는 callback 응답이 `bm25_vector_hybrid`인지, 요청의 기준일과 source kind가 일치하는지, status가 caller allowlist 안에 있는지, 결과 개수가 `top_k` 이하인지 검사한다. 직접 evidence는 현재 사고 ID와 교집합이 있어야 하고 historical candidate는 등록된 historical incident ID와 교집합이 있어야 한다. `available_at`은 설정 timezone의 `as_of` 날짜 종료 시점 이전이어야 한다. 문서·chunk·version·source locator와 유효기간·관계 메타데이터의 형태도 검증하며 `applicability_status`는 `unverified`로 고정한다.
- 이 계약은 기존 Hybrid RAG의 chunk를 다시 만들거나 삭제하지 않는다. 의미상 관련성, 출처 ACL, 현재 사고에 대한 적용 가능성을 자동으로 입증하지 않는다. historical candidate의 현재 사고 적용성은 확인되지 않은 상태로 남는다.
- `app/evidence_review.py`는 문서 결과의 chunk ID, 문서 ID/version/source reference, locator, 관계, 사고 ID, `available_at` 및 관측 시각을 evidence record/source group에 연결한다. `app/agent.py`는 문서 evidence와 그 review record/source group/issues를 Judge/Answer 문맥에 제공한다. engineering snapshot 역시 evidence review에서 source row를 추적한다.
- `app/enterprise_tools.py`의 enterprise row 수집은 source timezone에서 `as_of` 다음 날 자정인 exclusive cutoff를 사용해 그 시각 이후 `available_at`인 row를 제외한다. `available_at` 매핑이 없으면 row availability를 `unknown`으로 남기고 `AVAILABILITY_TIME_NOT_MAPPED` limitation을 기록한다. 매핑은 있으나 값이 null인 row도 `unknown` 및 `AVAILABILITY_TIME_NULL`로 표시한다. source event/observed time과 availability time은 별개다.
- 문서 및 LLM 입력 길이에는 문자 수 경계가 적용된다. 현재 기본 `runtime.max_context_characters`는 120000이고, 완성된 요청이 이를 넘으면 `app/llm_client.py`가 `MODEL_CONTEXT_LIMIT` 오류를 발생시킨다. 해당 한도는 토큰 한도가 아니다. 큰 문서를 조용히 잘라내는 동작으로 확인되지 않았으며, 실제 token 절감이나 응답 품질 영향은 측정하지 않았다.
- `app/mes_reference_contract.py`는 MES 기준정보 응답의 incident scope, as-of, 허용 kind, 결과 개수, availability 및 유효기간 메타데이터를 검증한다. 현재 `app/agent.py`의 `search_mes_reference` runtime Tool 및 `app/workbench.py`의 `mes_reference_search` source routing이 이 경로를 호출한다. demo 설정에서 `mes_reference.synthetic_sqlite`가 활성화되고 파일이 유효하면 Workbench/CLI가 합성 SQLite reader를 구성한다. 이를 실제 사내 MES Tool/접속으로 해석하지 않는다.

## 검증 기록

요청에 포함된 synthetic `agent.run` smoke 기록은 다음 경로를 확인했다: `find_incidents` → 문서 callback → Judge → Answer. fake `RoleClient`를 사용했고 두 Tool 호출, 문서 callback 1회, Judge/Answer의 text 및 locator 보존을 확인했다. `requested_tools` 경로도 통과했다. 이 기록은 실제 LLM 호출이나 답변 품질 평가가 아니다.

요청에 포함된 negative 경로에서는 미래 `available_at` 결과와 direct relation의 사고 scope 밖 결과가 evidence에 들어가지 않았고 Judge 호출도 없었다. `top_k` cap 초과 및 사고 scope 확정 전에는 문서 callback 호출이 0회였다.

추가로 지정된 검증 결과는 enterprise 및 evidence 테스트 19개 통과, config/role documents skill compile exit 0, 명시적 release freeze `quality-demo-0.83`이다. 이 문서 작성 과정에서 이 테스트를 다시 실행하지는 않았다. 위 결과만으로 실제 사내 자료나 실제 배포 연결을 검증했다고 보지 않는다.

## 연결 상태와 미확인 범위

- `document_query`는 `app/agent.py`에 주입하는 optional callback이다. `app/workbench.py`는 `engineer_note_search`와 `internal_document_search` source를 해당 Tool들에 라우팅하고 callback이 callable일 때 전달한다. 현재 기본 Workbench/CLI 구성에는 이 callback을 제공하는 site Hybrid RAG adapter가 없으므로 실제 Hybrid retrieval backend 연결은 확인되지 않았다. 합성 테스트 callback은 evidence 계약/호출 경로만 검증한다.
- 실제 site API/endpoint, 인증 및 ACL 동작, 사내 문서 schema/mapping, 실 Hybrid backend 연결과 실제 chunk 출처/기준시점은 미확인이다. base retrieval 설정은 off 상태다.
- runtime Tool 및 합성 SQLite reader 경로는 구현되어 있다. 실제 사내 MES schema, mapping, API, 접속, ACL 또는 조회는 확인되지 않았다.
- 실제 LLM을 통한 end-to-end 답변 품질, 생산 데이터, 생산 ACL, MES HOLD/RELEASE나 기타 생산계 조치는 검증 범위에 포함되지 않았다.

## 2026-10-30 runtime 상태 보완

현재 구현 상태는 `app/agent.py`의 `document_query`/`mes_reference_query` Tool 등록과 호출, `app/workbench.py`의 source routing, `app/runtime_factory.py::open_synthetic_mes_reference` factory를 기준으로 확인했다. `search_engineer_notes` 및 `search_internal_documents`는 활성 설정, status allowlist, callable 문서 callback이 모두 있어야 실행된다. `search_mes_reference`는 설정된 kind와 callable reader가 있어야 실행되며, demo mode의 합성 SQLite reader는 Workbench와 CLI에서 자동 구성될 수 있다. 기본 설정에서는 두 문서 retrieval과 MES reference가 꺼져 있다.

테스트는 synthetic MES reader의 자동 구성 및 source routing과 명시적인 synthetic 문서 callback 계약 경로를 다룬다. 이 결과는 실제 site Hybrid RAG backend, 사내 MES, ACL, 실제 문서 검색 또는 생산 데이터 검증을 뜻하지 않는다. 기존의 2026-10-29 검증 기록은 그 시점의 smoke/test 결과로 보존한다.

## 근거 파일

- `D:\project\q-agent\app\agent.py`
- `D:\project\q-agent\app\document_evidence_contract.py`
- `D:\project\q-agent\app\evidence_review.py`
- `D:\project\q-agent\app\enterprise_tools.py`
- `D:\project\q-agent\app\mes_reference_contract.py`
- `D:\project\q-agent\app\llm_client.py`
- `D:\project\q-agent\config\config.yaml`
- `D:\project\q-agent\app\skills\roles\router\references\tools.json`
- `D:\project\q-agent\app\skills\roles\router\SKILL.md`
