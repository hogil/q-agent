# 통합 모델 분석 런타임 v2

기준: 2026-10-25. **http://127.0.0.1:8788/?tab=model-lab** 의 `모델 분석` 화면에서 실행한다. 기존 앱이 별도 학습 환경의 persistent worker와 연결됐다. 관측·사고·조치는 합성 데이터이며, 실제 서비스 LLM 호출 수는 0이다.

## 주 흐름

| 순서 | 주체 | 실제 동작 |
|---:|---|---|
| 0 | 질문 / 이미지·METRO·OUT 사례 | 명시적으로 고른 cohort/row/Wafer/Chip/cutoff 고정 |
| 1 | Router | 현재는 코드 기반 계획. 같은 Orchestrator로 입력과 가용 modality에 맞는 Tool 실행 |
| 2 | 사고 DB | 최초 업무 Tool은 사고 DB 검색. 과거 후보를 현재 사고로 자동 선택하지 않음 |
| 3 | 후속 Tool | 공정 경로, 설비 DOWN, regular METRO/dense panel, 수치 Trend, 모델, 유사 이미지, 과거 RDB/원문, critical-step 설비 조합 조회 |
| 4 | Judge | 코드가 source hash·시점·의존성·scope를 검사. 실제 LLM Judge와 구분 |
| 5 | ActionExecutor | 별도 더미 DB의 상태/revision과 근거를 검사해 HOLD·투입 차단·계측 요청·조건부 RELEASE |
| 6 | Answer | 실제 조회와 모델 출력으로 구조화한 요약/JSON 보고서. 실제 LLM Answer와 구분 |
| 7 | 최종 조회 상태 | 현재 scope, 미래 OUT 미관측, 근거 원문, 모델/실행 방식, 제한과 더미 조치 receipt 표시 |

| 재조회/변경 규칙 | 처리 |
|---|---|
| 원문 결과 없음 | 같은 Router 경로에서 제한된 재조회 |
| modality 없음 | unavailable 표시. 다른 modality로 실제 관측을 대체하지 않음 |
| source/model/config 변경 | cache 무효화 또는 contract 재동결/재분석 요구 |
| MES revision 변경 | 오래된 조치 거절 |

기존 앱의 13개 LLM 업무 Tool registry와 lab의 16개 Tool은 다른 namespace다. 새 API/UI bridge는 실제 연결됐지만, 기존 채팅 사고 scope를 lab case에 자동 매핑하거나 실제 LLM 역할이 실행됐다고 표시하지 않는다.

## 학습 결과

관측 IN panel + 고정한 image/Trend representation + 관측 text embedding + availability mask를 사용했다. 현재 미래 OUT Measure/Yield, 사고 결론, 식별자, 생성 정답을 forecast feature로 넣지 않았다.

