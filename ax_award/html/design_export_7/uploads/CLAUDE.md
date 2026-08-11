# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Q-Agent 개발 브리핑 (CLAUDE.md)

반도체 품질 이상감지·판단 AI Agent. 계측 Trend를 24시간 감시하고, 이상 감지 시 LLM Agent가
사내 DB·이미지·문서 도구를 자율 호출해 근거 인용 판단과 조치안(Release/Hold)을 제시한다.
엔지니어 피드백이 월 4회 재학습으로 반영되는 살아있는 시스템. 대상: 품질·공정 엔지니어 약 1,000명.

이 문서가 최신 확정본이다. 아래 결정과 충돌하는 과거 문서가 있으면 이 문서를 따른다.

---

## 0. 레포 현황 (2026-08-06 기준) — 코드 없음, 문서만

이 레포에는 **아직 소스 코드가 없다.** `CLAUDE.md` + `docs/` 문서뿐이고 git 저장소도 아니다.
따라서 build·lint·test 명령이 아직 존재하지 않는다 — 첫 코드 커밋이 이것들을 함께 세우는 일이다.
명령어가 정해지면 이 절에 기록한다.

- **실제 인프라는 이 PC가 아니라 사내 VM(data01 등)에 있다.** DB·GPU 작업은 VM 접속 후 수행한다.
  로컬에서 `psql`·`nvidia-smi`가 붙을 것이라 가정하지 말 것.
- 작업 재개 시 **`docs/진행상황_2026-07-29.md`를 먼저 읽는다** — 마지막 실작업 로그(pgvector 실측·사고·복구·남은 작업).
- **문서를 찾을 때는 `docs/README.md`(색인)부터.** 12개 파일의 역할, 문서끼리 참조하는 `설계/` 경로의
  대응표, 폐기본 경고, 문서 간 충돌 1건이 정리돼 있다.
- 첫 코드 커밋에서 세울 것: Python 3.12 프로젝트 골격(§7 규약), `pytest`
  (§9-3 `to_search_text` 단위테스트가 첫 테스트), 평가 러너(recall@10).

---

## 1. 인프라 현황 (확정·배정)

### BIG VM 5대 — Ubuntu 24.04 LTS, 각 64core / 1TB MEM / 30TB Disk
| Host | LB | 역할 | 탑재 |
|---|---|---|---|
| svc01 | O | 운영 #1 | Agent Runtime(오케스트레이션), Chat Gateway, 인메모리 캐시(Redis) |
| svc02 | O | 운영 #2 (HA) | Agent Runtime 이중화, Prometheus+Grafana+Loki, 회귀평가 하네스 |
| data01 | X | 데이터 주 | PostgreSQL 16 + pgvector (직접 설치 — 관리형 신청 실패로 회귀), ETL |
| data02 | X | 데이터 부 | PostgreSQL standby(스트리밍 복제), 백업(pgBackRest→NAS), 감사로그 |
| train01 | X | 학습 | 데이터셋 빌드, 모델 웨이트 병합(FP8 743GB 메모리 적재 — 이 노드 전담) |

### GPU — H100 x 20 (별도 클러스터)
- 서빙: 판단 LLM 12장(TP, FP8) + 고정밀 VLM 5장 + 경량 VLM·검색기 2장 + 회귀평가 1장
- 학습 모드: 16장 SFT/DPO 전환, 경량 서빙 4장 유지(이미지 기능 무중단)
- vLLM: continuous batching + PagedAttention + prefix caching 필수 활성화

### 스토리지
- NAS 100TB: 모델 가중치 세대(3세대)·체크포인트·데이터셋 — GPU 노드+train01 공유 마운트
- OBJ 50TB: 불량 이미지·Wafer Map 원본 아카이브(20개월), 학습 스냅샷
- DB 데이터 ~4TB는 data01 로컬 30TB 內 (수식: 원문200+벡터색인300+키워드색인200+이력274+체크포인트450+시계열요약500+여유)

