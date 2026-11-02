# Workbench 검색 source 경계 및 통합 검증 기록

작성일: 2026-10-30

## 목적과 근거 범위

이 문서는 현재 체크아웃에서 확인한 `app/workbench.py`, `tests/test_workbench_source_callback_integration.py`, Workbench UI 코드와 기존 MES 기준정보 계약을 기록한다. 이번 변경은 이 문서 한 파일에 한정한다. 기존 수정 사항은 보존했다.

기준 근거:

- `D:\project\q-agent\app\workbench.py`의 source validation, Tool 허용 목록 구성, callback 주입, 결과 보고 코드
- `D:\project\q-agent\tests\test_workbench_source_callback_integration.py`의 합성 MES SQLite 및 synthetic document callback 테스트
- `D:\project\q-agent\web\src\AnalysisEvidence.tsx`, `web/src/EngineeringWorkspace.tsx`, `web/src/Sources.tsx`, `web/src/App.tsx`, `web/src/api.ts`
- `D:\project\q-agent\docs\current\MES_REFERENCE_RUNTIME_20261029_ROOT_v1.md`

이는 현재 로컬 구현·fixture에 대한 기록이다. 사내 문서, 실제 사고 기록 또는 운영 설정을 검증한 자료가 아니다.

## 서로 다른 검색 경로

| 경로 | 현재 의미 | 구현 및 표시 경계 |
|---|---|---|
| `inform` / Eng’r Inform snapshot | Workbench의 합성 engineering snapshot에서 기존 사고별 `inform_notes`와 연결된 자료를 읽는 경로다. `get_engineering_snapshot` 결과의 maps records는 관련 Inform ID를 붙일 수 있고, 화면의 과거 합성 사례 제목을 구성하는 데도 사용한다. | `EngineeringTools`가 합성 `raw_data`로 동작한다. 실제 Eng’r Inform 원문·승인 상태의 연결은 아니다. UI의 회의록은 합성 DB chunk로 표시하고, 별도 Eng’r Inform 원문 화면은 “사내 서비스 미연결”, “초안 · 실제 Inform 아님”으로 표시한다. |
| `engineer_note_search` | 사용자가 명시한 문서 검색 source다. 기존 Hybrid RAG에 연결하는 `search_engineer_notes` Tool 경로다. | 별도 `document_query` callback과 `retrieval.engineer_notes.enabled`, 허용 document status가 필요하다. 합성 통합 테스트 callback은 응답 계약을 흉내 내며, 본문에도 BM25 또는 vector retrieval을 실제 수행하지 않았다고 적혀 있다. |
| `internal_document_search` | 일반 사내문서 검색 source이며 `search_internal_documents` Tool을 사용한다. | `engineer_note_search`와 같은 기존 Hybrid RAG callback 계열이지만 source kind/config/status allowlist와 Tool 이름이 분리된다. 기존 chunk·출처를 연결하는 인터페이스이며 chunk를 이 Workbench가 재생성한다는 근거는 없다. |
| `mes_reference_search` | MES 기준정보 레코드 검색이다. 문서 chunk 검색과 다른 구조화된 참조 검색 Tool이다. | `search_mes_reference`는 별도 `mes_reference_query` callback을 요구한다. 통합 fixture는 매핑된 임시 SQLite에 만든 합성 레코드를 실제 `SyntheticMESReferenceReader`로 읽는다. 운영 MES 연결은 아니다. |

따라서 snapshot의 Inform 참조, 기존 Hybrid RAG 문서 검색, MES 기준정보 검색은 같은 source나 같은 검색 결과로 취급하지 않는다. UI에서 Eng’r Inform 원문은 현재 미연결로 표현되고, callback이 실제 연결된 경우에도 분석 evidence는 source별 검색 결과로 별도 기록된다.

## Source 선택, 실행 gate와 scope

- 요청의 `sources`는 비어 있지 않은 유일한 문자열 배열이어야 하며 알려진 source만 허용된다. 서버는 목록에 `incident`를 선두로 넣는다. 사고번호가 입력에 있으면 room의 선택 사고와 일치해야 한다. scope는 room의 선택 사고 및 검증된 분석 context와 맞아야 한다.
- Agent 호출의 `requested_tools`에는 먼저 `find_incidents`가 들어간다. 선택 사고 ID, `request_scope="incident"`, Workbench cutoff의 `as_of`를 함께 넘긴다. 선택된 source에 따라 후속 Tool만 허용 목록에 추가한다. 문서 또는 MES source가 요청되지 않으면 해당 retrieval Tool은 추가하지 않는다.
- 문서 검색에는 source별 `enabled is True`, callable `document_query`, 비어 있지 않고 중복이 없는 유효 status allowlist가 모두 필요하다. MES 기준정보 검색에는 `enabled is True`, callable `mes_reference_query`, 비어 있지 않고 중복 없는 `allowed_kinds`가 필요하다. 조건이 안 맞으면 해당 source는 unavailable detail로 남는다.
- Agent에 전달되는 document/MES callback은 Workbench 생성자에서 주입받은 trusted callable이다. 기본 실행 경로가 callback을 자동 생성하거나 사내 시스템에 연결한다고 볼 근거는 없다. 통합 테스트도 명시적으로 callback을 주입한다.
- runtime은 actor, 선택된 incident ID와 Workbench `as_of`를 callback 경로에 바인딩한다. MES Tool 입력은 `kind`, `query`, `top_k`로 제한하고 kind를 설정 allowlist와 대조한다. 테스트는 선택 사고의 실제 synthetic incident ID와 `2026-03-31` cutoff가 MES reader에 전달됨을 확인한다. 기존 MES 계약은 `available_at` 및 유효기간 검사와 적용성/범위 관계를 별도 필드로 다룬다.
- 문서 callback 응답은 기존 계약 validator에 넘겨 source kind, 사고 범위, cutoff, status allowlist, top-k 등을 검사한다. 테스트 응답은 `historical_candidate_not_current_scope` 제한을 유지한다. 과거 후보는 현재 범위 적용 확인으로 승격되지 않는다.

