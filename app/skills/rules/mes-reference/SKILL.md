---
name: mes-reference
description: MES 전산 기준정보를 사고 맥락에서 검토하기 위한 오프라인 설계 규칙.
---

# MES 기준정보 참조 규칙

이 Skill은 합성/오프라인 설계 초안이다. 사내 MES 자료, 테이블·컬럼, API, mapping, 권한, 기준시점 및 site 운영 연결은 확인되지 않았다. 실제 데이터 검증이나 운영 연결이 완료됐다고 주장하지 않는다.

## 조회 계약

- 사고 관련 업무의 최초 Tool은 사고 DB 검색/집계다. 선택된 사고 scope가 확정된 뒤에만 MES 기준정보 후속 조회를 계획한다.
- 논리적 기준정보 종류 예시는 product, route/step, equipment/chamber, recipe revision, code, sampling/spec, material이다. 요청에 없는 종류를 추가로 발명하지 않는다.
- `search_mes_reference(kind, query, top_k?, filters?)`에서 `kind`와 `query`는 필수이며, `query`는 이름 부분검색이다. `top_k`는 선택값이다. `filters`는 관리자가 설정에서 허용하고 매핑한 논리 키와 문자열 값 1~5개만 담으며, 각 조건은 문자열 exact-match AND로 적용한다. 질문이 요청한 조건만 전달한다. 키/값 또는 키의 허용·매핑 여부가 불명확하면 추측하지 말고 clarify한다. actor, scope, incident_ids, as_of는 실행 코드가 바인딩하며 인자로 제공하지 않는다. 물리 SQL 및 테이블/API 인자를 만들지 않는다.
- 실제 사내 테이블·컬럼·Join·API 연결은 site mapping 설정을 통해야 한다. 이 Skill은 사내 메타 사전이나 mapping을 대체하지 않는다.

## 합성 Adapter 응답 해석

- 합성 reader 계약에서 `scope_relation=current_scope`는 요청 scope의 `incident_ids` 중 하나 이상이 항목에 연결됐다는 adapter 표기이며, `incident_ids`는 비어 있지 않은 요청 scope 부분집합이어야 한다. `scope_relation=catalog_candidate`는 항목의 `incident_ids`가 비어 있으며, 요청 사고와 연결되지 않은 일반 기준정보 후보를 뜻한다.
- 두 `scope_relation` 값 모두 실제 site ACL, source 진위 또는 요청 사고에 대한 MES 적용성을 증명하지 않는다. `applicability`는 source-defined 값으로 보존하며 `scope_relation`만으로 값을 강제하거나 재해석하지 않는다. 실제 적용성은 별도 근거로 확인되지 않는 한 미검증이다.
- 기준: 2026-10-30 synthetic reader 및 `app/mes_reference_contract.py` 계약, 현재 Q-Agent 정책. 실제 사내 자료/데이터 및 site ACL은 미확인이다.

## 근거와 한계

- 결과에는 가능한 경우 출처 식별 정보와 provenance, 기준 시점, 가용 기간, 유효 기간, 적용 범위를 보존한다. 정보가 제공되지 않으면 unknown으로 기록하고 추정하지 않는다.
- MES 기준정보(정의/설정/기준)와 FDC 관측 신호·측정 결과는 서로 다른 근거 유형으로 구분한다.
- 종류나 결과가 없다는 것은 해당 기준정보가 존재하지 않는다는 증거가 아니다. 검색 결과만으로 미확인 범위에 일반화하지 않는다.
- 실제 source/API, ACL, mapping, 운영 Adapter가 미활성 또는 미확인인 동안은 이 조회가 실제 연결돼 있다고 표현하지 않는다.
- 이 optional filters 계약은 합성 MES 기준정보 검색 설계다. 실제 MES source, 논리 키 mapping, 사내 데이터 ACL의 검증을 의미하지 않는다. 기준: `app/skills/roles/router/SKILL.md` 및 `references/tools.json`의 2026-10-30 설계 계약; 사내 데이터 및 ACL은 미확인이다.
