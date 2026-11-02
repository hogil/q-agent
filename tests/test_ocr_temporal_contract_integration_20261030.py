"""Synthetic-only contract exercise; it proves no OCR engine accuracy, internal RAG integration, or ACL enforcement.

Artifact IDs, versions, and dependency links are caller-asserted synthetic
fixture data and do not establish production provenance.
"""

from datetime import datetime, timezone
import json

import pytest

from app.document_evidence_contract import validate_hybrid_response
from research.ocr_synthetic_contract_adapter_20261030 import (
    SyntheticAdapterError,
    make_synthetic_search_chunk,
)
from research.ocr_temporal_scoped_hybrid_20261030 import (
    ScopedTemporalError,
    search_scoped_temporal,
)


UTC = timezone.utc
AS_OF = "2026-10-20"
CUTOFF = datetime(2026, 10, 21, tzinfo=UTC)
ANALYSIS_AT = datetime(2026, 10, 22, 12, tzinfo=UTC)
SOURCE_AVAILABLE = datetime(2026, 10, 10, 9, tzinfo=UTC)
OCR_AVAILABLE = datetime(2026, 10, 15, 9, tzinfo=UTC)
EMBED_AVAILABLE = datetime(2026, 10, 16, 9, tzinfo=UTC)


def _fixture(*, source_incident="INC-SYN-1", source_chunk_id="chunk-original"):
    source = {
        "document_id": "doc-synthetic-1", "chunk_id": source_chunk_id,
        "version": "v1", "source_ref": "synthetic://document-1",
        "incident_ids": [source_incident], "available_at": SOURCE_AVAILABLE.isoformat(),
        "status": "active", "relation": "direct", "synthetic_fixture": True,
    }
    candidate = {
        "source_document_id": source["document_id"], "source_version": source["version"],
        "existing_chunk_id": source["chunk_id"], "anchor_id": "synthetic-anchor-1",
        "page": 3, "region_id": "region-7", "region_coords": [10, 20, 110, 80],
        "coordinate_frame": "image_pixels", "image_sha256": "a" * 64,
        "available_at": OCR_AVAILABLE.isoformat(),
        "ordered_text_confidence": [{"text": "synthetic bearing temperature", "confidence": 0.91}],
        "status": "candidate_unreviewed", "ocr_output_id": "ocr-syn-1",
        "ocr_output_version": "v1", "embedding_output_id": "embedding-syn-1",
        "embedding_output_version": "v1",
    }
    artifacts = {
        "source_version": {"id": source["document_id"], "version": source["version"], "available_at": SOURCE_AVAILABLE},
        "ocr_model": {"id": "ocr-model-synthetic", "version": "v1", "available_at": SOURCE_AVAILABLE},
        "ocr_output": {"id": "ocr-syn-1", "version": "v1", "available_at": OCR_AVAILABLE,
                       "generated_at": OCR_AVAILABLE,
                       "dependencies": {"source_version": {"id": source["document_id"], "version": source["version"]},
                                       "ocr_model": {"id": "ocr-model-synthetic", "version": "v1"}}},
        "embedding_model": {"id": "embedding-model-synthetic", "version": "v1", "available_at": OCR_AVAILABLE},
        "embedding_output": {"id": "embedding-syn-1", "version": "v1", "available_at": EMBED_AVAILABLE,
                             "generated_at": EMBED_AVAILABLE,
                             "dependencies": {"ocr_output": {"id": "ocr-syn-1", "version": "v1"},
                                             "embedding_model": {"id": "embedding-model-synthetic", "version": "v1"}}},
        "index_snapshot": {"id": "index-syn-1", "version": "v1", "available_at": EMBED_AVAILABLE,
                           "generated_at": EMBED_AVAILABLE,
                           "dependencies": {"ocr_output": {"id": "ocr-syn-1", "version": "v1"},
                                           "embedding_output": {"id": "embedding-syn-1", "version": "v1"}}},
    }
    chunk = make_synthetic_search_chunk(
        candidate, source, ocr_output=artifacts["ocr_output"],
        embedding_output=artifacts["embedding_output"],
    )
    return source, candidate, chunk, artifacts, {chunk["chunk_id"]: [1.0, 0.0]}


def _search(chunk, vectors, artifacts, *, incident_ids=("INC-SYN-1",),
            authorize=lambda _: True, authorize_document=lambda _: True):
    return search_scoped_temporal(
        chunks=[chunk], vectors=vectors, artifacts=artifacts,
        mode="historical_realized", historical_cutoff_exclusive=CUTOFF,
        analysis_at=ANALYSIS_AT, retrieval_kind="hybrid",
        query="bearing temperature", query_vector=[1.0, 0.0],
        incident_ids=list(incident_ids), as_of=AS_OF, timezone_name="UTC",
        top_k=5, similarity_threshold=0.0, authorize=authorize,
        authorize_document=authorize_document,
    )


def _validate(response, *, incident_ids=("INC-SYN-1",)):
    return validate_hybrid_response(
        response, source_kind="internal_documents", incident_ids=list(incident_ids),
        as_of=AS_OF, timezone_name="UTC", top_k=5,
        allowed_statuses=["active", "candidate_unreviewed"],
    )