### Day 1 시스템 설정 (체크리스트 문서는 아직 이 레포에 없음 — §8 참조)
- pg_stat_statements 활성화(shared_preload_libraries), chrony NTP, fio/iperf3 기준 성능 기록
- data01→data02 복제 + pgBackRest 리포지토리 초기화
- **pgvector 판정 종료(2026-08-06)**: 테스트 VM 실측 **PostgreSQL 16.14 / pgvector 0.8.1** →
  0.7 이상이므로 **스키마는 `halfvec(1024)` 확정**(벡터 색인 절반). 스키마·가드·평가 동작 확인됨.
  ⚠ **단, data01은 별개다.** 2026-07-29 data01에서는 사내 apt가 **0.6.0**까지만 줬고(halfvec 없음),
  0.8.2 소스 빌드 시도 중 tarball 없이 `apt remove postgresql-16-pgvector`가 실행돼 확장이
  통째로 빠진 사고가 있었다. **테스트 VM이 0.8.1을 어느 경로로 얻었는지 확인해 같은 경로를
  data01에 적용하기 전까지, data01에서 halfvec 컬럼 생성이 성공한다고 가정하지 말 것.**
  재설치 시 `docs/진행상황_2026-07-29.md` §2-1의 안전판 절차(`&&` 체인으로 실패 시 중단 +
  `apt remove` 대신 `apt-mark hold`)를 그대로 쓴다. 경위는 `docs/README.md` §5.

## 2. 모델 스택 (확정 — 2026-07 웹 검증 완료)
| 역할 | 모델 | 비고 |
|---|---|---|
| 판단·Tool호출·코딩 (주 모델) | GLM-5.2 **743B-A39B** MoE, FP8 | 단일 서빙 1개. 코딩·tool call도 이 모델 — 별도 모델 금지 |
| 고정밀 이미지+보조 판단 | Qwen3.5-397B-A17B (네이티브 멀티모달) | 이미지 지원 여부 모델 카드 최종 확인. 대안: InternVL3-78B, Qwen3-VL-235B |
| 경량 멀티모달 상시 | Qwen3.6-35B-A3B | vision encoder 내장. SFT 없음, 기본 가중치 서빙 |
| 불량/Map 분류 | ConvNeXt V2-Large(198M)/Base(89M) | 사내 데이터 학습 |
| 미지 불량 | PatchCore + WRN-50-2 | 정상 특징 메모리뱅크 |
| Trend 이상탐지 | PatchTST(~5M) + CUSUM/BOCPD | 채널별 학습 |
| 텍스트 검색 | Qwen3-Embedding-8B / Qwen3-Reranker-8B | MTEB 오픈 1위. 사내 튜닝 대상 |
| 이미지 유사사례 검색 | Qwen3-VL-Embedding | 2단계 도입 |
| OCR | PaddleOCR-VL-1.5 (0.9B) | 대안: GLM-OCR, DeepSeek-OCR |

주의: Qwen3.5-VL, Qwen4는 존재하지 않는다. GLM-5.2는 744B/753B가 아니라 743B-A39B다.

## 3. 아키텍처 (요약)
```
[감지] Trend 상시감시(PatchTST가 "언제·얼마나"를 수치로) + Map/Image 판별 + Chat 질의
  -> [두뇌] GLM-5.2 오케스트레이터: 도구 자율 선택·호출 5~15회/건, 모든 도구 결과는 텍스트로 복귀
  -> [도구] DB조회(GPM·변경점) / 이미지 1차분류 / VLM 정밀판독 / 유사사례 검색(문서+이미지) / OCR / 경량VLM
  -> [출구] 근거 인용 판단 + Release/Hold 조치안 + 신뢰도 -> 엔지니어 승인(HITL) -> 이력화(모델 버전 포함)
  -> [학습] 피드백(채택/수정/기각) -> 월 4회 SFT->DPO/GRPO -> 골든셋 회귀 통과 시 배포 -> 두뇌로 순환
```

## 4. 핵심 설계 결정 (Decision Log — 반드시 준수)
1. **GLM-5.2 단일 서빙 + 코드 레벨 라우팅**: 판단/코딩/tool용 역할은 시스템 프롬프트로만 분기. 같은 vLLM 엔드포인트 — prefix cache 공유가 목적. "Agent"는 모델명이 아니라 시스템 전체 명칭.
2. **Trend 2층**: PatchTST+CUSUM이 변화시점·변화량을 찍고(층1), 그 결과+변경점 이력+실측 value를 프롬프트로 받아 GLM-5.2가 원인 연관성을 설명(층2). 시계열 원본을 통째로 LLM에 넣지 않는다.
3. **RAG 3층 텍스트 분기** (한 소스에서 세 갈래, 한쪽 출력이 다른 쪽 입력이 되면 안 됨):
   - `content`: 원문 무가공 — LLM 반환용
   - `embedding`: expand_terms(content) 병기 확장문 → Qwen3-Embedding-8B (자연문 그대로, 조사 제거 금지)
   - `search_tsv`: expand_terms(content) → ID보호(`[A-Z]{2,}-[A-Z]?\d+` 통짜) → Kiwi 형태소 → 품사필터 KEEP={NNG,NNP,SL,SN,VV,VA,XR} → 원형 → to_tsvector('simple', ...)
   - 철칙: 적재와 질의에 반드시 같은 함수(to_search_text). 원본 보존 → 사전·필터 변경 시 재색인 배치 한 방.
