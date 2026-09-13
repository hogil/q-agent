# 사내 실행 스크립트

## 현재 지원 범위

Linux는 scripts/run_onprem.sh, Windows는 scripts/run_onprem.ps1을 사용한다.
두 스크립트는 같은 app/run_agent.py를 호출한다. 기본 동작은 사내 설정과 Skill 릴리스 확인이며,
`--mode prompt`는 선택한 역할의 시스템 프롬프트를 표준 출력으로 보낸다.
`--mode run --actor CALLER --question '질문'`은 Router → Tool → Judge → Answer를 실행한다.
기본 check와 prompt 모드는 네트워크에 접속하지 않는다. 웹 대화 서버는 시작하지 않는다.

## 사전 준비

Python 3.11+ 환경에서 requirements.txt를 설치한다. 설치를 실행 스크립트에서 자동으로 하지 않는다.
config/site.example.yaml을 참고해 Git에서 제외된 config/site.local.yaml을 준비한다.
예제의 경로와 YOUR_ 값은 실제 사내 정보가 아니며, 생략된 컬럼도 모두 매핑해야 한다.

- `environment: onprem`을 명시한다.
- `database`의 연결 대상과 7개 `tables`의 이름/모든 논리 컬럼 매핑을 명시한다. 사용하지 않는 선택 컬럼은 빈 문자열로 적는다.
- `paths.skills_root`, `dictionary_root`, `registry_file`, `skill_lock_file`, `terminology_file`을 사내 파일로 지정한다.
- 사전은 dictionary_root 안에 두고 version, fields, `synthetic: false`를 명시한다.
- 사내 자료를 검토한 담당자가 릴리스 lock을 사전에 만든다. 실행 중 자동 freeze하지 않는다.
- run 모드는 세 역할에 enabled/API 모델과 api_key_env 환경변수가 필요하다. 모델은 function calling과 JSON 응답을 지원해야 한다.

공통 실행 옵션은 config/config.yaml에서 상속하지만 연결 대상/테이블 매핑/Skill 위치는
명시적으로 지정해야 한다. 상대경로는 config/config.yaml이 있는 폴더 기준이다.
`--site-config` 인자의 상대경로 자체는 명령을 실행한 폴더 기준이다.
사내 Skills와 사전은 저장소 밖 또는 Git에서 제외된 config/private에 보관한다.

## Linux

다음은 `/opt/q-agent`에 설치한 경우의 예시이며 실제 설치 경로로 바꾼다.

```bash
QAGENT_PYTHON=/opt/q-agent/.venv/bin/python bash /opt/q-agent/scripts/run_onprem.sh \
  --site-config /opt/q-agent/config/site.local.yaml

QAGENT_PYTHON=/opt/q-agent/.venv/bin/python bash /opt/q-agent/scripts/run_onprem.sh \
  --site-config /opt/q-agent/config/site.local.yaml --mode prompt --role router --topics incident_search
```

## Windows

```powershell
$env:QAGENT_PYTHON = 'D:\project\q-agent\.venv\Scripts\python.exe'
& 'D:\project\q-agent\scripts\run_onprem.ps1' --site-config 'D:\project\q-agent\config\site.local.yaml'
```

Python 실행 경로는 설치 위치에 맞춰 지정한다. QAGENT_PYTHON이 없으면 Linux는 python3,
Windows는 python을 PATH에서 찾는다. PowerShell 실행 정책은 사내 정책을 따르며 스크립트가 변경하지 않는다.

## 중단 조건과 보장 범위

실행 예시:

```powershell
& 'D:\project\q-agent\scripts\run_onprem.ps1' --site-config 'D:\project\q-agent\config\site.local.yaml' --mode run --actor 'local-user' --question '사고번호에 해당하는 Lot과 Wafer를 조회해' --trace
```

실제 사고번호를 질문에 명시한다. --trace는 내부 조회 데이터를 포함할 수 있는 진행 이벤트를
stderr로 출력한다. 최종 JSON에는 답변, 근거, 실행 이벤트가 포함된다.
복수 후보의 경우 needs_selection으로 종료하며 반환된 ID를 --select-incident로 명시해 다시 실행한다.
독립적인 제공 자료 요약은 --request-scope independent로 실행하면 DB를 열지 않는다.
actor는 로컬 호출자 구분이며 인증/ACL을 대신하지 않는다. 외부 웹에 직접 노출하지 않는다.

site config 누락, environment 불일치, 명시적 설정 누락, Skill/사전 파일 누락,
번들 리소스 참조, 합성 사전, 릴리스 해시 불일치, 프롬프트 생성 실패 시 비정상 종료한다.
QAGENT_CONFIG/QAGENT_OVERLAY는 이 실행 경로의 설정을 바꾸지 못한다.
별도 창, 백그라운드 서버, 데모 데이터, 사내 Skill 복사본을 자동 생성하지 않는다.

check 성공 표시는 설정 구조와 파일 무결성 확인이다. 실제 사내 데이터의 정확성이나
접속 권한/운영 준비 완료를 뜻하지 않는다. 합성 사전의 표시만 바꿔 사내 사전으로 사용하면 안 된다.
생성된 프롬프트에도 내부 컬럼 설명이 들어가므로 사내 자료와 같은 기준으로 보관한다.
