# GPU 신청 별첨 — 서비스 시스템 아키텍처 구성도 (2026-07-29)

> cowork 세션 `cse_01FeEGgg7xjP6N4wLKgbdkAF` 산출물 원문 보존.

자원 활용 방안 이해용 구성도. 문서 삽입은 `arch.png`(세션 전달본 — 영문 본체 + 한글 범례) 사용.
아래는 텍스트 원본(고정폭 폰트 기준) — 전문은 `docs/arch.txt` 와 동일.

## 범례 (한글)

- **USERS** = 품질·공정 엔지니어 약 1,000명 (웹 Chat + 자동 경보)
- **SERVICE LAYER** = 본 신청 BIG VM 5대 —
  운영 2(Agent API·게이트웨이·캐시·관제·회귀평가) + 데이터 2(검색 DB 주/부·수집·감사)
  + 학습 1(데이터셋 빌드·웨이트 병합)
- **GPU CLUSTER** = 별도 신청 H100 20장 —
  서빙 19(판단 LLM 12 · 정밀 VLM 5 · 경량/검색 2) + 평가 1, **학습 시 16장 전환**
- **STORAGE** = NAS 100TB(가중치 3세대·체크포인트·데이터셋) + OBJ 50TB(이미지·Map 20개월)

## 용도

심사 질의 시 "이 자원이 왜 필요하냐" → **그림의 해당 상자를 짚는다.**
신청서의 모든 수치(VM 5대, GPU 20장, NAS/OBJ, 1,000명)가 그림 안에 자리를 가진다.

## 구성도 텍스트 원본

→ `docs/arch.txt` 참조 (동일 내용). 요지:

```
USERS(엔지니어 ~1,000명)
   ↕ ask / answer
SERVICE LAYER — BIG VM ×5 (each 64core / 1TB / 30TB)
   [LB]→ svc01 : agent API #1 + chat gateway + in-mem cache
   [LB]→ svc02 : agent API #2 + monitoring + regression eval
   cache : trend 90d + image features + case precompute
   data01 : PostgreSQL + pgvector (primary) + ETL ingest
   data02 : PostgreSQL (standby) + audit log + backup
   train01: dataset build + weight merge (time-shared)
   HA: API ×2, DB ×2 · audit: 판정마다 model version 기록
   all tool results return as TEXT to the agent
   ↕ prompt/tool ↔ text result
GPU CLUSTER — H100 ×20 (별도 신청)
   serve: judge LLM FP8 ×12 | deep-read VLM ×5 | lite VLM + retrievers ×2 | eval ×1
   train: 16 GPUs SFT/DPO (monthly ×4) — lite serving stays up while training
   ↕ weights load / checkpoint save
SHARED STORAGE — NAS 100TB(weights 3gen·ckpt·datasets, GPU+train01 마운트)
                 OBJ 50TB(image/map archive 20 months)

DATA SOURCES(read) → MES/SPC/YMS(DW) · FDC sensor·metrology · defect image/map · drawings·work notes

LEARNING LOOP : 엔지니어 피드백(adopt/fix) → train01 월 4회 재학습 → 개선 weights → GPU 재배포
BACKUP        : VM disk ×5(daily) | DB replication → data02 | 장기 아카이브 → OBJ
```
