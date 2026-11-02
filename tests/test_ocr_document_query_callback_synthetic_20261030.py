"""Contract checks for the synthetic-only document_query callback."""
from datetime import datetime, timezone
import json

import pytest

from app.document_evidence_contract import validate_hybrid_response
from research.ocr_document_query_callback_synthetic_20261030 import (
    SyntheticDocumentQueryError, make_synthetic_document_query_callback,
)
from research.ocr_synthetic_contract_adapter_20261030 import make_synthetic_search_chunk


UTC = timezone.utc
AS_OF = "2026-10-20"
ANALYSIS_AT = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _fixture():
    source = {"document_id": "doc-synthetic-1", "chunk_id": "chunk-original",
        "version": "v1", "source_ref": "synthetic://document-1",
        "incident_ids": ["INC-SYN-1"], "available_at": "2026-10-10T09:00:00+00:00",
        "status": "active", "relation": "direct", "synthetic_fixture": True}
    candidate = {"source_document_id": source["document_id"], "source_version": "v1",
        "existing_chunk_id": source["chunk_id"], "anchor_id": "synthetic-anchor-1",
        "page": 3, "region_id": "region-7", "region_coords": [10, 20, 110, 80],
        "coordinate_frame": "image_pixels", "image_sha256": "a" * 64,
        "available_at": "2026-10-15T09:00:00+00:00",
        "ordered_text_confidence": [{"text": "synthetic bearing temperature", "confidence": .91}],
        "status": "candidate_unreviewed", "ocr_output_id": "ocr-syn-1", "ocr_output_version": "v1",
        "embedding_output_id": "embedding-syn-1", "embedding_output_version": "v1"}
    arts = {
        "source_version": {"id": source["document_id"], "version": "v1", "available_at": datetime(2026, 10, 10, 9, tzinfo=UTC)},
        "ocr_model": {"id": "ocr-model-synthetic", "version": "v1", "available_at": datetime(2026, 10, 10, 9, tzinfo=UTC)},
        "ocr_output": {"id": "ocr-syn-1", "version": "v1", "available_at": datetime(2026, 10, 15, 9, tzinfo=UTC), "generated_at": datetime(2026, 10, 15, 9, tzinfo=UTC),
            "dependencies": {"source_version": {"id": source["document_id"], "version": "v1"}, "ocr_model": {"id": "ocr-model-synthetic", "version": "v1"}}},
        "embedding_model": {"id": "embedding-model-synthetic", "version": "v1", "available_at": datetime(2026, 10, 15, 9, tzinfo=UTC)},
        "embedding_output": {"id": "embedding-syn-1", "version": "v1", "available_at": datetime(2026, 10, 16, 9, tzinfo=UTC), "generated_at": datetime(2026, 10, 16, 9, tzinfo=UTC),
            "dependencies": {"ocr_output": {"id": "ocr-syn-1", "version": "v1"}, "embedding_model": {"id": "embedding-model-synthetic", "version": "v1"}}},
        "index_snapshot": {"id": "index-syn-1", "version": "v1", "available_at": datetime(2026, 10, 16, 9, tzinfo=UTC), "generated_at": datetime(2026, 10, 16, 9, tzinfo=UTC),
            "dependencies": {"ocr_output": {"id": "ocr-syn-1", "version": "v1"}, "embedding_output": {"id": "embedding-syn-1", "version": "v1"}}}}
    chunk = make_synthetic_search_chunk(candidate, source, ocr_output=arts["ocr_output"], embedding_output=arts["embedding_output"])
    return source, candidate, chunk, arts, {chunk["chunk_id"]: [1.0, 0.0]}


def _callback(*, source_kind="internal_documents", authorize=lambda _: True,
              doc_authorize=lambda _: True, source=None, candidate=None,
              artifacts=None, vectors=None, embed=None, analysis_at=ANALYSIS_AT):
    src, cand, chunk, arts, vecs = _fixture()
    return make_synthetic_document_query_callback(
        source_kind=source_kind, fixture_kind="internal_documents",
        actor_authorize=authorize, scope_authorize=authorize,
        document_authorize=doc_authorize, source=source or src,
        candidate=candidate or cand, artifacts=artifacts or arts,
        chunk_vectors=vectors or vecs, query_embed=embed or (lambda _: [1.0, 0.0]),
        analysis_at=analysis_at, timezone_name="UTC", similarity_threshold=0.0)