def test_strict_historical_search_passes_app_contract_and_preserves_locator():
    source, _, chunk, artifacts, vectors = _fixture()
    assert chunk["available_at"] == EMBED_AVAILABLE.isoformat()
    assert chunk["lineage_binding_provenance"] == "caller_asserted_unverified"
    response = _search(chunk, vectors, artifacts)
    validated = _validate(response)

    assert validated["status"] == "OK"
    item = validated["items"][0]
    assert (item["document_id"], item["version"], item["chunk_id"]) == (
        source["document_id"], source["version"], "chunk-original::ocr:3:region-7")
    assert item["source_ref"] == source["source_ref"]
    locator = json.loads(item["locator"])
    assert locator["originating_chunk_id"] == source["chunk_id"]
    assert (locator["page"], locator["region_id"], locator["bbox"]) == (3, "region-7", [10, 20, 110, 80])
    assert item["status"] == "candidate_unreviewed"


def test_make_ocr_chunk_rejects_source_document_version_or_chunk_mismatch():
    source, candidate, _, artifacts, _ = _fixture()
    candidate["existing_chunk_id"] = "different-chunk"
    with pytest.raises(ValueError, match="does not link"):
        make_synthetic_search_chunk(candidate, source, ocr_output=artifacts["ocr_output"],
                                    embedding_output=artifacts["embedding_output"])


@pytest.mark.parametrize("source_update", [
    {"synthetic_fixture": False},
    {"source_ref": "file://internal/document.pdf"},
])
def test_adapter_rejects_non_synthetic_source_before_chunk_creation(source_update):
    source, candidate, _, artifacts, _ = _fixture()
    source.update(source_update)
    with pytest.raises(SyntheticAdapterError, match="synthetic source fixtures"):
        make_synthetic_search_chunk(candidate, source, ocr_output=artifacts["ocr_output"],
                                    embedding_output=artifacts["embedding_output"])


def test_other_incident_and_document_denial_produce_no_match():
    _, _, chunk, artifacts, vectors = _fixture(source_incident="INC-SYN-OTHER")
    no_incident_match = _search(chunk, vectors, artifacts)
    assert no_incident_match["status"] == "NO_MATCH"
    assert no_incident_match["items"] == []

    _, _, chunk, artifacts, vectors = _fixture()
    denied = _search(chunk, vectors, artifacts, authorize_document=lambda _: False)
    assert denied["status"] == "NO_MATCH"
    assert denied["items"] == []


def test_artifact_candidate_binding_mismatch_is_rejected():
    _, _, chunk, artifacts, vectors = _fixture()
    artifacts["embedding_output"]["id"] = "other-output"
    response = _search(chunk, vectors, artifacts)
    assert response["status"] == "INELIGIBLE"
    assert "index_embedding_output_mismatch" in response["reasons"]


def test_cutoff_excluded_derived_output_is_not_retrieved():
    _, _, chunk, artifacts, vectors = _fixture()
    late = datetime(2026, 10, 21, 0, tzinfo=UTC)
    artifacts["embedding_output"]["available_at"] = late
    artifacts["embedding_output"]["generated_at"] = late
    chunk["available_at"] = late.isoformat()
    response = _search(chunk, vectors, artifacts)
    assert response["status"] == "INELIGIBLE"
    assert response["items"] == []


def test_candidate_available_after_cutoff_cannot_be_searched():
    source, candidate, _, artifacts, _ = _fixture()
    candidate["available_at"] = datetime(2026, 10, 22, tzinfo=UTC).isoformat()
    chunk = make_synthetic_search_chunk(
        candidate, source, ocr_output=artifacts["ocr_output"],
        embedding_output=artifacts["embedding_output"],
    )
    assert chunk["available_at"] == candidate["available_at"]
    vectors = {chunk["chunk_id"]: [1.0, 0.0]}
    response = _search(chunk, vectors, artifacts)
    assert response["status"] == "NO_MATCH"
    assert response["items"] == []


def test_scope_authorization_denial_is_rejected():
    _, _, chunk, artifacts, vectors = _fixture()
    with pytest.raises(ScopedTemporalError, match="authorization denied"):
        _search(chunk, vectors, artifacts, authorize=lambda _: False)


def test_retrospective_reprocessing_is_marked_posthoc_not_validated_as_historical():
    _, _, chunk, artifacts, vectors = _fixture()
    response = search_scoped_temporal(
        chunks=[chunk], vectors=vectors, artifacts=artifacts,
        mode="retrospective_reprocessing", historical_cutoff_exclusive=CUTOFF,
        analysis_at=ANALYSIS_AT, retrieval_kind="hybrid",
        query="bearing temperature", query_vector=[1.0, 0.0],
        incident_ids=["INC-SYN-1"], as_of=AS_OF, timezone_name="UTC",
        top_k=5, similarity_threshold=0.0, authorize=lambda _: True,
        authorize_document=lambda _: True,
    )
    assert response["posthoc"] is True
    assert response["temporal_mode"] == "retrospective_reprocessing"
    assert response["status"] == "OK"
    assert response["items"]
