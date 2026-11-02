# 통합 분석의 연구·로컬 코드 근거

최신 출처 검토·새 cohort 학습·현재 한계는 [PLATFORM_REFRESH_CURRENT.md](PLATFORM_REFRESH_CURRENT.md)를 따른다. 아래 출처와 구현 설명은 당시 검토 범위의 기록으로 보존한다.

확인일 2026-10-24. 실제 공정 자료와 사내 모델을 검증한 문서가 아니다.
Q-Agent의 현재 학습은 자체 합성 데이터의 CPU baseline이며, 아래 논문 모델을 그대로 구현했다고
주장하지 않는다. WM-811K와 외부 데이터셋은 사용하지 않았다.

## 논문·공식 기술 자료

| 자료 | 확인한 방법과 플랫폼 적용 판단 |
|---|---|
| [PatchCore, CVPR 2022](https://arxiv.org/abs/2106.08265) | 정상 이미지 patch feature의 대표 memory bank와 최근접 비교. SEM의 정상 기준·촬영 조건별 patch 검색을 확장할 때 참고한다. 현재는 procedural patch feature와 선형 분류기를 실행한다. |
| [SimCLR, ICML 2020](https://arxiv.org/abs/2002.05709) | 서로 다른 augmentation view의 contrastive 학습. SEM/Failbit 검색 encoder 설계에 참고하되, 방향·물리 의미를 바꾸는 augmentation은 조건별 검증이 필요하다는 것은 이 플랫폼의 설계 판단이다. |
| [ROCKET, 2020](https://arxiv.org/abs/1910.13051) | random convolution kernel 변환과 선형 분류로 시계열 분류 비용을 줄이는 접근. raw Trend의 다음 baseline 후보로 두었다. 현재 hand-crafted 16개 feature와 별도 classifier를 사용한다. |
| [1D ResNet for Semiconductor Equipment Fault Detection, 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10675586/) | 반도체 장비의 다변량 raw 시계열에 1D CNN/ResNet을 적용한다. 장비·recipe·센서·시간 정렬을 유지하는 데이터 계약의 참고 자료다. |
| [TRACE-GPT, 2023/2024](https://arxiv.org/abs/2309.11427) | temporal convolution embedding과 generative pre-training을 사용하는 반도체 sensor 이상 탐지 연구. 소량 label과 긴 이력의 후속 연구 후보이며 현재 배포 모델이 아니다. |
| [NIST SEM overlay metrology](https://www.nist.gov/programs-projects/overlay-metrology-using-physics-and-ai-based-scanning-electron-microscopy) | SEM의 물리 계측 모델·AI 및 측정 한계 검토. 플랫폼에서 합성 pixel 설정과 실제 CD/overlay 검교정을 구분하는 설계 근거다. |
| [FIB/SEM and TEM for SRAM Bit Failure Analysis](https://www.cambridge.org/core/journals/mrs-online-proceedings-library-archive/article/abs/application-of-fibsem-and-tem-to-bit-failure-analyses-in-sram-arrays/EF72F043CFF40C857F699702B13B5105) | bit 고장과 물리 분석의 교차 검토 사례. 논문의 EDS는 성분분석 문맥이며, 이 플랫폼의 Electrical Die Sorting stage와 같은 데이터로 취급하지 않는다. |

위 자료는 각 연구의 방법을 검토하기 위해 사용했다. 논문의 benchmark 점수를 합성 플랫폼의
성능 근거로 인용하지 않는다. 이 플랫폼의 분할·시점·정합 규칙과 late fusion 선택은 해당 자료에서
직접 입증된 결론이 아니라 현재 데이터 계약을 위한 구현 판단이다.

## 다른 로컬 프로젝트에서 확인한 연결 방식

| 프로젝트 | 코드 경로·확인한 내용 | Q-Agent에 적용한 범위 |
|---|---|---|
| fail-map | `D:\project\fail-map\positions_module.py`, `D:\project\fail-map\docs\pipeline-overview.md` — palette map와 chip 위치/bin 구조화 | Failbit bit 좌표와 die 좌표를 분리하고 structured feature/bitmap을 생성하는 계약 참고 |
| failure_agent | `D:\project\failure_agent\lib\contrastive_loader.py`, `D:\project\failure_agent\lib\search_core.py` — 이미지 encoder와 cosine gallery 검색 | 이미지 feature/검색 API를 분리하는 방식. 현재 검색은 합성 관측 descriptor를 사용 |
| known-cnn | `D:\project\known-cnn\wafer_train\cnn_train.py`, `D:\project\known-cnn\wafer_predict\cnn_predict.py` — supervised fail-bit 학습과 전처리·추론 경로 | 학습/추론 계약과 label 분리 참고. 기존 class 수나 checkpoint를 이식하지 않음 |
| unknown-contrastive | `D:\project\unknown-contrastive\_cache_features.py`, `D:\project\unknown-contrastive\_adaptor_train.py` — frozen feature cache와 adapter/InfoNCE | 대형 feature encoder의 후속 설계 후보. 현재 CPU baseline과 구분 |
| anomaly-detection | `D:\project\anomaly-detection\train.py`, `D:\project\anomaly-detection\scripts\two_stage_predict.py` — chart 이미지의 normal gate와 type classifier | chart 이미지와 raw 시계열 모델을 구분. 현재 Trend 모델은 원시 값에 직접 feature 계산 |
| wafer-defect-agentic-rag | `D:\project\wafer-defect-agentic-rag\lib\agents\image_search.py`, `D:\project\wafer-defect-agentic-rag\lib\agents\tools.py` — lazy model load, 이미지 검색 Tool, Trend SQL 집계 | source별 Tool과 모델 호출/수치 집계를 분리하는 방식 참고 |

이 조사에서는 각 프로젝트의 코드·README·적용 AGENTS를 읽었다. Q-Agent는 자체 생성 이미지·DB와
독립적인 config mapping을 사용한다. 다른 프로젝트의 실제 이미지·사고 내용·학습 데이터·로그·가중치는
가져오거나 수정하지 않았다. 현재 실행에는 다른 프로젝트 폴더나 pretrained checkpoint가 필요하지 않다.

## 학습에서 Tool까지의 계약

1. 데이터 생성/승인: 사고·Lot·Wafer·Chip 키, 시점, 단위, source provenance를 먼저 고정한다.
2. 분할: 같은 사고와 연결된 이미지·센서를 한 group으로 유지한다. 실제 자료 도입 시 Lot·기간·장비·recipe 간 전이도 따로 검토한다.
3. 학습: scaler/encoder/threshold는 train 자료로 정한다. label은 target이며 조회 근거와 feature에 넣지 않는다.
4. Artifact: 설정된 모델 경로에 버전, feature 규격, 자료 기준일과 split hash를 저장한다.
5. 추론: asset ID/범위를 먼저 검증하고 feature와 score·모델 metadata를 반환한다. 모델 score를 원인 확률로 쓰지 않는다.
6. Agent: Router가 사고 DB와 Lot을 확인한 후 Tool을 호출한다. Judge가 출처·모순·누락을 검토하고 Answer가 마지막 답변을 작성한다.

source별 관측의 가설 지지와 반대 근거를 함께 보존한다. 현재 구현은 학습된 end-to-end 원인
판별기, 물리 정합 모델, 운영 ACL 또는 생산 제어 모델을 구현했다고 표시하지 않는다.


## 2026-10-24 추가 확인: tabular와 공간 grain

- [scikit-learn covariance 공식 문서](https://scikit-learn.org/stable/modules/covariance.html)와
  [PCA 공식 문서](https://scikit-learn.org/stable/modules/decomposition.html#pca)를 확인했다.
  train-normal의 robust scaling 후 PCA 공간의 robust covariance와 재구성 residual을 별도로
  계산하는 구현 판단에 참고했다. 이 조합의 사내 성능을 문서가 입증하는 것은 아니다.
- [UCR Matrix Profile 연구 자료](https://www.cs.ucr.edu/~eamonn/MatrixProfile.html)는 시간 구간의
  motif/discord 검색 후속 후보다. 시간 반복과 공간 chip 반복을 같은 알고리즘/의미로 취급하지 않는다.
- `D:\project\ax_award`의 `uploads/META_SCHEMA.md`, `bkm_field_predict.md`,
  `two_stage_workflow.md`, `ARCHITECTURE.md`를 읽었다. wafer/chip taxonomy와 시간 신호 계약을
  참고했으며 분류 label 수를 전기 측정 feature 수로 사용하지 않았다. 문서 설계를 실행 구현의 증거로
  삼지 않았고 원본 문서/이미지는 변경하지 않았다.
- `로컬 데이터 경로`는 read-only inventory와 제한된 palette map/cohort를 확인했다. 한 cohort의
  positions JSON과 15개 crop의 die 좌표를 연결했으나 전체 데이터 정답 검증은 아니다.
  private index는 `D:\project\q-agent\var\data\reference-inputs\image-reference.local.json`에
  보관하며 원본 경로/해시/provenance를 보존한다. 실제 reference와 절차적 합성 사고 데이터는
  별도로 관리한다. SEM이라는 파일명만으로 전자현미경 이미지라고 분류하지 않는다.
- known-cnn의 chip crop/classification, unknown-contrastive의 wafer embedding/군집,
  fail-map의 positions 변환은 각기 다른 역할이다. embedding 유사도만으로 local localization이나
  chip 간 반복성 구현을 대신했다고 표시하지 않는다. 새 map Tool은 별도의 위치·mask 겹침·형상
  계산 결과와 비교 조건을 반환한다.
