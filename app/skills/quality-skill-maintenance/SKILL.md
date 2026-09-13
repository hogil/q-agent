---
name: quality-skill-maintenance
description: 품질 Agent 역할 지침·공통 Skill·사전·스키마 규칙을 수정하고 평가할 때 사용하는 변경 절차.
---

수정 전 현재 release lock, 관련 Skill, 해당 references, 실패 질의/근거/코드 검사 결과를 읽는다. Skill 밖의 즉석 system prompt 수정으로 문제를 우회하지 않는다.
변경 대상이 역할 지침/공통 규칙/사전 데이터/물리 매핑/코드 중 어디인지 구분하고 단일 원본을 수정한다. 공유 규칙을 여러 역할에 복사하지 않는다.
기존 기준 사례와 새 실패 사례를 함께 실행한다. 변경에 사용하지 않은 holdout 질의에서 회귀를 확인하고, 여러 실행의 실패율·지연·토큰을 비교한다.
Skill 파일, 참조, Tool 계약, mapping, 사전 버전, 모델/추론 설정의 릴리스 조합을 고정한다. Judge의 자체 평가만으로 배포하지 않는다.
검토 전 release lock을 갱신하지 않는다. 승인된 소스 변경을 버전 관리에 기록하고 릴리스 빌드를 생성한 뒤 제한 범위 검증과 롤백 가능성을 확인한다.
운영 피드백은 개선 후보이며 실시간 자기 수정의 권한이 아니다. 실패 유형별 최소 수정으로 최적화한다.

배포 경로/파일명/endpoint/물리 테이블명 변경은 config/default.toml과 사내 overlay의 책임이다. 이를 system prompt에 하드코딩하지 않는다. Skill 소스 릴리스 해시와 실행 설정 config_hash를 별도로 기록한다. 경로만 바꾸고 Skill 내용이 같으면 프롬프트 재작성이나 freeze를 요구하지 않는다. 논리 필드의 의미/타입/관계가 바뀌면 해당 Skill/Catalog와 회귀 사례를 수정한다. 상세 설정 계약은 저장소 docs/current/CONFIGURATION.md를 참고한다.
