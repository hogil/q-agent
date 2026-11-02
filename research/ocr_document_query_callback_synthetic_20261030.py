"""Synthetic-only document_query callback for scoped OCR contract studies.

All fixture, artifact, and authorization facts are caller asserted. This does
not validate production ACLs, OCR/embedding models, indexes, or the site's RAG.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from research.ocr_synthetic_contract_adapter_20261030 import make_synthetic_search_chunk
from research.ocr_hybrid_synthetic_bridge_20261030 import adapt_ocr_item_for_contract
from research.ocr_temporal_scoped_hybrid_20261030 import search_scoped_temporal
from research.ocr_temporal_lineage_policy_20261030 import evaluate_temporal_lineage


class SyntheticDocumentQueryError(ValueError):
    """Invalid or unauthorized synthetic document retrieval request."""


def make_synthetic_document_query_callback(*, source_kind: str, fixture_kind: str,
        actor_authorize: Callable[[Mapping], bool], scope_authorize: Callable[[Mapping], bool],
        document_authorize: Callable[[Mapping], bool], source: Mapping,
        candidate: Mapping, artifacts: Mapping[str, Mapping],
        chunk_vectors: Mapping[str, Sequence[float]], query_embed: Callable[[str], Sequence[float]],
        analysis_at: datetime, timezone_name: str = "UTC", similarity_threshold: float = 0.0):
    """Build the app.agent document_query keyword-only callback.

    The fixed input is one synthetic source/candidate/artifact set. Historical
    IDs are accepted as scope context but never emitted as evidence.
    """
    if source_kind not in ("engineer_notes", "internal_documents"):
        raise SyntheticDocumentQueryError("unsupported configured source_kind")
    if source_kind != fixture_kind:
        raise SyntheticDocumentQueryError("configured source_kind must match fixture_kind")
    configured_source_kind = source_kind
    def fail_auth(callback, payload):
        try:
            allowed = callback(payload) is True
        except Exception as exc:
            raise SyntheticDocumentQueryError("authorization denied") from exc
        if not allowed:
            raise SyntheticDocumentQueryError("authorization denied")

    def callback(*, source_kind, actor, incident_ids, historical_incident_ids,
                  as_of, query, top_k):
        if source_kind not in ("engineer_notes", "internal_documents"):
            raise SyntheticDocumentQueryError("unsupported source_kind")
        if (not isinstance(actor, str) or not actor.strip()
                or not isinstance(incident_ids, (list, tuple)) or not incident_ids
                or any(not isinstance(value, str) or not value.strip() for value in incident_ids)
                or len(set(incident_ids)) != len(incident_ids)):
            raise SyntheticDocumentQueryError("actor and selected incident scope must be non-empty and valid")
        if (not isinstance(historical_incident_ids, (list, tuple))
                or any(not isinstance(value, str) or not value.strip() for value in historical_incident_ids)
                or len(set(historical_incident_ids)) != len(historical_incident_ids)):
            raise SyntheticDocumentQueryError("historical_incident_ids must be a valid list")
        if not isinstance(query, str) or not query.strip() or len(query) > 12000:
            raise SyntheticDocumentQueryError("query must be non-empty and bounded")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise SyntheticDocumentQueryError("top_k must be an integer from 1 to 100")
        try:
            target = date.fromisoformat(as_of)
            if target.isoformat() != as_of:
                raise ValueError
            zone = ZoneInfo(timezone_name)
            cutoff = datetime.combine(target + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        except Exception as exc:
            raise SyntheticDocumentQueryError("invalid as_of or timezone") from exc
        if not isinstance(analysis_at, datetime) or analysis_at.tzinfo is None or analysis_at.utcoffset() is None:
            raise SyntheticDocumentQueryError("analysis_at must be timezone-aware")
        base = {"actor": actor, "source_kind": source_kind, "incident_ids": list(incident_ids),
                "historical_incident_ids": list(historical_incident_ids), "as_of": as_of}
        fail_auth(actor_authorize, {**base, "action": "synthetic_document_query_actor"})
        fail_auth(scope_authorize, {**base, "action": "synthetic_document_query_scope"})
        if source_kind != configured_source_kind:
            return _no_match(source_kind, incident_ids, as_of)
        if not isinstance(source, Mapping):
            raise SyntheticDocumentQueryError("synthetic source fixture required")
        if (source.get("synthetic_fixture") is not True
                or not isinstance(source.get("source_ref"), str)
                or not source["source_ref"].startswith("synthetic://")):
            raise SyntheticDocumentQueryError("synthetic source fixture required")
        if source.get("relation", "direct") != "direct":
            raise SyntheticDocumentQueryError("only direct document relation is supported")
        if (not isinstance(source.get("incident_ids"), (list, tuple))
                or not set(incident_ids).intersection(source["incident_ids"])):
            return _no_match(source_kind, incident_ids, as_of)
        # Document ID is the only source field read to authorize the document.
        fail_auth(document_authorize, {**base, "document_id": source.get("document_id"),
                                       "action": "synthetic_document_query_document"})
        try:
            lineage = evaluate_temporal_lineage(mode="historical_realized",
                historical_cutoff_exclusive=cutoff, analysis_at=analysis_at,
                retrieval_kind="hybrid", artifacts=artifacts)
            if lineage.get("allowed") is not True:
                raise SyntheticDocumentQueryError("synthetic artifact lineage is ineligible: " + ",".join(lineage.get("reasons", [])))
            if not isinstance(candidate, Mapping) or candidate.get("source_document_id") != source.get("document_id"):
                raise SyntheticDocumentQueryError("candidate/source mismatch")
            chunk = make_synthetic_search_chunk(candidate, source,
                ocr_output=artifacts["ocr_output"], embedding_output=artifacts["embedding_output"])
            if chunk.get("relation") != "direct":
                raise SyntheticDocumentQueryError("only direct document relation is supported")
            qv = query_embed(query)
            result = search_scoped_temporal(
                chunks=[chunk], vectors=chunk_vectors, artifacts=artifacts,
                mode="historical_realized", historical_cutoff_exclusive=cutoff,
                analysis_at=analysis_at, retrieval_kind="hybrid",
                query=query, query_vector=qv, incident_ids=list(incident_ids), as_of=as_of,
                timezone_name=timezone_name, top_k=top_k, similarity_threshold=similarity_threshold,
                authorize=lambda _: True, authorize_document=lambda _: True)
        except Exception as exc:
            raise SyntheticDocumentQueryError("synthetic lineage or retrieval rejected") from exc
        if result.get("status") == "INELIGIBLE":
            raise SyntheticDocumentQueryError("synthetic artifact lineage is ineligible: " + ",".join(result.get("reasons", [])))
        if result.get("status") not in ("OK", "NO_MATCH"):
            raise SyntheticDocumentQueryError("unexpected synthetic retrieval status")
        # search_scoped_temporal already applied the full source/OCR/embedding
        # cutoff. Expose the contract's source and OCR times at the callback edge.
        contract_items = []
        for result_item in result.get("items", []):
            item = dict(result_item)
            item["available_at"] = max(
                datetime.fromisoformat(item["source_available_at"]),
                datetime.fromisoformat(item["derivative_available_at"]),
            ).isoformat()
            contract_items.append(adapt_ocr_item_for_contract(item))
        return {"status": result["status"], "retrieval_method": "bm25_vector_hybrid",
                "as_of": as_of, "items": contract_items,
                "retrieval_completeness": "unknown",
                "limitations": ["synthetic_fixture_only", "historical_ids_unsupported",
                                "actor_and_document_authorization_caller_asserted",
                                "ocr_embedding_and_lineage_caller_asserted_unverified",
                                "ocr_marker_and_timestamps_are_structural_assertions_not_provenance_verification",
                                "not_site_rag_or_real_index"]}

    return callback


def _no_match(source_kind, incident_ids, as_of):
    return {"status": "NO_MATCH", "retrieval_method": "bm25_vector_hybrid",
            "as_of": as_of, "items": [], "retrieval_completeness": "unknown",
            "limitations": ["synthetic_fixture_only", "historical_ids_unsupported"]}
