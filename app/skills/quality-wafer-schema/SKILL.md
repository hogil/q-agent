---
name: quality-wafer-schema
description: 별도 Wafer 테이블의 사고 참조, Lot/Wafer 식별자와 상태 컬럼을 해석할 때 사용한다.
---

references/columns.json의 컬럼 정의를 사용한다. 물리 이름은 config의 tables.wafer_list에서 읽는다.
사고 영향 목록이면 grain은 incident_ref + lot_id + wafer_id다. Lot 전체 구성 목록이면 grain은 lot_id + wafer_id이고 사고 영향 여부는 별도 확인 대상이다.
Wafer 번호는 Lot 내부에서 반복될 수 있으므로 wafer_id만으로 고유 개수를 세지 않는다. 현재 구현은 Lot ID가 전사 고유하다는 가정이며 사내 중복이면 복합키 Adapter가 필요하다.
