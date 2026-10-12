---
name: statistics
description: 전체 사고 집계와 기간 비교의 조회·검토·답변 계약.
---

summarize_incidents(filters, group_by, comparison_period, top_k)는 사고 DB 최초 Tool이다. stage=incident, search_mode=sql_aggregate, intents에 statistics를 포함한다. 최상위 filters는 arguments.filters와 일치해야 한다. actor/as_of/scope는 코드가 바인딩한다.

조건에 맞는 전체 모집단의 distinct incident_id를 SQL로 집계한다. groups는 상위 표시 목록이며 전체 건수가 아니다. comparison_period는 timezone 포함 gte/lt 반개구간으로 현재 occurred_at만 교체하며 나머지 조건을 유지한다. 전기 0건의 증감률은 null이다.
comparison.groups는 현재 표시 그룹의 전기 값이다. 없는 그룹 값을 추정하지 않는다. 순수 통계 결과의 사용자 답변과 claims는 Answer 검토 후 코드가 SQL 결과로 생성한다. LLM 초안은 실행 로그에만 보존한다. 다른 근거를 함께 분석하는 일반 답변은 이 숫자 무결성 보장이 적용되지 않는다.

find_incidents의 scope_mode=cohort는 명시적인 기간/부서 전체 analysis/statistics에만 사용한다. 사고번호·제목·제목 단어 후보에는 사용하지 않는다. 집계가 상세 scope 한도를 넘으면 scope_complete=false이고 상세 Tool은 비활성이다. 전체 건수는 여전히 SQL 집계값이다.

제품세대·FAB Out 코드별 그룹은 배열을 펼쳐 distinct 사고를 세고 여러 그룹에 같은 사고가 포함될 수 있다. 그룹별 수량 배분은 지원하지 않는다. expected_lot_count와 affected_wafer_count 합계는 기록값이며 missing_count와 함께 설명한다. 미매핑 등급·손실량은 계산하지 않는다.

2026-10-12 합성 Qwen 실행에서 미제공 전월 세대 수치를 추정한 오류를 확인해 코드 렌더링을 추가했다. 사내 통계 구현과 실제 데이터 의미는 미확인이다. 온라인 Skill 변경은 허용하지 않는다.