CatBoost depth 6/7 후보를 각 6개 head로 학습하고 learning rate·L2·random strength·feature subspace를 조정했다. Logloss로 최적화하고 PRAUC로 early stopping했다. 공식 자료: [parameter tuning](https://catboost.ai/docs/en/concepts/parameter-tuning), [rsm과 훈련 속도](https://catboost.ai/docs/en/concepts/speed-up-training).

Validation으로 기존 모델 0.50 + 신규 후보 각각 0.25 ensemble과 threshold를 선택·고정했다. 이후 새 확인 cohort를 생성했으며 확인 결과로 재선정하지 않았다.

| 비교 | 기존 | 선택 모델 | 차이 |
|---|---:|---:|---:|
| Validation Macro AP | 0.868962 | 0.870095 | +0.001133 |
| 새 seed 4,096행 Macro AP | 0.866483 | 0.870030 | +0.003547 |
| 새 seed 4,096행 Macro F1 | 0.825522 | 0.833373 | +0.007851 |

공통 관측을 공유하는 두 문맥 시나리오를 **32개 원래 Lot group**으로 묶은 paired bootstrap AP 차이의 95% 구간은 **[0.001002, 0.005641]**이다. 최초 64개 시나리오 Lot 단위 구간은 보정 대상으로 보존했다. 개선 폭은 작다. 새 cohort도 같은 nuisance/geometry 참조를 쓰는 procedural seed이므로 사내 현장 검증이나 완전히 새로운 공정 도메인 검증으로 부르지 않는다.

Forecast는 **18개 CPU CatBoost head를 실제 실행**한다. Image/Trend/관측 OUT expert는 별도로 고정한 row-bound 결과를 참조한다. native 멀티모달 foundation pretraining, 실제 SEM/EDS/FBM encoder 연결, 새로운 Unknown 탐지 개선을 이번 결과로 주장하지 않는다. FDC 검출은 계속 보류한다.

## 코드 성능

| 변경 | 측정 결과 | 범위 |
|---|---|---|
| 128 Measure 집계 | 9,484ms → 308ms; 9,395ms → 330ms | UNION ALL 대신 1회 join·설정 기반 SUM/COUNT. 두 사례 전체 출력 일치, float 차이 없음 |
| persistent worker | 모델과 관측 feature를 프로세스 안에 유지 | source/전처리/모델 hash와 변경 상태 검증 |
| report cache | 최종 guard: image 첫 실행 12.81초, 동일 요청 재사용 8.81ms | 같은 case·질문·변경 없는 source에 한정. 이전 trace를 새 실행으로 표시하지 않음 |
| 화면 lazy loading | 초기 JS 약38.5KB/2.83% 감소 | 기존 대형 main bundle 경고는 남아 있음 |

첫 EXISTS-only 후보는 일관된 개선이 없어 채택 근거에서 제외했다. 이후 wide 집계의 동치/속도를 따로 검증했다. 원래 비교 함수·모델·DB는 보존했다. 최종 새 요청은 METRO 약1.58초, OUT/설비/문맥 사례 약3.5초였다. process/library 초기 로딩과 cache 재사용을 구분한다.

## 같은 관측, 다른 text

`문맥 비교 A/B`는 tabular·image·Trend·observed mask·availability가 정확히 같고 text가 다르다. 서로 다른 합성 Wafer/Chip scope다. 한 `open_signature` live forecast는 **0.94605 → 0.37204**로 달라졌다. 고정 모델의 문맥 반응을 보여주는 예시이며 성능 표본이 아니다. 선택에 미래 label을 쓰지 않았고 전체 성능은 위 4,096행으로 보고했다.

## 더미 MES

- 원본 warehouse는 읽기 전용이다. 조치는 별도 SQLite ledger에 쓴다. MES 키는 cohort+Wafer로 유지해 Chip 질문/cutoff 변경으로 HOLD가 초기화되지 않는다.
- DOWN의 설비/chamber와 실제 route의 step·recipe를 대조한다. cutoff에 확인된 WIP만 영향 Lot/Wafer로 포함한다. 검증 사례는 1 Lot/1 Wafer였다.
- HOLD는 해당 범위를 HELD로, BLOCK_DISPATCH는 별도 rule로 기록했다. dispatch-check에서 추가 투입 불가가 확인됐다.
- ADDITIONAL_METRO는 REQUESTED이며 PASS나 신규 실측 값이 아니다.
- RELEASE는 별도 더미 계측·승인 receipt가 있는 SCREENING HOLD 사례에만 허용했다. DOWN RELEASE는 차단했다. 이 qualified fixture를 회사 승인이나 모델의 물리 원인 확인으로 해석하지 않는다.
- 같은 request ID/payload는 같은 receipt를 반환한다. 다른 payload의 ID 재사용, stale revision, 변경된 조사 근거는 거절한다.
- 30개 typed runtime guard를 통과했다. 이는 LLM 정답 질문 세트나 LLM 답변 품질 평가가 아니다.

HTTP에서도 7개 사례를 실행해 78회의 중간 Tool 진행 상태를 관측했다. 동일 요청 재사용은 9.80ms였다. 실제 브라우저에서 수치 METRO 채널 변경·원문 펼치기·조건부 RELEASE를 확인했고, 조치 후 JSON 다운로드에 최신 상태와 receipt가 포함되는 것을 확인했다. 원래 UI 다운로드가 receipt를 빠뜨리는 문제를 재현한 뒤 report API에서 최신 내용을 받아 저장하도록 수정했다. Windows의 중복 포트 bind와 worker 자식 프로세스 종료도 보정했다.

## 설정과 재현

| 목적 | 절대경로 |
|---|---|
| 앱 base + demo overlay | `D:/project/q-agent/config/config.yaml` + `D:/project/q-agent/config/platform-demo.yaml` |
| 앱 실행 / bridge | `D:/project/q-agent/app/workbench.py`, `D:/project/q-agent/app/model_lab.py` |
| UI | `D:/project/q-agent/web/src/ModelLabView.tsx` |
| lab base + runtime overlay | `D:/project/q-agent-models/config/config.yaml` + `D:/project/q-agent-models/config/platform-runtime-v2.yaml` |
| 학습 / worker / SQL | `D:/project/q-agent-models/src/qmodels/platform_uplift.py`, `D:/project/q-agent-models/src/qmodels/platform_runtime.py`, `D:/project/q-agent-models/src/qmodels/tool_equipment_runtime.py` |
| 신규 모델 | `D:/project/q-agent-models/var/runs/platform-uplift-v1` |
| 학습·확인 결과 | `D:/project/q-agent-models/var/output/platform-uplift-v1/training-summary.json`, `D:/project/q-agent-models/var/output/platform-uplift-v1/confirmation-grouped.json` |
| 새 더미 cohort | `D:/project/q-agent-models/var/data/platform-uplift-confirm-v1/fresh` |
| 더미 MES | `D:/project/q-agent-models/var/data/platform-runtime-v2/workbench-actions.sqlite` |
| 런타임 출력 | `D:/project/q-agent-models/var/output/platform-runtime-v2` |
| guard / SQL 검증 | `D:/project/q-agent-models/var/research/platform-run-v2/guard-check-v3.json`, `D:/project/q-agent-models/var/research/platform-run-v2/equipment-sql-wide-check.json` |
| HTTP / 브라우저 검증 | `D:/project/q-agent-models/var/output/platform-runtime-v2/http-check.json`, `D:/project/q-agent-models/var/output/platform-runtime-v2/browser-check.json` |
| 실제 화면 캡처 | `D:/project/q-agent/output/playwright/model-lab-trend-v2.png`, `D:/project/q-agent/output/playwright/model-lab-release-v2.png` |
| 최신 조치 포함 보고서 | `D:/project/q-agent-models/var/output/platform-runtime-v2/release-reports/qualified-release-browser-download.json` |
| 파일 보존 검증 | `D:/project/q-agent-models/var/output/platform-runtime-v2/source-preservation-check.json` |

```powershell
Set-Location D:/project/q-agent
npm.cmd --prefix web run build
& D:/project/q-agent-models/.venv/Scripts/python.exe app/workbench.py --port 8788
```

기존 frozen run을 덮어쓰지 않고 새 overlay/run 경로로 재학습한다. runtime-contract와 Skill freeze13, release-artifacts의 source/hash를 확인한다. 앱의 기존 lock에서 달라진 파일은 선택적 model_lab 설정을 추가한 config_loader.py 하나였으며, 역할 Skill 내용은 바꾸지 않고 registry/lock을 quality-demo-0.72로 명시적으로 재동결했다. 원래 0.71 registry/lock은 보존했다.

Resource preservation 검증은 Git의 checkout line ending filter를 적용한 blob hash로 25개가 일치했다. 132개는 기존 명시적 사용자 삭제 예외다. 기존 누락 문서 1개는 별도 기록했으며 이번 작업에서 원본 자료를 수정·삭제·복원하지 않았다. 실제 Router/Judge/Answer LLM 연결은 endpoint/provider 선택이 남아 있고, 외부 API 호출·키 생성은 실행하지 않았다.
