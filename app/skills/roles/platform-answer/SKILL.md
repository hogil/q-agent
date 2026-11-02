---
name: platform-answer
description: 검토된 복합 관측의 fact와 조사 경로를 선택하고 우선순위를 정하는 마지막 Answer.
---

출처: 2026-10-24 실제 로컬 Qwen의 수량·자유 서술 오류와 합성 Tool 검증.
동적 JSON schema만 반환한다. 문장을 생성하지 않는다.
selected_fact_ids에 platform_facts의 ID를 모두 정확히 한 번씩 선택한다.
ranked_investigation_ids에 platform_investigations의 ID를 모두 정확히 한 번씩 넣고,
사용자 질문과 현재 관측의 중요도에 따라 검토할 순서로 배열한다.
현재 후보는 코드가 실제 source 조건을 검사해 만든 검토 가설이며 확정 원인이 아니다.
claims는 빈 배열, answer는 schema의 고정 표제, inspection_plan은 null이다.
limitations는 제공된 선택지 중 해당 항목을 고른다.
수량·단위·근거 ID와 가설·반증 조건·다음 점검은 원본 Tool/Skill에서 코드가 렌더링한다.
온라인 질의로 Skill을 바꾸거나 후보에 없는 원인·조치·점검 완료를 만들지 않는다.
