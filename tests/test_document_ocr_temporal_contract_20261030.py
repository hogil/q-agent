"""Synthetic temporal contract for explicitly marked OCR document chunks."""

import pytest

from app.document_evidence_contract import validate_hybrid_response


AS_OF = "2026-10-30"


def _item(**updates):
    item = {
        "document_id": "doc-synthetic-1",
        "chunk_id": "chunk-synthetic-1",
        "version": "v1",
        "text": "Synthetic OCR evidence",
        "source_ref": "synthetic://document/1",
        "locator": "page:1;region:1",
        "status": "active",
        "available_at": "2026-10-30T23:59:59+09:00",
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


def _validate(response):
    return validate_hybrid_response(
        response,
        source_kind="internal_documents",
        incident_ids=["INC-SYN-1"],
        as_of=AS_OF,
        timezone_name="Asia/Seoul",
        top_k=5,
        allowed_statuses=["active"],
    )


def test_explicit_ocr_marker_preserves_both_temporal_assertions():
    item = _item(
        content_kind="image_ocr",
        derivative_available_at="2026-10-20T12:00:00Z",
    )
    result = _validate(_response(item))["items"][0]

    assert result["content_kind"] == "image_ocr"
    assert result["available_at"] == item["available_at"]
    assert result["derivative_available_at"] == item["derivative_available_at"]


@pytest.mark.parametrize(
    "derivative_available_at",
    [None, "", "unknown", "2026-10-20T12:00:00", "2026-10-31T00:00:00+09:00"],
)
def test_marked_ocr_rejects_missing_unparseable_naive_or_after_local_as_of(
    derivative_available_at,
):
    item = _item(content_kind="image_ocr", derivative_available_at=derivative_available_at)
    with pytest.raises(ValueError):
        _validate(_response(item))


def test_marked_ocr_requires_derivative_field():
    item = _item(content_kind="image_ocr")
    with pytest.raises(ValueError):
        _validate(_response(item))


@pytest.mark.parametrize(
    "available_at",
    ["2026-10-31T00:00:00+09:00", "2026-10-30T15:00:00Z"],
)
def test_marked_ocr_rejects_source_availability_after_local_as_of(available_at):
    item = _item(
        available_at=available_at,
        content_kind="image_ocr",
        derivative_available_at="2026-10-20T12:00:00Z",
    )
    with pytest.raises(ValueError):
        _validate(_response(item))


def test_marked_ocr_does_not_impose_order_between_source_and_derivative_times():
    item = _item(
        available_at="2026-10-10T00:00:00+09:00",
        content_kind="image_ocr",
        derivative_available_at="2026-10-20T00:00:00+09:00",
    )
    result = _validate(_response(item))["items"][0]
    assert result["available_at"] < result["derivative_available_at"]


@pytest.mark.parametrize("item", [
    _item(derivative_available_at="2026-10-20T12:00:00Z"),
    _item(content_kind="text", derivative_available_at="2026-10-20T12:00:00Z"),
])
def test_unmarked_or_text_item_rejects_derivative_timestamp(item):
    with pytest.raises(ValueError):
        _validate(_response(item))


@pytest.mark.parametrize("content_kind", ["image", "ocr", "IMAGE_OCR", ""])
def test_unknown_content_kind_marker_is_rejected(content_kind):
    item = _item(content_kind=content_kind)
    with pytest.raises(ValueError):
        _validate(_response(item))


def test_legacy_item_without_temporal_metadata_keeps_existing_output_shape():
    item = _item()
    result = _validate(_response(item))["items"][0]

    assert "content_kind" not in result
    assert "derivative_available_at" not in result
    assert result["available_at"] == item["available_at"]


def test_text_marker_is_preserved_without_derivative_timestamp():
    item = _item(content_kind="text")

    result = _validate(_response(item))["items"][0]

    assert result["content_kind"] == "text"
    assert "derivative_available_at" not in result


def test_text_marker_with_derivative_timestamp_is_rejected():
    item = _item(
        content_kind="text",
        derivative_available_at="2026-10-20T12:00:00Z",
    )

    with pytest.raises(ValueError):
        _validate(_response(item))


def test_ocr_temporal_metadata_does_not_bypass_selected_incident_scope():
    item = _item(
        incident_ids=["INC-SYN-OTHER"],
        content_kind="image_ocr",
        derivative_available_at="2026-10-20T12:00:00Z",
    )
    with pytest.raises(ValueError, match="bound incident scope"):
        _validate(_response(item))


def test_ocr_item_keeps_existing_caller_provided_status_allowlist():
    item = _item(
        status="candidate_unreviewed",
        content_kind="image_ocr",
        derivative_available_at="2026-10-20T12:00:00Z",
    )
    with pytest.raises(ValueError, match="allowlist"):
        _validate(_response(item))
