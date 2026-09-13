# Judge 조건 예시

| 입력 근거 | 판정 |
|---|---|
| 전체 60 Wafer 중 첫 페이지 7개, next_offset=7, 추가 조회 가능 | need_evidence, router. 남은 페이지 회수 요청. |
| 60개 전부 회수했으나 source_completeness=unknown | 단순 '등록 목록' 요청은 제한을 명시해 pass 가능. '전사 영향 전부'를 요구하면 추가 근거 요청, 확보 불가면 abstain. |
| 화성 질문에 평택 사고 근거 | revise, router. 사고 조건을 바로잡고 종전 파생 근거를 무효화. |
| Hybrid 10개 후보로 전체 사고 10건이라는 집계 근거 | need_evidence, router. 검증된 모집단/집계 요청. 확보 불가면 abstain. |
| 문서 60 Wafer, 원장 72 Wafer, 기준시점 불명 | need_evidence, router. 버전/범위/기준시점을 확인. 임의로 한 수치를 채택하지 않음. |
| 원인 질문에 비슷한 이미지만 있음 | 원인 근거 missing. 추가 조사 가능하면 need_evidence, 불가면 abstain. |
| 도구 오류/권한 제한으로 추가 자료 확보 불가 | abstain, answer. 확인된 사실과 해당 제한 전달. |
| 질문의 모든 항목에 유효한 근거가 있고 코드 검사 통과 | pass, answer. |
