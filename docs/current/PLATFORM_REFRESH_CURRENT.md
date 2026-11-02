# 현재 All-in-One FAB 설계와 새 더미 재학습

기준 2026-10-25. 최신 사용자 계약에 맞춘 lab refresh 결과다. 이전 문서·DB·모델·자원 산정 자료를 보존했다. 이 문서는 기존 단계의 성능/완료 상태를 덮어 읽지 않도록 현재 데이터와 경계를 명시한다. 실제 FAB 데이터·LLM 답변 품질·생산계 MES 검증 완료를 뜻하지 않는다.

## 현재 데이터와 공통 키

| 항목 | Development | 독립 fresh |
|---|---:|---:|
| 원본 Lot group | 96 | 32 |
| 서로 다른 조건의 합성 Lot/Wafer | 192 | 64 |
| 선택 Chip/관측 sample | 12,288 | 4,096 |
| 전체 layout Chip inventory | 221,376 | 73,792 |
| Wafer×step 공정 run | 2,304 | 768 |
| Chip×step 합성 계측 panel | 147,456 | 49,152 |
| 일반 METRO sampling site | 2,496 | 832 |
| Chip별 FAB OUT Measure feature | 128 | 128 |

세 합성 structure는 bitline/wordline/contact의 연구 fixture이며 실제 메모리 제조 route가 아니다. 12개 공정 step에 CD1/CD2·overlay X/Y·recess·height·profile·roughness의 96개 IN feature를 구성했다. 물리 unit/spec은 미확인이고 `SYN_DEVIATION`이다. RCS는 recess를 뜻한다.

Chip key는 합성 Wafer ID + source frame + native X/Y다. signed X/Y, 파생 grid, canvas pixel, Chip-local fraction과 Failbit bit grid를 구분한다. geometry는 허가된 기존 position metadata의 대표 16개/4종만 재사용하고 실제 image/test 값은 읽지 않았다. 전체 20,378개 position 파일을 전수 검증한 것이 아니다.

64개 선택 Chip의 96개 값은 **합성 dense experimental panel**이다. 일반 13-point 측정이 모든 Chip에 존재한다고 표시하지 않는다. 일반 plan은 별도 `metro_site/metro_observation`으로 저장하고 CD1/CD2가 같은 Chip의 다른 합성 local 위치를 가리키게 했다. 측정되지 않은 값은 NULL이며 인접 Chip 값으로 대체하지 않는다.

같은 IN 관측에 다른 문맥을 부여한 twin은 별도 합성 Lot/Wafer/Chip scope를 가진다. development 6,144쌍 중 1,886쌍, fresh 2,048쌍 중 647쌍에서 OUT label이 달라졌다. 관측 하나에 상충하는 실제 정답을 덮어쓰는 방식이 아니다. pair/group의 정수 ID는 cohort 내부 키이므로 외부 join에는 dataset version/cohort를 포함한다. 모든 twin은 같은 split에 있다.

Yield는 Chip별 0/1(1 양호), Measure는 Chip별 128개 비음수 합성 severity(0 최선)다. Wafer 수율 집계와 원시 Chip Yield는 분리한다. 미검사는 tested=false/NULL이며 OUT 진단 모델은 미검사 행에서 abstain한다.

## IN 예측과 OUT 역추적

`fab_in_at`은 12개 critical step의 관측이 이미 존재하는 예측 snapshot이다. 공정 run은 snapshot 전 12시간~snapshot 안에 있고 available_at도 cutoff 이하다. OUT event는 72시간 뒤, 공개시점은 추가 6시간 뒤로 두었다. 두 시점을 중간 공정 진행 시간으로 혼동한 warehouse v1/v2는 과거 버전으로 보존하고 현재는 v3를 사용한다.

| 업무 | 허용 입력 | 결과/제한 |
|---|---|---|
| FAB IN→미래 OUT | cutoff 이전 IN panel, 이미지, 수치 METRO Trend, 조건·Inform text, 과거 공개 기록 | 미래 불량 classifier score와 기록 근거. 미래 Measure/Yield/사고 결론은 입력하지 않음 |
| FAB OUT→과거 IN | 공개된 Chip Measure/Yield·후속 map, 실제 이전 step/설비·계측과 과거 기록 | 과거 경로·조건·반례에 따른 원인 후보. 유사도/분포 차이를 인과 확정으로 바꾸지 않음 |
| 같은 관측·다른 text | recipe acceptance/recovery 조건·적용 구조/시점 | 현재 적용 가능성을 구분. 텍스트 안의 명령을 Tool 권한으로 사용하지 않음 |
| equipment DOWN | 해당 scope/가공 시점의 고장 기록 | 사용자 정책의 operational actual_defect 및 risk floor. 물리 원인 확정과 구분하며 정상 Inform으로 취소하지 않음 |
| Unknown | Known 점수와 독립된 기록 검색 + 별도 novelty score | Known taxonomy 밖의 기록도 검색. 미검색/낮은 Known score를 정상 근거로 쓰지 않음 |

