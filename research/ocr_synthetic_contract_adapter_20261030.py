"""Synthetic-only adapter for composing OCR and embedding lineage metadata.

All output identity/dependency bindings are caller asserted. This adapter does
not verify hashes, ACLs, the site's RAG index, or OCR/embedding computation.
"""

from datetime import datetime
from typing import Mapping

from research.ocr_hybrid_synthetic_bridge_20261030 import make_ocr_chunk


class SyntheticAdapterError(ValueError):
    """Invalid caller-supplied synthetic lineage binding."""


def _parse_time(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("timestamp must be an ISO string or datetime")


def make_synthetic_search_chunk(candidate: Mapping, source: Mapping, *,
                                ocr_output: Mapping, embedding_output: Mapping) -> dict:
    """Create an OCR chunk with caller-asserted OCR and embedding readiness."""
    if (not isinstance(source, Mapping) or source.get("synthetic_fixture") is not True or
            not isinstance(source.get("source_ref"), str) or
            not source["source_ref"].startswith("synthetic://")):
        raise SyntheticAdapterError("only explicitly marked synthetic source fixtures are accepted")
    chunk = make_ocr_chunk(candidate, source)
    for name, output in (("ocr_output", ocr_output), ("embedding_output", embedding_output)):
        if not isinstance(output, Mapping) or not all(
                isinstance(output.get(key), str) and output[key].strip()
                for key in ("id", "version")):
            raise SyntheticAdapterError(f"{name} id and version are required")
    if (ocr_output["id"] != candidate.get("ocr_output_id") or
            ocr_output["version"] != candidate.get("ocr_output_version")):
        raise SyntheticAdapterError("OCR output binding does not match candidate")
    if (embedding_output["id"] != candidate.get("embedding_output_id") or
            embedding_output["version"] != candidate.get("embedding_output_version")):
        raise SyntheticAdapterError("embedding output binding does not match candidate")
    try:
        source_available = _parse_time(source["available_at"])
        ocr_available = _parse_time(ocr_output["available_at"])
        embedding_available = _parse_time(embedding_output["available_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SyntheticAdapterError("source and derived availability must be ISO datetimes") from exc
    if any(value.tzinfo is None or value.utcoffset() is None
           for value in (source_available, ocr_available, embedding_available)):
        raise SyntheticAdapterError("source and derived availability must be timezone-aware")
    if source_available > ocr_available or ocr_available > embedding_available:
        raise SyntheticAdapterError("source, OCR, and embedding readiness order is invalid")

    candidate_available = _parse_time(candidate["available_at"])
    if candidate_available.tzinfo is None or candidate_available.utcoffset() is None:
        raise SyntheticAdapterError("candidate availability must be timezone-aware")

    chunk.update({
        "source_available_at": source_available.isoformat(),
        "ocr_output_id": ocr_output["id"],
        "ocr_output_version": ocr_output["version"],
        "embedding_output_id": embedding_output["id"],
        "embedding_output_version": embedding_output["version"],
        "available_at": max(datetime.fromisoformat(chunk["available_at"]),
                             ocr_available, embedding_available).isoformat(),
        "lineage_binding_provenance": "caller_asserted_unverified",
    })
    return chunk
