# Usage Guide

## 최초 setup

```powershell
cd D:\project\failure_agent

# 1. dependencies
pip install -r requirements.txt

# 2. .env 설정 (이미 생성됨, API key 입력 필요)
# OPENAI_API_KEY=sk-... 입력

# 3. gallery embedding 추출 (1회, ~5-10min)
python lib/embed_gallery.py

# 4. webapp 실행
streamlit run lib/webapp.py
```

브라우저: `http://localhost:8501`

## CLI 검색 (webapp 없이)

```python
from pathlib import Path
import json, numpy as np
from PIL import Image
from dotenv import load_dotenv
load_dotenv()
import os
from contrastive_loader import load_model, build_transform, embed_image

model = load_model(os.environ["CONTRASTIVE_CKPT"],
                   backbone_ckpt=os.environ["CONTRASTIVE_BACKBONE_CKPT"])
tfm = build_transform()

img = Image.open("YOUR_IMAGE.png").convert("RGB")
emb = embed_image(model, img, tfm)

data = np.load("embeddings/gallery.npz")
sims = data["embeddings"] @ emb
idx = np.argsort(-sims)[:10]

print(f"matched: {data['classes'][idx[0]]} (sim={sims[idx[0]]:.4f})")
```

## Batch 처리 (여러 이미지)

```python
import csv
from pathlib import Path

queries = list(Path("D:/test_batch").glob("*.png"))
results = []
for q in queries:
    img = Image.open(q).convert("RGB")
    emb = embed_image(model, img, tfm)
    sims = data["embeddings"] @ emb
    top = np.argmax(sims)
    results.append({
        "query": q.name,
        "matched_class": data["classes"][top],
        "similarity": float(sims[top]),
    })

with open("results.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["query","matched_class","similarity"])
    w.writeheader()
    w.writerows(results)
```

## 환경 변수

| 변수 | 의무 | 기본값 | 설명 |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | (없음) | OpenAI API |
| `LLM_MODEL` | ❌ | gpt-5.5-nano | LLM 이름 |
| `CONTRASTIVE_CKPT` | ❌ | (B4 default) | Step 1 B4 model |
| `CONTRASTIVE_BACKBONE_CKPT` | ❌ | (TAPT default) | backbone weights |
| `GALLERY_EMBEDDING` | ❌ | embeddings/gallery.npz | cache 경로 |
| `SIMILARITY_THRESHOLD` | ❌ | 0.7 | cosine threshold |

## 흔한 문제

### 1. `gallery.npz` 없음
```
Error: Gallery embedding 미생성
```
→ `python lib/embed_gallery.py` 실행

### 2. CUDA OOM (메모리 부족)
- B4 xeval 등 GPU 무거운 process 동시 실행 시
- 해결: BATCH=1 (이미 default), 또는 CPU 모드

### 3. OpenAI API 오류
- API key 잘못/만료 → `.env` 확인
- model name 잘못 (gpt-5.5-nano 가 존재하지 않으면) → `LLM_MODEL=gpt-4o-mini` 로 변경

### 4. Streamlit port 충돌
```
Error: port 8501 already in use
```
→ `streamlit run lib/webapp.py --server.port=8502`

### 5. `cp949` UnicodeEncodeError (Windows)
- 콘솔에서 한국어 출력 시
- 해결: `set PYTHONIOENCODING=utf-8` 또는 `chcp 65001`

## webapp 종료

```powershell
# PID 확인
Get-Process python | Where-Object { $_.ProcessName -eq 'python' }
# 종료
Stop-Process -Id <PID> -Force
```

또는 streamlit log:
```bash
tail D:/project/failure_agent/streamlit_app.log
```
