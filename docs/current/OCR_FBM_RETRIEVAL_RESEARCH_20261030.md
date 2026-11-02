# OCR·FBM 검색 표현 연구 결과와 검증 경계 (2026-10-30)

## 목적과 범위

이 기록은 2026-10-30 로컬에서 생성된 합성 OCR retrieval 관측, 합성 FBM 다중 후보 검색 관측, E5 로딩 전용 자원 probe 결과를 보존한다. 세 결과는 기능·입력 형식 관측 또는 제한된 실행 진단이며, 사내 문서 RAG 또는 실물 wafer 검색의 품질·운영 검증으로 해석하지 않는다. 선행연구와의 novelty 비교도 수행하지 않았다.

## 확인한 산출물

- OCR 합성 paraphrase retrieval: `D:\project\q-agent\var\output\ocr-e5-hybrid-paraphrase-20261030-20261030-092159\result.json`
- FBM 표현별 다중 후보 retrieval: `D:\project\q-agent\var\fbm-research\retrieval-1793319023158761200-181608\retrieval_results.json`
- E5 2 GiB 제한 probe: `D:\project\q-agent\var\output\e5-native-isolation-20261030-7335b07949a742d9a718d597471380f2\result.json`
- E5 2560 MiB 결합 probe(성공 실행): `D:\project\q-agent\var\output\e5-native-isolation-20261030-4b84dcfc4c6840948088a1ad94869d37\result.json`

## OCR 합성 retrieval 관측

산출물은 `status=passed`, `synthetic_only=true`, E5 차원 384, 모델 manifest SHA-256 `62a7504dbc3efd71ea004136df3cf33eecb2cc0fa707ff5d974926d0b560b302`로 기록되어 있다. 합성 OCR chunk에 대한 원문형 검색은 lexical/E5/hybrid 각 rank 1이었다. 추가 paraphrase 두 질의는 다음처럼 관측됐다.

| 질의 | FTS5 target hit | 벡터 target rank | Hybrid target rank |
|---|---:|---:|---:|
| `인공 문자 인식 검사` | 없음 | 1 | 1 |
| `이미지에서 읽어낸 문구와 관련된 자료를 검색해줘` | 없음 | 1 | 1 |

이는 source 문서 1개와 distractor 2개, 총 3개 chunk로 구성된 메모리 내 합성 fixture에서의 두 질의 결과다. FTS5의 zero와 vector의 1위는 해당 fixture와 tokenization에 한정된 관측이며, 일반적인 semantic retrieval 성능 또는 유의한 개선을 보이지 않는다. 원본 문서·이미지 및 OCR source metadata는 만들어낸 합성 fixture이고 OCR 상태는 `candidate_unreviewed`다. 호출자가 제시한 원본 SHA-256은 `caller_asserted_unverified`; checkpoint hash 설정은 실제 OCR engine 파일과 결속되지 않았고(`configured_checkpoint_hashes_unbound_to_engine`), fingerprint도 미검증 caller assertion이다. fake allow callback은 ACL이 아니다. 실제 사내 Hybrid RAG, 원래 chunk 연결, ACL, 검색 corpus 또는 서비스 연동은 수행·확인하지 않았다.

## FBM의 두 표현 비교 관측

데이터는 `center`, `edge`, `ring`, `random` 네 합성 패턴이다. 클래스별 gallery 2장, query 2장(총 gallery 8/query 8), wafer당 defect 10개, defect 반경 3 px, seed base 20261030 및 ID assignment offset 500000을 사용했다. gallery와 query 입력은 독립 wafer이며, 동일 base wafer에서 `raw_fbm`과 `object_id_yield`를 짝 렌더링했다. 모델 식별자는 `convnextv2_base.fcmae_ft_in22k_in1k_384+fbm_projection`, 출력 차원 128이다.

`object_id_yield`는 실제 object ID·measure·yield 데이터가 아니다. 합성 per-wafer known_A/known_B/unknown defect ID와 `normal_yield` 배경색을 사용한 proxy rendering이다. 보고된 top-1은 클래스 정답 gallery 후보가 8개 중 2개이므로 무작위 기준선 2/8=0.25로 읽을 수 있다. Top-3의 무작위 기준선은 8개 후보 중 정답 2개가 포함된 3개를 비복원 추출하는 경우 `1 - C(6,3)/C(8,3) = 9/14 ≈ 0.643`이다. 두 기준선은 이 작은 설정의 조합론적 참고값이며, 통계적 기준선 추정이나 유의성 검정은 아니다.

