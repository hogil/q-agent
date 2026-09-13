---
name: skill-maintenance
description: 품질 Agent 역할 지침·공통 Skill·사전·스키마 규칙을 수정하고 평가할 때 사용하는 변경 절차.
---

수정 전 현재 release lock, 관련 Skill, 해당 references, 실패 질의/근거/코드 검사 결과를 읽는다. Skill 밖의 즉석 system prompt 수정으로 문제를 우회하지 않는다.
변경 대상이 역할 지침/공통 규칙/사전 데이터/물리 매핑/코드 중 어디인지 구분하고 단일 원본을 수정한다. 공유 규칙을 여러 역할에 복사하지 않는다.
설정·Skill 로딩·출력 계약과 변경한 실행 경로를 확인한다. 평가 스크립트와 정답 세트는 현재 저장소에 없으므로 실행했다고 보고하지 않는다. 승인된 실제 질의와 모델을 사용할 수 있을 때만 별도의 행동 검증을 수행하고, 정적 검사·합성 실행·실제 모델 검증 결과를 구분한다.
Skill 파일, 참조, Tool 인터페이스, mapping, 사전 버전, 모델/추론 설정의 릴리스 조합을 고정한다. Judge의 자체 평가만으로 배포하지 않는다.
검토 전 release lock을 갱신하지 않는다. 승인된 소스 변경을 버전 관리에 기록하고 릴리스 빌드를 생성한 뒤 제한 범위 검증과 롤백 가능성을 확인한다.
운영 피드백은 개선 후보이며 실시간 자기 수정의 권한이 아니다. 실패 유형별 최소 수정으로 최적화한다.

배포 경로/파일명/endpoint/물리 테이블명 변경은 config/config.yaml과 사내 overlay의 책임이다. 이를 system prompt에 하드코딩하지 않는다. Skill 소스 릴리스 해시와 실행 설정 config_hash를 별도로 기록한다. 경로만 바꾸고 Skill 내용이 같으면 프롬프트 재작성이나 freeze를 요구하지 않는다. 논리 필드의 의미/타입/관계가 바뀌면 해당 Skill/Catalog와 회귀 사례를 수정한다. 상세 설정 계약은 저장소 docs/current/CONFIGURATION.md를 참고한다.

## 프롬프트 수정 책임

| 변경 내용 | 수정할 원본 | 확인 범위 |
|---|---|---|
| 근거 취급, 권한 경계, 공통 업무 태도 | core/SKILL.md와 core/references | Router·Judge·Answer 모두 |
| 업무 조회 규칙, 컬럼 의미·타입·관계 | schema의 해당 SKILL.md와 references JSON | 해당 topic을 사용하는 역할 |
| 용어 해석, 조치 경계 | rules의 해당 Skill | 해당 업무 topic |
| 조회 계획·Tool 선택 | roles/router | submit_plan 인자와 실제 Tool 계약 |
| 근거 충분성·재조회 판정 | roles/judge | coverage, verdict, return_to |
| 최종 답변·출처·한계 표현 | roles/answer | status, claims, evidence_ids, limitations |

역할별 SKILL.md는 역할 지침, references/conditions.md는 조건 예시, output.schema.json은 출력 형식의 원본이다. 같은 규칙을 여러 역할에 복사하지 않는다. 공통 원칙을 해당 역할에서 어떻게 적용하는지만 역할 지침에 둔다. topic 이름과 연결은 registry, 프롬프트 조립은 skill_loader.py의 책임이다. 생성된 프롬프트를 직접 고쳐 원본을 대신하지 않는다.

기준: 2026-09-14 로컬 registry, compiler, ReAct 실행 코드와 출력 계약을 확인했다. 사내 원본·운영 모델은 미검증이며 이번 정리는 프롬프트 관리 책임과 실행 계약의 일치가 목적이다.

## 실제 데이터 확인 후 변경

수정 전 관련 실제 원본과 대표 데이터를 확인하고 출처, 기준시점, 변경 근거를 기록한다. 실제 데이터에 접근할 수 없으면 미확인으로 표시하고 설계/더미 초안으로만 관리한다. 더미 검증을 실제 데이터 검증으로 주장하거나 확인 없이 컬럼 의미, 관계, 코드값을 확정하지 않는다. 이 규칙은 원본 데이터 수정이나 온라인 Skill 자기 수정 권한을 부여하지 않는다.
