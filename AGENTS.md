# Q-Agent 개발 규칙

- 최신 사용자 요구와 docs/current 설계를 따른다. 원본 CLAUDE.md와 docs/의 기존 자료는 보존된 자원/과거 프로젝트 문맥이며 현재 구현 완료의 증거가 아니다.
- GPU, 서버, VM, DB 용량, 스토리지, 자원 산정, 예산, ROI, 인프라 자료를 삭제하거나 임의 수정하지 않는다. docs/current/RESOURCE_PRESERVATION.json의 원본 경로와 Git blob 해시를 확인한다.
- 사고 관련 최초 업무 Tool은 사고 DB 검색/집계다. 선조회 강제와 권한은 프롬프트가 아닌 Orchestrator/Adapter 코드에서 보장한다.
- 기존 제품세대 배열을 유지한다. 부문별 통계에서 다중 세대를 폭발시킨 뒤 distinct 사고를 세고, 수량을 균등 배분하지 않는다.
- 사내문서/Eng’r Inform Note는 기존 BM25+vector Hybrid RAG와 기존 chunk를 연결한다.
- Router/Answer/Judge 동작 변경은 app/skills 및 공유 참조를 먼저 수정한다. 관련 평가 사례를 수정하고 명시적으로 freeze한 뒤 검증한다. 온라인 질의로 Skill 원본을 변경하지 않는다.
- 사내 테이블/컬럼/Join은 매핑 설정을 통해 연결한다. 비밀정보, 실제 Lot/이미지/사내 문서 내용을 합성 데이터 예제에 넣지 않는다.
- 구현하지 않은 LLM, ACL, 생산계 조치, 이미지/Trend 모델을 구현 완료로 표시하지 않는다.
- 검증 명령: cd app 후 python demo.py, python array_demo.py, python check_skills.py. Skill 변경 시 먼저 python skill_loader.py freeze.

- 배포 설정의 단일 진입점은 config/default.toml + site overlay다. DB/폴더/모델명을 코드나 Skill 지침에 하드코딩하지 않는다.
- 6개 테이블의 논리 컬럼 명세는 각 Schema Skill의 references에서 관리하고 check_config.py로 누락/불일치를 검사한다.
- 추가 검증: python app/check_config.py. 사내 *.local.toml, var/ 생성 DB와 전체 결과는 Git에 올리지 않는다.
