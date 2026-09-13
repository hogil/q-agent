---
name: quality-document-evidence
description: 사고 DB 결과에 사고 문서·Inform의 chunk 근거를 보강할 때 사용한다.
---

사고번호로 확인된 문서 연결을 먼저 사용한다. 사고명은 후보 검색용이며 도시/라인/시점/제품과 함께 연결을 검증한다.
승인상태·권한·기준시각·버전으로 문서 집합을 제한한 뒤 실제 질문의 원인/조치/검증 의미로 chunk를 검색한다.
PPT/PDF가 동일 버전의 표현이면 중복 근거로 세지 않는다. 표 단위와 제목, 페이지/슬라이드를 보존한다.
문서가 없는 사고는 정형 통계에서 제외하지 않는다. 일부 문서를 전체 사고의 공통 원인으로 일반화하지 않는다.
DB와 문서가 충돌하면 출처/버전/시간 차이를 표시하고 추가 확인을 요청한다. 원장 자동 수정은 수행하지 않는다.

사내문서 저장소와 Eng’r Inform Note는 이미 chunking된 BM25 + Vector Similarity Hybrid RAG를 사용한다. search_internal_documents와 search_engineer_notes를 별도 Tool로 유지한다. 신규 chunking 구축은 초기 작업 범위가 아니다. 기존 인덱스와 원문을 재생성하거나 삭제하지 않는다. 결과 결합, top-k, reranker는 기존 계약을 확인하며 새 가중치를 추정하지 않는다.
