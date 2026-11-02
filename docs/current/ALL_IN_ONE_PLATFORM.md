# Q-Agent 합성 통합 불량 분석 플랫폼

현재 재생성 데이터·모델·시점/좌표 계약은 [PLATFORM_REFRESH_CURRENT.md](PLATFORM_REFRESH_CURRENT.md)를 따른다. 아래는 2026-10-24 앱 prototype의 수량과 구현 기록이며 새 lab 모델/DB의 서비스 통합 완료를 뜻하지 않는다.

기준일: 2026-10-24. `quality-demo-0.71`의 실행 가능한 합성 데이터 기능이다.
화면: `http://127.0.0.1:18743/?tab=platform` 또는 Workbench의 **불량 분석** 탭.
데이터·이미지는 절차적으로 생성하며 WM-811K는 사용하지 않는다.

## 연결한 데이터

| 데이터 | 생성량 | 연결·의미 |
|---|---:|---|
| 사고 DB | 240건 | 내부 ID와 표시 사고번호 분리. 제품세대·Failure code 배열 유지 |
| Lot / Wafer / Chip | 720 / 2,880 / 184,320 | Chip 식별자는 사고·Lot·Wafer·Chip 복합키 |
| MES Lot status | 720행 | 장비, Step, Recipe, RUN/WAIT/HOLD, 대기 시간 |
| EDS / Fab out | 5,760행 | Electrical Die Sorting과 FAB_OUT stage를 분리. tested/failed chip으로 수율 계산 |
| 기존 Chip Measure | 368,640 long행 | 16개 물리 컬럼, 실제 전기 항목은 Vth·leakage 2개 |
| 확장 Chip tabular | 184,320 wide행 × 128 features | 원래 2항목 + 더미 전기 채널 126개, 동일 chip 복합키 |
| 공간 map | wafer 240장 + chip crop 1,440장 | 등록 chip/die 좌표, local·내부 형상·chip 간 반복성 분리 |
| Failbit | 4,224행 | chip 내부 bit 좌표와 실패 관측. die 위치 좌표와 구분 |
| SEM | 480장 | normal/bridge/gap procedural patch, 픽셀 feature, 촬영 조건·해시 |
| Failbit bitmap | 1,056장 | 같은 chip의 bit 좌표를 실제 PNG로 생성, manifest와 메타데이터 연결 |
| Trend | 69,120행 | temperature/pressure/current 각 96시점의 원시 시계열 |
| Eng’r Inform Note | 480건 | 가설·반대 근거, 버전과 available_at, 기존 document/chunk 및 회의록에 연결 |

기본 DB의 14개 테이블/149개 논리 컬럼을 보존하고, 별도 tabular DB에 wide chip 테이블을 추가했다.
wide 테이블은 물리 컬럼 149개 중 전기 feature 128개이며 나머지는 식별·시점·점수 metadata다.
업무 컬럼 프로파일은 15개 논리 테이블/277개 컬럼을 설명한다. Feature catalogue와 모델 metadata는
별도 내부 테이블에 저장한다. 실제 사내 feature 개수는 확인되지 않았으며 128은 명시적 더미 설정이다.
물리 테이블/컬럼 이름과 데이터·모델 경로는 `config/config.yaml` +
`config/platform-demo.yaml`에서 설정한다. Workbench는 `config/workbench.yaml`의
`platform_overlay`로 이 프로파일을 선택한다. 기존 분석 작업실과 통합 불량 분석 화면의
데이터 선택은 각각 표시된 사고 범위를 사용한다.

모든 사례에 정상 SEM 비교를 제공하고 정상 대조군·미확정 사례를 포함한다.
Failbit가 관측돼도 SEM이 정상일 수 있고, 한 센서만 이상일 때 다른 센서의 학습 label은
normal이다. 이런 차이는 조합별 관측과 반대 근거를 검토하기 위한 합성 설계다.
두 검사 stage의 fail count는 Vth 규격 초과·leakage 규격 초과·Failbit 대상 chip의 합집합으로
정의한 fixture 규칙이다. 실제 공정의 인과 모델로 해석하지 않는다.