def _invoke(callback, *, incident_ids=("INC-SYN-1",), actor="synthetic-user", as_of=AS_OF):
    return callback(source_kind="internal_documents", actor=actor,
        incident_ids=list(incident_ids), historical_incident_ids=["INC-HIST-1"],
        as_of=as_of, query="bearing temperature", top_k=5)


def _validate(result):
    return validate_hybrid_response(result, source_kind="internal_documents",
        incident_ids=["INC-SYN-1"], historical_incident_ids=["INC-HIST-1"],
        as_of=AS_OF, timezone_name="UTC", top_k=5,
        allowed_statuses=["active", "candidate_unreviewed"])


def test_synthetic_ocr_result_preserves_origin_locator_and_validates():
    result = _invoke(_callback())
    normalized = _validate(result)
    assert normalized["status"] == "OK"
    assert normalized["retrieval_completeness"] == "unknown"
    item = normalized["items"][0]
    assert item["relation"] == "direct"
    locator = json.loads(item["locator"])
    assert locator["originating_chunk_id"] == "chunk-original"


def test_empty_scope_rejected_and_nonmatching_scope_is_no_match():
    cb = _callback()
    with pytest.raises(SyntheticDocumentQueryError, match="non-empty"):
        _invoke(cb, incident_ids=())
    assert _invoke(cb, incident_ids=("INC-OTHER",))["status"] == "NO_MATCH"


@pytest.mark.parametrize("actor,scope", [("", ["INC-SYN-1"]), ("u", [])])
def test_invalid_actor_or_scope_rejected_before_authorization(actor, scope):
    calls = []
    cb = _callback(authorize=lambda _: calls.append("auth") or True)
    with pytest.raises(SyntheticDocumentQueryError):
        _invoke(cb, actor=actor, incident_ids=scope)
    assert calls == []


@pytest.mark.parametrize("decision", [False, None])
def test_auth_denial_precedes_embedding(decision):
    embedded = []
    cb = _callback(authorize=lambda _: decision, embed=lambda q: embedded.append(q) or [1, 0])
    with pytest.raises(SyntheticDocumentQueryError, match="authorization denied"):
        _invoke(cb)
    assert embedded == []


def test_auth_exception_precedes_embedding():
    embedded = []
    def deny(_):
        raise RuntimeError("denied")
    cb = _callback(authorize=deny, embed=lambda q: embedded.append(q) or [1, 0])
    with pytest.raises(SyntheticDocumentQueryError, match="authorization denied"):
        _invoke(cb)
    assert embedded == []


def test_document_auth_exception_precedes_embedding():
    embedded = []
    def deny(_):
        raise RuntimeError("denied")
    cb = _callback(doc_authorize=deny, embed=lambda q: embedded.append(q) or [1, 0])
    with pytest.raises(SyntheticDocumentQueryError, match="authorization denied"):
        _invoke(cb)
    assert embedded == []


def test_query_embedding_runs_after_all_authorization():
    order = []
    cb = _callback(authorize=lambda _: order.append("auth") or True,
                   doc_authorize=lambda _: order.append("doc") or True,
                   embed=lambda _: order.append("embed") or [1, 0])
    _invoke(cb)
    assert order == ["auth", "auth", "doc", "embed"]


