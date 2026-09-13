---
name: wafer-schema
description: Wafer 테이블의 컬럼 설명과 사고·Lot 범위 검증, 영향 목록과 Lot 구성 구분 규칙.
---

references/columns.json의 컬럼 정의를 사용한다. 물리 이름은 config의 tables.wafer_list에서 읽는다.
사고 영향 목록이면 grain은 incident_ref + lot_id + wafer_id다. Lot 전체 구성 목록이면 grain은 lot_id + wafer_id이고 사고 영향 여부는 별도 확인 대상이다.
Wafer 번호는 Lot 내부에서 반복될 수 있으므로 wafer_id만으로 고유 개수를 세지 않는다. 현재 구현은 Lot ID가 전사 고유하다는 가정이며 사내 중복이면 복합키 Adapter가 필요하다.

## Wafer 조회

사고명은 find_incidents에서 검색한다. exact 결과가 없으면 제한된 contains 검색으로 후보를 찾을 수 있다. 후보가 여러 건이면 도시/라인/발생시점/번호로 구분하고 select_incidents로 선택한다. 사용자가 전체 후보를 명시한 경우에만 모두 선택한다.
선택 scope로 list_incident_lots를 조회한 뒤 list_incident_wafers를 호출한다. Wafer Tool도 내부적으로 Lot 우선 조회를 검증한다. lot_ids는 선택 사고에 속한 Lot만 허용한다. 요청에 없는 Lot 범위로 확장하지 않는다.
사고 영향 Wafer 테이블은 사고 참조와 Lot ID를 함께 연결한다. Lot 구성 테이블이면 lot_inventory임을 표시하고 전체 Wafer를 모두 사고 불량으로 서술하지 않는다.
사고명만 가진 원본 테이블은 관리자가 title Join을 명시하고 고유성이 검증된 경우 사용한다. 중복 사고명을 가진 title Join은 임의로 결합하지 않고 고유키/복합키 View가 필요하다고 알린다.
출력에는 사고번호/사고명, Lot ID, Wafer ID를 유지한다. 사고-Wafer 관계 수와 고유 Lot+Wafer 수를 구분하고 목록이 없는 Lot도 숨기지 않는다. 0행/미등록/건수 불일치를 정상 또는 영향 없음으로 바꾸지 않는다.
전체 목록 요청은 마지막 페이지까지 전달한다. 대량 데이터는 표/파일 내보내기를 사용하며 LLM이 Wafer 번호를 생성하지 않는다. source_completeness와 예상수 비교는 ID 정확성의 완전한 증명이 아니다.

## 실제 데이터 확인 후 변경

수정 전 관련 실제 원본과 대표 데이터를 확인하고 출처, 기준시점, 변경 근거를 기록한다. 실제 데이터에 접근할 수 없으면 미확인으로 표시하고 설계/더미 초안으로만 관리한다. 더미 검증을 실제 데이터 검증으로 주장하거나 확인 없이 컬럼 의미, 관계, 코드값을 확정하지 않는다. 이 규칙은 원본 데이터 수정이나 온라인 Skill 자기 수정 권한을 부여하지 않는다.
