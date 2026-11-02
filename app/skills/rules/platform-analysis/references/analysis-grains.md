# 복합 분석의 관측 단위

출처/기준: 2026-10-24 로컬 코드·합성 fixture 및 로컬 연구 fixture 및 palette-map 자료의 제한된 표본,
fail-map/known-cnn/unknown-contrastive/ax_award 자료. 사내 측정 의미·정답은 미검증이다.

| 질문 | 검토할 결과 | 판정 경계 |
|---|---|---|
| 전기 특성 조합이 비정상인가 | tabular_analysis: chip wide vector, feature catalogue, covariance score·PCA residual·결측 | ID/좌표/규격은 feature가 아니다. 원래 long Measure와 더미 확장 feature 수를 각각 표시 |
| wafer의 특정 local 영역인가 | map_analysis: wafer_local_anomaly의 위치·영역·밀도 | wafer pixel region은 chip 내부 motif가 아니다. 좌표 등록과 정상 기준 없으면 후보 |
| chip 안에 어떤 모양인가 | chip_internal_motif: component/방향/형상 | morphology는 의미 label·원인·chip 간 반복성 확정이 아니다 |
| 서로 다른 chip에서 같은 모양이 반복되는가 | cross_chip_repeated_motif: 정합된 chip mask의 직접 겹침·서로 다른 die 수·기준값 | 여러 이미지 또는 embedding 유사도만으로 반복 판정 금지. 비교 가능 crop 크기/방향 확인 |
| Trend·전기·이미지가 같은 문제를 가리키는가 | source별 시간·장비/recipe·복합키·cross_modal_alignment | 동일 chip 교집합과 시간 선후관계는 상관 근거이며 인과 확정이 아님 |

한 사고가 여러 관측 유형을 함께 가질 수 있다. 유형을 하나로 강제하지 않는다.
정상 SEM 또는 정상 센서는 다른 source의 이상을 취소하지 않으며 반대/비지지 근거로 남긴다.
학습 label, illustration_mode, 생성 recipe를 불량 분석의 관측 근거로 사용하지 않는다.
온라인 근거에는 모델/알고리즘의 계산 결과만 넣는다. 실제 reference는 원본 provenance와 해시를
유지하며 등록되지 않은 실제 이미지를 합성 사고 scope에 합치지 않는다.

Tabular 전처리·PCA·covariance·threshold는 train-normal에만 fit한다. 사고 group이 train/holdout에
겹치지 않고 holdout은 이후 기간이어야 한다. per-feature robust deviation은 설명용 단변량 진단이며
covariance score의 합산 기여도로 부르지 않는다. 각 score/분모·판정 기준을 보존한다.