## 모델과 고정 fresh 결과

train/validation/test는 Lot group 단위 chronological 분리다. 전처리·PWL bin은 train에서만 맞추고 epoch/모델·threshold는 validation에서만 선택했다. 모델 28개 파일과 selection·전처리·text cache를 freeze한 다음 독립 seed의 fresh cohort를 생성했다. 2개 신경망 seed 확률 평균과 별도 CPU CatBoost를 비교했다. 예전 cohort의 숫자와 새 숫자를 빼서 향상이라고 주장하지 않는다.

| 과제 | 기준 모델 AP/F1 | 개선 후보 AP/F1 | 판단 |
|---|---|---|---|
| 관측 OUT tabular | MLP 0.9639/0.9598 | 공식 PWL-TabM 0.9643/0.9609 | AP delta CI가 0 포함. 뚜렷한 우위 아님 |
| IN 이미지 local/repetition | global CNN 0.7455/0.7160 | spatial CNN 0.9590/0.9435 | AP delta +0.2135, Lot-bootstrap CI [0.1693,0.2463] |
| 수치 METRO Trend | temporal CNN 0.8860/0.8485 | temporal patch 0.8869/0.8517 | AP delta CI [-0.0016,0.0034], 우위 불확정 |
| IN→미래 OUT | dense fusion 0.8204/0.7972 | context-gated 0.8284/0.8005 | AP delta +0.0080, CI [0.0029,0.0141] |
| IN→미래 OUT | 동일 dense fusion | context feature CatBoost 0.8706/0.8246 | validation 선택 primary. AP delta +0.0503, CI [0.0407,0.0571] |

이미지 비교는 같은 32 epoch 예산의 결과다. global CNN의 validation이 끝까지 상승했으므로 충분히 수렴시킨 모든 CNN보다 우수하다는 주장은 하지 않는다. Tabular CatBoost의 fresh F1은 0.9732로 높지만 AP 우위는 없었고, test 숫자로 primary를 재선정하지 않았다.

Trend는 chart 이미지로 바꾸지 않았다. 16-point/stride8 수치 patch와 관측 mask를 temporal attention에 넣고 channel 간 attention을 추가한 소형 classifier다. PatchTST/iTransformer/Crossformer 원본 forecasting 재현이나 사전학습 foundation weight라고 부르지 않는다. 기존 anomaly-detection 생성 곡선은 source-family가 분리된 nuisance 요소로 재사용했다. FDC 검출기는 사용자 지시대로 보류한다.

공식 TabM/PWL을 실제 학습했고 이미지/Trend expert도 새 cohort에서 학습했다. Fusion은 supervised encoder의 penultimate representation과 공개 MiniLM의 고정 text feature를 이용한다. in-sample class 확률을 stacking하지 않으며 out-of-fold 학습이라고 주장하지 않는다. native multimodal foundation pretraining은 구현하지 않았다.

Unknown는 아직 약하다. fresh global AP 약0.198, conditioned AP 약0.196으로 향상되지 않았다. conditioned recall 0.431은 global 0.399보다 높지만 FPR도 0.140으로 상승했다. unlabeled unfamiliar 예제가 train에도 있으므로 엄격한 held-out-mechanism 발견 성능으로 표시하지 않는다. 결측·정보 소거·구분하기 어려운 사례도 삭제하지 않았다.

## 현재 실행 흐름

| 순서 | 단계 | 현재 상태 |
|---:|---|---|
| 0 | 사용자 질문·방향·cutoff·현재 scope | lab CLI가 typed 입력 검증 |
| 1 | Router | 제품 설계상 단일 Router. 새 lab CLI는 고정 업무 흐름이며 LLM Router가 아님 |
| 2 | 사고 DB | 새 CLI 첫 업무 SQL로 과거 공개 사고 검색을 강제 |
| 3 | 후속 Tool | scope/공정·좌표·asset 참조, 문서 Hybrid, 미래 OUT 모델 또는 관측 OUT 조회 |
| 4 | Judge | lab는 cutoff/scope/hash의 코드 검사. 서비스 LLM Judge 통합은 별도 |
| 5 | ActionExecutor | DOWN/risk와 추가 계측·HOLD 계획 표시. 이번 warehouse에서 생산 액션은 실행하지 않음 |
| 6 | Answer | 실제 조회·모델 결과 JSON 보고서. 서비스 LLM Answer는 별도 |
| 7 | 최종 조회 상태 | 현재/과거 scope, 조회 누락, 합성 여부, 실행되지 않은 조치를 표시 |

Judge의 부족 근거 재조회는 같은 Router로 보낸다. 재조회 예산·권한·current scope 검증은 코드가 보장해야 한다. 앱 role 변경은 app/skills와 공유 계약을 선행 freeze한 후 수행한다. 개발용 저비용 서브에이전트 설정과 제품 Router/Judge/Answer 배포 모델 설정은 별개다.

