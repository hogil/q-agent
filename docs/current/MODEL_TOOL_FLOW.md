# Detection and Model Tool Flow

## Current Status

2026-09-19, 사용자 요구와 로컬 코드 기준. 운영 이미지, 모델 서비스, MES 권한은 미검증이다.
SEM/Overlay 비교는 Router가 별도 모델 Tool을 호출한다. UI의 이미지 나란히 보기,
색 중첩, Die 통계는 모델 추론이 아니며 미연결 모델의 대체 결과로 사용하지 않는다.

현재 Workbench는 합성 DB 데모다. 합성 감지 이벤트 재생은 서버 큐에서 DB/회의록을
조회하고 검토 요청을 저장한다. 모델 상시 실행, 실제 LLM 판정, 생산계 조치는 하지 않는다.
실제 이상감지 결과를 받는 인증된 ingress와 신규 사고 후보 매칭은 후속 연결 사항이다.

## Analysis Sequence

| 순서 | 실행 | 코드 / 계약 |
| --- | --- | --- |
| 1 | 질문 또는 감지 이벤트를 Router에 전달 | `app/agent.py`; 감지는 추후 인증된 ingress 필요 |
| 2 | 사고 DB 검색, 명시적 사고 선택 | `find_incidents`; 원본 DB 쓰기 없음 |
| 3 | Lot/Wafer 확인, 같은 Item 이미지 후보 조회 | `list_incident_lots`, `list_incident_wafers`, `list_comparison_assets` |
| 4 | 전문 모델 Tool 호출 | `compare_sem_images` 또는 `compare_overlay_maps` |
| 5 | Judge 근거 검토 | Item/Step/계측 조건/좌표/버전/한계 확인 |
| 6 | Answer 설명 | 모델 관측과 원인 가설 구분; 실제 evidence ID 인용 |
| 7 | 최종 조회 상태 / 사고 범위 표시 | 모델 미연결·비교 불가·범위 밖은 그대로 표시 |

| 상황 | 처리 |
| --- | --- |
| Judge의 근거 부족 | 같은 Router로 돌아가 필요한 Tool만 재조회 |
| 모델 비활성 또는 호출 실패 | unavailable; UI 점수로 대체하지 않음 |
| 계측 조건 / 좌표 불일치 | 비교 차단; 동일 Item만으로 비교 가능 판단 금지 |
| 생산 조치 요청 | 권한·승인·실행 ID·결과 확인이 별도 필요; Judge PASS는 승인 아님 |

## Image Service Contract

설정은 `config/config.yaml`의 `image_tools.sem` / `image_tools.overlay`와 site overlay다.
각각 `enabled`, `endpoint`, `served_model`, `api_key_env`, `timeout_seconds`를 가진다.
실행은 `app/image_tools.py`. 모델 로딩/상주는 외부 서비스가 담당하며 Tool 호출마다
모델 프로세스를 다시 띄우지 않는다. 기본값은 모두 비활성이다.

`POST {endpoint}/assets`는 코드가 바인딩한 `actor`, `incident_ids`, `item`, `modality`,
`as_of`를 받는다. 응답 `assets`에는 다음 메타데이터가 필요하다:

```text
asset_id, incident_id, lot_id, wafer_id, item, step, equipment, modality,
coordinate_system, acquisition, acquired_at, revision
```

이는 모델 서비스의 자산 카탈로그 계약이며 기존 7개 DB 테이블에 컬럼이 있다고 가정하지 않는다.
사용자가 전달한 파일 경로/URL은 조회하지 않는다. 반환 자산은 실제 사고 DB의
등록 Wafer와 대조한다. 범위 밖 정상 비교군은 별도의 승인된 참조 Adapter가 필요하다.

`POST {endpoint}/compare`는 조회·검증한 두 `asset_ids`, `asset_revisions`, 모델 이름,
같은 Item, 바인딩된 사고 범위 및 `request_id`를 받는다. 응답 필수값:

```text
request_id, model, model_version, item, modality, asset_ids, asset_revisions,
status, alignment_verified, similarity, findings, limitations, artifact_ids
```

응답의 request ID, 모델 이름, 자산 ID/Revision이 요청과 달라지면 거부한다. 모델 버전은 서비스가 보고한 값으로 보존한다. `status=OK`에는 유효한 정렬과
유한한 0~1 유사도가 필요하다. `INCOMPARABLE`은 성공 판정이 아니다.
유사도는 원인 확률이나 조치 효과가 아니며 artifact ID는 자동 파일 접근 권한이 아니다.

## Detection Replay Boundary

`app/detection_workflow.py`는 이벤트 중복 방지, 저장, 순차 처리, 실패 재시도와 검토 기록을 담당한다.
`app/workbench.py`의 `/api/monitoring/replay`는 합성 이벤트만 만든다. 같은 입력은
같은 이벤트로 취급한다. 브라우저를 닫아도 서버에 접수된 작업은 서버에서 처리한다.
재시작 중단 건은 실패로 표시하며 완료로 추정하지 않는다.

확인/기각은 검토 요청에 대한 기록일 뿐 생산 실행이 아니다. Lot Hold, 설비 정지,
Recipe 변경, 외부 알림 전송은 현재 미구현이며 원본 사고 DB도 수정하지 않는다.
Skill 수정은 오프라인 검토와 명시적 freeze 후 배포한다. 감지 이벤트로 Skill을 변경하지 않는다.

## Prompt Budget

컬럼 원본 JSON은 유지하고, 조립된 프롬프트에서만 `column_fields`와 행 배열로 중복 키를 줄인다.
7개 Schema의 모든 값을 복원 비교한다. Router의 중복 설명과 예시도 축약했다.
이미지/회의록/Wafer 동시 로딩을 위해 문자 상한은 36,000으로 명시하며 초과하면 중단한다.
이는 토큰 수나 모델 품질 보장이 아니다. 운영 모델의 tokenizer/context 한도와 실제 응답은 별도 검증한다.