4. **용어 사전**: terms.csv (표준키/변형/병기문). ACI(After Clean Inspection, 세정 후 계측) 식 병기. 실제 등장한 문서에만 적용(전 문서 도장 금지 — IDF 붕괴). 병기의 최대 수혜자는 BM25.
5. **하이브리드 검색**: 벡터(pgvector) + BM25(tsvector) + 메타 WHERE(eqp_id·공정·기간) → 후보 ~200 → Reranker-8B 상위 20. 리랭커는 cross-encoder라 검색기와 계열 무관.
6. **캐시 규칙**: 판단 결과에 semantic cache 절대 금지(지난주 답 재사용=사고). 조회성 캐시만 짧은 TTL. 인메모리 캐시(svc01): 시계열 90일·이미지 특징·유사사례 프리컴퓨트.
7. **HITL**: Agent의 기간계 접근은 조회 전용. 조치(Release/Hold)는 엔지니어 승인 후 실행.
8. **재현성**: 모든 판정에 근거 인용 + 신뢰도 + 사용 모델 버전을 함께 기록. 감사 대응이 요구사항.
9. **기간계 접속**: 운영계 직접 조회 금지 — 정보계(DW·ODS) 경유(접속점은 IT 확인). statement_timeout, 기간 제한, LIMIT, 사건당 캐시 필수. (조사규칙_기간시스템확인.md)
10. **학습 주기**: 월 4회. train01이 데이터셋 빌드+웨이트 병합 전담(GPU 슬롯 회당 3~5h 절약). DPO reference는 LoRA adapter off로 base 재사용(메모리 2배 불필요).
11. **평가 우선**: 골든 시나리오(골든시나리오_포토4종.jsonl, 30건으로 확장 예정)가 회귀 기준. 모델·프롬프트·색인 변경 시 recall@10과 판정 정답률 전후 비교 없이 배포 금지.

## 5. DB 스키마 방향 (data01)
```sql
-- 문서(informnote 등)
CREATE TABLE inform_notes (
  id bigserial PRIMARY KEY,
  content     text NOT NULL,            -- 원문 (성역)
  embedding   halfvec(1024),           -- 병기 확장문의 임베딩 (0.8.1 실측 → halfvec 확정. data01 적용 전 §1 경고 확인)
  search_tsv  tsvector,                 -- 색인어 (ID보호+Kiwi+품사필터 결과)
  eqp_id text, process text, item text, created_at timestamptz, ...
);
-- 판정 이력 (감사 대응 — 영구)
CREATE TABLE judgements (
  id bigserial PRIMARY KEY, case_id text, verdict text, action text,
  evidence jsonb,          -- 근거 인용 목록
  confidence numeric, model_ver text NOT NULL, decided_by text, approved_by text,
  created_at timestamptz
);
-- Agent 체크포인터(LangGraph) 테이블은 프레임워크 표준 사용, 90일 보존 배치 삭제
```

## 6. 개발 순서 (Phase)
- **P0 환경**: 패키지 설치(체크리스트), PG 복제·백업, vLLM로 GLM-5.2 FP8 기동(12장 TP), 경량 VLM·검색기 서빙, 모니터링 배선
- **P1 스켈레톤**: LangGraph 오케스트레이터 + Postgres 체크포인터 + 도구 3종(DB조회 mock→정보계, 문서검색, trend 조회) + Chat API. 골든셋 4건이 end-to-end로 도는 것이 완료 조건
- **P2 검색 품질**: 용어사전 v1 + to_search_text + 하이브리드+리랭커 + recall@10 측정 루프
- **P3 이미지·trend 도구**: PatchTST 학습 파이프, ConvNeXt 분류, VLM 판독 연결, 유사 이미지 검색
- **P4 판단·조치**: 그라운딩 규칙(판단조치답변_그라운딩설계.md), HITL 승인 플로우, 이력화
- **P5 학습 루프**: 피드백 수집 스키마 → 데이터셋 빌드(train01) → SFT/DPO → 회귀 평가 게이트
- 각 Phase 완료 조건은 설계_실행체크리스트.md와 동기