단일 조회도 고정 batch 예측과 일치하게 확인했다. classifier text는 학습과 같은 192-token 계약을 쓰고 RAG의 128-token 계약과 분리한다. 결측 이미지/Trend는 학습된 empty-input 상수를 재사용해 해당 encoder 실행을 건너뛴다. 처음 구현의 zero-vector 대체에서 생긴 불일치는 수정했으며 모델 가중치·fresh 결과를 바꾼 것은 아니다. 현재 조회 예시는 `D:\project\q-agent-models\var\output\platform-refresh-v1\investigations\forecast-verified.json`, 과거 IN 역추적은 `D:\project\q-agent-models\var\output\platform-refresh-v1\investigations\out_to_in.json`이다. 초기 `in_to_out.json`은 현재 predictor 검증 예시로 사용하지 않는다.

## DB·문서와 최적화

실제 생성한 사고 48건, Inform 12건, 반박 회의 12건, 공개시점 점검용 미래 문서 1건을 PDF/PPTX/DOCX/MHT/MD 파일로 저장하고 282 chunk로 파싱했다. RDB의 incident→document→chunk가 실제 파일/locator/hash로 연결된다. 검색은 visible corpus의 word/char TF-IDF와 기존 로컬 MiniLM vector를 RRF로 결합한다. 기존 사내 BM25+vector 서비스는 보존하며 이 lab 검색으로 교체했다고 표시하지 않는다. 한국어 업무 의미 검색 품질은 미검증이다.

이미지/Trend payload는 DB BLOB에 복제하지 않고 immutable array path/hash/row/available_at/mask/frame을 참조한다. Wafer×step run을 Chip×step 관측과 분리해 잘못 중복 세지 않는다. development DB는 391,180,288→191,270,912 byte로 51.1% 줄었다. 실패·이전 버전은 보존했다.

단순 자료 조사·DB builder·문서 생성·분석은 gpt-6-luna/low로 분담했다. parent는 데이터·scope·시점·모델 입력 경계와 실제 결과를 검토했다. GPU 작업은 하나씩 실행하고 기존 가중치/encoder cache를 검증해 재사용했다.

## 적용한 공개 근거와 한계

숫자 embedding/parameter-efficient ensemble은 [TabM](https://arxiv.org/abs/2410.24210), 수치 temporal patch는 [PatchTST](https://arxiv.org/abs/2211.14730), 문맥 결합은 [MMTM](https://arxiv.org/abs/1911.08670), 결측 modality 비교는 [CVPR 2022 원논문](https://arxiv.org/abs/2204.05454)을 참고했다. 새 코드가 이들 원본 모델을 그대로 재현했다는 뜻은 아니다.

[Hitachi CD-SEM 자료](https://www.hitachi-hightech.com/global/en/knowledge/semiconductor/room/manufacturing/cd-sem.html)는 recipe에 지정된 측정 위치와 top/bottom 측정 조건의 구분을, [TEL 공개 자료](https://www.tel.com/ir/policy/mplan/gtehh90000000038-att/SEMICON_West_2023_IR_Fireside_Chat_Q%26A_Summary_%28English%29.pdf)는 etch/deposition/clean/photo/prober의 step 간 지식 연결을 뒷받침한다. 공개 장비 기능을 사내 특정 불량의 원인 증명이나 spec으로 사용하지 않는다. GaN recess 논문은 다른 소자 도메인의 정성적 lead이며 DRAM/NAND 인과·수치를 전이하지 않았다. 17개 조사 entry에는 기존 연구와 중복된 자료도 있다.

## 현재 artifact와 다음 개선 기준

- 새 데이터: `D:\project\q-agent-models\var\data\platform-refresh-v1\development`, `D:\project\q-agent-models\var\data\platform-refresh-v1\fresh`
- 현재 DB: `D:\project\q-agent-models\var\output\platform-refresh-v1\development\warehouse-v3.sqlite`, `D:\project\q-agent-models\var\output\platform-refresh-v1\fresh\warehouse-v3.sqlite`
- 고정 모델: `D:\project\q-agent-models\var\runs\platform-refresh-v2`
- Fresh 결과/CI: `D:\project\q-agent-models\var\output\platform-refresh-v1\fresh\analysis.json`
- 현행 registry: `D:\project\q-agent-models\var\output\platform-refresh-v1\current-artifacts.json`
- 재현 설정: `D:\project\q-agent-models\config\config.yaml` + 학습용 `D:\project\q-agent-models\config\platform-refresh-v2.yaml`; 조회용 `D:\project\q-agent-models\config\platform-refresh-runtime-v1.yaml`

다음 개선은 validation에서 설계하고 다시 독립 cohort로 확인한다. 우선순위는 Unknown false positive 감소, regular sparse plan만 보이는 조건과 dense panel의 차이 검증, 충분히 수렴시킨 이미지 control, 긴 METRO 이력/다른 구조의 drift, 사내 schema/좌표 registration 연결이다. 이미 본 fresh set으로 모델·threshold를 고르지 않는다. 실제 LLM 답변 품질과 MES 실행 검증은 이 모델 실험과 분리해 수행한다.
