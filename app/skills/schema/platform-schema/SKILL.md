---
name: platform-schema
description: 합성 MES·검사·Measure·Failbit·SEM·Trend·Inform 컬럼 계약.
---

출처: platform_demo.py·config, 2026-10-24 합성 검증; 사내 미검증.
컬럼/type/unit/grain은 references/logical-schema.json, 물리 이름은 config를 따른다.
Chip 키는 사고/Lot/Wafer/Chip 복합키다. die/bit/SEM pixel 좌표를 구분한다.
EDS는 Electrical Die Sorting이며 FAB_OUT과 별도 stage다. training_label은 학습 전용으로
조회 근거에서 제외한다. 합성 관측·모델 score는 실제 원인·물리 정합의 증거가 아니다.
