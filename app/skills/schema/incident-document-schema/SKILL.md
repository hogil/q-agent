---
name: incident-document-schema
description: 사고문서 컬럼 설명과 문서 연결, 기존 Hybrid RAG 근거, 권한·버전·인용 검토 규칙.
---

references/columns.json을 해당 엔티티가 필요한 역할에만 로드한다. 정의된 grain은 사고에 연결된 문서 버전 한 건이고 식별 기준은 document_id + version다.
논리 필드와 실제 이름을 구분한다. 물리 table/column은 config의 tables.incident_document에 있으며 Adapter가 적용한다. 컬럼 정의를 system prompt 여러 곳에 복사하지 않는다.
NULL/미등록/사용 불가를 0이나 정상으로 바꾸지 않는다. 허용 연산 목록이 실행 Tool 구현 완료를 의미하지 않는다. 의미/단위/관계가 바뀌면 이 Skill의 reference와 회귀 검사를 함께 갱신한다.

## 문서 근거

사고 관련 요청은 사고번호로 확인된 문서 연결을 먼저 사용한다. 사고명은 후보 검색용이며 도시/라인/시점/제품과 함께 연결을 검증한다. 개념상 independent 일반 문서 조회에는 사고번호가 필요 없지만, 현재 Router Skill/agent는 incident scope만 허용하고 별도 ACL adapter가 없어 실행을 지원하지 않는다. trusted source authorization, 기준시각, 버전, 적용범위 계약과 별도 adapter를 검증한 뒤에만 허용한다. 이 제한을 풀어 사고문서 adapter에 빈 scope를 전달하지 않는다.
승인상태·권한·기준시각·버전으로 문서 집합을 제한한 뒤 실제 질문의 원인/조치/검증 의미로 chunk를 검색한다.
PPT/PDF가 동일 버전의 표현이면 중복 근거로 세지 않는다. 표 단위와 제목, 페이지/슬라이드를 보존한다.
문서가 없는 사고는 정형 통계에서 제외하지 않는다. 일부 문서를 전체 사고의 공통 원인으로 일반화하지 않는다.
DB와 문서가 충돌하면 출처/버전/시간 차이를 표시하고 추가 확인을 요청한다. 사고 테이블 자동 수정은 수행하지 않는다.

사내문서 저장소와 Eng’r Inform Note는 이미 chunking된 BM25 + Vector Similarity Hybrid RAG를 사용한다. search_internal_documents와 search_engineer_notes를 별도 Tool로 유지한다. 신규 chunking 구축은 초기 작업 범위가 아니다. 기존 인덱스와 원문을 재생성하거나 삭제하지 않는다. 결과 결합, top-k, reranker는 기존 계약을 확인하며 새 가중치를 추정하지 않는다.

검색 응답이 source-reported `truncated` 값을 제공하면 그대로 보존한다. 값이 없으면 completeness는 unknown이다. `truncated=false`는 source가 잘림이 없다고 보고했다는 뜻일 뿐, corpus 전체를 검색했다는 증거가 아니다. source가 `candidate_count`를 제공하는 경우도 source 반환 직전 후보 수라는 합성 계약에서만 해석하며, 실제 source 의미는 미검증이다. 실제 site source/API와 데이터는 확인되지 않았으며, 이 메타데이터 규칙은 설계 초안이다.

합성 OCR 시간 계보 초안(2026-10-30): document Hybrid 결과 item에 `content_kind=image_ocr`가 명시된 경우 `available_at`은 원본 문서 가용 시점, `derivative_available_at`은 OCR 결과의 별도 가용 시점이다. 두 시점 모두 요청 `as_of`의 site timezone 종료 이전이어야 한다. 파생 시점이 누락·형식 오류·미래 시점이면 해당 결과를 거부하며 `unknown`을 원본 시점으로 대체하지 않는다. 두 시점 사이의 선후 관계는 강제하지 않는다. 일반 legacy 문서 item은 기존 계약을 유지한다. 이 metadata는 source assertion일 뿐 OCR 생성 여부, source integrity, site ACL을 증명하지 않으며, `content_kind`가 표시되지 않은 OCR 여부는 코드가 식별할 수 없다. 변경 근거: 사용자 OCR 검색 통합 요청, `app/document_evidence_contract.py`의 원본 시점만 검사하는 로컬 합성 재현, `research/ocr_temporal_lineage_policy_20261030.py`. 실제 사내 자료와 ACL은 미확인이다.

합성 OCR marker 완전성 초안(2026-10-30): 문서 source 설정에서 `require_content_kind=true`이면 각 반환 item에 `content_kind=text` 또는 `content_kind=image_ocr`를 명시적으로 요구한다. marker가 없거나 다른 값이면 item을 거부한다. `image_ocr` item은 위 원본·파생 시점 검사를 반드시 통과해야 한다. 기본값 `false`는 legacy 호환이며 marker 누락을 허용한다. 이 설정은 label의 진실성, 검색대상 누락 여부, 실제 OCR 수행, site ACL을 증명하지 않는다. 근거: 2026-10-30 `app/document_evidence_contract.py` 로컬 합성 경계에서 marker가 없으면 legacy 허용으로 derivative 시각 검사가 건너뛰는 점, 사용자 Eng’r Inform 이미지 OCR 검색 요구. 실제 사내 source·OCR·ACL은 미확인인 설계 초안이다.

합성 문서 scope 계약(2026-10-30): source item의 `relation=direct`는 선택된 current `incident_ids`와 item `incident_ids`의 교집합이 비어 있지 않아야 한다. `historical_candidate`는 등록된 `historical_incident_ids`와 item `incident_ids`의 교집합이 비어 있지 않아야 한다. Orchestrator는 결과 metadata `incident_ids`를 해당 relation에서 허용된 교집합으로 제한한다. 이는 `app/document_evidence_contract.py`의 local synthetic scope 결함을 확인해 명시한 설계 요구이며, `app/mes_reference_contract.py`의 subset 경계 및 `app/skills/schema/document-chunk-schema/references/meetings.md`의 multi-incident attribution 원칙을 따른다. 2026-10-30 사용자 범위 요구에 따른다. 실제 사내 원본과 ACL은 미확인이다.

## 실제 데이터 확인 후 변경

이 문서의 independent 조회 지원 여부는 2026-10-30 코드/설계 기준이며, 실제 사내 데이터와 ACL은 확인되지 않았다.

수정 전 관련 실제 원본과 대표 데이터를 확인하고 출처, 기준시점, 변경 근거를 기록한다. 실제 데이터에 접근할 수 없으면 미확인으로 표시하고 설계/더미 초안으로만 관리한다. 더미 검증을 실제 데이터 검증으로 주장하거나 확인 없이 컬럼 의미, 관계, 코드값을 확정하지 않는다. 이 규칙은 원본 데이터 수정이나 온라인 Skill 자기 수정 권한을 부여하지 않는다.
