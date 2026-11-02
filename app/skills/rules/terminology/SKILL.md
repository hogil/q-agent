---
name: terminology
description: 반도체 품질 업무의 오타·동의어·조직 별칭을 공식 값에 매핑할 때 사용하는 공통 규칙.
---

NFKC, 대소문자, 공백 정규화 후 공식 코드/승인 별칭을 우선 조회한다. 퍼지·임베딩 검색은 후보 생성이다.

## 현재 연결된 DB 값 후보 조회

match_incident_values는 설정된 사고 컬럼의 unique value를 읽고 정규화된 exact 후보를 먼저 반환한다. `value_matching.fuzzy_enabled`가 켜진 경우에만 추가로 `typo_candidate`를 제안하며, 후보에는 `score`와 `requires_confirmation=true`가 있다. fuzzy는 길이 4 미만, 숫자/하이픈 포함 값, ID/number/code 컬럼을 건너뛴다. 배열은 원소별로 비교한다. candidates의 field/value는 DB의 논리 컬럼과 원본값이고 mention은 정규화된 질문 표현이다. 모든 unique value를 프롬프트에 넣지 않는다. 이 fuzzy 제안은 승인 별칭 사전의 resolve와 별개다.

ambiguous=true이면 같은 표현에 여러 컬럼/값 후보가 있다. fuzzy 후보는 score가 높더라도 사용자 확인 전 필터에 넣지 않는다. 확인되면 원본 DB value를 사용해 find_incidents를 별도로 호출한다. 부정·제외·인용을 포함 조건으로 바꾸지 않는다. coverage의 unmapped, invalid_array, invalid_value_type, distinct_limit_exceeded 또는 truncated=true가 있으면 후보 없음이 DB 값 없음의 증거가 아니다. 이 조회는 사고 scope나 사고 검색 완료를 발급하지 않는다.

기준: 2026-10-24 로컬 `app/terminology.py::match_values`, `app/incident_tools.py::match_incident_values`, `config/config.yaml`의 value_matching 계약 및 incident-schema logical-schema references. 같은 날짜 합성 문자열 inline 확인에서 exact 호환 shape, 조사 제거 typo 후보, ambiguous 표시와 ID/code exclusion을 확인했다. 사내 DB 값·별칭·오타율은 검증하지 않았다. 점수 threshold는 후보 생성 설정이지 자동 승인 기준이 아니다.
용어는 entity_type, 도시/라인/조직 범위, 유효기간, 승인상태와 함께 해석한다. 포토와 PHOTO는 승인 사전 기준으로 매핑한다. 노광 공정과 PHOTO 부서는 동일 개체가 아니다.
전체 백과사전을 system prompt에 넣지 않는다. references/dictionary-contract.json의 규격으로 후보 몇 개와 근거만 Tool에서 반환한다. 대형 사전은 분야별 파일/DB 인덱스로 운영한다.
모호한 별칭을 임의 확정하지 않는다. 원문과 후보/선택 근거를 기록한다. 신규 표현은 승인 대기 후보로 저장하며 즉시 정식 사전에 추가하지 않는다.
컬럼 별칭과 값 별칭을 구분하고 필드별로 해석한다. 미확인 필터/배열 원소를 버려 조회 범위를 넓히지 않는다. 사고/Lot 식별자의 O/0, 앞자리 0을 임의 보정하지 않는다. 라인 코드와 전체 표시명은 별개다.

## 실제 데이터 확인 후 변경

수정 전 관련 실제 원본과 대표 데이터를 확인하고 출처, 기준시점, 변경 근거를 기록한다. 실제 데이터에 접근할 수 없으면 미확인으로 표시하고 설계/더미 초안으로만 관리한다. 더미 검증을 실제 데이터 검증으로 주장하거나 확인 없이 컬럼 의미, 관계, 코드값을 확정하지 않는다. 이 규칙은 원본 데이터 수정이나 온라인 Skill 자기 수정 권한을 부여하지 않는다.
