# 오타와 동의어를 섞은 다중 컬럼 조회 데모

2026-09-13 기준. 이번 구현은 **변형 입력 → 필드별 정규화 → 실제 합성 SQLite 사고 조회 → 별도 Lot/Wafer 조회**다. 실제 Router/Judge/Answer LLM과 RAG는 호출하지 않았다. 자유로운 자연어 채팅 대신 `컬럼명=값; 컬럼명=값; 요청=...`이라는 한정 문법을 사용한다. 향후 Router가 추출한 논리 조건을 같은 정규화/조회 Tool로 전달할 수 있게 분리했다.

## 1. 만든 데이터

| 구분 | 개수 | 의미 |
|---|---:|---|
| 사고 테이블 | 128 | 16개 합성 사고 템플릿을 확장 |
| 사고-Lot 관계 | 640 | 사고당 5개. 일부 사고는 같은 Lot 공유 |
| 고유 Lot | 576 | 관계 수와 중복 제거 개수가 다름 |
| 사고-Lot-Wafer 관계 | 7,680 | 사고당 60개, Lot당 12개 |
| 고유 Lot/Wafer | 6,912 | `(lot_id, wafer_id)` 기준 |
| 사고문서 연결 | 384 | 사고문서/사내문서/Eng’r Inform Note 합성 자료 |
| 문서 chunk | 1,152 | 합성 Markdown 구간. 실제 BM25/vector 검색 실행 아님 |
| FAB/EDS 이미지 메타데이터 | 256 | 절차적으로 만든 합성 SVG 연결 |
| Trend 메타데이터 | 128 | 합성 시계열 연결 |
| 변형 질문 | 234 | 정답 조회, 조건 불일치, 모호성, 형식 오류, 관계 오류 |
| raw 변형 행 | 40 | 원래 컬럼명/값 표현과 기대 canonical 필터를 별도 저장 |
| 입력 필드 / 사전 항목 | 14 / 72 | 컬럼 별칭, 값 별칭, 요청 종류, 배열 조건 포함 |

사고 테이블의 공식값은 보존한다. 오타/동의어를 섞은 질문과 raw 행은 별도 fixture다. 원본을 임의로 고치거나 다른 사고를 맞는 사고처럼 만드는 과정은 없다. 신설 템플릿에는 PHOTO, ETCH, CMP, DIFF, CVD, METAL, EDS 사례와 원인 미확정 상태, 확인 시험, 임시 조치, 개선, 효과 검증, 재발 방지 내용을 넣었다. 전부 가상 설정이다.

## 2. 실행한 복합 질문

```text
사고번호=syn-2026-0001;
위치=Hwaseong;
생산라인=65라인;
부셔=phpto;
제품새대={디원에이,디원지};
세대조건=모두;
팹아웃=엣지페일;
사고몀=외곽샷;
요청=웨이펴목록
```

| 입력 | 정규화 결과 |
|---|---|
| syn-2026-0001 | SYN-2026-0001 |
| 위치=Hwaseong | city=화성 |
| 생산라인=65라인 | line_code=65L |
| 부셔=phpto | department=PHOTO |
| 제품새대={디원에이,디원지} | product_generations=[D1a,D1z] |
| 세대조건=모두 | 배열 all 조건 |
| 팹아웃=엣지페일 | fab_out_failure_codes=[SYNTH_EDS_EDGE_FAIL] |
| 사고몀=외곽샷 | title_terms=[외곽 Shot] |
| 요청=웨이펴목록 | Lot 우선 조회 후 Wafer 목록 |

결과: **SYN-2026-0001 한 건, 5 Lot, 60 Wafer**. 페이지당 7개이므로 Wafer 9페이지를 조회했다. 조건은 모두 SQL에 적용했고 사고번호만 맞는다고 다른 조건을 버리지 않았다. 번호/목록을 예상해서 출력하지 않고 실제 조회했다.

실제 실행 결과와 정규화 audit, 목록, 페이지/출처 정보는 [complex_query_result.json](../../examples/generated/variants/complex_query_result.json)에 있다. 운영 source_completeness는 unknown이므로 조회된 목록을 전사 영향 범위가 완전하다는 증거로 쓰지 않는다.

## 3. 자동 변환과 확인 요청의 구분

