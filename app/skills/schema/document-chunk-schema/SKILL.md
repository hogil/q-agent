---
name: document-chunk-schema
description: 문서 chunk 테이블의 컬럼 의미·타입·단위·NULL·키 관계를 해석할 때 사용하는 공통 Schema Skill.
---

references/columns.json을 해당 엔티티가 필요한 역할에만 로드한다. 정의된 grain은 원문 버전 내 chunk 한 건이고 식별 기준은 chunk_id다.
논리 필드와 실제 이름을 구분한다. 물리 table/column은 config의 tables.document_chunk에 있으며 Adapter가 적용한다. 컬럼 정의를 system prompt 여러 곳에 복사하지 않는다.
공통 NULL 및 Tool 구현 경계는 core/SKILL.md를 따른다. 의미/단위/관계 변경 시 reference와 회귀 사례를 갱신한다.

회의록 검색에는 references/meetings.md의 출처·시점·가설/확정 계약도 적용한다. 로컬 더미 FTS5와 사내 Hybrid RAG를 같은 검색 품질로 간주하지 않는다.

변경 전 출처·기준시점 확인은 core/SKILL.md를 따른다.
