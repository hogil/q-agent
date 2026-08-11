# Architecture

## 시스템 구성

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit Webapp                         │
│                       (lib/webapp.py)                        │
└────────┬────────────────────────────┬───────────────────────┘
         │                            │
         ▼                            ▼
┌────────────────────┐      ┌──────────────────────┐
│ Contrastive Model  │      │   Gallery Embedding  │
│ (CL + Proj head)   │◄─────│   215 × 128          │
│ B4 checkpoint      │      │   (gallery.npz)      │
└────────┬───────────┘      └──────────┬───────────┘
         │                              │
         ▼                              ▼
┌──────────────────────────────────────────┐
│  Similarity Search (cosine, L2 norm)     │
│  Top-1 class + Top-10 paths              │
└────────┬─────────────────────────────────┘
         │
         ▼
┌──────────────────────┐
│  Meta Lookup         │
│  meta/<class>/       │
│  meta.json           │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────┐
│  LLM (gpt-5.5-nano)      │
│  자연어 응답 생성        │
└──────────────────────────┘
```

## 데이터 flow

### 1. Setup (1회)
- `_make_meta.py` → 43 class meta.json 합성
- `embed_gallery.py` → 215 image embedding 추출 → `gallery.npz`

### 2. Query (사용자 요청 시)
1. Streamlit upload widget → PIL Image
2. `embed_image(model, pil, tfm)` → 128-dim L2-norm vector
3. `gallery_emb @ query_emb` → 215 cosine similarity
4. `argsort(-sims)[:10]` → top-10
5. top-1 class → `meta/<class>/meta.json` read
6. LLM API call:
   - system: "반도체 wafer defect 사고 분석 전문가"
   - user: query + matched class + similarity + meta JSON
7. 응답 + top-10 image preview 출력

## Contrastive Model 상세

| 항목 | 값 |
|---|---|
| Backbone | ConvNeXtV2-base (FCMAE pretrained + TAPT) |
| 입력 size | 384×384 RGB |
| Proj head | Linear(d, d) + BN + ReLU + Linear(d, 128) |
| Output | L2-normalized 128-dim vector |
| 학습 | Step 1 B4 recipe (Global InfoNCE + Local + Queue + NEG 0.72) |
| 학습 data | per class 30 (avg30 anchor, 900 wafer) |
| 학습 metric | AMI 0.956 / ARI 0.860 / noise 0.52% |

## Gallery 상세

| 항목 | 값 |
|---|---|
| Source | E:/data/images/unknown/ |
| Class 수 | 43 (Normal 포함) |
| Image per class | 5 (sorted filename) |
| Total | 215 |
| Embedding dim | 128 |
| Storage | numpy .npz (float32 + str arrays) |
| 크기 | ~500 KB |

## LLM

| 항목 | 값 |
|---|---|
| Provider | OpenAI |
| Default model | gpt-5.5-nano (.env LLM_MODEL) |
| Fallback | gpt-4o-mini |
| Temperature | 0.3 |
| System prompt | "반도체 wafer defect 사고 분석 전문가" |
| Input | query text + matched class + sim + meta JSON |

## 보안

- `.env` 의 OPENAI_API_KEY 는 `.gitignore` 처리
- `embeddings/` 도 `.gitignore` (재생성 가능)
- contrastive model checkpoint = 외부 경로 (project 미포함)

## 확장 가능

- **새 class 추가**: images/ 폴더 추가 + `_make_meta.py` 의 dict 업데이트 + `embed_gallery.py` 재실행
- **threshold 변경**: `.env` `SIMILARITY_THRESHOLD`
- **LLM 변경**: `.env` `LLM_MODEL` (gpt-5.5-nano, gpt-4o-mini, claude-haiku 등)
- **Top-K 변경**: `lib/webapp.py:cosine_topk(k=10)` 조정
