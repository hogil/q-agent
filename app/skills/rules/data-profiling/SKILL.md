---
name: data-profiling
description: DB 컬럼 프로파일 해석.
---

출처: Schema/config/column_profile.py, 2026-10-24 합성 검증; 사내 미검증.
의미는 Schema를 따르며 분포만으로 확정하지 않는다. 통계는 fixture 전체이며 선택 사고 수량이 아니다.
배열 원소 distinct와 사고 수량을 구분하고 균등 배분하지 않는다. ID는 exact, 오타는 확인 후 쓴다.
Skill 변경은 오프라인 검토/freeze이며 온라인 원본 수정은 금지한다.
