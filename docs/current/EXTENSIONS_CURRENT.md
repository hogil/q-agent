# 개발 Skill · MCP · 플러그인 설치 현황

기준일: 2026-10-25. 사용자가 요청한 GitHub 인기 확장 검색·설치 작업의 실제 결과다. GitHub REST API의 별 수·최근 push·보관 상태, 공식 문서, 설치한 패키지 소스를 확인했다. 별 수는 선택 참고이며 성능 검증 지표가 아니다.

## 설치한 Skill

모두 공식 저장소의 commit을 고정해 `skill-installer`로 설치했다. 세 Skill의 frontmatter 검사를 통과했다. 자동 Skill 탐색에는 다음 사용자 턴부터 반영된다.

| Skill / 공식 출처 | 저장소 별 수 | 고정 commit / 라이선스 | 실제 설치 위치 | 적용 작업 |
|---|---:|---|---|---|
| [mcp-builder](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/mcp-builder) | 183,599 | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` / Skill 내 Apache-2.0 | `%USERPROFILE%/.codex/skills/mcp-builder` | MCP schema·Tool 설명·bounded output·stdio Adapter 개발. 이번 문서 변환 wrapper에 적용 |
| [vercel-react-best-practices](https://github.com/vercel-labs/agent-skills/tree/063bee94c3f4df8453406c830b0a7df0f2860278/skills/react-best-practices) | 32,978 | `063bee94c3f4df8453406c830b0a7df0f2860278` / Skill 선언 MIT | `%USERPROFILE%/.codex/skills/vercel-react-best-practices` | Q-Agent React 화면의 rendering·data fetching·bundle 성능 검토. Vite에 Next.js 전용 규칙은 적용하지 않음 |
| [huggingface-datasets](https://github.com/huggingface/skills/tree/fabc634a893f62ad5c2039830397efa35fa62715/skills/huggingface-datasets) | 11,210 | `fabc634a893f62ad5c2039830397efa35fa62715` / 저장소 Apache-2.0 | `%USERPROFILE%/.codex/skills/huggingface-datasets` | 공개 Dataset Viewer의 schema·split·통계·필터 탐색. 업로드·trace 전송·원격 유료 작업은 실행하지 않음 |

원본 Skill을 수정하지 않았다. 외부 Skill이 Q-Agent의 scope·권한·사고 DB 우선 조회·Skill freeze 규칙을 변경하거나, 제거한 LLM 정답 질문 세트를 복원할 근거가 되지 않는다.

## 설치·설정하고 실제 호출한 MCP

프로젝트 설정: [D:/project/q-agent/.codex/config.toml](D:/project/q-agent/.codex/config.toml). 기존 `gpt-6-luna` / `low` / 최대 3개 서브에이전트 설정을 유지했다. `codex mcp list`에서도 아래 네 서버가 enabled로 확인됐다. 이 턴에서는 독립 MCP client가 서버를 실행해 initialize/list_tools/call_tool을 확인했다. 현재 대화의 Tool 목록에 동적으로 추가됐다는 의미는 아니다.

| MCP | 공식 출처 / 버전 | 노출 Tool | 실행 확인 |
|---|---|---|---|
| `qagent_markitdown` | [Microsoft MarkItDown](https://github.com/microsoft/markitdown), 192,037 stars; `markitdown-mcp==0.0.1a8`, `markitdown==0.1.9`, MIT | `convert_dummy_document` | 더미 PDF·DOCX·PPTX 추출, source SHA256 일치, 출력 140자 제한 확인. HTTP/data URI·범위 밖 경로·경로 이동·MHT 입력 거절 |
| `qagent_dbhub` | [Bytebase DBHub](https://github.com/bytebase/dbhub), 3,717 stars; npm `@bytebase/dbhub@1.5.0`, MIT | `execute_sql`, `search_objects` | 더미 3개 테이블·24개 사고·96개 Chip·Measure 128컬럼 조회 성공. UPDATE·DDL·PRAGMA 쓰기 우회 거절, 전후 DB SHA256 일치 |
| `qagent_arxiv` | [arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server), 3,232 stars; `0.8.2`, Apache-2.0 | `search_papers`, `get_abstract`, `download_paper`, `list_papers`, `read_paper` | 공개 논문 `2211.14730` 검색·초록 조회·다운로드·읽기 성공. upstream 19개 Tool 중 5개만 Codex에 허용 |
| `qagent_openai_docs` | [OpenAI 공식 Docs MCP](https://developers.openai.com/learn/docs-mcp), 공개 원격 endpoint | `search_openai_docs`, `fetch_openai_doc` | 인증정보 없이 MCP 초기화·문서 검색 성공. endpoint는 `https://developers.openai.com/mcp` |