## 7. 코딩 규약
- Python 3.12, async 우선(도구 호출 병렬 — 독립 조회는 asyncio.gather), type hint 필수
- 시스템 프롬프트·도구 스키마는 앞부분 고정(프롬프트 캐시 적중률) — 동적 내용은 뒤에
- 도구는 Tool카탈로그_레퍼런스.md 계약(입출력 스키마) 준수, 모든 도구 결과는 텍스트/JSON 직렬화
- 에러: 도구 실패 시 Agent에게 실패 사실을 텍스트로 반환(예외 삼키기 금지), 재시도는 조회성만
- 로그: 구조화(JSON), case_id 단위 추적, 비밀정보 로그 금지
- 설정은 env/config 분리, 모델 버전·프롬프트 버전을 상수로 관리(이력 기록에 사용)

## 8. 참조 문서

**`docs/README.md`가 문서 색인이다** — 12개 파일의 역할, `설계/` 경로 대응표, 폐기본 경고,
문서 간 충돌 1건(pgvector)이 거기 있다. 문서를 찾을 때는 먼저 그것을 읽는다.

자주 쓰는 것만 추리면:

| 파일 | 쓸모 |
|---|---|
| `docs/진행상황_2026-07-29.md` | **VM 작업 재개 전 필독.** pgvector 실측·사고·복구 절차 |
| `docs/GPU신청_종합정리.html` | **신청 자료 중 가장 넓다(18절).** 능력 누적표·심사 방어 논거는 여기에만 있다 |
| `docs/GPU신청_종합정리.md` | 위의 텍스트 요약본(9절) — 숫자의 계보와 역검증 결과 |
| `docs/GPU수요신청_최종본_H100_20장.xlsx` | 제출·재신청용 11시트 |
| `docs/INFRA_발급정보.md` | 발급 현황 + 남은 확인 6건 |
| `docs/GPU신청_통합본_복원.md` | 원본 6건 원문. **수요등록표(§1)·워크플로우(§5)의 유일한 사본** |

### 이 레포에 없는 문서
**참조 지시를 받으면 "없다"고 말하고, 내용을 지어내지 말 것**:
`설계/DB_구축_실행순서.md`(DB 구축 절차 — 실작업에 필요) · `설계/개발과정_Ablation.md`(내용 일부가
종합정리 HTML §10에만) · 구현명세서_클로드코드지시서.md · 구현_LangGraph_스켈레톤.md ·
Tool카탈로그_레퍼런스.md · 판단조치답변_그라운딩설계.md · 심화_RAG·체크포인터·DB·골든셋.md ·
조사규칙_기간시스템확인.md · 설계_실행체크리스트.md · 서버설치_패키지체크리스트.md ·
평가/골든시나리오_포토4종.jsonl · terms.csv · VM산정근거_상세.xlsx · arch.png·flow.png·dbarch.png

### 폐기본 — 인용 금지
`GPU수요신청_등록표.xlsx`(2026-07-28 21:26판). H200 20장·8건 등록 중간 초안이며 존재하지 않는
`Qwen3.5-VL`, 교체된 `bge-m3`, 잘못된 `753B` 표기가 남아 있다. 대체본은 `docs/GPU수요신청_최종본_H100_20장.xlsx`.

## 9. 지금 바로 할 일 (Day 1 지시)
0. ~~pgvector 버전 판정~~ **종료** — 0.8.1 실측, `halfvec(1024)` 확정. 단 data01 적용 경로 확인 필요 (§1)
1. 남은 DB 설정 2건: `pg_stat_statements` 활성화(preload 후 재시작 1회) / data02 스트리밍 복제 연결
2. PG 스키마 생성(§5, `qagent` DB에) + 복제·백업 확인
3. `expand_terms()`(terms.csv 로드)와 `to_search_text()`(ID보호→Kiwi→KEEP→원형) 구현 + 단위테스트
   (케이스: "PHO-D03 설비에서 CD가 크게 올랐다" → 색인어에 PHO-D03 통짜·설비·CD·크·오르 포함, 조사 없음)
4. ingest 파이프: content/embedding/search_tsv 3분기 저장 + 재색인 배치 스크립트
5. 골든셋 4건 로드 + 평가 러너(정답 문서 recall@10 출력)까지 — 이게 P1 진입 조건
