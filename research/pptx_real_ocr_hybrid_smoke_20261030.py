"""Replay a saved synthetic real-OCR candidate through synthetic hybrid search.

The OCR result is reused from an earlier process. Search provenance, vectors,
manifest, and scope are synthetic assertions and do not establish production
RAG, ACL, or OCR timing. Matching source and image hashes do not prove that the
saved OCR text was generated from those bytes in an earlier run; this replay
cannot establish text-to-image provenance, even if report hashes are rewritten.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.pptx_ocr_hybrid_bridge_synthetic_20261030 import bind_pptx_candidate, search_bound_pptx


DEFAULT_RESULT = ROOT / "var/pptx-real-ocr-cpu-20261030-0003/result.json"
UTC = timezone.utc


class SmokeError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_candidate(result_path: Path) -> tuple[dict, dict]:
    report = json.loads(result_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("synthetic_only") is not True:
        raise SmokeError("saved OCR report must be a passed synthetic-only report")
    if report.get("candidate_count") != 1 or len(report.get("full_candidates", [])) != 1:
        raise SmokeError("exactly one saved OCR candidate is required")
    pptx = Path(report["pptx_path"]).resolve(strict=True)
    candidate = deepcopy(report["full_candidates"][0])
    actual_pptx_hash = sha256(pptx)
    if actual_pptx_hash != report.get("pptx_sha256") or actual_pptx_hash != report.get("independent_pptx_sha256"):
        raise SmokeError("source PPTX hash mismatch")
    if candidate.get("original_sha256") != actual_pptx_hash:
        raise SmokeError("candidate source snapshot hash mismatch")
    with __import__("zipfile").ZipFile(pptx) as archive:
        name = "ppt/media/image1.png"
        if name not in archive.namelist():
            raise SmokeError("expected embedded synthetic image is missing")
        image_hash = hashlib.sha256(archive.read(name)).hexdigest()
    recorded_image = report.get("sha256", {}).get("image")
    if image_hash != recorded_image or candidate.get("image_sha256") != image_hash:
        raise SmokeError("embedded image hash mismatch")
    candidate["real_ocr_report_path"] = str(result_path.resolve())
    return report, candidate


def run(result_path: Path = DEFAULT_RESULT) -> dict:
    result, _ = run_with_scope(result_path)
    return result


def run_with_scope(result_path: Path = DEFAULT_RESULT) -> tuple[dict, dict]:
    report, candidate = load_candidate(result_path)
    # This synthetic scenario date is not asserted source data.
    source_at = datetime(2026, 10, 10, 9, tzinfo=UTC)
    # These timestamps are deliberately invented for a synthetic replay, not OCR observations.
    ocr_at = datetime(2026, 10, 15, 9, tzinfo=UTC)
    embedding_at = datetime(2026, 10, 16, 9, tzinfo=UTC)
    analysis_at = datetime(2026, 10, 30, 12, tzinfo=UTC)
    as_of = "2026-10-29"
    cutoff = datetime(2026, 10, 30, tzinfo=UTC)
    source = {"document_id": candidate["source_document_id"], "chunk_id": candidate["existing_chunk_id"],
              "version": candidate["source_version"], "source_ref": "synthetic://pptx-ocr-ko",
              "incident_ids": ["INC-SYN-OCR-1"], "available_at": source_at.isoformat(),
              "status": "active", "relation": "direct", "synthetic_fixture": True}
    candidate["source_available_at"] = source_at.isoformat()
    anchor = candidate["anchor_id"]
    locator = {"locator_type": "pptx_embedded_picture", "slide_ordinal": candidate["slide_ordinal"],
               "slide_file_number": candidate["slide_file_number"], "picture_shape_id": candidate["picture_shape_id"],
               "anchor_id": anchor, "image_sha256": candidate["image_sha256"],
               "source_snapshot_sha256": candidate["original_sha256"], "image_bbox": candidate["region_coords"],
               "coordinate_frame": "image_pixels", "image_size": candidate["image_size"],
               "originating_chunk_id": source["chunk_id"],
               "ocr_confidence": [r["confidence"] for r in candidate["ordered_text_confidence"]]}
    artifacts = {
        "source_version": {"id": source["document_id"], "version": source["version"], "available_at": source_at},
        "ocr_model": {"id": "rapidocr-synthetic-asserted", "version": "local-cpu-candidate", "available_at": source_at},
        "ocr_output": {"id": "ocr-syn-real-candidate", "version": "1", "available_at": ocr_at, "generated_at": ocr_at,
                       "dependencies": {"source_version": {"id": source["document_id"], "version": source["version"]},
                                        "ocr_model": {"id": "rapidocr-synthetic-asserted", "version": "local-cpu-candidate"}}},
        "embedding_model": {"id": "vector-syn-asserted", "version": "1", "available_at": ocr_at},
        "embedding_output": {"id": "embed-syn-real-candidate", "version": "1", "available_at": embedding_at, "generated_at": embedding_at,
                             "dependencies": {"ocr_output": {"id": "ocr-syn-real-candidate", "version": "1"},
                                              "embedding_model": {"id": "vector-syn-asserted", "version": "1"}}},
        "index_snapshot": {"id": "index-syn-real-candidate", "version": "1", "available_at": embedding_at, "generated_at": embedding_at,
                           "dependencies": {"ocr_output": {"id": "ocr-syn-real-candidate", "version": "1"},
                                            "embedding_output": {"id": "embed-syn-real-candidate", "version": "1"}}},
    }
    manifest = {"provenance": "caller_asserted_unverified_synthetic_manifest", "image_sha256": candidate["image_sha256"],
                "anchor_id": anchor, "source_snapshot_sha256": candidate["original_sha256"], "candidate_available_at": None}
    for kind in ("ocr_output", "embedding_output"):
        manifest[kind] = {k: artifacts[kind][k] for k in ("id", "version", "available_at", "generated_at")}
        manifest[kind]["binding"] = {"image_sha256": candidate["image_sha256"], "anchor_id": anchor,
                                     "source_snapshot_sha256": candidate["original_sha256"]}
    chunk = bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    text = " ".join(r["text"] for r in candidate["ordered_text_confidence"])
    # Explicit synthetic vector; no embedding model is run.
    vector = [1.0, 0.0]
    result = search_bound_pptx(chunk=chunk, vectors={chunk["chunk_id"]: vector}, artifacts=artifacts,
        query=text, query_vector=vector, incident_ids=source["incident_ids"], as_of=as_of,
        historical_cutoff_exclusive=cutoff, analysis_at=analysis_at,
        authorize=lambda _: True, authorize_document=lambda _: True)
    result.update({"status": result["status"], "experiment": "saved_real_ocr_candidate_synthetic_hybrid_replay",
        "synthetic_source": True, "source_ref": source["source_ref"], "ocr_report_path": str(result_path.resolve()),
        "ocr_and_search_same_process": False, "ocr_performed_in_this_process": False,
        "ocr_candidate_time": None, "ocr_candidate_time_status": "unknown_unverified",
        "synthetic_temporal_scenario": {"source_available_at": source_at.isoformat(),
            "ocr_generated_at": ocr_at.isoformat(), "embedding_generated_at": embedding_at.isoformat(), "as_of": as_of},
        "synthetic_manifest_and_vector": True, "scope": source["incident_ids"],
        "production_rag_acl_verified": False, "source_pptx_sha256_revalidated": report["pptx_sha256"],
        "embedded_image_sha256_revalidated": candidate["image_sha256"],
        "limitations": list(result.get("limitations", [])) + ["OCR report was produced in an earlier process; this run revalidated hashes only",
            "source and image hashes do not prove saved OCR text was generated from those bytes; rewritten report hashes do not establish provenance",
            "synthetic temporal values, manifest, vector, and allow scope are assertions",
            "production RAG, ACL, real vectors, OCR timing, and search quality are unverified"]})
    return result, {"chunk": chunk, "vectors": {chunk["chunk_id"]: vector}, "artifacts": artifacts,
                    "as_of": as_of, "cutoff": cutoff, "analysis_at": analysis_at,
                    "query": text, "query_vector": vector, "source": source}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.result)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        print(payload, end="")
    if result.get("status") != "OK":
        raise SystemExit("synthetic hybrid replay did not return a hit")


if __name__ == "__main__":
    main()
