"""Synthetic-only FTS5/BM25 smoke over prior OCR output; no model is loaded."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
OCR_RESULT = ROOT / "var/ocr-adapter-smoke-20261030-v2/result.json"
OUTPUT = ROOT / "var/ocr-lexical-synthetic-smoke-20261030"
INCIDENT = "synthetic-ocr-lexical-incident"
AS_OF = "2026-10-30"


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"output already exists: {OUTPUT}")
    payload = json.loads(OCR_RESULT.read_text(encoding="utf-8"))
    if payload.get("status") != "passed" or payload.get("synthetic_inputs_only") is not True:
        raise RuntimeError("prior OCR result is not passed and synthetic-only")
    candidate = payload["outputs"][0]["candidate"]
    observed = "".join(row["text"] for row in candidate["ordered_text_confidence"])
    if candidate.get("source_document_id") != "synthetic-ko-document" or observed != "합성OCR테스트입니다" or candidate.get("status") != "candidate_unreviewed":
        raise RuntimeError("unexpected synthetic Korean OCR text, source, or review status")

    sys.path.insert(0, str(ROOT / "research"))
    from ocr_hybrid_synthetic_bridge_20261030 import make_ocr_chunk

    source = {
        "document_id": "synthetic-source-document-ko",
        "chunk_id": "synthetic-source-chunk-ko",
        "version": "synthetic-v1",
        "source_ref": "synthetic://invented/ocr-ko/page-1",
        "incident_ids": [INCIDENT],
        "available_at": "2026-10-29T00:00:00+00:00",
        "synthetic_fixture": True,
    }
    candidate_for_bridge = dict(candidate)
    candidate_for_bridge["source_document_id"] = source["document_id"]
    candidate_for_bridge["source_version"] = source["version"]
    candidate_for_bridge["existing_chunk_id"] = source["chunk_id"]
    chunk = make_ocr_chunk(candidate_for_bridge, source)
    distractor = {
        "document_id": "synthetic-distractor",
        "chunk_id": "synthetic-distractor::chunk-1",
        "version": "1",
        "text": "합성 웨이퍼 가장자리 스크래치 점검 기록입니다.",
        "source_ref": "synthetic://distractor/1",
        "locator": "fixture:1",
        "status": "active",
        "available_at": "2026-10-29T00:00:00+00:00",
        "incident_ids": [INCIDENT],
        "synthetic_fixture": True,
    }
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(chunk_id UNINDEXED, text)")
    for item in (chunk, distractor):
        conn.execute("INSERT INTO docs VALUES (?, ?)", (item["chunk_id"], item["text"]))
    query = '"OCR테스트입니다"'
    ranked = [
        {"chunk_id": row[0], "bm25": row[1]}
        for row in conn.execute(
            "SELECT chunk_id, bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)",
            (query,),
        )
    ]
    conn.close()
    target_rank = next((i for i, row in enumerate(ranked, 1) if row["chunk_id"] == chunk["chunk_id"]), None)
    if target_rank != 1:
        raise RuntimeError(f"OCR chunk did not rank first: {ranked}")

    locator = json.loads(chunk["locator"])
    available = datetime.fromisoformat(chunk["available_at"]).astimezone(timezone.utc)
    result = {
        "status": "passed",
        "synthetic_only": True,
        "retrieval_method": "fts5_bm25_only",
        "model_loaded": False,
        "query": query,
        "candidate_chunk_id": chunk["chunk_id"],
        "candidate_rank": target_rank,
        "ranked_chunk_ids": [row["chunk_id"] for row in ranked],
        "locator": {key: locator[key] for key in ("page", "region_id", "image_sha256")},
        "candidate_status": chunk["status"],
        "source_lineage": {
            "source_document_id": chunk["document_id"],
            "originating_chunk_id": chunk["originating_chunk_id"],
            "source_ref": chunk["source_ref"],
            "incident_scope": chunk["incident_ids"],
            "source_metadata_origin": "invented_synthetic_fixture",
        },
        "as_of": AS_OF,
        "available_at_utc": available.isoformat(),
        "limitations": [
            "synthetic OCR result and invented source metadata only",
            "FTS5/BM25 lexical retrieval only; no vectors or semantic captions",
            "no production ACL, site RAG, or index behavior validated",
            "OCR candidate remains unreviewed",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    with (OUTPUT / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(OUTPUT / "result.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke refused/failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