def test_source_kind_mismatch_and_non_synthetic_source():
    calls = []
    callback = _callback(authorize=lambda _: calls.append("auth") or True,
                         embed=lambda _: calls.append("embed") or [1, 0])
    result = callback(source_kind="engineer_notes", actor="u", incident_ids=["INC-SYN-1"],
        historical_incident_ids=[], as_of=AS_OF, query="x", top_k=5)
    assert result["status"] == "NO_MATCH" and result["retrieval_completeness"] == "unknown"
    assert calls == ["auth", "auth"]
    src, _, _, _, _ = _fixture()
    src["source_ref"] = "https://example.invalid/doc"
    events = []
    cb = _callback(source=src,
        authorize=lambda _: events.append("auth") or True,
        doc_authorize=lambda _: events.append("document") or True,
        embed=lambda _: events.append("embed") or [1, 0])
    with pytest.raises(SyntheticDocumentQueryError, match="synthetic source"):
        _invoke(cb)
    assert events == ["auth", "auth"]


def test_source_scope_mismatch_skips_document_authorization_and_embedding():
    src, _, _, _, _ = _fixture()
    src["incident_ids"] = ["INC-OTHER"]
    events = []
    cb = _callback(source=src,
        authorize=lambda _: events.append("auth") or True,
        doc_authorize=lambda _: events.append("document") or True,
        embed=lambda _: events.append("embed") or [1, 0])
    result = _invoke(cb)
    assert result["status"] == "NO_MATCH"
    assert events == ["auth", "auth"]


def test_incomplete_or_late_lineage_is_rejected_not_no_match():
    _, _, _, arts, _ = _fixture()
    arts["embedding_output"]["available_at"] = datetime(2026, 10, 21, tzinfo=UTC)
    embedded = []
    cb = _callback(artifacts=arts, embed=lambda q: embedded.append(q) or [1, 0])
    with pytest.raises(SyntheticDocumentQueryError, match="lineage"):
        _invoke(cb)
    assert embedded == []


def test_lineage_failure_occurs_after_document_authorization_before_embedding():
    _, _, _, arts, _ = _fixture()
    arts["embedding_output"]["dependencies"]["ocr_output"]["version"] = "mismatch"
    events = []
    cb = _callback(artifacts=arts,
        authorize=lambda _: events.append("scope/auth") or True,
        doc_authorize=lambda _: events.append("document") or True,
        embed=lambda _: events.append("embed") or [1, 0])
    with pytest.raises(SyntheticDocumentQueryError, match="lineage"):
        _invoke(cb)
    assert events == ["scope/auth", "scope/auth", "document"]


def test_timezone_local_next_midnight_boundary_excludes_later_source():
    src, cand, _, arts, vecs = _fixture()
    # 2026-10-20 in Los Angeles ends at 2026-10-21 07:00 UTC.
    src["available_at"] = datetime(2026, 10, 21, 7, tzinfo=UTC).isoformat()
    arts["source_version"]["available_at"] = datetime(2026, 10, 21, 7, tzinfo=UTC)
    # Keep a coherent fixture dependency chain; boundary equality is excluded.
    arts["ocr_output"]["available_at"] = datetime(2026, 10, 21, 8, tzinfo=UTC)
    arts["ocr_output"]["generated_at"] = arts["ocr_output"]["available_at"]
    arts["embedding_output"]["available_at"] = datetime(2026, 10, 21, 9, tzinfo=UTC)
    arts["embedding_output"]["generated_at"] = arts["embedding_output"]["available_at"]
    arts["index_snapshot"]["available_at"] = arts["embedding_output"]["available_at"]
    arts["index_snapshot"]["generated_at"] = arts["embedding_output"]["available_at"]
    cand["available_at"] = arts["ocr_output"]["available_at"].isoformat()
    cb = make_synthetic_document_query_callback(source_kind="internal_documents",
        fixture_kind="internal_documents", actor_authorize=lambda _: True,
        scope_authorize=lambda _: True, document_authorize=lambda _: True,
        source=src, candidate=cand, artifacts=arts, chunk_vectors=vecs,
        query_embed=lambda _: [1, 0], analysis_at=datetime(2026, 10, 22, tzinfo=UTC),
        timezone_name="America/Los_Angeles")
    with pytest.raises(SyntheticDocumentQueryError, match="lineage"):
        cb(source_kind="internal_documents", actor="u", incident_ids=["INC-SYN-1"],
            historical_incident_ids=[], as_of=AS_OF, query="x", top_k=5)
