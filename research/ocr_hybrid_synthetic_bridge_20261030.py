"""Synthetic-only bridge for exploring OCR-derived chunks with hybrid retrieval.

This is an in-memory SQLite FTS5/BM25 plus caller-supplied normalized-vector
nearest-neighbor example. Its reciprocal-rank fusion is not the site's RAG.
The OCR availability timestamp is only the maximum of supplied source/OCR
candidate timestamps; actual OCR generation time is not independently known.
The vector similarity threshold is a synthetic candidate filter and does not
prove semantic relevance or validate the embedding model.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import math
import sqlite3
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class BridgeError(ValueError):
    pass


def _aware_iso(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise BridgeError(f"{name} must be timezone-aware ISO datetime")
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            raise ValueError
    except (ValueError, OverflowError) as exc:
        raise BridgeError(f"{name} must be timezone-aware ISO datetime") from exc
    return result


def _pdf_locator_fields(candidate: Mapping) -> dict:
    fields = ("page_bbox", "page_bbox_coordinate_frame", "page_rotation_degrees",
              "visibility_status", "original_sha256", "original_sha256_provenance",
              "page_chunk_id_provenance")
    present = [key for key in fields if key in candidate]
    if not present:
        return {}
    if len(present) != len(fields):
        raise BridgeError("PDF locator metadata bundle is incomplete")
    bbox = candidate["page_bbox"]
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox) or
            bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise BridgeError("PDF page bounding box is invalid")
    frame = candidate["page_bbox_coordinate_frame"]
    if not isinstance(frame, str) or not frame.strip():
        raise BridgeError("PDF page bounding box coordinate frame is required")
    rotation = candidate["page_rotation_degrees"]
    if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation) or rotation not in (0, 90, 180, 270):
        raise BridgeError("PDF page rotation must be 0, 90, 180, or 270 degrees")
    if not isinstance(candidate["visibility_status"], str) or not candidate["visibility_status"].strip():
        raise BridgeError("PDF visibility status is required")
    digest = candidate["original_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise BridgeError("original_sha256 must be a SHA-256 hex digest")
    if candidate["original_sha256_provenance"] != "caller_asserted_unverified" or candidate["page_chunk_id_provenance"] != "caller_asserted_mapping_unverified_against_index":
        raise BridgeError("PDF provenance must remain caller_asserted and unverified")
    return {key: (list(candidate[key]) if key == "page_bbox" else candidate[key]) for key in fields}


def _rendered_page_locator_fields(candidate: Mapping) -> dict:
    keys = ("page_rect_points", "page_cropbox_points", "page_rotation_degrees", "render_dpi",
            "pixmap_irect", "derotation_matrix", "rendered_page_pixels",
            "original_sha256", "original_sha256_provenance", "page_chunk_id_provenance")
    present = [key for key in keys if key in candidate]
    if not present:
        return {}
    if len(present) != len(keys):
        raise BridgeError("rendered-page locator metadata bundle is incomplete")

    def numbers(value, length, name, *, integers=False):
        if not isinstance(value, (list, tuple)) or len(value) != length:
            raise BridgeError(f"{name} has invalid format")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or
               (integers and not isinstance(v, int)) for v in value):
            raise BridgeError(f"{name} must contain finite {'integer' if integers else 'numeric'} values")
        return list(value)

    rect = numbers(candidate["page_rect_points"], 4, "page_rect_points")
    crop = numbers(candidate["page_cropbox_points"], 4, "page_cropbox_points")
    pix = numbers(candidate["pixmap_irect"], 4, "pixmap_irect", integers=True)
    matrix = numbers(candidate["derotation_matrix"], 6, "derotation_matrix")
    for name, box in (("page_rect_points", rect), ("page_cropbox_points", crop)):
        if box[0] >= box[2] or box[1] >= box[3]:
            raise BridgeError(f"{name} bounds are invalid")
    if pix[0] >= pix[2] or pix[1] >= pix[3]:
        raise BridgeError("pixmap_irect bounds are invalid")
    rotation, dpi = candidate["page_rotation_degrees"], candidate["render_dpi"]
    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation not in (0, 90, 180, 270):
        raise BridgeError("page rotation must be 0, 90, 180, or 270 degrees")
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not math.isfinite(dpi) or dpi <= 0:
        raise BridgeError("render_dpi must be finite and positive")
    dims = candidate["rendered_page_pixels"]
    if not isinstance(dims, Mapping) or set(dims) != {"width", "height"}:
        raise BridgeError("rendered_page_pixels dimensions are invalid")
    width, height = dims["width"], dims["height"]
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (width, height)):
        raise BridgeError("rendered_page_pixels dimensions must be positive integers")
    if width != pix[2] - pix[0] or height != pix[3] - pix[1]:
        raise BridgeError("rendered_page_pixels dimensions do not match pixmap_irect")
    digest = candidate["original_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise BridgeError("original_sha256 must be a SHA-256 hex digest")
    if candidate["original_sha256_provenance"] != "computed_from_single_pdf_byte_snapshot" or candidate["page_chunk_id_provenance"] != "caller_asserted_mapping_unverified_against_index":
        raise BridgeError("rendered-page provenance is unknown or unverified")
    return {"page_rect_points": rect, "page_cropbox_points": crop,
            "page_rotation_degrees": rotation, "render_dpi": dpi, "pixmap_irect": pix,
            "derotation_matrix": matrix, "rendered_page_pixels": dict(dims),
            "original_sha256": digest,
            "original_sha256_provenance": candidate["original_sha256_provenance"],
            "page_chunk_id_provenance": candidate["page_chunk_id_provenance"],
            "pixel_to_original_page_transform_accuracy": "unverified",
            "annotations": "excluded",
            "crop_limitations": "partial_page_crop_may_omit_context"}


def _docx_locator_fields(candidate: Mapping) -> dict:
    """Validate the narrow unresolved-layout DOCX anchor candidate contract."""
    if candidate.get("page") is not None or candidate.get("page_status") != "unknown_requires_layout_rendering":
        raise BridgeError("DOCX page must remain unknown until layout rendering")
    if candidate.get("anchor_part") != "word/document.xml":
        raise BridgeError("DOCX anchor part is invalid")
    ordinal = candidate.get("anchor_ordinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 1 <= ordinal <= 1_000_000:
        raise BridgeError("DOCX anchor ordinal is invalid")
    anchor = candidate.get("anchor_id")
    region = candidate.get("region_id")
    expected = f"word/document.xml#drawing-{ordinal}"
    if anchor != expected or region != expected:
        raise BridgeError("DOCX anchor identity is invalid")
    if candidate.get("coordinate_frame") != "image_pixels":
        raise BridgeError("DOCX coordinate frame must be image_pixels")
    if candidate.get("original_sha256_provenance") != "computed_from_single_docx_byte_snapshot":
        raise BridgeError("DOCX hash provenance is invalid")
    if candidate.get("chunk_link_status") != "caller_asserted_unverified":
        raise BridgeError("DOCX source chunk mapping must be caller asserted and unverified")
    bbox = candidate.get("region_coords")
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1_000_000_000 for v in bbox) or
            bbox[0] < 0 or bbox[1] < 0 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise BridgeError("DOCX image pixel bounding box is invalid")
    digest = candidate.get("original_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise BridgeError("DOCX original_sha256 must be a SHA-256 hex digest")
    if candidate.get("visibility_status", "unverified") != "unverified":
        raise BridgeError("DOCX visibility must remain unverified")
    if not isinstance(candidate.get("existing_chunk_id"), str) or not candidate["existing_chunk_id"].strip():
        raise BridgeError("DOCX candidate must have a caller-mapped source chunk")
    return {"page": None, "page_status": "unknown_requires_layout_rendering",
            "anchor_part": "word/document.xml", "anchor_id": anchor, "anchor_ordinal": ordinal,
            "region_id": region, "bbox": list(bbox), "coordinate_frame": "image_pixels",
            "original_sha256": digest,
            "original_sha256_provenance": "computed_from_single_docx_byte_snapshot",
            "visibility_status": "unverified", "page_chunk_id_provenance": "caller_asserted_mapping_unverified_against_index",
            "chunk_link_status": "caller_asserted_unverified",
            "mapping_verification": "unverified_against_index_or_acl"}


def make_ocr_chunk(candidate: Mapping, source: Mapping) -> dict:
    """Create a separate unreviewed OCR chunk, preserving source provenance."""
    is_docx = isinstance(candidate, Mapping) and candidate.get("anchor_part") == "word/document.xml"
    required = ("source_document_id", "source_version", "region_id",
                "region_coords", "image_sha256", "available_at", "existing_chunk_id",
                "ordered_text_confidence", "status")
    if not isinstance(candidate, Mapping) or any(candidate.get(k) is None for k in required) or (not is_docx and candidate.get("page") is None):
        raise BridgeError("OCR candidate metadata is incomplete")
    if candidate["status"] != "candidate_unreviewed":
        raise BridgeError("OCR candidate must remain unreviewed")
    if not isinstance(source, Mapping) or any(source.get(k) is None for k in
            ("document_id", "chunk_id", "version", "source_ref", "incident_ids", "available_at")):
        raise BridgeError("originating chunk metadata is incomplete")
    if source["document_id"] != candidate["source_document_id"] or source["version"] != candidate["source_version"] or source["chunk_id"] != candidate["existing_chunk_id"]:
        raise BridgeError("OCR candidate does not link to the supplied originating chunk")
    ocr_available = _aware_iso(candidate["available_at"], "OCR available_at")
    source_available = _aware_iso(source["available_at"], "source available_at")
    if not isinstance(source["incident_ids"], (list, tuple)) or not source["incident_ids"]:
        raise BridgeError("originating incident_ids are required")
    if not isinstance(candidate["region_coords"], (list, tuple)) or len(candidate["region_coords"]) != 4:
        raise BridgeError("OCR bounding box must have four coordinates")
    rows = candidate["ordered_text_confidence"]
    if not isinstance(rows, list) or not rows or any(not isinstance(r, Mapping) or not isinstance(r.get("text"), str) or not r["text"].strip() or isinstance(r.get("confidence"), bool) or not isinstance(r.get("confidence"), (float, int)) or not 0 <= r["confidence"] <= 1 for r in rows):
        raise BridgeError("OCR text/confidence regions are invalid")
    text = "[기계 OCR 미검토]\n" + "\n".join(r["text"] for r in rows)
    frame = candidate.get("coordinate_frame", "image_pixels")
    if frame not in ("image_pixels", "rendered_page_pixels"):
        raise BridgeError("OCR coordinate frame is unknown")
    if not isinstance(candidate["region_coords"], (list, tuple)) or len(candidate["region_coords"]) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in candidate["region_coords"]):
        raise BridgeError("OCR bounding box must have four finite coordinates")
    if candidate["region_coords"][0] >= candidate["region_coords"][2] or candidate["region_coords"][1] >= candidate["region_coords"][3]:
        raise BridgeError("OCR bounding box bounds are invalid")
    provenance = {"page": candidate["page"], "region_id": candidate["region_id"],
                  "bbox": list(candidate["region_coords"]), "coordinate_frame": frame,
                  "image_sha256": candidate["image_sha256"], "originating_chunk_id": source["chunk_id"],
                  "ocr_status": "candidate_unreviewed", "ocr_confidence": [float(r["confidence"]) for r in rows]}
    if is_docx:
        docx_fields = _docx_locator_fields(candidate)
        provenance.update(docx_fields)
        provenance["ocr_confidence"] = [float(r["confidence"]) for r in rows]
    elif frame == "rendered_page_pixels":
        provenance.update(_rendered_page_locator_fields(candidate))
    else:
        provenance.update(_pdf_locator_fields(candidate))
    if frame == "rendered_page_pixels":
        if not provenance.get("rendered_page_pixels"):
            raise BridgeError("rendered-page coordinate frame requires rendered-page metadata")
        if (candidate["region_coords"][0] < 0 or candidate["region_coords"][1] < 0 or
                candidate["region_coords"][2] > provenance["rendered_page_pixels"]["width"] or
                candidate["region_coords"][3] > provenance["rendered_page_pixels"]["height"]):
            raise BridgeError("rendered-page pixel bounding box exceeds page dimensions")
    return {
        "document_id": source["document_id"],
        "chunk_id": f"{source['chunk_id']}::ocr:{candidate['anchor_id']}" if is_docx else f"{source['chunk_id']}::ocr:{candidate['page']}:{candidate['region_id']}",
        "version": source["version"], "text": text,
        "source_ref": source["source_ref"],
        "locator": json.dumps(provenance, ensure_ascii=False, sort_keys=True),
        "status": "candidate_unreviewed", "available_at": max(source_available, ocr_available).isoformat(),
        "source_available_at": source_available.isoformat(),
        "derivative_available_at": ocr_available.isoformat(),
        "incident_ids": list(source["incident_ids"]), "relation": source.get("relation", "direct"),
        "score": 0.0, "observed_at": source.get("observed_at"),
        "effective_from": source.get("effective_from"), "effective_to": source.get("effective_to"),
        "applicability": source.get("applicability"),
        "ocr_status": "candidate_unreviewed", "ocr_confidence": provenance["ocr_confidence"],
        "originating_chunk_id": source["chunk_id"],
        "synthetic_fixture": source.get("synthetic_fixture") is True,
        "retrieval_score_note": "similarity threshold is a synthetic filter, not relevance validation",
    }


class SyntheticOCRHybridIndex:
    """Disposable synthetic index. No persistence, model loading, or networking."""
    def __init__(self, chunks: Sequence[Mapping], vectors: Mapping[str, Sequence[float]], *,
                 authorize: Callable[[Mapping], bool] | None):
        if authorize is None or not callable(authorize):
            raise BridgeError("trusted authorization callback is required before indexing")
        if not isinstance(chunks, (list, tuple)) or not chunks or any(not isinstance(c, Mapping) or c.get("synthetic_fixture") is not True or not str(c.get("source_ref", "")).startswith("synthetic://") for c in chunks):
            raise BridgeError("only explicitly marked synthetic fixtures may be indexed")
        try:
            decision = authorize({"action": "index_synthetic_fixtures", "chunk_ids": [c.get("chunk_id") for c in chunks]})
        except Exception as exc:
            raise BridgeError("index authorization decision failed") from exc
        if decision is not True:
            raise BridgeError("index authorization denied")
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE docs USING fts5(chunk_id UNINDEXED, text)")
        self.chunks = {}
        self.vectors = {}
        dimension = None
        for chunk in chunks:
            cid, text = chunk.get("chunk_id"), chunk.get("text")
            if not isinstance(cid, str) or not cid or cid in self.chunks or not isinstance(text, str) or not text.strip():
                raise BridgeError("each synthetic chunk needs unique chunk_id and text")
            incident_ids = chunk.get("incident_ids")
            if (not isinstance(incident_ids, (list, tuple)) or not incident_ids or
                    any(not isinstance(incident_id, str) or not incident_id.strip() for incident_id in incident_ids)):
                raise BridgeError("each synthetic chunk requires a list of non-empty incident IDs")
            vec = vectors.get(cid)
            if not isinstance(vec, (list, tuple)) or not vec:
                raise BridgeError("every chunk requires a supplied normalized vector")
            vals = tuple(float(v) for v in vec)
            norm = math.sqrt(sum(v * v for v in vals))
            if any(not math.isfinite(v) for v in vals) or abs(norm - 1.0) > 1e-5:
                raise BridgeError("vectors must be finite and normalized")
            dimension = dimension or len(vals)
            if len(vals) != dimension:
                raise BridgeError("vector dimensions must match")
            self.chunks[cid], self.vectors[cid] = dict(chunk), vals
            self.db.execute("INSERT INTO docs VALUES (?, ?)", (cid, text))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def search(self, *, query: str, query_vector: Sequence[float], incident_ids: Sequence[str],
               as_of: str, top_k: int, authorize: Callable[[Mapping], bool] | None,
               timezone_name: str, similarity_threshold: float, rrf_k: int = 60) -> dict:
        if authorize is None or not callable(authorize):
            raise BridgeError("trusted authorization callback is required")
        if (not isinstance(incident_ids, (list, tuple)) or not incident_ids or
                any(not isinstance(x, str) or not x.strip() for x in incident_ids)):
            raise BridgeError("incident scope must contain non-empty IDs")
        scope = set(incident_ids)
        if len(scope) != len(incident_ids):
            raise BridgeError("incident scope must contain non-empty IDs")
        try:
            cutoff = date.fromisoformat(as_of)
            if cutoff.isoformat() != as_of: raise ValueError
        except (TypeError, ValueError):
            raise BridgeError("as_of must be an ISO date")
        try: zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc: raise BridgeError("timezone_name must identify a ZoneInfo timezone") from exc
        if isinstance(similarity_threshold, bool) or not isinstance(similarity_threshold, (float, int)) or not math.isfinite(similarity_threshold) or not -1 <= similarity_threshold <= 1:
            raise BridgeError("similarity_threshold must be finite and between -1 and 1")
        if not isinstance(query, str) or not query.strip() or isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise BridgeError("query and top_k are invalid")
        qv = tuple(float(v) for v in query_vector)
        if not self.vectors or len(qv) != len(next(iter(self.vectors.values()))) or any(not math.isfinite(v) for v in qv) or abs(math.sqrt(sum(v*v for v in qv))-1) > 1e-5:
            raise BridgeError("query vector must be finite, normalized, and dimension-matched")
        auth_scope = {"incident_ids": sorted(scope), "as_of": as_of}
        try: decision = authorize(auth_scope)
        except Exception as exc: raise BridgeError("authorization decision failed") from exc
        if decision is not True: raise BridgeError("authorization denied")
        eligible = {}
        for cid, chunk in self.chunks.items():
            if not all(k in chunk for k in ("document_id", "version", "source_ref", "locator", "status", "available_at", "incident_ids")):
                continue
            try: available = _aware_iso(chunk["available_at"], "available_at")
            except BridgeError: continue
            cutoff_utc = datetime.combine(cutoff + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
            if available.astimezone(timezone.utc) >= cutoff_utc or not scope.intersection(chunk["incident_ids"]): continue
            eligible[cid] = chunk
        bm25_ids = []
        # FTS MATCH syntax errors (e.g. unmatched quote) fail closed.
        try:
            bm25_ids = [row[0] for row in self.db.execute("SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)", (query,)) if row[0] in eligible]
        except sqlite3.OperationalError as exc:
            raise BridgeError("invalid FTS query") from exc
        vector_scores = {cid: sum(a*b for a,b in zip(qv, self.vectors[cid])) for cid in eligible}
        vector_ids = sorted((cid for cid, score in vector_scores.items() if score >= similarity_threshold),
                            key=lambda cid: (-vector_scores[cid], cid))
        ranks = {}
        for rank, cid in enumerate(bm25_ids, 1): ranks[cid] = ranks.get(cid, 0) + 1 / (rrf_k + rank)
        for rank, cid in enumerate(vector_ids, 1): ranks[cid] = ranks.get(cid, 0) + 1 / (rrf_k + rank)
        full_ranked = sorted(ranks, key=lambda cid: (-ranks[cid], cid))
        ranked = full_ranked[:top_k]
        items = []
        for cid in ranked:
            item = dict(eligible[cid]); item["score"] = ranks[cid]; items.append(item)
        return {"status": "OK" if items else "NO_MATCH", "retrieval_method": "bm25_vector_hybrid",
                "as_of": as_of, "truncated": len(full_ranked) > top_k, "candidate_count": len(full_ranked), "items": items,
                "synthetic_only": True, "fusion": "reciprocal_rank_fusion_local_example",
                "limitations": ["ocr_generation_time_unverified", "vector_threshold_is_not_relevance_proof",
                                "synthetic_fusion_is_not_site_rag"]}


def adapt_ocr_item_for_contract(item: Mapping) -> dict:
    """Convert a structurally consistent explicit OCR chunk; provenance is unverified."""
    item = dict(item)
    if item.get("ocr_status") != "candidate_unreviewed":
        return item
    try:
        locator = json.loads(item["locator"])
        origin_id = item["originating_chunk_id"]
        source_at = _aware_iso(item["source_available_at"], "source_available_at")
        derivative_at = _aware_iso(item["derivative_available_at"], "derivative_available_at")
        indexed_at = _aware_iso(item["available_at"], "available_at")
    except (KeyError, TypeError, json.JSONDecodeError, BridgeError) as exc:
        raise BridgeError("OCR marker provenance or timestamps are incomplete") from exc
    if (not isinstance(origin_id, str) or not origin_id.strip() or
            not isinstance(locator, dict) or
            locator.get("originating_chunk_id") != origin_id or
            locator.get("ocr_status") != "candidate_unreviewed" or
            not isinstance(locator.get("region_id"), str) or not locator["region_id"].strip() or
            not isinstance(item.get("chunk_id"), str) or not item["chunk_id"].strip()):
        raise BridgeError("OCR marker provenance fields are inconsistent")
    expected_ready = max(source_at, derivative_at)
    if indexed_at.astimezone(timezone.utc) != expected_ready.astimezone(timezone.utc):
        raise BridgeError("OCR retrieval available_at must equal max(source, derivative)")
    item["content_kind"] = "image_ocr"
    item["available_at"] = item["source_available_at"]
    return item


def validate_for_qagent_contract(response: dict, *, incident_ids: Sequence[str], as_of: str,
                                 source_kind: str = "internal_documents", timezone_name: str = "UTC", top_k: int = 10,
                                 require_content_kind: bool = False):
    """Adapt explicit OCR chunks; structural consistency is not provenance verification."""
    from app.document_evidence_contract import validate_hybrid_response
    adapted = dict(response)
    adapted["items"] = [adapt_ocr_item_for_contract(item) for item in response.get("items", [])]
    return validate_hybrid_response(adapted, source_kind=source_kind, incident_ids=list(incident_ids),
        as_of=as_of, timezone_name=timezone_name, top_k=top_k,
        allowed_statuses=["active", "candidate_unreviewed"], require_content_kind=require_content_kind)
