# Q-Agent `search_similar_fbm` 통합 범위 (2026-10-30)

## 상태와 근거

이 문서는 2026-10-30 체크아웃에서 확인한 FBM 검색 Tool 계약과 적용 경계를 기록한다. `app/agent.py`, `app/fbm_search_contract.py`, `app/workbench.py`, `app/config_loader.py`, `config/config.yaml`, image-metadata Schema Skill, `research/fbm_embedding_catalog_20261030.py`, `research/fbm_agent_catalog_adapter_synthetic_20261030.py` 및 FBM retrieval 설계·연구 메모를 근거로 한다. 아래의 self-match 동작은 합성 설계 및 그 범위의 코드 검증 사실이며 배포 완료를 뜻하지 않는다. 운영 storage, encoder/model, 실제 ACL, 물리적 lineage, 실장현 연결 및 검색 품질은 확인되지 않았다.

## 범위 및 호출 순서

`search_similar_fbm`은 Router가 사고 관련 최초 업무 Tool로 호출하는 도구가 아니라, 현재 사고를 확인하고 `list_incident_lots` 및 `list_incident_wafers`의 최신 페이지 체인이 끝난 뒤에만 고려할 후속 retrieval이다. Incident-first 조회 및 사고 scope 검증은 Orchestrator 코드가 강제한다. Skill은 이 계약을 설명하지만 권한 집행은 아니다.

도구 입력은 `source_incident_id`, `lot_id`, `wafer_id`, `representation`, 선택적 `top_k`로 제한된다. `actor`, 현재/과거 사고 ID, `as_of`, query scope는 Router가 전달하지 않는다. 런타임은 사고 DB에서 현재 사고 membership을 가져오고, 사전 `search_related_incidents` 결과에서 등록된 historical candidate를 계산하며, trusted caller가 주입한 `fbm_search_query` callback에 해당 값들을 바인딩한다. `config/config.yaml`의 `fbm_search.enabled` 기본값은 `false`, `top_k`는 10이다. 설정 loader는 top-k 1..50을 확인한다. 비활성화 또는 callback 부재 시 검색은 unavailable/fail-closed이다.

`representation`은 요청마다 정확히 하나를 선택하며 값은 `raw_fbm` 또는 `object_id_yield_fbm`이다. 두 표현은 독립 검색으로 취급한다. 한 표현에서 누락된 후보를 다른 표현 결과로 메우거나 similarity 점수를 직접 비교·평균하지 않는다. 반환 결과에는 요청 표현 및 모델 식별자/버전, preprocessing version, checkpoint SHA-256가 요구된다. 이는 callback 응답의 형식 검증이지 해당 모델·checkpoint가 실제 원본으로부터 생성되었음을 입증하지 않는다.

## 사고–Lot/Wafer chain 및 source 상태

FBM 호출 전 runtime은 활성 incident scope에서 마지막 offset-zero 시작점부터 동일 membership 조건으로 이어지는 Lot 및 Wafer page chain을 확인한다. 페이지 정렬·연속성·총 membership·metadata 일관성과 현재 scope를 확인하고, 각 wafer의 `(incident_id, lot_id, wafer_id)`가 해당 사고의 등록 Wafer이며 Lot page에도 부모 Lot이 있는지 확인한다. 요청 tuple은 이 등록 집합 안에 있어야 한다. 이 gate는 조회 절차와 tuple의 source 등록 상태 확인이다.

이 페이지 체인 검증은 Lot/Wafer DB 조회가 `as_of` 시점의 snapshot에서 수행되었음을 보장하지 않는다. 페이지 간 `scope_id`, mapping/completeness 등 metadata 일치는 같은 DB transaction/snapshot 또는 과거 membership의 일관성을 입증하지 않으며, 결과의 `available_at` 검사도 source page가 cutoff 기준으로 조회되었음을 소급 보증하지 않는다. 현장 adapter를 연결할 때는 snapshot/transaction pinning 또는 동등한 source 보증, cutoff 적용 방식, 페이지 간 snapshot identity를 별도 검증·기록해야 한다.

두 조회의 page chain 완료는 source completeness를 자동으로 `declared_complete`로 만들지 않는다. 원본 `source_completeness`는 별도 보존된다. Wafer scope가 `incident_affected`이면 해당 사고 영향 wafer 조회이며, `lot_inventory`이면 Lot inventory에서 온 image-context 조회일 수 있다. 후자의 검색 결과는 `inventory_context_only` (`inventory_context_only_not_incident_impact`)로 제한되며 사고 영향 Wafer 근거나 action-planning의 완전/affected gate로 승격하지 않는다. `unknown`/`partial` source completeness도 그대로 유지하고 declared complete가 아니면 제한을 표시한다. `lot_inventory` 사용 허용은 정확히 검증된 incident+lot+wafer tuple에 한정된다.