## Agent와 Tool 호출

| 순서 | 역할 | 구현 |
|---|---|---|
| Router | 사고/기간/업무 의도를 분해하고 필요한 Tool과 Skill 선택 | `app/agent.py`, 역할 Skill과 tools.json |
| 사고 DB | 사고 검색 또는 집계, 후보 선택, scope 발급 | `find_incidents`, `summarize_incidents`, `match_incident_values` |
| 후속 Tool | 등록 Lot 검증 후 MES·검사·Measure·이미지·Trend·Inform 조회 | `list_incident_lots` → `get_platform_evidence` / `search_platform_history` |
| Judge | 현재 근거 ID, 시점, lineage, 부족·모순·비교 가능성 검토 | `evidence_review.py`, Judge 계약 |
| Answer | 관측·가설·미확인 사항·추가 점검을 구분해 최종 답변 | 기존 Answer 계약 |
| 최종 표시 | 실제 조회 상태와 선택 사고/기준 시점 표시 | 사건 scope와 Tool 결과/제한 보존 |

| 재조회·보호 규칙 | 처리 |
|---|---|
| 근거 부족/수정 필요 | Judge가 같은 Router로 반환. 조회 예산 소진 시 부분 답변 |
| Lot 미조회 | 복합 Tool을 Router에 활성 표시하지 않고 실행 코드에서도 거부 |
| 조회 범위 | actor/scope/사고 ID/as_of를 코드가 바인딩. SQL 입력은 받지 않음 |
| source 연결 | 사고 ID와 등록 Lot·영향 Wafer의 EXISTS 조건으로 검증. 중복 멤버 행이 집계를 증폭하지 않음 |
| 시간 경계 | runtime.timezone의 다음 날 00:00 미만. event time과 available_at을 모두 검사 |
| 학습 label | source `training_label`은 모델 target 전용이며 Tool 근거에서 제외 |
| 모델 시점 | 학습 자료 기준일보다 이른 질문에는 해당 모델 추론 보류 |
| 과거 사례 | 현재 사고보다 이전 자료의 관측 descriptor cosine 비교. 공통 modality와 별도 참조 scope 표시 |
| 숫자·수량 | item/unit/stage별 집계. rows는 제한된 샘플, summary/count는 전체 일치 범위 |

화면 진입·검색·사고 전환은 읽기 전용 조회와 합성 모델 추론이다. “LLM 복합 분석 실행”은
POST /api/platform/analyze를 통해 설정된 실제 Router → Tool → Judge → Answer를 호출한다.
명시한 사고번호 외의 필터 추론, 중복 조회, 원시 행의 과다 전송을 실제 로컬 Qwen 실행에서 수정했다.
텍스트 모델/roles/runtime은 활성 모델 overlay를 사용하며 synthetic DB/image mapping을 보존한다.
LLM 최초 답변의 chip/wafer 수량 오류도 발견했다. 수량 fact는 Tool의 전체 집계에서 코드가 만들고,
Answer는 fact ID와 조건별 조사 후보 ID를 선택하고 우선순위를 정한다. 수량 문장과 가설·반증 조건·
다음 점검 문구는 Adapter와 freeze된 Skill에서 직접 렌더링한다. 자유 서술을 검증된 분석으로 표시하지
않으며, 코드가 후보 범위·누락·중복·근거 ID를 검사한다. 원본 실제 LLM trace를 보존한다.
이 검사는 의미·인과 검증을 대신하지 않으며 사내 ACL·생산 제어를 구현했다고 표시하지 않는다.

## unique 값·오타·컬럼 설명 Skill

- 기본 7개 Schema와 `schema/platform-schema/references/logical-schema.json`이 모든 논리 컬럼의
  설명·type·unit·grain을 제공한다. 설정 로딩에서 platform source/컬럼 매핑의 일치를 확인한다.
