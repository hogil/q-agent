---
name: image-metadata-schema
description: 이미지 메타데이터 테이블의 컬럼 의미·타입·단위·NULL·키 관계를 해석할 때 사용하는 공통 Schema Skill.
---

references/columns.json을 해당 엔티티가 필요한 역할에만 로드한다. 정의된 grain은 이미지 자산 한 건이고 식별 기준은 image_id다.
논리 필드와 실제 이름을 구분한다. 물리 table/column은 config의 tables.image_metadata에 있으며 Adapter가 적용한다. 컬럼 정의를 system prompt 여러 곳에 복사하지 않는다.
공통 NULL 및 Tool 구현 경계는 core/SKILL.md를 따른다. 의미/단위/관계 변경 시 reference와 회귀 사례를 갱신한다.

## 모델 Tool 비교

2026-09-21 로컬 합성 모델·참조 이미지 기준. 운영 SEM/Overlay·사내 이미지는 미검증이다.
- list_comparison_assets(item, modality)로 현재 사고·Lot·Wafer 범위의 자산 ID를 먼저 조회한다. modality는 sem 또는 overlay다. asset_id/revision은 서비스 메타데이터이며 DB storage_ref나 사용자가 준 URL로 대체하지 않는다.
- SEM은 compare_sem_images, Overlay는 compare_overlay_maps를 호출한다. 두 Tool은 독립된 모델 배포 설정을 사용한다. asset_ids는 앞서 반환된 서로 다른 두 ID다.
- 같은 Item/Step/계측 조건(acquisition)/좌표계가 확인된 경우만 비교한다. 같은 Item이라도 배율·좌표·계측 조건이 다르면 비교 불가다. 다른 설비는 비교할 수 있으나 설비 차이를 원인으로 단정하지 않는다.
- 모델 응답의 model/model_version, asset_ids/asset_revisions, alignment_verified, similarity, findings, limitations, artifact_ids를 근거로 보존한다. similarity는 불량 확률·원인 확률이 아니다.
- 화면의 나란히 보기, 색 중첩, Jaccard·Bin 통계는 모델 추론이 아니다. 모델 비활성·응답 오류·INCOMPARABLE을 자체 계산 점수로 대체하지 않는다.
- 사고 범위 밖 정상 비교군은 별도 권한·참조 범위 Adapter가 필요하다. 사고 영향 Wafer로 편입하거나 현재 사고 Tool로 임의 조회하지 않는다.
- 합성 서비스의 historical candidate는 등록된 과거 참조 중 같은 Item·Step·modality, 현재 촬영 이전 자료의 descriptor 거리다. 작을수록 가깝지만 불량/원인 확률이나 정렬된 similarity가 아니다. 참조 사고 ID·날짜를 보존하고 현재 영향 범위와 분리한다.
- 합성 설계에서 SEM/Overlay 자산의 `acquired_at`은 timezone-aware 시각이어야 한다. 이를 `runtime.timezone`의 현지 날짜로 환산해 요청 `as_of` 이내인지 판단한다. 예: `2026-03-01T17:00Z`는 서울에서 `2026-03-02`다. 이는 사용자 기준시점·이미지 조회 요구를 반영한 규칙이며, 2026-10-30 로컬 재현에서 `app/image_tools.py`의 날짜 판정은 현지 변환을 하지 않았고 `app/config_loader.py`에서 `runtime.timezone` 설정을 확인했다. 실제 사내 이미지 source/API·ACL은 미확인이다. 취득시각은 검색 가용시각이나 확정 인과를 뜻하지 않는다.

## FBM 유사 검색 계약 초안

2026-10-30 사용자 요청과 `docs/current/DOCUMENT_IMAGE_AND_FBM_RETRIEVAL_DESIGN_20261030_ROOT_v1.md`, 합성 탐색 실험 `research/fbm_dual_view_search_20261030.py`를 근거로 한 미검증 설계다. 실제 사내 DB/storage/ACL/model, map lineage와 geometry·좌표는 확인되지 않았다.