## 통합 테스트에서 확인한 범위

`tests/test_workbench_source_callback_integration.py`는 2개 통합 경로를 다룬다.

1. 임시 합성 SQLite와 실제 `SyntheticMESReferenceReader`를 주입하고, scripted LLM을 붙여 incident-first → MES reference Tool → Judge → Answer 흐름을 확인한다. 테스트는 Router 호출 순서, actor/scope/as_of/kind/query 전달, retrieval evidence 기록과 합성 `SYN-PROD-1` 응답을 확인한다.
2. synthetic document callback으로 기존 Hybrid RAG 응답 계약을 검증하고, incident scope와 cutoff 전달, retrieval evidence 및 역사적 후보 limitation을 확인한다. 이 callback fixture는 BM25+vector 검색을 실행하지 않는다.

요청에 제공된 실행 기록은 Workbench test 35개와 추가 통합 11개 통과, `config_loader.py` demo 및 기본 설정 확인 exit 0, `skill_loader.py router` 확인 exit 0, `npm run build` exit 0이다. Frontend build에서는 500KB 초과 chunk warning이 출력됐다. 이후 임시 합성 Workbench를 실제 브라우저에서 확인했다. 검색 source가 기본 미선택이고 연결 필요 문구가 표시됐으며, 사내문서와 MES 검색을 선택해 demo 분석을 제출했을 때 HTTP 200, 두 source의 unavailable 표시, 콘솔 errors 0을 확인했다. screenshot은 [04-demo-analysis-unavailable.png](D:/project/q-agent/var/ui-check-20261030/evidence/04-demo-analysis-unavailable.png)이다. 이 결과들은 합성 fixture와 callback 미연결 상태의 동작 확인에 한정된다.

재현 명령은 프로젝트 루트 PowerShell에서 실행한다. 테스트는 전체 Workbench 발견 실행과 source callback 통합 파일 단독 실행으로 구분한다.

```powershell
$env:PYTHONPATH = "D:\project\q-agent\app;D:\project\q-agent-models\src;D:\project\q-agent\tests"
python -m unittest discover -s tests -p "test_workbench_*.py"
python -m unittest discover -s tests -p test_workbench_source_callback_integration.py
python app/config_loader.py --config config/config.yaml --check-paths
python app/config_loader.py --config config/config.yaml --overlay config/demo.yaml --check-paths
python app/skill_loader.py router --topics incident_search
Push-Location web
npm run build
Pop-Location
```

`config_loader`와 `skill_loader`는 설정/Skill 로더의 실행 확인이다. Skill 로더 확인을 신규 freeze 생성이나 생산용 배포 승인으로 해석하지 않는다. 코드나 Skill 원본을 이 작업에서 변경하지 않았고 freeze를 재생성하지 않았다. 기존 기준에 따라 Router/Answer/Judge 계약 변경은 별도 검토와 명시적 freeze가 필요하다.

## UI 근거 표시

- Workbench의 analysis report는 `search_engineer_notes`, `search_internal_documents`, `search_mes_reference` Tool 응답을 `retrieval_evidence`로 보존한다. 실패/미선택 상태는 source step의 unavailable detail로 나타낼 수 있다.
- `AnalysisEvidence.tsx`는 문서·MES 검색 evidence를 접힌 근거 영역에서 source별로 나누어 표시한다. status, source kind/retrieval method, `as_of`, 선택 및 Tool incident 범위, historical incident 후보, NO_MATCH, truncation, 문서 chunk 또는 MES record locator, 출처, version, available_at, 유효기간, 적용 상태, 제한사항을 표시한다. UI 문구는 검색 결과를 출처·시점 정보로 한정하고 후보·미검증 적용 상태를 확인 완료로 보지 않는다.
- App의 Source status와 Engineering Workspace는 현재 합성 DB 및 원본 미연결 상태를 표시한다. Eng’r Inform 화면은 합성 사고 기록과 실제 Inform 원문·승인을 분리한다.
- 임시 합성 Workbench의 브라우저 확인은 미선택/연결 필요 상태와 선택 source unavailable 상태의 UI 표시만 검증했다. 실제 Hybrid RAG 또는 MES 검색이 성공한 결과를 브라우저에서 확인한 것은 아니다.

## 미검증 범위 및 제한

실제 LLM endpoint/답변 품질, 실제 Hybrid RAG 검색 성공 및 chunk provenance, 운영 MES schema/API/연결과 검색 성공 결과, 실제 사내 문서·Eng’r Inform, 사용자·역할 ACL은 검증되지 않았다. 브라우저 검증은 임시 합성 Workbench의 source 선택 제출과 unavailable UI 상태 확인이다. 통합 테스트는 scripted LLM을 사용하며 실제 모델 호출을 하지 않는다. 합성 SQLite reader와 contract fixture는 production DB 또는 권한을 증명하지 않는다. 기본 Workbench CLI에는 retrieval callback을 주입하는 별도 연결 인자가 확인되지 않았으므로 callback이 없는 default CLI 실행만으로 이 검색 경로가 가용하다고 볼 수 없다.

