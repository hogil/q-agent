"""Opt-in local E5/FTS5 smoke over one synthetic DOCX OCR candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(r"D:\project\q-agent-models\var\weights\multilingual-e5-small-v1")
INCIDENT = "synthetic-docx-e5-incident"
AS_OF = "2026-10-30"
QUERY = "OCR테스트입니다"
JOB_CHOICES = range(2048, 3073)


def load_payload(result_path: Path, expected_sha: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "research"))
    from pdf_ocr_e5_hybrid_synthetic_20261030 import confined_var_file

    path = confined_var_file(result_path).resolve(strict=True)
    if (not isinstance(expected_sha, str) or len(expected_sha) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in expected_sha)):
        raise RuntimeError("expected input SHA-256 must be 64 hexadecimal characters")
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("DOCX OCR result must be a regular local var file no larger than 16 MiB")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha.lower():
        raise RuntimeError("DOCX OCR result must be a local var file matching its supplied SHA-256")
    payload = json.loads(raw.decode("utf-8"))
    if (payload.get("status") != "passed" or payload.get("attempt") != "synthetic_docx_real_rapidocr_cpu"
            or payload.get("authorization") != "fake_allow_only"
            or payload.get("candidate_count") != 2):
        raise RuntimeError("expected passed synthetic DOCX RapidOCR result, fake auth, and two candidates")
    candidates = payload.get("full_candidates")
    source_info = payload.get("source")
    if not isinstance(candidates, list) or len(candidates) != 2 or not isinstance(source_info, dict) or source_info.get("synthetic_only") is not True:
        raise RuntimeError("two full candidates and synthetic source provenance are required")
    docx_hash = payload.get("docx_sha256")
    if (not isinstance(docx_hash, str) or len(docx_hash) != 64 or
            payload.get("independent_docx_sha256") != docx_hash):
        raise RuntimeError("DOCX snapshot hashes in the OCR result must agree")
    digest = source_info.get("original_sha256")
    if (not isinstance(digest, str) or len(digest) != 64 or
            source_info.get("original_sha256_provenance") != "computed_from_single_docx_byte_snapshot"):
        raise RuntimeError("synthetic DOCX snapshot hash provenance is incomplete")
    linked = [c for c in candidates if c.get("chunk_link_status") == "caller_asserted_unverified"]
    unlinked = [c for c in candidates if c.get("chunk_link_status") == "unlinked"]
    if len(linked) != 1 or len(unlinked) != 1:
        raise RuntimeError("expected one caller_asserted_unverified and one unlinked candidate")
    c = linked[0]
    if (c.get("status") != "candidate_unreviewed" or c.get("source_document_id") != source_info.get("source_document_id")
            or c.get("source_version") != source_info.get("source_version") or not c.get("existing_chunk_id")
            or c.get("original_sha256") != digest or digest != docx_hash
            or c.get("original_sha256_provenance") != "computed_from_single_docx_byte_snapshot"
            or c.get("page") is not None or c.get("page_status") != "unknown_requires_layout_rendering"
            or c.get("anchor_part") != "word/document.xml" or not c.get("anchor_id")
            or c.get("available_at") is None):
        raise RuntimeError("linked DOCX candidate identity, version, chunk, locator, or snapshot provenance is incomplete")
    rejected = unlinked[0]
    if rejected.get("existing_chunk_id") is not None or rejected.get("status") != "candidate_unreviewed":
        raise RuntimeError("second unlinked candidate must remain explicitly unlinked and unreviewed")
    recognized = "\n".join(row.get("text", "") for row in c.get("ordered_text_confidence", []))
    if QUERY not in recognized:
        raise RuntimeError("linked OCR text does not contain the pinned exact query phrase")
    source = {"document_id": c["source_document_id"], "chunk_id": c["existing_chunk_id"],
              "version": c["source_version"], "source_ref": "synthetic://docx/synthetic-docx-ko/document.xml",
              "incident_ids": [INCIDENT], "relation": "direct", "available_at": c["available_at"],
              "synthetic_fixture": True}
    return path, payload, c, rejected, source


def make_chunk(candidate: dict, source: dict) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "research"))
    from ocr_hybrid_synthetic_bridge_20261030 import make_ocr_chunk
    chunk = make_ocr_chunk(candidate, source)
    locator = json.loads(chunk["locator"])
    for key, expected in (("page", None), ("page_status", "unknown_requires_layout_rendering"),
                          ("anchor_id", candidate["anchor_id"]), ("bbox", candidate["region_coords"]),
                          ("coordinate_frame", "image_pixels"), ("original_sha256", candidate["original_sha256"]),
                          ("original_sha256_provenance", "computed_from_single_docx_byte_snapshot"),
                          ("page_chunk_id_provenance", "caller_asserted_mapping_unverified_against_index"),
                          ("chunk_link_status", "caller_asserted_unverified"),
                          ("mapping_verification", "unverified_against_index_or_acl"),
                          ("ocr_status", "candidate_unreviewed")):
        if locator.get(key) != expected:
            raise RuntimeError(f"DOCX locator lost required provenance: {key}")
    if not chunk["text"].startswith("[기계 OCR 미검토]"):
        raise RuntimeError("OCR chunk lost its unreviewed marker")
    return chunk


def verify_unlinked_rejected(candidate: dict, source: dict) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "research"))
    from ocr_hybrid_synthetic_bridge_20261030 import BridgeError, make_ocr_chunk
    try:
        make_ocr_chunk(candidate, source)
    except BridgeError:
        return
    raise RuntimeError("bridge unexpectedly accepted the unlinked DOCX candidate")


def model_manifest_sha256(model_path: Path) -> str:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "research"))
    from pdf_ocr_e5_hybrid_synthetic_20261030 import model_manifest_sha256 as shared_manifest_sha256
    return shared_manifest_sha256(model_path)


def distractors():
    return [{"document_id": f"synthetic-distractor-{i}", "chunk_id": f"synthetic-distractor-{i}::chunk-1",
             "version": "1", "text": f"합성 웨이퍼 스크래치 검사 기록 {i}.",
             "source_ref": f"synthetic://distractor/{i}", "locator": f"fixture:{i}", "status": "active",
             "available_at": "2026-10-29T00:00:00+00:00", "incident_ids": [INCIDENT],
             "relation": "direct", "synthetic_fixture": True} for i in (1, 2)]


def run(args) -> Path:
    if not args.run:
        raise RuntimeError("--run is required")
    from pdf_ocr_e5_hybrid_synthetic_20261030 import (
        apply_job_memory_cap, block_network, confined_var_file,
        require_windows_capacity,
    )
    input_path, payload, candidate, rejected, source = load_payload(args.input_result, args.expected_input_sha256)
    chunk = make_chunk(candidate, source)
    verify_unlinked_rejected(rejected, source)
    model_path = args.model.resolve(strict=True)
    if (not isinstance(args.expected_model_sha256, str) or len(args.expected_model_sha256) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in args.expected_model_sha256)
            or not model_path.is_dir() or model_manifest_sha256(model_path) != args.expected_model_sha256.lower()):
        raise RuntimeError("local E5 model missing or manifest SHA-256 mismatch")
    output = confined_var_file(args.output_root)
    require_windows_capacity(output, args.job_limit_mib)
    from ocr_e5_hybrid_smoke_20261030 import require_idle_model_use
    require_idle_model_use(model_path)

    chunks = [chunk, *distractors()]
    os.environ.update({name: "1" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    apply_job_memory_cap(args.job_limit_mib)
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(1); torch.manual_seed(0); torch.use_deterministic_algorithms(True)
    block_network()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(model_path, local_files_only=True, trust_remote_code=False).to("cpu").eval()

    def encode(texts):
        batch = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        with torch.no_grad():
            hidden = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
            return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().tolist()

    vectors = encode(["passage: " + c["text"] for c in chunks])
    if any(len(v) != 384 for v in vectors):
        raise RuntimeError("expected 384-dimensional E5 vectors")
    vector_map = {c["chunk_id"]: v for c, v in zip(chunks, vectors)}
    from ocr_hybrid_synthetic_bridge_20261030 import SyntheticOCRHybridIndex, validate_for_qagent_contract
    qv = encode(["query: " + QUERY])[0]
    index = SyntheticOCRHybridIndex(chunks, vector_map, authorize=lambda _scope: True)
    try:
        fts = [r[0] for r in index.db.execute("SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)", (QUERY,))]
        response = index.search(query=QUERY, query_vector=qv, incident_ids=[INCIDENT], as_of=AS_OF,
                                top_k=3, authorize=lambda _scope: True, timezone_name="UTC", similarity_threshold=0.0)
    finally:
        index.close()
    validated = validate_for_qagent_contract(response, incident_ids=[INCIDENT], as_of=AS_OF,
                                             source_kind="internal_documents", timezone_name="UTC", top_k=3)
    ids = [item["chunk_id"] for item in response["items"]]
    if chunk["chunk_id"] not in fts or chunk["chunk_id"] not in ids:
        raise RuntimeError("DOCX OCR chunk missing from FTS5 or hybrid top 3")
    output.mkdir(parents=True, exist_ok=False)
    dest = output / "result.json"
    report = {"status": "passed", "attempt": "synthetic_docx_ocr_e5_hybrid_cpu", "synthetic_only": True,
              "input_result_path": str(input_path), "input_result_sha256": args.expected_input_sha256.lower(),
              "model_directory": str(model_path), "model_manifest_sha256": args.expected_model_sha256.lower(),
              "device": "cpu", "dimensions": 384, "passage_prefix": "passage: ",
              "pooling": "attention-mask mean then L2 normalization", "source_metadata_origin": "synthetic DOCX OCR candidate",
              "source_record": source, "candidate_chunk_id": chunk["chunk_id"], "locator": json.loads(chunk["locator"]),
              "rejected_unlinked_candidate": {"anchor_id": rejected.get("anchor_id"), "chunk_link_status": "unlinked",
                                               "rejected": True, "reason": "no verified source chunk mapping"},
              "query": QUERY, "fts5_hits": fts, "hybrid_ranked_chunk_ids": ids,
              "hybrid_items": response["items"], "validated_response": validated,
              "ocr_chunk_in_fts_and_top3": True, "authorization": "fake_allow_only",
              "limitations": ["query repeats OCR text; no semantic quality claim",
                              "candidate/source mapping is caller asserted and unverified against index or ACL",
                              "DOCX page layout and source visibility are unverified; embedded-image coverage is incomplete",
                              "no actual site ACL, source indexing, production RAG, or operational validation"]}
    with dest.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2); stream.write("\n")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--input-result", type=Path, required=True)
    parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--job-limit-mib", type=int, required=True)
    args = parser.parse_args()
    if args.job_limit_mib not in JOB_CHOICES:
        parser.error("--job-limit-mib must be from 2048 through 3072 MiB")
    if not args.run:
        parser.print_help(); return 0
    try:
        print(run(args)); return 0
    except Exception as exc:
        print(f"smoke refused/failed: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
