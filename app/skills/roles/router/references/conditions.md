# Router 조건 예시

고정 업무 조건표다. 추가 few-shot on/off와 무관하게 적용한다. 예시 값은 합성이며 available_tools에 구현된 기능만 계획한다.

request_scope=independent인 용어 설명/제공 자료 요약은 stage=independent로 사고 DB를 생략한다. 독립 문서 검색도 이 단계의 Tool만 사용한다. '사고 원인 조사하되 DB는 생략'은 independent로 인정하지 않는다.

| 사용자 질문 / 현재 상태 | 해야 할 행동 |
|---|---|
| 명확한 사고번호 | find_incidents, sql_exact. 다른 조건도 보존한다. |
| 도시/부서/기간별 건수 | distinct 사고 집계가 가능한 Tool 필요. 없으면 blocked. |
| 서술형 사고 검색 | 사고 Hybrid/mixed가 실제 등록된 경우만 사용. 회의록 검색으로 사고 DB 확인을 대신하지 않는다. |
| 사고번호와 부서 조건이 불일치 | 0건과 적용 조건을 보존한다. 부서를 삭제해 재검색하지 않는다. |
| 컬럼 값/별칭이 모호함 | DB 값 후보 또는 승인 사전으로 확인. 추측해 필터를 만들거나 삭제하지 않는다. |
| 사고가 여러 건인데 그 사고 Wafer 요청 | 선택 의도를 확인한다. 사용자가 전체 후보를 명시하면 검증된 집합 선택을 요청한다. |
| 유효 scope에서 Wafer 다음 페이지 부족 | 같은 Router에서 list_incident_wafers의 다음 페이지를 계획한다. |
| 요청한 근거가 모두 모임 | plan=[]와 ready_for_judge. 최종 답변을 만들지 않는다. |
| 사용자가 원인을 단정 | 가설로 유지하고 검증 근거를 찾는다. |
| 도시/기간/사고 변경 | 이전 scope와 연결 근거를 폐기하고 다시 조회한다. |
| 등록 Lot 목록만 요청 | 원인 조사나 문서 검색을 추가하지 않는다. |
| 회의록 분석 필요 | meetings topic과 search_meeting_minutes. as_of/IDs는 코드가 바인딩. |
