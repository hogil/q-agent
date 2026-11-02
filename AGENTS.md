# Q-Agent 개발 규칙

- 설명과 시스템 프롬프트는 익숙한 기술 용어를 사용한다. 사고 데이터는 '사고 테이블' 또는 '사고 DB'로 부르고, Router/Tool/scope 등의 용어를 억지로 번역하지 않는다.

- 최신 사용자 요구와 docs/current 설계를 따른다. 원본 CLAUDE.md와 docs/의 기존 자료는 보존된 자원/과거 프로젝트 문맥이며 현재 구현 완료의 증거가 아니다.
- GPU, 서버, VM, DB 용량, 스토리지, 자원 산정, 예산, ROI, 인프라 자료를 삭제하거나 임의 수정하지 않는다. docs/current/RESOURCE_PRESERVATION.json의 원본 경로와 Git blob 해시를 확인한다.
- 사고 관련 최초 업무 Tool은 사고 DB 검색/집계다. 우선 조회 강제와 권한은 프롬프트가 아닌 Orchestrator/Adapter 코드에서 보장한다.
- 기존 제품세대 배열을 유지한다. 부문별 통계에서 다중 세대를 펼친 뒤 distinct 사고를 세고, 수량을 균등 배분하지 않는다.
- 사내문서/Eng’r Inform Note는 기존 BM25+vector Hybrid RAG와 기존 chunk를 연결한다.
- Router/Answer/Judge 동작 변경은 app/skills 및 공유 참조를 먼저 수정하고 명시적으로 freeze한다. 온라인 질의로 Skill 원본을 변경하지 않는다.
- 사내 테이블/컬럼/Join은 매핑 설정을 통해 연결한다. 비밀정보, 실제 Lot/이미지/사내 문서 내용을 합성 데이터 예제에 넣지 않는다.
- 구현하지 않은 LLM, ACL, 생산계 조치, 이미지/Trend 모델을 구현 완료로 표시하지 않는다.
- 평가 스크립트와 정답 질문 세트는 사용자 요청으로 제거했다. 실행 확인은 config_loader.py, skill_loader.py와 조회 CLI로 수행한다. 실행 시 입력/출력 검사는 유지한다.
- 사용자 예외(2026-10-28): 다양한 자연어→SQL→합성 DB 실행 결과의 새로운 NL2SQL 골든셋과 학습·검증을 명시 요청했다. 이 한정된 연구용 데이터/평가는 별도로 생성할 수 있다. 기존의 포괄적인 Q-Agent 정답 질문 세트를 복원하거나 생산 DB/쓰기 권한을 부여하는 예외가 아니다. 기존 main 실행 확인 방식은 유지한다.

- 배포 설정의 단일 진입점은 config/config.yaml + site overlay다. DB/폴더/모델명을 코드나 Skill 지침에 하드코딩하지 않는다.
- 7개 테이블의 논리 컬럼 명세는 각 Schema Skill의 references에서 관리한다.
- 사내 *.local.yaml, *.local.toml, var/ 생성 DB와 전체 결과는 Git에 올리지 않는다.

- 사고명 복수 후보는 명시적으로 선택한다. Wafer 조회는 선택 사고와 Lot 범위를 함께 검증하고, lot_inventory를 사고 영향 Wafer로 단정하지 않는다.

- 모든 Skill 수정 전 관련 실제 자료의 출처/기준시점/변경 근거를 확인한다. 사내 데이터 접근이 없으면 미확인 설계/더미 초안임을 기록하고 실제 데이터 검증 완료를 주장하지 않는다. 온라인 Skill 자기 수정이나 원본 DB 수정 권한으로 해석하지 않는다.

- LLM 호출 순서는 Router → Tool 조회 → Judge 근거 검토 → Answer 최종 답변이다. 사고 DB 우선 조회 후 후속 Tool을 허용한다. Judge의 근거 부족은 Router로 돌리고 Answer는 마지막 LLM으로 배치한다.