| 표현 | Top-1 | Top-3 | 클래스별 Top-1 (center / edge / ring / random) | 클래스별 Top-3 |
|---|---:|---:|---|---|
| raw_fbm | 7/8 (0.875) | 8/8 (1.000) | 2/2, 1/2, 2/2, 2/2 | 2/2, 2/2, 2/2, 2/2 |
| object_id_yield proxy | 4/8 (0.500) | 7/8 (0.875) | 2/2, 0/2, 1/2, 1/2 | 2/2, 2/2, 1/2, 2/2 |

실패 양상은 raw_fbm에서 edge query 1건이 top-1 오답이나 top-3 정답이고, object_id_yield proxy에서 edge 2건 모두 top-1 오답(top-3 정답), ring 1건 top-1 및 top-3 오답, random 1건 top-1 오답(top-3 정답)이다. center는 두 표현 모두 top-1/top-3 2/2다. 표본이 클래스당 query 2건이라 비율·차이의 통계적 추론이나 일반화 주장을 하지 않는다. 입력은 synthetic이고 object/yield 매핑의 의미는 검증되지 않았다. 모델 checkpoint SHA-256은 `92898360d97a0b7583655f6275fbaf8f44ad1af0b9ed7920e974b658b87edaad`지만, 파일 해시는 산출물 모델 식별에만 쓰인다. 이것은 모델 출처, 학습 이력, 데이터 provenance 또는 사내 원본과의 진위를 증명하지 않는다.

## E5 자원 probe 해석

2 GiB 작업 한도(2,147,483,648 bytes) 실행에서는 tokenizer/config/safetensors metadata·작은/큰 tensor 및 empty-model 개별 probe가 통과했지만, 결합 probe가 `failed_or_incomplete`로 끝나 전체 결과는 `partial_failure`였다. 로그는 `combined_tensor_read_before` marker 뒤 `probe_complete` marker 없이 종료되었으며, tensor 읽기 완료를 확인하지 못했다. 이를 E5 전체 모델 로딩의 원인이나 일반적인 2 GiB 불가 판정으로 확대하지 않는다.

2560 MiB(2,684,354,560 bytes) 결합 probe는 `diagnostic_complete_success`, return code 0, 완료로 기록됐다. 단, 이것은 config의 무작위 초기화 empty model을 유지하면서 사전 지정된 단일 pretrained tensor(384,056,832 bytes)를 읽은 probe다. full pretrained weight load 및 embedding 의미 품질 검증은 하지 않았다. 로그 자체가 명시하듯 앞선 전체 로딩 성공/실패의 원인은 증명하지 않는다. 반복 실행 간 차이의 원인도 확정하지 않는다. 두 결과 모두 crash cause와 semantic quality 주장을 하지 않는다.

## 공개 선행연구 및 novelty

- Wu et al., DOI: `10.1109/TSM.2014.2364237`
- Nakazawa et al., DOI: `10.1109/TSM.2018.2795466`

이 서지 표기는 요청된 DOI 수준의 참고 정보다. 여기서는 논문 내용의 신규 검색·대조를 수행하지 않았으므로 제목·기여 비교나 related-work coverage를 주장하지 않는다. 따라서 연구 신규성은 미입증이다.

## 사용자가 제시한 설계 원칙과 다음 검증 단계

사용자 설계 원칙은 합성 object/yield 색상 proxy를 실제 의미로 간주하지 않고 원본 FBM 이미지에서 object ID와 yield 표현을 분리하는 것이다. 후속 검증은 순서대로 진행한다.

1. 승인된 원본 FBM 및 authoritative object ID/yield 별도 데이터를 확보하고 출처·시점·매핑을 검증한다. 접근 전에는 합성 proxy를 유지하며 실제 의미가 확인됐다고 쓰지 않는다.
2. 원본 wafer identity와 defect annotation을 확인하고 데이터 누수 없는 독립 wafer split, 고정 전처리·seed·모델 checkpoint provenance를 기록한다.
3. raw FBM과 분리된 object ID 및 yield 표현을 동일 query/gallery 구성에서 각각 평가하고, 충분한 표본·반복/신뢰구간 및 사전 정한 retrieval metric으로 비교한다.
4. 검색 후보 및 오답을 클래스·장비/제품 범위 등 사전에 정한 층으로 검토하고, 결과를 도메인 전문가가 확인한다.
5. 별도 승인된 사내 RAG/index와 실제 ACL에서 source provenance, scope, 권한 filtering 및 원본 chunk 연결을 검증한 뒤에만 서비스 통합 여부를 평가한다.

## 결론

현재 증거는 합성 OCR paraphrase 두 건의 FTS5/vector 관측, 16개 작은 합성 wafer 쌍 렌더링에서의 표현별 검색 수치, 제한된 E5 tensor resource probe에 국한된다. 실측 FBM·실제 object ID/yield 의미, 사내 RAG·ACL·서비스 통합, 통계적 우위, 공개 문헌 대비 신규성은 모두 입증되지 않았다.