- `column_profile.py`가 read-only SQLite에서 row/NULL/distinct/type와 낮은 cardinality 분포를
  읽는다. ID·긴 문서 내용은 값 예시에서 제외한다. JSON 배열 문자열과 배열 원소 distinct를 구분한다.
- `rules/data-profiling`, `rules/terminology`, `rules/platform-analysis`가 값 분포와 업무 의미,
  source 선택, 단위·기간·scope를 해석하는 규칙이다. 전체 프로파일은 오프라인 Skill 초안으로 저장한다.
- `match_incident_values`는 설정된 실제 DB unique 값과 정규화된 exact 후보를 우선 대조한다.
  optional fuzzy는 길이와 후보 수가 제한되며 ID·숫자·하이픈 코드를 임의 복구하지 않는다.
- 예: `temperatre` → `trend.item: temperature`는 `typo_candidate`와 확인 필요 표시를 반환한다.
  화면에서 사용자가 `이 값으로 조회`를 누르면 선택한 컬럼/DB 값의 exact 조건으로 카탈로그를 조회한다.
  후보를 자동 필터로 승격하지 않는다. Router가 helper를 생략해도 사고 검색 직전의 제한된
  DB 값 검증이 확인되지 않은 오타 후보의 필터 적용을 거부한다.
- 온라인 질의로 Skill을 생성·수정·freeze하지 않는다. 합성 프로파일을 사내 의미 검증으로 해석하지 않는다.

## 이미지·Trend 학습과 추론

| 모델 | 현재 실행 | 다음 단계의 구체적 방법 |
|---|---|---|
| SEM | 실제 생성 픽셀의 16개 feature → train-only StandardScaler → LogisticRegression | 촬영 조건별 supervised encoder, 정상 patch memory bank, contrastive retrieval 검토 |
| Trend | item별 raw 시계열 16개 feature → 별도 scaler/classifier | ROCKET 또는 1D CNN/TCN, 긴 시계열 self-supervised 학습 검토 |
| Failbit / EDS / Measure | composite chip의 규격 초과·bit 관측과 검사 분자/분모를 계산 | bit signature 및 검사조건별 multi-label 분류, 공정·기간별 calibration 검토 |
| Fusion | source별 원자료/집계 + 합성 모델 관측 + 과거 descriptor 비교 | modality 누락과 근거 의존성을 보존한 late fusion, 전문가 검토 데이터 확보 후 학습 |

현재 SEM과 Trend는 각각 사고 192개 train / 48개 holdout으로 분리했다. 같은 사고의 이미지나
센서가 양쪽에 섞이지 않으며 scaler는 train에만 fit한다. SEM 100%, Trend 약 98.6%는
단순 합성 분포에서 학습 연결을 확인한 수치다. 실측 성능·물리 결함 판정·일반화 근거로 사용하지 않는다.
선택 사례가 학습에 포함됐을 수 있음을 개별 추론에 기록한다.

NPZ checkpoint는 숫자 배열과 JSON metadata만 사용하고 `allow_pickle=False`로 읽는다.
이 프로파일의 `models.image.enabled`와 `models.trend.enabled`가 해당 CPU 추론을 제어한다.
학습 당시 설정 hash는 모델에 보존하고, 활성화 후 배포 설정 hash는 실행·프로파일 기록으로 남긴다.
학습 시점, 자료 기준일, 설정 해시, 사고 분할 hash·개수와 합성 여부를 기록한다.
모델의 label/score는 원인 확정을 대신하지 않는다. 참고한 논문과 로컬 코드 경로는
[연구·재사용 근거](PLATFORM_RESEARCH_AND_REUSE.md)에 정리했다.

## 실행과 산출물

저장소 루트 `D:\project\q-agent`에서 실행한다. 생성·학습은 새 설정 경로에 최초 한 번 수행하며
기존 DB·이미지·checkpoint가 있으면 덮어쓰기를 거부한다. 재생성은 별도의 버전 경로를 설정한다.

