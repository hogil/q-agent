---
name: image-metadata-schema
description: 이미지 메타데이터 테이블의 컬럼 의미·타입·단위·NULL·키 관계를 해석할 때 사용하는 공통 Schema Skill.
---

references/columns.json을 해당 엔티티가 필요한 역할에만 로드한다. 정의된 grain은 이미지 자산 한 건이고 식별 기준은 image_id다.
논리 필드와 실제 이름을 구분한다. 물리 table/column은 config의 tables.image_metadata에 있으며 Adapter가 적용한다. 컬럼 정의를 system prompt 여러 곳에 복사하지 않는다.
NULL/미등록/사용 불가를 0이나 정상으로 바꾸지 않는다. 허용 연산 목록이 실행 Tool 구현 완료를 의미하지 않는다. 의미/단위/관계가 바뀌면 이 Skill의 reference와 회귀 검사를 함께 갱신한다.

## 모델 Tool 비교

2026-09-21 로컬 합성 모델·참조 이미지 기준. 운영 SEM/Overlay·사내 이미지는 미검증이다.
- list_comparison_assets(item, modality)로 현재 사고·Lot·Wafer 범위의 자산 ID를 먼저 조회한다. modality는 sem 또는 overlay다. asset_id/revision은 서비스 메타데이터이며 DB storage_ref나 사용자가 준 URL로 대체하지 않는다.
- SEM은 compare_sem_images, Overlay는 compare_overlay_maps를 호출한다. 두 Tool은 독립된 모델 배포 설정을 사용한다. asset_ids는 앞서 반환된 서로 다른 두 ID다.
- 같은 Item/Step/계측 조건(acquisition)/좌표계가 확인된 경우만 비교한다. 같은 Item이라도 배율·좌표·계측 조건이 다르면 비교 불가다. 다른 설비는 비교할 수 있으나 설비 차이를 원인으로 단정하지 않는다.
- 모델 응답의 model/model_version, asset_ids/asset_revisions, alignment_verified, similarity, findings, limitations, artifact_ids를 근거로 보존한다. similarity는 불량 확률·원인 확률이 아니다.
- 화면의 나란히 보기, 색 중첩, Jaccard·Bin 통계는 모델 추론이 아니다. 모델 비활성·응답 오류·INCOMPARABLE을 자체 계산 점수로 대체하지 않는다.
- 사고 범위 밖 정상 비교군은 별도 권한·참조 범위 Adapter가 필요하다. 사고 영향 Wafer로 편입하거나 현재 사고 Tool로 임의 조회하지 않는다.
- 합성 서비스의 historical candidate는 등록된 과거 참조 중 같은 Item·Step·modality, 현재 촬영 이전 자료의 descriptor 거리다. 작을수록 가깝지만 불량/원인 확률이나 정렬된 similarity가 아니다. 참조 사고 ID·날짜를 보존하고 현재 영향 범위와 분리한다.

## 실제 데이터 확인 후 변경

변경 출처·기준일·근거를 기록한다. 사내 원본이 없으면 더미 초안이며 실제 검증을 주장하지 않는다. 원본 DB·온라인 Skill 수정은 허용하지 않는다.
