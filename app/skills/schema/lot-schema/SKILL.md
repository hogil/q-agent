---
name: lot-schema
description: 사고-Lot 테이블의 컬럼 설명과 조회 범위, 중복, 페이지, 완전성 처리 규칙.
---

references/columns.json을 해당 엔티티가 필요한 역할에만 로드한다. 정의된 grain은 사고-Lot 관계 한 건이고 식별 기준은 incident_ref + lot_id다.
논리 필드와 실제 이름을 구분한다. 물리 table/column은 config의 tables.lot_list에 있으며 Adapter가 적용한다. 컬럼 정의를 system prompt 여러 곳에 복사하지 않는다.
NULL/미등록/사용 불가를 0이나 정상으로 바꾸지 않는다. 허용 연산 목록이 실행 Tool 구현 완료를 의미하지 않는다. 의미/단위/관계가 바뀌면 이 Skill의 reference와 회귀 검사를 함께 갱신한다.

## Lot 조회

사고 검색으로 확정한 scope_id를 list_incident_lots에 전달한다. 새 사고를 이름 유사성만으로 기존 Lot 목록에 연결하지 않는다.
incident_lots 관계는 내부 PK 또는 검증된 사고번호 Join이 기본이다. 원본이 사고명만 저장하면 config에서 title Join을 명시하고 사고명 고유성 검증을 통과해야 한다. 실제 Join 키는 매핑 설정과 메타데이터 검증 결과를 따른다.
사고명 검색이 복수 후보를 반환하면 선택 전 목록 조회를 하지 않는다. Wafer 요청은 확정한 사고/Lot 범위로 별도 wafer_list 테이블을 조회한다.
사고별 Lot 관계 수와 여러 사고를 합친 고유 Lot 수를 구분한다. Lot ID가 도시/사업부별 재사용되면 고유성 범위를 반영한 복합키/View가 필요하다.
page_size, next_offset 또는 cursor를 사용하고 전체 요청은 모든 페이지가 끝난 뒤 완료로 표시한다. 대량 목록은 UI 페이지와 서버 export를 사용한다.
등록 예상수와 반환 총수를 비교하고 source_completeness를 확인한다. 건수 일치만으로 ID 정확성이나 전체 적재를 보장하지 않는다.
동일 Lot의 상충 상태를 MAX 등으로 임의 선택하지 않는다. 시간 기준이 검증된 current-state View로 정리하도록 오류를 반환한다.

## 실제 데이터 확인 후 변경

수정 전 관련 실제 원본과 대표 데이터를 확인하고 출처, 기준시점, 변경 근거를 기록한다. 실제 데이터에 접근할 수 없으면 미확인으로 표시하고 설계/더미 초안으로만 관리한다. 더미 검증을 실제 데이터 검증으로 주장하거나 확인 없이 컬럼 의미, 관계, 코드값을 확정하지 않는다. 이 규칙은 원본 데이터 수정이나 온라인 Skill 자기 수정 권한을 부여하지 않는다.
