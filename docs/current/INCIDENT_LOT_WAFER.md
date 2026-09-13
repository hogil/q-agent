# 사고명 검색에서 별도 Lot/Wafer 목록 조회까지

사용자가 사고명을 말하면 사고 DB에서 해당 사고를 찾고, 별도 Lot 목록과 Wafer 목록 테이블을 조회한다. 아래 구조의 LLM/문서/멀티모달은 목표 서비스 구조이고, 이번에 실행되는 것은 config 기반 SQLite 사고명 검색과 별도 Lot/Wafer 조회다.

| 위에서 아래 순서 | 처리 내용 |
|---|---|
| 사용자 질문 / 이미지 / Trend 의뢰 | 원문, 첨부 자료, 사고명/번호, 도시, 라인, 기간, 대상 제품을 받는다. |
| ↓ | |
| **Router LLM** | 질문의 요구사항, 논리 검색 조건, 필요한 Tool과 Skill을 결정한다. |
| ↓ | |
| **1계층: 사고 DB 우선 조회** | 정형 사고 검색 또는 SQL 집계를 실행하고 사고 범위와 조회 상태를 기록한다. |
| ↓ | |
| **2계층: 필요한 추가 Tool 조회** | Lot/Wafer, 사고문서, 사내문서, Eng’r Inform Note, 이미지, Trend, 기간시스템을 필요한 만큼 조회한다. |
| ↓ | |
| **Judge LLM** | 원문 질문에 답할 근거가 충분한지, 사고 범위가 맞는지, 누락/모순이 있는지 검토한다. |
| ↓ | 검토 통과 후 진행한다. 근거 부족이나 사고 오류는 맨 위 Router로 돌린다. |
| **Answer LLM** | 검토된 근거로 최종 답변을 작성한다. 마지막 LLM이다. |
| ↓ | |
| **최종 결과 표시** | 답변, 조회 상태, 확정된 사고 범위, Lot/Wafer 목록, 문서 출처와 이미지, 미확인 항목을 표시한다. |

Router는 위의 한 노드만 사용하고 Judge 재조회도 그 Router로 복귀한다. 추가 Tool은 Lot/Wafer, 문서 RAG, 이미지, Trend, 기간시스템이며 불필요하면 생략한다. 사고 DB 우선 조회/범위 검증은 실행 코드에서 검사한다. Answer 아래에는 검증된 조회 상태와 사고 범위를 최종 표시한다.

LLM 호출 위치와 모델 서버 연결 설정은 [LLM_PLACEMENT.md](LLM_PLACEMENT.md)에 별도로 표시했다.

## 데이터 연결

| 논리 테이블 | 한 행의 의미 | 연결 |
|---|---|---|
| incident | 사고 한 건 | 내부 ID, 표시번호, 사고명, 도시, 라인, 발생시각 |
| lot_list | 사고에 등록된 Lot 관계 한 건 | incident_ref → 설정된 사고 키 |
| wafer_list | 사고에 등록된 Lot/Wafer 관계 한 건 | incident_ref + lot_id로 사고/Lot 범위를 함께 제한 |

Wafer 번호 W01은 여러 Lot에 반복되므로 고유 Wafer 수는 `(lot_id, wafer_id)`로 센다. 사고별 관계 수는 `(incident_id, lot_id, wafer_id)`다. Lot ID가 사내에서 재사용되면 사이트 등 복합키 Adapter/View를 먼저 확정한다.

사고명은 사용자의 검색 조건이다. 관계 테이블이 내부키/사고번호를 가지고 있으면 해당 키로 연결한다. 원본 관계 테이블이 사고명만 가지고 있으면 config의 incident_parent_key를 `title`로 바꾸고 각 테이블의 incident_ref 물리 컬럼을 실제 사고명 컬럼으로 지정한다. title Join은 사고명 고유성을 검증하며 중복이면 명시적으로 차단한다. 동명이지만 다른 도시의 사고를 임의로 합치지 않는다. 이런 원본은 고유 사고키 또는 검증된 복합키 View가 필요하다.

## 실제 실행 순서

1. `find_incidents(title=..., title_match='exact' 또는 'contains')`로 사고 DB 조회.
2. 후보가 여러 개면 `NEEDS_SELECTION`과 사고번호/도시/라인/가능한 발생시각 반환. 해당 scope로 목록 조회를 바로 호출하면 오류.
3. `select_incidents(scope_id, incident_ids)`로 후보 범위 내 하나 또는 명시한 여러 사고를 선택. 검색 밖 사고를 끼워 넣을 수 없다.
4. `list_incident_lots(scope_id)`가 별도 Lot 테이블을 조회한다.
5. `list_incident_wafers(scope_id, lot_ids=선택사항)`가 Lot 범위를 검증한 뒤 별도 Wafer 테이블을 조회한다. Lot 우선 조회는 Wafer Tool 내부에서도 수행한다.
6. 사고명/번호, Lot ID, Wafer ID를 유지해 표로 반환. 전체 목록은 마지막 페이지까지 조회한다.

contains 검색의 `%`와 `_`는 SQL 와일드카드가 아닌 실제 문자로 취급한다. 사용자 값은 SQL 파라미터로 바인딩한다. 원본 상태가 충돌하는 같은 Wafer를 임의로 하나 선택하지 않는다.

## config 예시

```yaml
tables:
  lot_list:
    name: INCIDENT_LOT_LIST
    columns:
      incident_ref: INCIDENT_NAME
      lot_id: LOT_NO
  wafer_list:
    name: INCIDENT_WAFER_LIST
    columns:
      incident_ref: INCIDENT_NAME
      lot_id: LOT_NO
      wafer_id: WAFER_NO
      status: WAFER_STATUS
relations:
  incident_parent_key: title
  wafer_parent_key: title
  wafer_scope: incident_affected
```

Lot는 relations.incident_parent_key, Wafer는 relations.wafer_parent_key로 각각 사고 테이블의 연결 컬럼을 지정한다. Lot는 사고명, Wafer는 사고번호를 저장하는 서로 다른 구조도 지원한다.

위 이름은 예시다. 실제 DB에 내부키나 사고번호가 있다면 기본 incident_id 또는 incident_number 연결을 유지한다. source_completeness와 wafer_source_completeness는 각각 Lot/Wafer 원본의 적재 보장을 뜻하며 기본 unknown이다.

별도 테이블이 사고 영향 목록이 아니라 Lot 전체 구성 목록이면 `wafer_scope = "lot_inventory"`로 지정한다. 사고 참조 컬럼이 없으면 `tables.wafer_list.columns.incident_ref = ""`로 둔다. 이 모드에서는 해당 Lot의 전체 Wafer를 가져오되 **사고 영향 Wafer 수로 단정하거나 사고 테이블의 영향 Wafer 수와 비교하지 않는다.**

특정 Lot만 요청하면 사고 테이블의 사고 전체 Wafer 수와 그 부분 목록을 비교하지 않는다. 연결 Wafer가 없는 Lot는 `lots_without_wafer_rows`에 표시한다. 등록 예상수와 다르면 0건이어도 PARTIAL/count_mismatch를 유지한다.

## 실행 범위

사고/Lot/Wafer 조회 구현은 app/incident_tools.py와 app/runtime_factory.py에 유지한다.
app/query_demo.py는 별도로 준비한 SQLite를 조회하는 개발용 CLI다.
더미 생성기, 데모 설정, 저장된 결과는 제거했다. 실제 사내 DB Adapter와 운영 인증,
대량 export, snapshot, LLM 연결은 별도 통합 대상이다.
