"""Synthetic-only PPTX picture OCR binding and temporal hybrid replay.

The source chunk mapping and OCR/embedding lineage are caller assertions. This
module does not establish an internal index, model, ACL, or OCR quality fact.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
import re
from typing import Callable, Mapping, Sequence

from app.document_evidence_contract import validate_hybrid_response
from research.ocr_temporal_scoped_hybrid_20261030 import search_scoped_temporal


class PPTXBridgeError(ValueError):
    pass


def _time(value, name):
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise PPTXBridgeError(f"{name} must be a timezone-aware datetime") from None


def _sha(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PPTXBridgeError(f"{name} must be a lowercase SHA-256 digest")


_LOCATOR_KEYS = {"locator_type", "slide_ordinal", "slide_file_number", "picture_shape_id",
                 "anchor_id", "image_sha256", "source_snapshot_sha256", "image_bbox",
                 "coordinate_frame", "image_size", "originating_chunk_id", "ocr_confidence"}


def _same_instant(left, right):
    from datetime import timezone
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def bind_pptx_candidate(candidate: Mapping, source: Mapping, *, locator: Mapping,
                        artifacts: Mapping[str, Mapping], manifest: Mapping) -> dict:
    """Bind one extracted picture candidate to its caller-mapped source chunk.

    ``locator`` is a separate JSON-ready structure and deliberately contains no
    PDF-like page field. The OCR and embedding records in ``manifest`` must
    assert image, presentation anchor, and PPTX snapshot dependencies.
    """
    if not isinstance(candidate, Mapping) or not isinstance(source, Mapping):
        raise PPTXBridgeError("candidate and source mappings are required")
    if "available_at" not in candidate or "source_available_at" not in candidate:
        raise PPTXBridgeError("candidate and source availability fields are required")
    if not isinstance(locator, Mapping):
        raise PPTXBridgeError("PPTX locator must be a mapping")
    if set(locator) - _LOCATOR_KEYS or "page" in locator:
        raise PPTXBridgeError("PPTX locator contains unsupported fields")
    if locator.get("locator_type") != "pptx_embedded_picture" or locator.get("coordinate_frame") != "image_pixels":
        raise PPTXBridgeError("PPTX locator type and image pixel coordinate frame are required")
    if source.get("synthetic_fixture") is not True or not str(source.get("source_ref", "")).startswith("synthetic://"):
        raise PPTXBridgeError("only synthetic_fixture source_ref synthetic:// is accepted")
    if not source.get("document_id") or not source.get("version") or not source.get("chunk_id"):
        raise PPTXBridgeError("source document, version, and chunk identity are required")
    if (candidate.get("source_document_id") != source["document_id"] or
            candidate.get("source_version") != source["version"]):
        raise PPTXBridgeError("candidate source document/version mismatch")
    if candidate.get("chunk_link_status") != "caller_asserted_unverified" or candidate.get("existing_chunk_id") != source["chunk_id"]:
        raise PPTXBridgeError("source chunk must be an exact caller_asserted_unverified binding")
    if not isinstance(source.get("incident_ids"), (list, tuple)) or not source["incident_ids"]:
        raise PPTXBridgeError("selected incident binding is required")
    if locator.get("slide_ordinal") != candidate.get("slide_ordinal") or locator.get("slide_file_number") != candidate.get("slide_file_number"):
        raise PPTXBridgeError("unknown or mismatched slide ordinal/file number")
    if locator.get("picture_shape_id") != candidate.get("picture_shape_id") or locator.get("anchor_id") != candidate.get("anchor_id"):
        raise PPTXBridgeError("unknown or mismatched picture shape/anchor")
    if candidate.get("slide_ordinal_status") != "presentation_order_resolved":
        raise PPTXBridgeError("presentation slide ordinal is unresolved")
    ordinal, file_no, shape = candidate.get("slide_ordinal"), candidate.get("slide_file_number"), candidate.get("picture_shape_id")
    if (any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in (ordinal, file_no)) or
            not isinstance(shape, str) or not shape.isascii() or not re.fullmatch(r"0|[1-9][0-9]*", shape) or int(shape) > 4294967295):
        raise PPTXBridgeError("slide and picture shape identity is invalid")
    anchor = f"ppt/slides/slide{file_no}.xml#shape-{shape}"
    if candidate.get("anchor_id") != anchor or locator.get("anchor_id") != anchor:
        raise PPTXBridgeError("presentation anchor is malformed")
    image_hash, snapshot_hash = candidate.get("image_sha256"), candidate.get("original_sha256")
    _sha(image_hash, "candidate image_sha256"); _sha(snapshot_hash, "candidate original_sha256")
    bbox = candidate.get("region_coords")
    image_size = candidate.get("image_size")
    if (not isinstance(image_size, Mapping) or set(image_size) != {"width", "height"} or
            any(isinstance(image_size.get(k), bool) or not isinstance(image_size.get(k), int) or image_size[k] < 1 for k in ("width", "height"))):
        raise PPTXBridgeError("image_size must contain positive integer width and height")
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox) or
            bbox[0] < 0 or bbox[1] < 0 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3] or
            bbox[2] > image_size["width"] or bbox[3] > image_size["height"]):
        raise PPTXBridgeError("image bounding box is invalid")
    if (locator.get("image_sha256") != image_hash or locator.get("source_snapshot_sha256") != snapshot_hash or
            locator.get("image_bbox") != list(bbox) or locator.get("image_size") != dict(image_size)):
        raise PPTXBridgeError("locator image, snapshot hash, or bbox mismatch")
    if locator.get("originating_chunk_id") != source["chunk_id"]:
        raise PPTXBridgeError("locator source chunk binding mismatch")
    if candidate.get("status") != "candidate_unreviewed":
        raise PPTXBridgeError("OCR text must remain candidate_unreviewed")
    rows = candidate.get("ordered_text_confidence")
    if (not isinstance(rows, list) or not rows or any(not isinstance(r, Mapping) or
            not isinstance(r.get("text"), str) or not r["text"].strip() or
            isinstance(r.get("confidence"), bool) or not isinstance(r.get("confidence"), (int, float)) or
            not math.isfinite(r["confidence"]) or not 0 <= r["confidence"] <= 1 for r in rows)):
        raise PPTXBridgeError("OCR text rows are required")
    confidences = [float(r["confidence"]) for r in rows]
    if locator.get("ocr_confidence") != confidences:
        raise PPTXBridgeError("locator OCR confidence does not match candidate rows")
    if not isinstance(manifest, Mapping) or manifest.get("provenance") != "caller_asserted_unverified_synthetic_manifest":
        raise PPTXBridgeError("explicit caller-asserted synthetic derivation manifest is required")
    if manifest.get("image_sha256") != image_hash or manifest.get("anchor_id") != anchor or manifest.get("source_snapshot_sha256") != snapshot_hash:
        raise PPTXBridgeError("manifest candidate image/anchor/source snapshot mismatch")
    if "candidate_available_at" not in manifest or manifest["candidate_available_at"] != candidate.get("available_at"):
        raise PPTXBridgeError("manifest must explicitly assert the candidate availability value, including null")
    if not isinstance(artifacts, Mapping):
        raise PPTXBridgeError("temporal artifact records are required")
    for kind in ("ocr_output", "embedding_output"):
        output, asserted = artifacts.get(kind), manifest.get(kind)
        if not isinstance(output, Mapping) or not isinstance(asserted, Mapping):
            raise PPTXBridgeError(f"{kind} generation and availability assertion is required")
        for key in ("id", "version", "available_at", "generated_at"):
            if output.get(key) != asserted.get(key):
                raise PPTXBridgeError(f"{kind} manifest does not match temporal artifact {key}")
        _time(output.get("available_at"), f"{kind}.available_at"); _time(output.get("generated_at"), f"{kind}.generated_at")
        binding = asserted.get("binding")
        if not isinstance(binding, Mapping) or any(binding.get(k) != v for k, v in (("image_sha256", image_hash), ("anchor_id", anchor), ("source_snapshot_sha256", snapshot_hash))):
            raise PPTXBridgeError(f"{kind} image/anchor/source dependency binding mismatch")
    source_available = _time(source.get("available_at"), "source.available_at")
    candidate_source_available = _time(candidate.get("source_available_at"), "candidate.source_available_at")
    if not _same_instant(source_available, candidate_source_available):
        raise PPTXBridgeError("candidate source_available_at does not match the bound source")
    ocr_available = _time(artifacts["ocr_output"]["available_at"], "ocr_output.available_at")
    embedding_available = _time(artifacts["embedding_output"]["available_at"], "embedding_output.available_at")
    candidate_available = candidate.get("available_at")
    candidate_available = _time(candidate_available, "candidate.available_at") if candidate_available is not None else None
    ready = max(t for t in (source_available, ocr_available, embedding_available, candidate_available) if t is not None)
    output_ids = {k: {"id": artifacts[k]["id"], "version": artifacts[k]["version"]} for k in ("ocr_output", "embedding_output")}
    loc = dict(locator)
    loc.update({"originating_chunk_id": source["chunk_id"], "source_chunk_binding": "caller_asserted_unverified",
                "pptx_snapshot_sha256": snapshot_hash, "ocr_embedding_binding": "caller_asserted_unverified",
                "time_lineage_provenance": "caller_asserted_unverified"})
    chunk_id = f"{source['chunk_id']}::pptx-ocr:{ordinal}:{shape}"
    return {
        "document_id": source["document_id"], "chunk_id": chunk_id, "version": source["version"],
        "text": "[기계 OCR 미검토]\n" + "\n".join(r["text"] for r in rows),
        "source_ref": source["source_ref"], "locator": json.dumps(loc, ensure_ascii=False, sort_keys=True),
        "status": "candidate_unreviewed", "available_at": ready.isoformat(),
        "source_available_at": source_available.isoformat(), "incident_ids": list(source["incident_ids"]),
        "relation": source.get("relation", "direct"), "score": 0.0,
        "observed_at": source.get("observed_at"), "effective_from": source.get("effective_from"),
        "effective_to": source.get("effective_to"), "applicability": source.get("applicability"),
        "synthetic_fixture": True, "source_chunk_id": source["chunk_id"],
        "ocr_output_id": output_ids["ocr_output"]["id"], "ocr_output_version": output_ids["ocr_output"]["version"],
        "embedding_output_id": output_ids["embedding_output"]["id"], "embedding_output_version": output_ids["embedding_output"]["version"],
        "lineage_binding_provenance": "caller_asserted_unverified",
        "time_lineage_provenance": "caller_asserted_unverified",
        "retrieval_score_note": "synthetic caller-supplied vector; not a relevance or model-quality proof",
    }


def search_bound_pptx(*, chunk: Mapping, vectors: Mapping[str, Sequence[float]], artifacts: Mapping[str, Mapping],
                      query: str, query_vector: Sequence[float], incident_ids: Sequence[str], as_of: str,
                      historical_cutoff_exclusive: datetime, analysis_at: datetime,
                      authorize: Callable, authorize_document: Callable, timezone_name="UTC", top_k=5):
    """Run temporal lineage gates before synthetic hybrid retrieval and app validation."""
    response = search_scoped_temporal(chunks=[chunk], vectors=vectors, artifacts=artifacts,
        mode="historical_realized", historical_cutoff_exclusive=historical_cutoff_exclusive,
        analysis_at=analysis_at, retrieval_kind="hybrid", query=query, query_vector=query_vector,
        incident_ids=list(incident_ids), as_of=as_of, timezone_name=timezone_name,
        top_k=top_k, similarity_threshold=0.0, authorize=authorize,
        authorize_document=authorize_document)
    if response.get("status") == "INELIGIBLE":
        raise PPTXBridgeError("temporal artifact lineage is ineligible: " + ", ".join(response.get("reasons", [])))
    if response.get("status") in ("OK", "NO_MATCH"):
        response.setdefault("retrieval_method", "bm25_vector_hybrid")
        response.setdefault("as_of", as_of)
        response.pop("candidate_count", None)
        response.pop("source_reported_candidate_count", None)
        response.pop("truncated", None)
        response.pop("source_reported_truncated", None)
        # The temporal retriever gates on the latest source/derivative/index
        # availability. For app validation, preserve that retrieval timestamp
        # while explicitly identifying the source timestamp and caller-asserted
        # OCR derivative timestamp.
        if response.get("status") == "OK":
            items = response.get("items")
            if not isinstance(items, list):
                raise PPTXBridgeError("temporal retrieval items are invalid")
            for item in items:
                if (not isinstance(item, dict) or item.get("chunk_id") != chunk.get("chunk_id") or
                        item.get("document_id") != chunk.get("document_id") or
                        item.get("version") != chunk.get("version")):
                    raise PPTXBridgeError("retrieval result does not match the bound PPTX chunk")
                if (item.get("source_available_at") != chunk.get("source_available_at") or
                        item.get("available_at") != chunk.get("available_at") or
                        item.get("ocr_output_id") != artifacts["ocr_output"].get("id") or
                        item.get("ocr_output_version") != artifacts["ocr_output"].get("version")):
                    raise PPTXBridgeError("retrieval result time or OCR artifact does not match the bound chunk")
                item["source_available_at"] = chunk["source_available_at"]
                item["content_kind"] = "image_ocr"
                derivative_at = artifacts["ocr_output"]["available_at"]
                item["derivative_available_at"] = (derivative_at.isoformat()
                    if isinstance(derivative_at, datetime) else derivative_at)
                # Search readiness has already been enforced by the temporal
                # retriever. The app contract's available_at denotes source
                # availability, so adjust only the validator-bound response.
                item["available_at"] = chunk["source_available_at"]
    validated = validate_hybrid_response(response, source_kind="internal_documents", incident_ids=list(incident_ids),
        as_of=as_of, timezone_name=timezone_name, top_k=top_k,
        allowed_statuses=["active", "candidate_unreviewed"])
    validated["synthetic_only"] = True
    validated["limitations"] = list(validated.get("limitations", []))
    if "site_acl_index_model_and_lineage_unverified" not in validated["limitations"]:
        validated["limitations"].append("site_acl_index_model_and_lineage_unverified")
    return validated
