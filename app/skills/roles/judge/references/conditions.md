# Judge 조건 예시

independent 문서 요약에는 사고 DB 미조회를 누락으로 판정하지 않는다. 제공된 문서가 요약 요구를 충족하면 pass할 수 있다.

| 입력 근거 | 판정 |
|---|---|
| 전체 60 Wafer 중 첫 페이지 7개, next_offset=7, 추가 조회 가능 | need_evidence, router. 남은 페이지 조회 요청. |
| 60개 전부 조회했으나 source_completeness=unknown | 단순 '등록 목록' 요청은 제한을 명시해 pass 가능. '전사 영향 전부'를 요구하면 추가 근거 요청, 확보 불가면 abstain. |
| 화성 질문에 평택 사고 근거 | revise, router. 사고 조건을 바로잡고 종전 연결된 근거를 무효화. |
| Hybrid 10개 후보로 전체 사고 10건이라는 집계 근거 | need_evidence, router. 검증된 모집단/집계 요청. 확보 불가면 abstain. |
| 문서 60 Wafer, 사고 테이블 72 Wafer, 기준시점 불명 | need_evidence, router. 버전/범위/기준시점을 확인. 임의로 한 수치를 채택하지 않음. |
| 원인 질문에 비슷한 이미지만 있음 | 원인 근거 missing. 추가 조사 가능하면 need_evidence, 불가면 abstain. |
| 도구 오류/권한 제한으로 추가 자료 확보 불가 | abstain, answer. 확인된 사실과 해당 제한 전달. |
| 질문의 모든 항목에 유효한 근거가 있고 코드 검사 통과 | pass, answer. |
| 같은 보고서의 chunk 세 개가 동일 원인 가설을 반복 | 독립 출처 세 개로 세지 않는다. 확인 원인 질문이면 검증/반증 근거를 점검한다. |
| coverage는 전부 satisfied이나 issues에 미해결 수량 충돌이 있음 | pass 불가. 재조회 가능하면 need_evidence, 불가하면 abstain. |
| 등록 Lot 목록과 범위는 충분하지만 원인은 미확정, 질문은 목록만 요구 | 원인 미확정을 추가 요구사항으로 만들지 않는다. 코드 검사 통과 시 pass와 issues=[]로 끝낸다. |
| 점검 계획 요청. 현재 Fab 쌍, 과거 참조/EDS, 변경 이력이 있고 현재 EDS는 미연결 | 계획 작성 근거는 충분할 수 있다. 현재 결과 완료를 요구하지 않는다. pass는 계획에 대한 판정이며 현재 불량/원인 확정이 아니다. |
| 현재 실측 Yield나 확정 원인을 요청했지만 현재 EDS는 미연결 | 해당 결과는 unavailable. 조회 수단이 없으면 abstain, answer. 과거 EDS로 채우거나 미래 결과를 지금 재조회하지 않는다. |