- 완료된 현재 사고·Lot·Wafer 조회 tuple이 일치한 경우에만 `search_similar_fbm` 후속 조회를 고려한다. actor/incident scope/as_of는 trusted code가 바인딩하며 Router가 제공하지 않는다.
- 완료는 Lot/Wafer 조회 page chain이 끝났고 source scope 및 coverage 상태를 확인·보존했다는 절차 조건이다. source completeness가 unknown/partial이면 그대로 유지한다. `lot_inventory` scope도 정확한 incident+lot+wafer tuple이 확인된 FBM image-context 조회에는 허용할 수 있으나, 결과는 `inventory_context_only`이며 incident-affected Wafer 증거가 아니다. 이 허용은 `incident_affected` completeness 주장이나 synthetic action planning의 완전/affected gate를 완화하지 않는다.
- `raw_fbm`과 `object_id_yield_fbm`은 별도 요청·결과다. 한 뷰의 누락을 다른 뷰로 채우지 않고 unknown으로 둔다.
- 결과 관계는 현재 선택 사고 또는 사전에 `search_related_incidents`가 반환한 historical candidate로 구분한다. 과거 후보는 현 사고 영향 Wafer나 원인으로 간주하지 않는다.
- callback 검색 결과에서는 query와 동일한 `(incident_id, lot_id, wafer_id, asset_id, revision, representation)` item을 코드가 identity 검사 후 제외한다. 다른 Wafer의 identical bytes/hash 또는 다른 revision은 이 계약으로 자동 제외하지 않는다. 동일 Wafer의 별도 revision 중복은 미검증이다.
- top-k, truncation 및 빈 결과는 query 제외 후 검색 범위의 source 결과로 해석한다. source `rank`는 반환값 그대로 보존하되 순위 의미는 미검증이다.
- FBM 후속 조회 문맥의 Lot/Wafer coverage는 선택 사고별로 `coverage_grain=incident`를 유지한다. Lot coverage와 Wafer coverage의 상태 및 `expected_*`/`returned_total_*` counts를 별도로 전달하고, 누락 값은 `missing` 또는 `unknown`으로 남긴다. `count_mismatch`, `inventory_not_incident_impact`, `partial`, `unknown` 등 source 상태를 요약·정상화해 숨기지 않는다. 이 값은 사고별 membership coverage 보고이며 Lot별 통계, 완전성 증명, 사고 영향 Wafer 판정 또는 원인 근거가 아니다. `lot_inventory`는 incident-affected Wafer를 뜻하지 않는다.
- source가 반환한 검색 순서와 `rank`/`similarity` 값은 있는 그대로 보존한다. 순위 의미가 검증되지 않았으면 rank 1이 cosine similarity 최댓값을 뜻한다고 해석하지 않는다.
- 유사도는 원인 확률이나 정상 보증이 아니다. 이 계약은 합성 설계 초안이며 config enabled와 callable trusted adapter가 모두 있어야 사용 가능하다; 기본 설정은 disabled다.

이 범위 변경은 2026-10-30 로컬 `app/agent.py`의 `fbm_source_wafers` 보존 범위, `app/incident_tools.py`의 252행 Lot coverage 및 303행 Wafer coverage 상태, `inventory_not_incident_impact` 값과 사용자 요구를 근거로 하며, 실제 source/ACL/site 동작은 확인되지 않았다. query 자기 일치 규칙은 `research/fbm_agent_catalog_adapter_synthetic_20261030.py`의 callback query identity 확인 및 검색 결과 구성과 `research/fbm_embedding_catalog_20261030.py`의 `exclude_asset_id`/`exclude_sha256` 지원을 함께 근거로 한 합성 계약 변경이다. 현장 데이터·ACL·lineage·retrieval 품질은 미검증이다.

변경 전 출처·기준시점 확인은 core/SKILL.md를 따른다.