네 서버에서 총 10개 Tool을 allowlist했다. 프로젝트별 MCP 설정과 `enabled_tools`는 [공식 MCP 설정 문서](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)를 기준으로 적용했다. 앱에서 신규 MCP를 읽으려면 새 세션 또는 MCP 재시작이 필요할 수 있다.

### 경로·버전 관리

- lab 단일 진입점: [D:/project/q-agent-models/config/config.yaml](D:/project/q-agent-models/config/config.yaml) + [D:/project/q-agent-models/config/extensions-v1.yaml](D:/project/q-agent-models/config/extensions-v1.yaml).
- 로컬 변환 wrapper: [D:/project/q-agent-models/src/qmodels/extension_markitdown_mcp.py](D:/project/q-agent-models/src/qmodels/extension_markitdown_mcp.py).
- MarkItDown 환경: `D:/project/q-agent-models/var/extensions-v1/markitdown/.venv`.
- arXiv 환경: `D:/project/q-agent-models/var/extensions-v1/arxiv/.venv`.
- DBHub 환경: `D:/project/q-agent-models/var/extensions-v1/node`; 직접 설치한 Node entry point로 실행하며 시작할 때 `@latest`를 받지 않는다. npm lifecycle script는 비활성화해 설치했다.
- DBHub 설정: `D:/project/q-agent-models/var/extensions-v1/dbhub/dbhub.local.toml`; Tool 설정 `readonly=true`, `max_rows=200`. [공식 TOML 형식](https://github.com/bytebase/dbhub/blob/main/docs/config/toml.mdx)을 사용했다.
- DBHub 더미 DB: `D:/project/q-agent-models/var/extensions-v1/dbhub/synthetic.sqlite`. Yield는 Chip별 0/1이며 1이 양호하고, Measure는 0이 최선이며 증가할수록 불량인 합성 값이다.
- arXiv 논문 저장소: `D:/project/q-agent-models/var/extensions-v1/arxiv-papers`; 확인한 공개 논문은 `D:/project/q-agent-models/var/extensions-v1/arxiv-papers/2211.14730.md`.

MarkItDown은 upstream MCP 패키지를 설치한 뒤, 같은 공식 변환 library를 호출하는 local-only wrapper를 등록했다. 원본 MCP의 임의 URI 입력 대신 overlay의 더미 문서 폴더만 허용한다. 변환은 plugin을 끄고 수행하며 MHT는 이 wrapper의 지원 대상이 아니다. Python 환경은 MCP SDK 버전 충돌 때문에 분리했다: MarkItDown은 MCP 2.3.0, arXiv는 MCP 1.30.0. 기존 모델 학습 환경에는 설치하지 않았다.

`markitdown-mcp==0.0.1a8`은 upstream prerelease다. 설치에 필요했던 `azure-ai-contentunderstanding==1.2.0b1`도 명시적으로 고정했으며, Azure endpoint·키·클라우드 변환은 설정하거나 호출하지 않았다. Python 전체 freeze와 npm integrity/lock을 결과 폴더에 기록했다.

## 플러그인

[Context7](https://github.com/upstash/context7)은 63,630 stars이며 라이브러리별 최신 API 문서 확인에 적합하다. 설치 가능한 플러그인으로 확인하고 설치 선택을 제시했다. **설치/연결 확인은 아직 없으므로 대기 상태다.** 사용자가 Context7 설치를 선택하면 연결 상태를 확인한 뒤 공개 라이브러리 문서 조회에 사용한다. 중복 Context7 MCP는 추가하지 않았다.

GitHub·브라우저·일반 웹 검색은 이미 있는 도구를 사용한다. Firecrawl·Scite·Superpowers·광범위 `hf-cli`는 이번에 추가 설치하지 않았다. 기존 기능 중복 또는 현재 필요한 범위보다 넓은 계정·업로드·워크플로 요구를 피하고, 실제 필요한 확장만 선택했다.

## Q-Agent에 적용하는 위치

| 작업 | 사용할 확장 | 후속 연결과 완료 기준 |
|---|---|---|
| 논문·장비사·모델 구현 조사 | arXiv / 기존 웹 검색 / 공식 Docs / 연결 완료 후 Context7 | 출처·발행일·모델/패키지 버전 기록 후 실험 설계. 논문 다운로드 자체를 모델 성능 개선으로 계산하지 않음 |
| 사고 보고서·Eng’r Inform 더미 문서 추출 | MarkItDown | 문서 ID·버전·공개시점·사고 연결을 유지해 기존 BM25+vector chunk 수집 경로로 연결. 현재는 추출 확인까지이며 자동 RAG upsert는 추가하지 않음 |
| schema·unique·Join 후보 개발 조회 | 읽기 전용 DBHub | 현재는 별도 더미 DB의 introspection만 실행. 실제 업무 Adapter는 7개 Schema Skill과 매핑 설정, 사고 DB 우선 조회 및 scope receipt를 따라야 함 |
| 공개 데이터셋 구조 검토 | huggingface-datasets | 공개 source/split/license를 기록하고 합성 FAB 데이터와 구분. 내부 데이터 업로드 금지 |
| 새 MCP Adapter·UI 성능 변경 | mcp-builder / Vercel Skill | 필요한 변경에만 적용하고 입출력·scope·실제 호출 결과를 확인. 새로운 생산 권한을 부여하지 않음 |

신규 확장은 Codex 개발 보조이며 Q-Agent 서비스의 Tool registry에 등록한 업무 Tool이 아니다. 이 작업은 MCP 실행 확인이다. 실제 LLM Router/Judge/Answer 답변 품질, 사내 ACL, 생산 MES HOLD/RELEASE 검증을 완료했다고 주장하지 않는다.

## 재현 자료

- 설치·출처·해시·상태: [D:/project/q-agent-models/var/output/extensions-v1/installation-manifest.json](D:/project/q-agent-models/var/output/extensions-v1/installation-manifest.json).
- 문서/DB/공식 문서 MCP 확인: [D:/project/q-agent-models/var/output/extensions-v1/local-runtime-check.json](D:/project/q-agent-models/var/output/extensions-v1/local-runtime-check.json).
- arXiv 확인: [D:/project/q-agent-models/var/research/extensions-v1/arxiv-runtime-check.json](D:/project/q-agent-models/var/research/extensions-v1/arxiv-runtime-check.json).
- Python lock: `D:/project/q-agent-models/var/output/extensions-v1/requirements-markitdown.lock.txt`, `D:/project/q-agent-models/var/output/extensions-v1/requirements-arxiv.lock.txt`.
- npm lock: `D:/project/q-agent-models/var/extensions-v1/node/package-lock.json`.
- 설치 전 프로젝트 설정: `D:/project/q-agent-models/var/output/extensions-v1/codex-config.before.toml`.

실행 실패 이력도 manifest에 남겼다: MarkItDown 최초 resolver 실패는 필요한 beta dependency를 명시적으로 고정해 해결했고, Windows cp949 출력/Skill 검사 문제는 해당 프로세스 UTF-8 설정으로 해결했다. 리서치 scout의 초기 `installation_not_performed`·조건부 추천은 조사 시점 기록이며 최종 설치 상태는 이 문서와 installation manifest가 기준이다. 생성 DB·전체 결과·로컬 설정은 기존 `var/` ignore 경로에 보관한다.
