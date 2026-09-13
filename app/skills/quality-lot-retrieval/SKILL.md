---
name: quality-lot-retrieval
description: 사고에 연결된 Lot 목록·고유 Lot 수·페이지·연결 완전성을 조회할 때 사용한다.
---

사고 검색으로 확정한 scope_id를 list_incident_lots에 전달한다. 새 사고를 이름 유사성만으로 기존 Lot 목록에 연결하지 않는다.
incident_lots 관계는 내부 PK 또는 검증된 사고번호 Join이다. 실제 Join 키는 매핑 설정과 메타데이터 검증 결과를 따른다.
사고별 Lot 관계 수와 여러 사고를 합친 고유 Lot 수를 구분한다. Lot ID가 도시/사업부별 재사용되면 고유성 범위를 반영한 복합키/View가 필요하다.
page_size, next_offset 또는 cursor를 사용하고 전체 요청은 모든 페이지가 끝난 뒤 완료로 표시한다. 대량 목록은 UI 페이지와 서버 export를 사용한다.
등록 예상수와 반환 총수를 비교하고 source_completeness를 확인한다. 건수 일치만으로 ID 정확성이나 전체 적재를 보장하지 않는다.
동일 Lot의 상충 상태를 MAX 등으로 임의 선택하지 않는다. 시간 기준이 검증된 current-state View로 정리하도록 오류를 반환한다.
