# [합성 0001] 노광 조건 변경 이후 Wafer 외곽 Shot의 EDS Fail 증가

ALL SYNTHETIC. No fab data, model inference, BM25/vector retrieval or production action.

Source fixture: engineer_notes

## Section 1

DRAM_X 제품의 동일 노광 Layer에서 조건 변경 이후 처리한 4개 Lot, 80 Wafer에 영향이 확인된 가상 사고. EDS Fail이 Wafer 외곽 Shot에 집중됐고 중앙 Shot에서는 같은 수준의 증가가 관찰되지 않았다. 영향 수량은 해당 사고의 판정 기준으로 집계한 값이다.

## Section 2

동일 제품·Layer·Recipe 계열의 전후 구간을 비교하고 변경 시점과 각 Wafer의 실제 처리시각을 정렬했다. 가상 측정 기록에서 외곽 Focus 잔차와 외곽 EDS Fail 증가가 함께 관찰됐다. 변경 이전 조건을 적용한 확인 구간에서 두 지표가 함께 감소한 기록을 근거로 해당 조건 변경의 영향을 확정한 사례로 설정했다. 단순 이미지 유사성만으로 판단한 사례가 아니다.

## Section 3

변경 이력과 승인 기준을 대조해 외곽 보정 조건을 복원하고, 확인용 Wafer에서 Focus 잔차 및 패턴 측정값을 확인한 뒤 승인 절차에 따라 적용 범위를 확대한다.
가상 결과: 연속 3개 확인 Lot에서 Focus 잔차와 외곽 EDS Fail 지표가 내부 판정 기준을 충족했다. 실제 허용값은 이 더미에 정의하지 않았다.
