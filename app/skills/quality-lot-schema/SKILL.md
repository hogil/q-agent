---
name: quality-lot-schema
description: Lot 목록 테이블의 컬럼 의미·타입·단위·NULL·키 관계를 해석할 때 사용하는 공통 Schema Skill.
---

references/columns.json을 해당 엔티티가 필요한 역할에만 로드한다. 정의된 grain은 사고-Lot 관계 한 건이고 식별 기준은 incident_ref + lot_id다.
논리 필드와 실제 이름을 구분한다. 물리 table/column은 config의 tables.lot_list에 있으며 Adapter가 적용한다. 컬럼 정의를 system prompt 여러 곳에 복사하지 않는다.
NULL/미등록/사용 불가를 0이나 정상으로 바꾸지 않는다. 허용 연산 목록이 실행 Tool 구현 완료를 의미하지 않는다. 의미/단위/관계가 바뀌면 이 Skill의 reference와 회귀 검사를 함께 갱신한다.

## 실제 데이터 확인 후 변경

수정 전 관련 실제 원본과 대표 데이터를 확인하고 출처, 기준시점, 변경 근거를 기록한다. 실제 데이터에 접근할 수 없으면 미확인으로 표시하고 설계/더미 초안으로만 관리한다. 더미 검증을 실제 데이터 검증으로 주장하거나 확인 없이 컬럼 의미, 관계, 코드값을 확정하지 않는다. 이 규칙은 원본 데이터 수정이나 온라인 Skill 자기 수정 권한을 부여하지 않는다.