| 유형 | 동작 |
|---|---|
| photo / Photo / PHOTO, 전각 문자, 공백 | NFKC/대소문자/공백 정규화 후 사전 대조 |
| 포토 / 포토팀 / phpto | 더미에서 검토된 별칭만 PHOTO로 변환 |
| 화셩 / 평텍 / 용잉 | 더미 승인 오타 예시로만 처리. 실제 사내 검토 사실 아님 |
| photox | 퍼지 후보 PHOTO를 제시하되 자동 확정하지 않음 |
| p기술팀, 도시 없음 | 도시 범위 확인 요청 |
| p기술팀, 화성 | 합성 사전에서 PHOTO |
| p기술팀, 평택 | 충돌 시험용 합성 사전에서 ETCH. 실제 조직을 설명하는 값이 아님 |
| 공정기술팀 | PHOTO/ETCH 두 후보이므로 확인 요청 |
| 구포토팀 / 신포토팀 | 용어 기준일과 유효기간을 비교 |
| 부서=노광 | 공정과 부서를 섞지 않고 확인 요청 |
| 사고번호의 O/0 또는 빠진 앞자리 0 | 임의 복원하지 않음 |
| 부ㅅㅓ | 유니코드 정규화로 부서가 되는 조합형 입력 |
| 미등록 컬럼명 / 중복 필터 | 요청 형식 오류로 차단. 필터를 조용히 버리지 않음 |
| 세대={D1a,D1x} | D1x가 미확인이면 전체 요청을 확인 상태로 둠 |
| 사고명에 SQL 문구, `%_` | 바인딩된 실제 문자열로 검색. SQL/와일드카드로 실행하지 않음 |

컬럼 별칭과 값 별칭은 다른 사전 항목이다. line_code와 전체 line 표시명도 구분한다. `라인=65엘`, `라인명=65l (abcd)`, `라인별칭=a b c d`를 각각 해석한다. 자유 제목 검색어는 사전에 없으면 literal substring으로 유지하며, 인식하지 못했다고 없애지 않는다.

## 4. 배열/기간/사고 범위

동일 합성 DB에서 D1a와 D1z 조건을 바꾼 조회 결과:

| 배열 조건 | 조회 사고 수 |
|---|---:|
| 하나라도(any) | 46 |
| 모두(all) | 26 |
| 정확히(exact) | 12 |

DB의 배열 NULL과 빈 배열을 별도 사례로 만들었다. 문자열/객체/숫자 원소 등 계약에 맞지 않는 JSON 배열은 데이터 오류로 차단한다. SQLite는 json_text 배열만 사용한다. 사내 native array는 해당 DB Adapter가 필요하며 SQLite 설정으로 바꾸어 해석하지 않는다.

기간은 `2026년 1월`, `2026-01`, `2026/01`을 명시적 월 범위로 변환한다. 시간대가 있는 시작 이상/다음 달 시작 미만으로 실제 시점을 비교한다. '최근'은 이 한정 문법에서 임의 기간으로 바꾸지 않는다.

사고 후보가 여러 개이면 사고 목록 요청에는 후보 집합을 반환할 수 있다. Lot/Wafer 요청은 사고 선택 전 진행하지 않는다. 선택한 사고 범위 밖 Lot이나 검색 후보 밖 사고를 지정하면 오류다. 다른 사고가 동일 Lot을 공유하더라도 Wafer 조회에는 사고 관계를 함께 적용한다.

## 5. 검증 결과

변형 질문 **234/234 기대 결과 일치**. 이 중 성공만을 세는 시험이 아니라 기대한 실패/확인 요청을 정확히 반환했는지도 확인했다.

| 결과 | 사례 수 |
|---|---:|
| MATCHED | 173 |
| NO_MATCH | 30 |
| NEEDS_CLARIFICATION | 25 |
| INVALID_REQUEST | 3 |
| TOOL_ERROR | 2 |
| NEEDS_SELECTION | 1 |

추가로 독립적인 동작 검증 21개를 실행했다. 실제 테이블/컬럼명 변경, 배열 any/all/exact, 시간대 월 경계, 원본 파일 불변, 조건 누락 방지, 동명 사고 선택, 권한 주체가 다른 scope 사용 차단, 합성 사전의 onprem 사용 차단 등을 확인했다. 기존 설정 31개, Wafer 15개, Lot 19개, 배열 7개, Skill 33개 검증도 통과했다.