- 아키텍처 도식은 사용자 질문부터 아래로 배치하며 Router 노드는 최상단 한 개만 둔다. Judge의 모든 재조회는 그 Router로 연결한다. Answer 아래에는 최종 조회 상태/사고 범위 표시를 둔다. 실행 전 사고 DB 범위 검증과 최종 결과 표시는 구분한다.

- 사용자 확인을 받은 주 흐름은 세로 표로 표시한다. Router → 사고 DB → 후속 Tool → Judge → Answer의 행 순서를 유지하고 재조회는 별도 규칙 표로 설명한다. 자동 도식 배치로 Judge가 Router 위에 나타나는 표현을 반복하지 않는다.

## 개발 서브에이전트 운영

- 단순 파일 탐색·검색·설정 확인·리드 조회·접속 확인·지정된 CLI/빌드 실행 및 검증과 같이 범위가 좁고 독립적인 일은 가능한 한 반드시 서브에이전트에 위임한다. 이때 사용할 수 있는 모델 중 비용이 가장 낮은 모델과 low 추론 수준을 우선 적용하며, 해당 모델/수준을 쓸 수 있으면 상위 비용의 모델이나 추론 수준을 선택하지 않는다. 단순 파일 탐색·설정 확인은 `.codex/agents/qagent_scout.toml`, 지정된 CLI·빌드 확인은 `qagent_verify.toml`에 맡긴다. 가능한 독립 수정도 좁게 분리해 같은 원칙으로 위임한다. 기본 모델은 `.codex/config.toml`에서 관리한다.
- 독립된 좁은 작업만 병렬 위임한다. 부모를 제외한 동시 서브에이전트는 최대 3개이며, 이미 얻은 정보와 전체 대화 이력을 불필요하게 반복 전달하지 않는다.
- 결과에는 절대경로·줄번호·실행 결과·미확인 사항을 간결하게 남긴다. 복잡한 원인 분석, scope·권한·Judge 계약 변경과 최종 수정 검토는 부모가 맡고, 이런 작업에만 필요에 따라 모델/추론 수준을 높인다.
- 개발 서브에이전트 설정은 Q-Agent의 Router/Judge/Answer 배포 설정과 별개다. 배포 모델과 reasoning 설정은 `config/config.yaml` + site overlay에서만 관리한다.

## 개발 확장 도구 사용

- 설치 출처·버전·역할·실행 확인은 `docs/current/EXTENSIONS_CURRENT.md`를 따른다. MCP 개발에는 `mcp-builder`, React 성능 검토에는 `vercel-react-best-practices`, 공개 데이터셋 탐색에는 `huggingface-datasets`를 적용한다. Vite 화면에 Next.js 전용 규칙을 강제하지 않는다.
- `.codex/config.toml`의 `qagent_*` MCP는 개발 보조다. 사고 업무 조회는 기존 Orchestrator의 사고 DB 우선 조회와 scope 검증을 따른다. 개발용 범용 SQL을 Q-Agent 업무 Adapter로 간주하지 않는다.
- 문서 변환은 lab의 `config/config.yaml` + `config/extensions-v1.yaml`에 지정한 더미 폴더만 사용한다. 변환 출력은 수집 후보이며 기존 Hybrid RAG의 chunk·출처·기준시점 검증과 별개다. MHT는 이 MCP의 지원 형식이 아니다.
- DBHub는 별도 합성 SQLite를 읽기 전용으로 조회한다. 사내 DB 접속, MES HOLD/RELEASE, 기존 DB 수정 권한을 이 설정에서 유추하지 않는다.
- arXiv·공식 문서·Context7은 공개 기술 자료 조회에만 사용한다. 사내 기록·실제 Lot/이미지/문서·토큰·agent trace를 외부 서비스에 전송하지 않는다. Hugging Face 업로드·삭제·유료 원격 작업은 현재 작업 범위에 포함되지 않는다.
- 외부 Skill의 평가 예제 지침으로 제거된 Q-Agent LLM 정답 질문 세트를 복원하지 않는다. MCP 연결/입출력 확인과 실제 LLM 답변 품질 검증은 구분한다.
