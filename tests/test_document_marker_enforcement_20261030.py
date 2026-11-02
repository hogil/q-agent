"""Synthetic source-level marker enforcement for document retrieval."""

import pytest

from app.document_evidence_contract import validate_hybrid_response


AS_OF = "2026-10-30"


def _item(**updates):
    item = {
        "document_id": "doc-synthetic-marker-1",
        "chunk_id": "chunk-synthetic-marker-1",
        "version": "v1",
        "text": "Synthetic document evidence",
        "source_ref": "synthetic://document/marker-1",
        "locator": "page:1",
        "status": "active",
        "available_at": "2026-10-20T12:00:00+09:00",
        "incident_ids": ["INC-SYN-1"],
        "relation": "direct",
        "score": 0.9,
        "observed_at": None,
        "effective_from": None,
        "effective_to": None,
        "applicability": None,
    }
    item.update(updates)
    return item


def _response(item):
    return {
        "status": "OK",
        "retrieval_method": "bm25_vector_hybrid",
        "as_of": AS_OF,
        "items": [item],
    }


def _validate(item, *, require_content_kind=False):
    return validate_hybrid_response(
        _response(item),
        source_kind="internal_documents",
        incident_ids=["INC-SYN-1"],
        as_of=AS_OF,
        timezone_name="Asia/Seoul",
        top_k=5,
        allowed_statuses=["active"],
        require_content_kind=require_content_kind,
    )


@pytest.mark.parametrize("marker", ["missing", None])
def test_required_marker_rejects_missing_or_null_content_kind(marker):
    item = _item()
    if marker is None:
        item["content_kind"] = None

    with pytest.raises(ValueError, match="content_kind"):
        _validate(item, require_content_kind=True)


def test_required_text_marker_is_accepted():
    result = _validate(_item(content_kind="text"), require_content_kind=True)

    assert result["items"][0]["content_kind"] == "text"


def test_required_image_ocr_marker_requires_source_and_derivative_times_within_as_of():
    item = _item(
        content_kind="image_ocr",
        derivative_available_at="2026-10-30T23:59:59+09:00",
    )

    result = _validate(item, require_content_kind=True)

    assert result["items"][0]["content_kind"] == "image_ocr"
    assert result["items"][0]["derivative_available_at"] == item["derivative_available_at"]


@pytest.mark.parametrize(
    "updates",
    [
        {"available_at": "2026-10-31T00:00:00+09:00"},
        {"derivative_available_at": "2026-10-31T00:00:00+09:00"},
        {"derivative_available_at": "2026-10-30T15:00:00Z"},
        {"derivative_available_at": "2026-10-30T23:59:59"},
        {"derivative_available_at": "unknown"},
    ],
)
def test_required_image_ocr_rejects_future_naive_or_unknown_times(updates):
    item = _item(
        content_kind="image_ocr",
        derivative_available_at="2026-10-20T12:00:00Z",
    )
    item.update(updates)

    with pytest.raises(ValueError):
        _validate(item, require_content_kind=True)


def test_legacy_default_false_keeps_unmarked_item_accepted():
    result = _validate(_item())

    assert "content_kind" not in result["items"][0]


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_require_content_kind_must_be_exact_bool(value):
    with pytest.raises(ValueError, match="require_content_kind"):
        _validate(_item(content_kind="text"), require_content_kind=value)
