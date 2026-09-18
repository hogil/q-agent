---
name: skill-maintenance
description: 품질 Agent 역할 지침·공통 Skill·사전·스키마 규칙을 수정하고 평가할 때 사용하는 변경 절차.
---

수정 전 현재 release lock, 관련 Skill, 해당 references, 실패 질의/근거/코드 검사 결과를 읽는다. Skill 밖의 즉석 system prompt 수정으로 문제를 우회하지 않는다.
변경 대상이 역할 지침/공통 규칙/사전 데이터/물리 매핑/코드 중 어디인지 구분하고 단일 원본을 수정한다. 공유 규칙을 여러 역할에 복사하지 않는다.
설정·Skill 로딩·출력 계약과 변경한 실행 경로를 확인한다. 2026-09-18 사용자 요청으로 합성 DB·회의록·golden 생성과 오프라인 검증을 다시 추가했다. retrieval 모드는 지정 검색어의 검색 계약만 검증하고 Router/Answer 정확도를 측정하지 않는다. live 모드는 실제 설정된 모델을 사용하며 결과의 의미 정확도는 전문가가 별도 검토한다. 정적 검사·합성 실행·실제 모델 검증을 구분한다.
Skill 파일, 참조, Tool 인터페이스, mapping, 사전 버전, 모델/추론 설정의 릴리스 조합을 고정한다. Judge의 자체 평가만으로 배포하지 않는다.
검토 전 release lock을 갱신하지 않는다. 승인된 소스 변경을 버전 관리에 기록하고 릴리스 빌드를 생성한 뒤 제한 범위 검증과 롤백 가능성을 확인한다.
운영 피드백은 개선 후보이며 실시간 자기 수정의 권한이 아니다. 실패 유형별 최소 수정으로 최적화한다.

## Golden 기반 개선

- 2026-09-18 사용자 결정: 답변 평가의 제1 기준은 Token Recall이다. golden의 질문별 reference_answer 토큰을 생성 답변이 얼마나 포함하는지 측정하고 Precision/F1이나 답변 길이로 감점하지 않는다. 회의록에 없는 근거 기반 추가 설명은 허용한다. 사실 오류·근거 위반은 별도로 검토하며 Recall 점수에 혼합하지 않는다.
- unicode_word_v1 토큰화(NFC, casefold, Unicode 문자·숫자 연속 구간)를 고정하고 등장 횟수를 제한한 overlap/reference token count를 사용한다. 조사·동의어는 자동 일치하지 않고 LLM subword 토큰도 아니다. 모델 답변이 없거나 reference 토큰이 없으면 미측정이다. 모든 사례가 측정된 경우의 macro 평균이 주점수이며 일부만 측정된 평균은 따로 표시한다.
- 같은 사고의 반복 회의·질문은 한 group/split에 묶는다. 시간순 분리와 별도로 기준시점 이후 문서·수정본 유입을 막는다. 합성 초안은 전문가 검증 정답으로 표시하지 않는다.
- train에서만 예시를 선택한다. dev는 실패 분석·후보 비교에 사용하고 test는 최종 확인용으로 보관한다. test 실패 문구를 예시에 복사하지 않는다.
- 먼저 DB 매핑/검색 누락/시점/범위/판정/답변 중 실패 원인을 분류한다. 검색 누락을 정답 암기 프롬프트로 덮지 않는다. propose는 수정 제안일 뿐 Skill·lock을 변경하지 않는다.
- retrieval의 annotated 검색어와 question 원문을 분리해 확인한다. 질문 원문 모드도 사고 scope는 정답 annotation을 사용하므로 Router 성능이 아니다. 필수 chunk가 있는 사례의 recall을 따로 보고, 정답이 비어 있는 사례의 통과로 검색 성능을 부풀리지 않는다.
- baseline/candidate 비교는 같은 데이터·DB fingerprint·config·split·query source·case 집합으로 제한한다. compare는 gain과 회귀를 표시할 뿐 배포 승인이 아니다. 필수 chunk 목록은 전체 관련 문서 목록이 아니므로 precision은 별도 라벨로 검증한다.
- 역할별 references/examples.md는 필요한 행동 예시만 소수 유지한다. "예시" 표시만으로 과적합이 방지되지는 않는다. ID·값·표현을 바꾼 사례와 유사하지만 다른 답이 필요한 반례도 검토한다.
- runtime.prompt_examples=false/true를 동일 모델·데이터·예산·release에서 비교한다. 기존 conditions.md 규칙은 양쪽에 동일하게 유지하므로 이는 추가 few-shot의 효과 비교다. retrieval 모드 결과만으로 예시의 모델 성능 개선을 주장하지 않는다.
- dev 개선과 회귀 부재를 전문가가 확인한 후보만 운영 반영한다. 모델 비용·호출 수·지연도 비교한다. 원본 Skill을 검토 후 수정하고 명시적으로 freeze한다. 이는 프롬프트 개선이며 가중치 fine-tuning이 아니다.

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
