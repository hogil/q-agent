"""Opt-in local E5/FTS5 smoke over one synthetic rendered-page OCR result."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(r"D:\project\q-agent-models\var\weights\multilingual-e5-small-v1")
INCIDENT = "synthetic-rendered-page-e5-incident"
AS_OF = "2026-10-30"
EXPECTED_TEXT = ("SYNTHETIC OCR TEST 2026", "VECTOR TEXT TEST 2026")
_JOB_HANDLES = []


def validate_pdf_provenance(candidate: dict, pdf_source: dict) -> None:
    if (not isinstance(candidate.get("original_sha256"), str)
            or candidate.get("original_sha256") != pdf_source.get("original_sha256")
            or candidate.get("original_sha256_provenance") != "computed_from_single_pdf_byte_snapshot"
            or pdf_source.get("original_sha256_provenance") != "computed_from_single_pdf_byte_snapshot"
            or candidate.get("page_chunk_id_provenance") != "caller_asserted_mapping_unverified_against_index"
            or pdf_source.get("page_chunk_mapping_provenance") != "caller_asserted_mapping_unverified_against_index"):
        raise RuntimeError("candidate/PDF source hash or unverified provenance contract mismatch")


def load_payload(pdf_result: Path, expected_sha: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "research"))
    from pdf_ocr_e5_hybrid_synthetic_20261030 import confined_var_file, sha256_file
    path = confined_var_file(pdf_result).resolve(strict=True)
    if not path.is_file() or sha256_file(path) != expected_sha.lower():
        raise RuntimeError("PDF result must be a local var file matching its caller-supplied SHA-256")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("status") != "passed" or payload.get("attempt") != "synthetic_pdf_rendered_page_real_rapidocr_cpu"
            or payload.get("synthetic_only") is not True or payload.get("authorization") != "fake_allow_only"
            or payload.get("candidate_count") != 1):
        raise RuntimeError("expected passed synthetic-only rendered-page OCR, fake authorization, and one candidate")
    candidates = payload.get("full_candidates")
    pdf_source = payload.get("pdf_source")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(pdf_source, dict) or pdf_source.get("synthetic_only") is not True:
        raise RuntimeError("one synthetic candidate and synthetic PDF source are required")
    c = candidates[0]
    validate_pdf_provenance(c, pdf_source)
    if (c.get("status") != "candidate_unreviewed" or c.get("source_document_id") != pdf_source.get("source_document_id")
            or c.get("source_version") != pdf_source.get("source_version") or c.get("existing_chunk_id") is None
            or c.get("available_at") is None):
        raise RuntimeError("candidate source identity, version, chunk, status, or availability is incomplete")
    recognized = "\n".join(row.get("text", "") for row in c.get("ordered_text_confidence", []))
    if any(text not in recognized for text in EXPECTED_TEXT):
        raise RuntimeError("synthetic OCR candidate does not contain both pinned query strings")
    source = {"document_id": c["source_document_id"], "chunk_id": c["existing_chunk_id"],
              "version": c["source_version"], "source_ref": f"synthetic://pdf/{c['source_document_id']}/page-{c['page']}",
              "incident_ids": [INCIDENT], "relation": "direct", "available_at": c["available_at"],
              "synthetic_fixture": True}
    return path, payload, c, source


def smoke_contract(pdf_result: Path, expected_sha: str) -> dict:
    """Model-less contract/locator check; deliberately does no embedding or search."""
    _, _, candidate, source = load_payload(pdf_result, expected_sha)
    sys.path.insert(0, str(ROOT / "research"))
    from ocr_hybrid_synthetic_bridge_20261030 import (
        SyntheticOCRHybridIndex, make_ocr_chunk, validate_for_qagent_contract,
    )
    chunk = make_ocr_chunk(candidate, source)
    locator = json.loads(chunk["locator"])
    keys = ("page_rect_points", "page_cropbox_points", "page_rotation_degrees", "render_dpi", "pixmap_irect",
            "derotation_matrix", "rendered_page_pixels", "original_sha256", "original_sha256_provenance",
            "page_chunk_id_provenance")
    if any(locator.get(k) != candidate.get(k) for k in keys):
        raise RuntimeError("rendered-page locator provenance did not survive make_ocr_chunk")
    if locator.get("bbox") != candidate.get("region_coords") or locator.get("coordinate_frame") != "rendered_page_pixels":
        raise RuntimeError("OCR crop locator did not preserve rendered-page pixel coordinates")
    distractors = [
        {"document_id": f"synthetic-distractor-{i}", "chunk_id": f"synthetic-distractor-{i}::chunk-1", "version": "1",
         "text": f"합성 웨이퍼 스크래치 검사 기록 {i}.", "source_ref": f"synthetic://distractor/{i}", "locator": f"fixture:{i}",
         "status": "active", "available_at": "2026-10-29T00:00:00+00:00", "incident_ids": [INCIDENT],
         "relation": "direct", "synthetic_fixture": True} for i in (1, 2)]
    chunks = [chunk, *distractors]
    # Identical normalized vectors are only a deterministic mechanics fixture;
    # they are not generated by or evidence for E5.
    vectors = {item["chunk_id"]: [1.0] + [0.0] * 383 for item in chunks}
    authorize = lambda _scope: True
    checked = []
    for query in EXPECTED_TEXT[::-1]:
        index = SyntheticOCRHybridIndex(chunks, vectors, authorize=authorize)
        try:
            fts = [r[0] for r in index.db.execute("SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)", (query,))]
            response = index.search(query=query, query_vector=vectors[chunk["chunk_id"]], incident_ids=[INCIDENT],
                as_of=AS_OF, top_k=3, authorize=authorize, timezone_name="UTC", similarity_threshold=0.0)
        finally:
            index.close()
        validated = validate_for_qagent_contract(response, incident_ids=[INCIDENT], as_of=AS_OF,
            source_kind="internal_documents", timezone_name="UTC", top_k=3)
        ids = [item["chunk_id"] for item in response["items"]]
        if chunk["chunk_id"] not in fts or chunk["chunk_id"] not in ids:
            raise RuntimeError(f"model-less bridge search missed OCR chunk for {query!r}")
        checked.append({"query": query, "fts5_hits": fts, "hybrid_ranked_chunk_ids": ids, "validated_response": validated})
    return {"status": "passed", "chunk_id": chunk["chunk_id"], "locator": locator,
            "source_available_at": source["available_at"], "search_contract_checks": checked, "model_loaded": False}


def run(args) -> Path:
    if not args.run:
        raise RuntimeError("--run is required")
    from pdf_ocr_e5_hybrid_synthetic_20261030 import (
        apply_job_memory_cap, block_network, confined_var_file, model_manifest_sha256,
        require_windows_capacity,
    )
    pdf_result, payload, candidate, source = load_payload(args.pdf_result, args.expected_pdf_sha256)
    model_path = args.model.resolve(strict=True)
    if not model_path.is_dir() or model_manifest_sha256(model_path) != args.expected_model_sha256.lower():
        raise RuntimeError("local model directory missing or manifest SHA-256 mismatch")
    output = confined_var_file(args.output_root)
    require_windows_capacity(output, args.job_limit_mib)
    from ocr_e5_hybrid_smoke_20261030 import require_idle_model_use
    require_idle_model_use(model_path)
    sys.path.insert(0, str(ROOT / "research"))
    from ocr_hybrid_synthetic_bridge_20261030 import make_ocr_chunk, SyntheticOCRHybridIndex, validate_for_qagent_contract
    ocr_chunk = make_ocr_chunk(candidate, source)
    distractors = [
        {"document_id": f"synthetic-distractor-{i}", "chunk_id": f"synthetic-distractor-{i}::chunk-1", "version": "1",
         "text": f"합성 웨이퍼 스크래치 검사 기록 {i}.", "source_ref": f"synthetic://distractor/{i}", "locator": f"fixture:{i}",
         "status": "active", "available_at": "2026-10-29T00:00:00+00:00", "incident_ids": [INCIDENT],
         "relation": "direct", "synthetic_fixture": True} for i in (1, 2)]
    chunks = [ocr_chunk, *distractors]
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
    if any(len(v) != 384 for v in vectors): raise RuntimeError("expected 384-dimensional E5 vectors")
    vector_map = {c["chunk_id"]: v for c, v in zip(chunks, vectors)}
    authorize = lambda _scope: True
    results = []
    for query in EXPECTED_TEXT[::-1]:
        qv = encode(["query: " + query])[0]
        index = SyntheticOCRHybridIndex(chunks, vector_map, authorize=authorize)
        try:
            fts = [r[0] for r in index.db.execute("SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)", (query,))]
            response = index.search(query=query, query_vector=qv, incident_ids=[INCIDENT], as_of=AS_OF, top_k=3,
                authorize=authorize, timezone_name="UTC", similarity_threshold=0.0)
        finally: index.close()
        validated = validate_for_qagent_contract(response, incident_ids=[INCIDENT], as_of=AS_OF,
            source_kind="internal_documents", timezone_name="UTC", top_k=3)
        ids = [item["chunk_id"] for item in response["items"]]
        if ocr_chunk["chunk_id"] not in fts or ocr_chunk["chunk_id"] not in ids:
            raise RuntimeError(f"OCR candidate missing from FTS or top 3 for query {query!r}")
        results.append({"query": query, "query_prefix": "query: ", "fts5_hits": fts,
                        "hybrid_ranked_chunk_ids": ids, "hybrid_items": response["items"], "validated_response": validated})
    output.mkdir(parents=True, exist_ok=False)
    dest = output / "result.json"
    report = {"status": "passed", "attempt": "synthetic_pdf_rendered_page_ocr_e5_hybrid_cpu", "synthetic_only": True,
        "pdf_result_path": str(pdf_result), "pdf_result_sha256": args.expected_pdf_sha256.lower(),
        "model_directory": str(model_path), "model_manifest_sha256": args.expected_model_sha256.lower(),
        "device": "cpu", "dimensions": 384, "passage_prefix": "passage: ",
        "pooling": "attention-mask mean then L2 normalization", "source_metadata_origin": "synthetic OCR candidate",
        "source_record": source, "candidate_chunk_id": ocr_chunk["chunk_id"], "locator": json.loads(ocr_chunk["locator"]),
        "queries": results, "both_queries_found_ocr_chunk_in_fts_and_top3": True, "authorization": "fake_allow_only",
        "limitations": ["identical OCR text is repeated verbatim in queries; no semantic quality claim",
            "pixel-to-original-page coordinate precision is unverified", "OCR coverage is incomplete and unverified",
            "no ACL, production RAG, or operational validation"]}
    with dest.open("x", encoding="utf-8") as stream: json.dump(report, stream, ensure_ascii=False, indent=2); stream.write("\n")
    return dest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", action="store_true"); p.add_argument("--pdf-result", type=Path, required=True)
    p.add_argument("--expected-pdf-sha256", required=True); p.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    p.add_argument("--expected-model-sha256", required=True); p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--job-limit-mib", type=int, choices=range(2048, 3073), required=True)
    args = p.parse_args()
    if not args.run: p.print_help(); return 0
    try: print(run(args)); return 0
    except Exception as exc: print(f"smoke refused/failed: {exc}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
