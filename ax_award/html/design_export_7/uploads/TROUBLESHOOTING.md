# Troubleshooting

## 자주 발생하는 문제

### 1. `Gallery embedding 미생성: embeddings/gallery.npz`

**증상**: webapp 실행 시 첫 화면에 빨간 에러.

**원인**: `embed_gallery.py` 미실행.

**해결**:
```bash
cd D:/project/failure_agent
python lib/embed_gallery.py
```

### 2. `Can't get local object 'extract.<locals>.SingleView'`

**증상**: embed_gallery.py 실행 시 multiprocessing pickle 오류.

**원인**: `NUM_WORKERS > 0` 으로 Windows multiprocessing spawn 시 local class pickle 불가.

**해결**: contrastive_loader.py 가 NUM_WORKERS=0 사용 — 이미 default. 변경 X.

### 3. `BackboneCKPT not found`

**증상**:
```
FileNotFoundError: backbone ckpt not found: D:\project\unknown-contrastive\logs_wafer\overall\best_model.pth
```

**원인**: backbone path 잘못.

**해결**: `.env` 의 `CONTRASTIVE_BACKBONE_CKPT` 가 올바른 path 인지 확인:
```
CONTRASTIVE_BACKBONE_CKPT=C:/Users/hgcho/AppData/Local/Temp/contrastive_init_best_model.pth
```

### 4. CUDA OOM (메모리 부족)

**증상**: torch.cuda.OutOfMemoryError.

**원인**: 다른 GPU process 동시 실행 (B4 xeval, 학습 등).

**해결**:
- 다른 GPU process 종료 후 실행
- 또는 CPU 모드: `CUDA_VISIBLE_DEVICES=""` 환경 변수
- 또는 BATCH=1 (이미 default)

### 5. OpenAI API 오류

**증상 a**: `401 Unauthorized` → API key 잘못/만료
**해결**: `.env` 의 `OPENAI_API_KEY` 재확인

**증상 b**: `404 model not found` (gpt-5.5-nano 가 실제 model 명이 아니거나 미릴리즈)
**해결**: `.env` 의 `LLM_MODEL` 을 다른 값으로 변경:
```
LLM_MODEL=gpt-4o-mini
```

**증상 c**: `429 rate limit`
**해결**: 잠시 후 재시도 또는 plan upgrade

### 6. Streamlit port 충돌

**증상**: `Port 8501 is already in use`

**해결 a**: 기존 streamlit 종료
```powershell
Get-NetTCPConnection -LocalPort 8501 | Select-Object OwningProcess
# 출력된 PID 종료
Stop-Process -Id <PID> -Force
```

**해결 b**: 다른 port 사용
```bash
streamlit run lib/webapp.py --server.port=8502
```

### 7. UnicodeEncodeError 'cp949'

**증상**: 한국어 print 시 Windows cmd 인코딩 오류.

**해결**:
- 환경 변수: `set PYTHONIOENCODING=utf-8`
- 또는: `chcp 65001` (UTF-8 codepage)
- 또는 코드 안: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`

### 8. Similarity 모두 낮음 (< 0.5)

**증상**: 어떤 이미지를 넣어도 sim < 0.5.

**원인** (가능성):
- query image 가 wafer image 가 아님 (다른 도메인)
- contrastive model checkpoint 잘못된 경로
- gallery embedding 오래됨 (재생성 필요)

**해결**:
1. `.env` 의 `CONTRASTIVE_CKPT` 가 올바른 path 인지
2. `python lib/embed_gallery.py` 재실행
3. query 가 wafer image 인지 확인

### 9. webapp 응답 매우 느림

**증상**: 검색 버튼 누른 후 1분+ 대기.

**원인**:
- model 첫 load (~10-15s, cache 됨)
- LLM API 응답 (보통 2-5s)
- GPU 다른 process 점유 (B4 xeval 등)

**해결**:
- 첫 검색은 model load 포함 — 정상
- 2회 차부터 빨라야 (`@st.cache_resource` 적용)
- GPU 충돌 시 CPU 모드 또는 다른 process 종료

### 10. meta.json 편집 후 webapp 반영 안 됨

**증상**: meta 수정했는데 webapp 응답에 반영 안 됨.

**원인**: Streamlit cache.

**해결**:
- webapp 페이지 새로고침 (F5)
- 또는 `@st.cache_resource` 대상 아닌지 확인 (meta load 는 매 query 마다 새로)

## Log 확인

| Log file | 용도 |
|---|---|
| `D:/project/failure_agent/streamlit_app.log` | webapp stdout/stderr |
| `D:/project/failure_agent/lib/_make_meta.py` 실행 출력 | meta 합성 결과 |
| `D:/project/failure_agent/lib/embed_gallery.py` 실행 출력 | embedding 추출 진행 |

## 지원 채널

- 코드 issue: Claude Code agent (`.claude/agents/wafer-search-orchestrator.md`)
- 도메인 meta 편집: meta-curator agent
- webapp 실행: streamlit-runner agent