수치는 **한정 문법과 합성 사전에 대한 회귀 검증**이며 자연어 이해 정확도나 실제 LLM 성능 수치가 아니다. 생성 조합은 그 조합의 정답 라벨을 가진 합성 회귀 세트다. 별도 실제 질문/정답을 이용한 운영 평가는 추가로 필요하다.

[검증 요약과 대표 사례](../../examples/generated/variants/report_summary.json), [전체 질문 및 기대 결과](../../app/data/variant_queries.json), [컬럼 실제 합성값 프로파일](../../examples/generated/variants/column_profile.json)을 참고한다. 프로파일은 21개 사고 컬럼의 NULL 수, distinct 수, 대표 값을 기록하며 컬럼 의미는 기존 Schema Skill Catalog에서 관리한다.

## 6. 실행 방법

저장소 루트에서 최초 실행:

```bash
python app/build_variant_fixtures.py --inputs
python app/generate_dummy.py --overlay config/demo.variants.toml
python app/build_variant_fixtures.py --cases --overlay config/demo.variants.toml
python app/variant_query_demo.py --overlay config/demo.variants.toml --run-cases
python app/check_variants.py
```

DB 생성은 기존 파일을 덮어쓰지 않는다. 이미 생성했다면 generate_dummy를 건너뛰고 조회/검증을 재실행한다. 새로운 세트를 만들려면 별도 overlay에서 data_root와 output_root를 바꾼다. 질문 fixture에 기대하는 사고 ID가 있으므로 전체 234개 사례 재현에는 제공된 128개 사고/5 Lot/12 Wafer 설정을 유지한다.

```bash
python app/variant_query_demo.py --overlay config/demo.variants.toml --question '사고번호=SYN-2026-0001; 부셔=phpto; 제품새대=디원에이; 요청=웨이펴목록'
python app/variant_query_demo.py --overlay config/demo.variants.toml --question '사고명=외곽샷; 요청=웨이퍼목록' --select-incident synthetic-pk-0001
```

사전 유효기간 시험은 `--effective-at 2024-12-31`로 용어 기준일을 지정한다. 미지정 시 합성 사전의 as_of를 사용하고 응답에 기록한다.

## 7. 파일과 변경 위치

| 파일/설정 | 역할 |
|---|---|
| app/terminology.py | 필드 라벨과 값 정규화, 후보/범위/기간 판정 |
| app/incident_filters.py | 다중 컬럼/배열/기간 바인딩 SQL 조건 |
| app/incident_tools.py | 기존 사고 scope와 Lot/Wafer 조회에 연결 |
| app/variant_query_demo.py | 실제 정규화/DB 실행 및 기대 결과 비교 |
| app/build_variant_fixtures.py | 합성 템플릿, 사전, 변형 질문/raw 행 재현 |
| app/check_variants.py | 생성 조합과 별도인 동작 검증 |
| config/demo.variants.toml | 별도 DB/폴더, 물리 테이블/컬럼명 변경, 생성 규모 |
| paths.terminology_file | 현재 사용하는 사전 JSON 경로 |
| paths.variant_cases_file | 질문과 기대 결과 세트 경로 |
| paths.variant_report_file | 전체 실행 보고서 경로. output_root 내부로 제한 |

`quality-terminology` Skill과 출력 참조 계약을 보강했고 기존 '실제 데이터 확인 후 변경' 규칙을 유지했다. 릴리스는 quality-demo-0.11이다. 새 검색/정규화 모듈도 소스 해시에 포함했다. 사내 도입 시 실제 컬럼/관계/공식값/별칭을 확인해 사전을 교체해야 한다. 승인 표시를 포함해 이번 데이터는 전부 합성이다.

Router → 사고 DB → 추가 Tool → Judge → Answer 배치는 유지한다. 이번 실행은 그 중 정규화와 정형 DB/Lot/Wafer Tool 부분이다. 자유 채팅의 조건 추출, 실제 LLM Judge의 재조회, SQL 통계 Tool 전체, 문서 RAG 및 기간시스템/조치 연결은 아직 통합하지 않았다. 현재 배열 사고 테이블 검증은 소규모 SQLite 전체 검사이므로 운영 규모에서는 검증된 View/ETL과 DB 인덱스/쿼리 비용 정책으로 바꿔야 한다.

GPU와 자원 원본 문서는 변경하지 않았다.
