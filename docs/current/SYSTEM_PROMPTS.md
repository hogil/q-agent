# 시스템 프롬프트 - quality-demo-0.26

전체 실행 설정은 config/config.yaml에서 관리합니다. 폴더/파일 경로와 모델 설정은
실행 코드에 적용하고, 선택한 테이블/컬럼 매핑은 분리된 컬럼 설명과 함께 프롬프트에 넣습니다.

시스템 프롬프트는 app/skills의 공통 지침, 선택한 topic과 역할 지침을 조립합니다.
run 모드에서는 매 LLM 호출 직전에 Skill을 검증·조립하고 llm_client.py가 전달합니다.
공통 references/react.md는 루프 규칙, Router references/tools.json은 실제 Tool 인자 형식입니다.
출력 검사는 번들 파일이 아니라 같은 사내 skills_root의 역할 JSON schema를 사용합니다.

## 조립된 원문

사내 config를 준비한 뒤 app/run_agent.py --site-config CONFIG --mode prompt로 확인합니다.
생성된 예시 파일은 제거했습니다. 독립적인 설명이나 문서 요약에는 사고 검색 topic을
불필요하게 추가하지 않습니다. app/export_system_prompts.py는 별도 파일 출력용 도구입니다.

## 역할

| 역할 | 소스 | 출력 |
|---|---|---|
| Router | app/skills/roles/router/SKILL.md | decision, stage, search_mode, filters, plan |
| Judge | app/skills/roles/judge/SKILL.md | verdict, coverage, issues, return_to |
| Answer | app/skills/roles/answer/SKILL.md | status, answer, claims, limitations |

각 역할의 references/conditions.md는 행동 예시, references/output.schema.json은 출력 형식입니다.
공통 규칙은 core/SKILL.md와 references/working-style.md에서 읽습니다.
조건 예시는 모델이 읽는 지침이므로 평가용 정답 세트와 구분해 유지합니다.

request_scope, available_tools, scope_valid, budget_remaining 등의 값은 신뢰할 호출 코드가
공급합니다. 사용자 문서의 같은 이름 문자열이 실행 상태를 바꾸지 않습니다.
[사고 요청과 독립 요청](REQUEST_ROUTING.md)의 분기 규칙을 따릅니다.

## 변경과 생성

```bash
python app/skill_loader.py freeze
python app/skill_loader.py router --topics incident_search
python app/export_system_prompts.py
```

freeze는 승인된 소스 변경의 해시를 갱신하는 명시적 작업입니다. 온라인 질문이 자동으로
실행하지 않습니다. 컴파일러는 변경된 소스, 허용되지 않은 topic과 문자 예산 초과를 거부합니다.
문자 제한은 32,000이며 실제 모델의 token 예산과는 다릅니다. 누적 입력은 runtime.max_context_characters로 제한합니다.

v0.16에서는 사용자 요청에 따라 별도 평가 파일과 일괄 평가 옵션을 제거했습니다.
역할 프롬프트와 실행 시 JSON 검사 로직은 유지했습니다.