```powershell
python app/config_loader.py --config config/config.yaml --overlay config/platform-demo.yaml
python app/platform_demo.py --config config/config.yaml --overlay config/platform-demo.yaml
python app/train_platform_models.py --config config/config.yaml --overlay config/platform-demo.yaml
python app/column_profile.py --config config/config.yaml --overlay config/platform-demo.yaml --output-skill var/output/platform-demo-v3/column-profile/SKILL.md
python app/platform_tools.py --config config/config.yaml --overlay config/platform-demo.yaml --incident-number SYN-P-0085 --as-of 2026-10-24
npm --prefix web run build
python app/workbench.py --port 18743
```

현재 생성된 주요 경로:

- DB: `D:\project\q-agent\var\data\platform-demo-v3\quality_demo.sqlite`
- Manifest: `D:\project\q-agent\var\data\platform-demo-v3\platform-manifest.json`
- 이미지: `D:\project\q-agent\var\data\platform-demo-v3\images`
- SEM: `D:\project\q-agent\var\models\platform-demo-v3\sem\synthetic_sem.npz`
- Trend: `D:\project\q-agent\var\models\platform-demo-v3\trend\synthetic_trend.npz`
- 전체 컬럼 Skill 초안: `D:\project\q-agent\var\output\platform-demo-v3\column-profile\SKILL.md`
- 프로파일 JSON: `D:\project\q-agent\var\output\platform-demo-v3\column-profile.json`
- 실행 확인: `D:\project\q-agent\var\output\platform-demo-v3\verification.json`
- 화면: `D:\project\q-agent\output\playwright\platform-overview-20261024.png`

var의 DB·모델·전체 결과는 Git에서 제외한다. 평가 스크립트·정답 질문 세트는 생성하지 않았다.
검증은 config/Skill/조회 CLI, 합성 입력·출력 검사, 브라우저 흐름과 production build로 수행했다.
1,536개 이미지 해시, source 연결과 5,760개 검사 행의 분모·실패 chip 수를 대조했다.
일반 Workbench의 최초 DB 준비에서도 정답 질문 세트 builder와 파일 생성을 생략한다.
모든 source·프로파일·Lot/Wafer topic을 함께 로딩한 Router/Judge/Answer 프롬프트도 기존
36,000자 한도에서 검증했고, 초과 규칙을 조용히 잘라내지 않는다.


## 추가 분석 계약과 실행

Tabular는 train-normal의 median/MAD, PCA, robust covariance 및 재구성 residual을 사용한다.
전처리·threshold는 학습 표본에만 fit하고 사고 group과 시간 경계를 분리한다. source SHA와
데이터 계약 hash를 검사하며 텍스트 모델 설정 변경은 데이터 모델을 stale로 만들지 않는다.
128개 feature의 unit/spec/NULL/distinct 및 선택 컬럼 값을 catalogue로 조회한다.
`GET /api/platform/measure-catalog?q=Vth_V`로 정의를 확인하고 Tool의 `measure_features`에
정확한 이름을 최대 8개 전달한다. unknown/중복 이름은 거부하며 오타 후보를 자동 대체하지 않는다.

Map은 절차적 합성 공간 측정 예시이며 기존 failbit bitmap과 같은 물리 측정이라고 주장하지 않는다.
wafer 8-connected 색상 영역 후보, chip morphology, 위치 등록된 chip mask의 직접 Dice overlap을
구분한다. 반복성 기준은 서로 다른 등록 die 3개 이상이며 방향/촬영 조건의 물리 정합은 미검증이다.
회색/저채도 local 이상은 이 color baseline이 놓칠 수 있다. 정확도와 원인을 주장하지 않는다.

추가 생성 명령(기존 산출물 덮어쓰기 거부):

```powershell
python app/tabular_demo.py --overlay config/platform-demo.yaml --platform
```

Map 생성은 `map_analysis.generate_demo_maps(settings)`를 오프라인에서 호출한다.
새 산출물은 다음 위치다.