검색 대상의 관계는 `direct` 또는 사전에 검색된 과거 사고의 `historical_candidate`로 보존된다. Direct는 현재 사고 ID 및 등록된 wafer tuple에 속해야 하며, historical candidate는 사전 historical incident ID에 속해야 한다. 과거 후보는 현 사고 범위, 현 사고 영향 wafer 또는 원인으로 간주하지 않는다.

## Callback 결과 검증과 한계

`validate_fbm_response`는 응답 status/표현/as_of, query wafer tuple, 등록 wafer, 항목 수와 연속 rank, 중복 identity, cosine 범위, 관계별 incident 범위, cutoff 이전의 timezone-aware `available_at`, model metadata 및 checkpoint hash 형식을 검사한다. Query와 동일한 `(asset_id, revision, representation)`인 결과는 callback 응답에 있으면 validator가 거부한다. 런타임은 actor, 현재/과거 사고 ID, query tuple, 표현, cutoff, top-k를 callback 인자에 바인딩하며 callback signature도 확인한다. 오류는 retrieval failure로 닫힌다.

이 validator는 trusted Python callback이 돌려준 **주장을 요청과 대조**한다. `source_query_assertion_unverified`, `source_model_assertion_unverified`, `historical_wafer_scope_unverified`, `site_acl_unverified`, `coordinate_lineage_unverified`, `source_ranking_unverified` 제한을 명시한다. Source ranking의 정확성, 같은 Wafer의 여러 asset/revision 결과를 합치거나 중복 제거하는 의미, site source 및 물리적 lineage는 확인되지 않았다. 응답 안의 scope ID, 모델 ID, lineage 정보나 actor 인자는 그 자체로 원본 저장소의 진실, 실제 ACL enforcement, wafer identity 또는 authorization을 증명하지 않는다. Callback은 trusted integration boundary로 가정되며, 호출자 제공 값만으로 악의적/잘못된 adapter의 허위 응답을 검증할 수 없다.

합성 카탈로그 어댑터는 query asset을 catalog에서 resolve한 뒤 선택된 표현 안에서 `(asset_id, revision)`을 제외 조건으로 `catalog.search`에 전달한다. 카탈로그의 검색 키가 `(asset_id, revision, representation)`이므로 이 조건은 해당 query identity의 정확한 self-match만 제거한다. 다른 revision은 물론 다른 asset ID가 같은 SHA-256 bytes를 가리키는 경우도 `exclude_sha256`를 지정하지 않는 한 후보로 보존한다. 제외 조건은 후보 SQL의 검색 대상 제한에 top-k 정렬·잘라내기 전에 적용되므로, 이 어댑터의 top-k/truncated 및 validator가 허용하는 결과 길이는 self-match 제외 후 후보 모집단을 보고한다. Validator 역시 응답에 동일한 asset+revision+representation이 남아 있으면 거부한다.

이 self-match 보장은 확인한 합성 카탈로그·어댑터 경로의 계약이다. 일반 trusted callback이 동일 규칙을 준수하는지는 운영 source에서 별도로 확인해야 한다. 응답의 `truncated`는 bool 또는 null로만 검사한다. null은 truncation 의미 `unknown`, bool은 `source_assertion_only`로 표기한다. top-k와 source가 보고한 truncation은 검색 corpus 전체의 recall/완전성 보장이 아니다. top-k 바깥 후보, query/응답의 source completeness, source ranking 품질 및 실데이터의 실제 검색 품질도 이 계약만으로 확정할 수 없다.

## 연결 경계

`Workbench` 생성자는 `fbm_search_query`를 optional trusted callback으로 받아 agent에 전달한다. 기본 경로가 운영 FBM backend를 자동 생성·연결한다는 근거는 확인되지 않았다. `run_agent.py`의 일반 CLI 경로도 현재 확인 범위에서 FBM callback을 전달하지 않는다. 따라서 설정을 켜는 것만으로 검색 가능한 source가 생기지 않는다. 별도의 site adapter 구현 시 storage/encoder/ACL 및 source metadata 계약을 확인하고 callback 신뢰 경계를 명시해야 한다.

이 통합은 기존 사고 검색, `search_related_incidents`, Lot/Wafer 조회 API나 source mapping을 대체하지 않는다. `lot_inventory` evidence를 사고 영향으로 재분류하지 않고, retrieval similarity를 원인 확률·인과 근거나 정상 보증으로 해석하지 않는다. 합성 contract 및 research prototype이 존재하더라도 실제 FBM gallery, 실제 운영 연결·권한, 실장현 연결·품질 검증이 완료되었다고 주장할 수 없다.

