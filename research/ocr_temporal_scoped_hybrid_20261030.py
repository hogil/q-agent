"""Synthetic-only wrapper applying temporal and caller-asserted scope gates before indexing."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping, Sequence

from research.ocr_temporal_lineage_policy_20261030 import evaluate_temporal_lineage
from research.ocr_hybrid_synthetic_bridge_20261030 import BridgeError, SyntheticOCRHybridIndex


class ScopedTemporalError(ValueError):
    pass


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def search_scoped_temporal(*, chunks: Sequence[Mapping], vectors: Mapping[str, Sequence[float]],
        artifacts: Mapping[str, Mapping], mode: str, historical_cutoff_exclusive: datetime,
        analysis_at: datetime, retrieval_kind: str = "hybrid", caller_verifier=None,
        query: str, query_vector: Sequence[float], incident_ids: Sequence[str], as_of: str,
        timezone_name: str, top_k: int = 10, similarity_threshold: float = -1,
        authorize: Callable[[Mapping], bool] | None,
        authorize_document: Callable[[Mapping], bool] | None):
    """Synthetic replay; authorize and filter before building FTS/vector state.

    ``as_of`` is the source-document date cutoff. In retrospective mode the
    bridge query date is analysis_at's local date, while source and derived
    timestamps remain separately constrained by the lineage policy.
    """
    if not _aware(historical_cutoff_exclusive) or not _aware(analysis_at):
        raise ScopedTemporalError("temporal boundaries must be timezone-aware")
    if retrieval_kind != "hybrid":
        raise ScopedTemporalError("this wrapper supports hybrid retrieval only")
    if not callable(authorize) or not callable(authorize_document):
        raise ScopedTemporalError("scope and document authorization callbacks are required")
    try:
        from datetime import date, time, timedelta, timezone
        from zoneinfo import ZoneInfo
        source_cutoff_date = date.fromisoformat(as_of)
        zone = ZoneInfo(timezone_name)
        source_boundary = datetime.combine(source_cutoff_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        if source_boundary != historical_cutoff_exclusive.astimezone(timezone.utc):
            raise ScopedTemporalError("as_of source boundary does not match historical cutoff")
        bridge_as_of = as_of if mode == "historical_realized" else analysis_at.astimezone(zone).date().isoformat()
    except ScopedTemporalError:
        raise
    except Exception as exc:
        raise ScopedTemporalError("invalid as_of date or timezone") from exc

    try:
        decision = authorize({"incident_ids": list(incident_ids), "as_of": as_of, "action": "search_synthetic"})
    except Exception as exc:
        raise ScopedTemporalError("authorization denied") from exc
    if decision is not True:
        raise ScopedTemporalError("authorization denied")
    if not isinstance(chunks, (list, tuple)) or not chunks:
        raise ScopedTemporalError("synthetic chunks are required")
    allowed_chunks = []
    seen_ids = set()
    for c in chunks:
        if not isinstance(c, Mapping) or c.get("synthetic_fixture") is not True or not str(c.get("source_ref", "")).startswith("synthetic://"):
            raise ScopedTemporalError("synthetic fixtures only")
        cid = c.get("chunk_id")
        if not isinstance(cid, str) or not cid or cid in seen_ids:
            raise ScopedTemporalError("chunk IDs must be unique non-empty strings")
        seen_ids.add(cid)
        try:
            source_available = datetime.fromisoformat(c["source_available_at"])
            derived_available = datetime.fromisoformat(c["available_at"])
            if source_available.utcoffset() is None or derived_available.utcoffset() is None:
                continue
        except Exception:
            continue
        if not source_available < historical_cutoff_exclusive or derived_available > analysis_at:
            continue
        if mode == "historical_realized" and not derived_available < historical_cutoff_exclusive:
            continue
        if not isinstance(c.get("incident_ids"), (list, tuple)) or not set(incident_ids).intersection(c["incident_ids"]):
            continue
        auth_request = {"document_id": c.get("document_id"), "incident_ids": list(incident_ids),
                        "as_of": as_of, "action": "search_synthetic_document"}
        try:
            doc_decision = authorize_document(auth_request)
        except Exception as exc:
            raise ScopedTemporalError("document authorization denied") from exc
        if doc_decision is not True:
            continue
        allowed_chunks.append(c)

    lineage = evaluate_temporal_lineage(mode=mode, historical_cutoff_exclusive=historical_cutoff_exclusive,
        analysis_at=analysis_at, retrieval_kind=retrieval_kind, artifacts=artifacts, caller_verifier=caller_verifier)
    if lineage["allowed"] is not True:
        return {"status": "INELIGIBLE", "reasons": lineage["reasons"], "items": [], "synthetic_only": True}
    source_meta = lineage.get("artifact_metadata", {}).get("source_version", {})
    ocr_meta = lineage.get("artifact_metadata", {}).get("ocr_output", {})
    emb_meta = lineage.get("artifact_metadata", {}).get("embedding_output", {})
    ocr_available = artifacts["ocr_output"]["available_at"]
    embedding_available = artifacts["embedding_output"]["available_at"]
    chunks = [c for c in allowed_chunks if c.get("document_id") == source_meta.get("id") and c.get("version") == source_meta.get("version")
              and c.get("ocr_output_id") == ocr_meta.get("id") and c.get("ocr_output_version") == ocr_meta.get("version")
              and c.get("embedding_output_id") == emb_meta.get("id") and c.get("embedding_output_version") == emb_meta.get("version")
              and datetime.fromisoformat(c["source_available_at"]) == artifacts["source_version"]["available_at"]
              and datetime.fromisoformat(c["available_at"]) >= ocr_available
              and datetime.fromisoformat(c["available_at"]) >= embedding_available]
    selected = chunks
    if not selected:
        return {"status": "NO_MATCH", "items": [], "candidate_count": 0, "synthetic_only": True,
                "posthoc": mode == "retrospective_reprocessing", "temporal_mode": mode,
                "input_provenance": "caller_asserted_unverified",
                "historical_index_proof": "caller_asserted_synthetic_replay; rebuilt_now_not_historical_index_proof"}
    selected_vectors = {c["chunk_id"]: vectors[c["chunk_id"]] for c in selected if c.get("chunk_id") in vectors}
    if len(selected_vectors) != len(selected):
        raise ScopedTemporalError("eligible chunks require vectors")
    index = None
    try:
        index = SyntheticOCRHybridIndex(selected, selected_vectors, authorize=lambda _: True)
        result = index.search(query=query, query_vector=query_vector, incident_ids=incident_ids,
            as_of=bridge_as_of, top_k=top_k, authorize=lambda _: True, timezone_name=timezone_name,
            similarity_threshold=similarity_threshold)
    except BridgeError as exc:
        raise ScopedTemporalError("synthetic retrieval failed") from exc
    finally:
        if index is not None:
            index.close()
    result["posthoc"] = mode == "retrospective_reprocessing"
    result["temporal_mode"] = mode
    result["input_provenance"] = "caller_asserted_unverified"
    result["historical_index_proof"] = "caller_asserted_synthetic_replay; rebuilt_now_not_historical_index_proof"
    result["content_vector_lineage"] = "caller_asserted_unverified"
    result["source_as_of"] = as_of
    result["bridge_search_as_of"] = bridge_as_of
    return result