- Wide DB: `D:\project\q-agent\var\data\platform-demo-v3\tabular-v1\chip_tabular.sqlite`
- Map manifest: `D:\project\q-agent\var\data\platform-demo-v3\map-analysis-v1\map-analysis-manifest.json`
- 오프라인 컬럼 Skill: `D:\project\q-agent\var\output\platform-demo-v3\column-profile\SKILL.md`
- 실제 LLM trace: `D:\project\q-agent\var\output\platform-demo-v3\llm-traces`

합성 holdout의 규격 초과 heuristic label 기준으로 covariance+residual 후보 검출은 TP 562,
FP 1,207, FN 0, TN 35,095였다. 이는 독립 실측 정답에 대한 성능이 아니며 추가 dummy channel의
분포 변화는 그 label과 일치하지 않을 수 있다. 단순 합성 accuracy로 플랫폼의 분석 품질을 대체하지 않는다.


## 실제 LLM 검증과 최종 Answer 범위

로컬 Qwen을 실제 호출해 임의 필터 추가, 불필요 재조회, 문맥 초과, chip/wafer 수량 혼동,
수량 재작성 및 자유 서술의 낮은 품질을 확인했다. 따라서 현재 platform Answer는 자유 보고서 생성기가
아니다. Tool이 계산한 fact ID와 실제 관측 조건으로 제한한 Skill 조사 후보의 순위를 반환한다.
보고서에 수량과 source ID, 검토 가설·반증 조건·다음 점검을 원문 그대로 표시한다.
`answer_generation_mode`로 이 방식을 API에 공개한다. 이는 임의 생성 문장의 의미 검증이 끝났다는
주장이 아니라, 검증할 수 있는 답변 범위로 실행 계약을 바꾼 것이다.

조사 후보는 `D:\project\q-agent\app\skills\rules\platform-analysis\references\investigation-recipes.json`에
오프라인으로 관리한다. Tabular 조합, chip 반복, wafer local, 규격 초과 없는 bit 관측, Trend 변화,
MES HOLD, Inform 가설의 source 조건을 코드가 확인한다. 특히 sparse Failbit 행의 미관측은 별도의
등록 map 반복 후보를 취소하지 않는다. 실제 공정 조치는 실행하지 않는다.

platform용 Judge/Answer Skill을 분리해 불필요한 SQL schema와 중복 원시 행을 최종 답변 입력에서
제외했다. 실제 Answer input은 초기 31,757 tokens에서 최종 사례의 6,751 tokens로 줄었다.
긴 수량·계획 문장을 모델이 반복 생성하지 않고 ID를 선택하므로 출력 token도 줄이는 구조다.
최종 수치와 실행 결과는 별도 verification JSON과 실제 호출 trace를 기준으로 확인한다.


최종 실제 웹 버튼 실행 사례 `SYN-P-0003`은 `partial`로 보고서를 반환했다. source 완전성과 물리
정합의 미확인을 유지하면서 fact 11개와 관측 조건에 해당하는 조사 경로 5개를 표시했다.
Answer는 input 6,751/output 337 tokens, 약 18.28초였다. 전체 경로는 실제 LLM 6회와 Tool 4회이며
모의 응답을 사용하지 않았다. 자유 서술 품질을 검증 완료로 표시하지 않는다.
실행 기록: `D:\project\q-agent\var\output\platform-demo-v3\llm-traces\2415b9e7c6a64cc9992cf5d42e058a9f.jsonl`이다.
최종 검증 요약은 `D:\project\q-agent\var\output\platform-demo-v3\verification-0.71.json`에 저장했다.


추가 검증: `SYN-P-0085`에서도 EDS/FAB_OUT 각각 768 chip-test 중 12 fail, Failbit 48 bit-site와
12 distinct chip을 보존해 이전 wafer 수량 혼동이 재발하지 않았다. `SYN-P-0004`에서는 wafer local
검토와 chip 반복 검토를 함께 유지했다. 해당 Answer는 input 6,745/output 337 tokens, 약 18.11초였다.
합성 채널 이탈은 실제 전기 특성 불량과 구분하고 Inform의 조회를 승인으로 간주하지 않는다.
검토 가설과 반증 조건은 확정 원인이나 이미 관측된 반증 사실을 뜻하지 않는다.
