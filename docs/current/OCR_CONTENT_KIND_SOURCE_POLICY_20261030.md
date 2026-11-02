# 문서 OCR content kind source 정책 (2026-10-30)

## 범위와 현재 상태

이 문서는 Eng’r Inform Note 및 사내 공용문서의 이미지 텍스트를 기존 문서 검색 경로에서 구분하기 위한 현재 코드 계약을 정리한다. 이는 source별 반환값 validator의 marker/시각 검증이다. 실제 사내 문서, ACL, OCR 파이프라인 또는 site Hybrid RAG 연결을 확인한 기록은 아니다.

기본 설정에서 `retrieval.internal_documents.require_content_kind`와 `retrieval.engineer_notes.require_content_kind`는 모두 `false`다. 두 source 모두 비활성이고 endpoint는 비어 있다. 따라서 현 설정만으로 운영 검색이나 OCR 이미지 텍스트 검색이 활성화되지 않는다. 각 source를 실제 환경에서 연결할 때 해당 source의 플래그를 `true`로 두면 반환 item에 명시적인 `content_kind`가 요구된다.

## Marker 및 시간 계약

- `content_kind: "text"`는 일반 텍스트 chunk임을 callback이 표시한다. validator는 이 표식이 사실인지 원문을 재검사하지 않는다.
- `content_kind: "image_ocr"`는 이미지에서 나온 OCR 파생 텍스트임을 callback이 표시하며, `derivative_available_at`도 함께 요구한다. 기존 `available_at`은 source/chunk 가용 시각으로 유지된다. OCR 파생물 가용 시각은 별도 필드이며 둘 다 요청의 `as_of` 날짜 이하여야 한다.
- `require_content_kind: true`일 때 marker 누락, 지원하지 않는 marker 값, OCR marker의 파생 시각 누락/잘못된 값은 validator에서 거부된다. 파생 시각은 `image_ocr`에만 허용된다.
- `false`일 때 marker를 생략한 레거시 item은 종전처럼 허용되고, marker가 있으면 그 값과 관련 시각 형식은 여전히 검사한다. 그러므로 레거시 미표기 item은 일반 텍스트라고 판별된 것이 아니다.

Marker는 callback의 주장이다. `text`로 잘못 표시된 OCR 본문을 탐지하거나 OCR 누락을 판별하지 않는다. 이 계약만으로 OCR 추출의 정확성/완전성, 실제 출처 및 이미지 연결, 원문 ACL 권한을 입증할 수 없다. caller가 전달한 scope/status 검증도 실제 저장소 권한 확인의 대체물이 아니다.

## 설정 및 fail closed

기본 설정은 [config/config.yaml](</D:/project/q-agent/config/config.yaml:212>)에 있다. 설정 진입은 `config/config.yaml`과 선택적 site overlay이며, overlay는 두 source의 값을 따로 지정할 수 있다. 구형 standalone base/overlay에서 필드가 빠진 경우 loader는 `false`를 채워 레거시 동작을 유지한다. `require_content_kind`가 boolean이 아닌 값이면 config shape/value 검증이 실패하며, 실행 중 source 설정이 dict가 아니거나 값이 정확한 boolean이 아니어도 문서 Tool은 `INVALID_DOCUMENT_CONTENT_KIND_CONFIG`로 fail closed 한다. 설정 변경은 원본 설정과 site overlay의 실제 배포 상태를 함께 확인해야 한다.

## 구현 경계와 확인 자료

확인한 구현 파일은 [app/config_loader.py](</D:/project/q-agent/app/config_loader.py:47>), [app/agent.py](</D:/project/q-agent/app/agent.py:1035>), [app/document_evidence_contract.py](</D:/project/q-agent/app/document_evidence_contract.py:134>), [app/evidence_review.py](</D:/project/q-agent/app/evidence_review.py:100>)다. 문서 Tool은 caller가 제공한 `document_query` callback을 source별로 검증하는 경로다. 현재 확인 범위에서 실제 site RAG callback, 사내 원문/ACL 조회 또는 문서 OCR adapter가 이 경로에 연결되었다고 볼 근거는 없다. 합성 OCR adapter/bridge 연구는 별도 synthetic 자료이며 운영 연결의 증거가 아니다.

합성 테스트 출처와 재현 명령:

- Marker 및 레거시/필수 marker 검증: [tests/test_document_marker_enforcement_20261030.py](</D:/project/q-agent/tests/test_document_marker_enforcement_20261030.py>) — `python -m pytest tests/test_document_marker_enforcement_20261030.py`
- OCR 파생 시각 계약: [tests/test_document_ocr_temporal_contract_20261030.py](</D:/project/q-agent/tests/test_document_ocr_temporal_contract_20261030.py>) — `python -m pytest tests/test_document_ocr_temporal_contract_20261030.py`
- 합성 PPTX OCR에서 validator/검색 bridge까지의 흐름: [tests/test_pptx_ocr_hybrid_bridge_synthetic_20261030.py](</D:/project/q-agent/tests/test_pptx_ocr_hybrid_bridge_synthetic_20261030.py>) — `python -m pytest tests/test_pptx_ocr_hybrid_bridge_synthetic_20261030.py`

위 테스트는 합성 입력의 코드 계약 재현용이다. 이 문서는 실행 수나 실행 결과를 주장하지 않으며, 실제 사내 문서나 site 검색/OCR/ACL 검증 완료를 의미하지 않는다.
