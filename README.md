# Q-Agent · 반도체 품질 사고 조사 Agent

사고 원장 DB를 먼저 조회하고, Lot·사고 문서·사내문서·Eng’r Inform Note·이미지·Trend 근거를 연결해 원인 분석과 개선 조언을 지원하는 사내 품질 Agent 설계 및 실행 예제입니다.

**현재 상태: 설계 + 합성 데이터 + 독립 Tool/Skill 컴파일러 데모.** 실제 LLM, 사내 DB, Hybrid RAG, 이미지/Trend 모델 및 조치 시스템과 연결된 운영 서비스는 아직 아닙니다.

## 시작하기

- [현재 아키텍처와 상세 구현 계획](docs/current/ARCHITECTURE_AND_PLAN.md)
- [사내 설치: 물리 테이블·컬럼 교체 및 Skill 관리](docs/current/INSTALLATION_AND_SKILLS.md)
- [도시·라인·다중세대·FAB Out 합성 사고 데이터](app/data/incident_cases.json)
- [화면 디자인 미리보기](design/workspace-preview.html): 파일을 내려받아 브라우저에서 열기. 합성 데이터 기반 디자인 시안이며 운영 UI가 아닙니다.
- [GPU·VM·스토리지 등 기존 자원 문서](docs/README.md)
- [원본 보존 파일 및 Git 해시](docs/current/RESOURCE_PRESERVATION.json)

```bash
cd app
python demo.py
python array_demo.py
python check_skills.py
python skill_loader.py router --topics terminology,lots
```

예제는 Python 표준 라이브러리와 SQLite를 사용합니다. 사내 운영용 비동기 API/DB Adapter는 별도 구현 대상입니다. `demo.py`는 사고→별도 Lot 테이블 연결, `array_demo.py`는 배열 원소 조회와 중복 없는 세대 통계, `check_skills.py`는 Skill 로딩·버전·변조 검출을 확인합니다. 실 LLM 품질 평가를 대신하지 않습니다.

## 확정한 설계

1. 사고 DB 접근은 **정형 사고 조회·집계(Structured Incident Retrieval / Analytics)**입니다. 그래프 관계 추론을 구현하지 않은 조회를 Graph RAG라고 부르지 않습니다.
2. 최초 업무 조회는 사고 DB 검색 또는 DB 집계입니다. 그 결과로 범위를 확정한 뒤 필요한 다른 Tool을 호출합니다.
3. 제품세대는 기존 배열 `{D1a,D1z,D20,FET,V5,V6,V7,V8}`을 유지합니다. 배열 원소를 이용해 검색·집계하며 관계 테이블로의 이전을 요구하지 않습니다.
4. 사내문서와 Eng’r Inform Note는 기존 chunk 및 **BM25 + vector similarity Hybrid RAG**를 연결합니다.
5. Router / Answer / Judge 시스템 프롬프트는 `app/skills`의 분절된 Skill과 공통 참조 파일로 조립하고 릴리스 해시를 검증합니다.
6. 물리 테이블명·컬럼명·Join 키는 설정으로 교체합니다. 기간시스템 조회와 승인 기반 조치 실행을 분리합니다.

## 기존 자료 보존

GPU 신청, VM·DB·NAS·Object Storage, 예산·ROI, 인프라 발급정보 등 기존 `docs/` 전체와 원본 Markdown·Office·텍스트 문서는 동일 경로·동일 Git blob SHA로 보존합니다. 숫자나 신청 사양을 이번 설계에서 재산정하지 않았습니다. 보존 문서의 과거 아키텍처와 구현 상태는 작성 당시 기록이며 현재 앱 계획은 `docs/current/`를 기준으로 읽습니다.

기존 저장소 전체는 `archive/pre-quality-rebuild-20260913` 브랜치에도 남아 있습니다. 연결 기능에 저장소 삭제·생성이 없어 저장소와 이력을 유지한 채 현재 작업 구성을 새로 구성했습니다. 원본 문서가 참조하는 과거 생성물은 해당 백업 브랜치에서 확인할 수 있습니다.
