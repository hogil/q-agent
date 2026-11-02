"""Synthetic unit contract for document incident-scope projection."""

from copy import deepcopy

import pytest

from app.document_evidence_contract import validate_hybrid_response


def _item(*, document_id="doc-1", relation="direct", incident_ids=None):
    return {
        "document_id": document_id,
        "chunk_id": f"{document_id}-chunk-1",
        "version": "v1",
        "text": "Synthetic evidence text",
        "source_ref": "synthetic://source/doc-1",
        "locator": "page 1, paragraph 2",
        "status": "active",
        "available_at": "2026-10-29T10:00:00+09:00",
        "incident_ids": incident_ids if incident_ids is not None else ["selected_A"],
        "relation": relation,
        "score": 0.9,
        "observed_at": None,
        "effective_from": None,
        "effective_to": None,
        "applicability": None,
    }


def _response(*items):
    return {
        "status": "OK" if items else "NO_MATCH",
        "retrieval_method": "bm25_vector_hybrid",
        "as_of": "2026-10-30",
        "items": list(items),
    }


def _validate(response, *, incident_ids=("selected_A", "selected_B"), historical_ids=("registered_H",)):
    return validate_hybrid_response(
        response,
        source_kind="internal_documents",
        incident_ids=list(incident_ids),
        historical_incident_ids=list(historical_ids),
        as_of="2026-10-30",
        timezone_name="Asia/Seoul",
        top_k=10,
        allowed_statuses=["active"],
    )


def test_projects_direct_ids_to_current_scope_and_preserves_document_fields():
    raw_item = _item(incident_ids=["unrelated_X", "selected_A"])
    result = _validate(_response(raw_item))

    projected = result["items"][0]
    assert projected["incident_ids"] == ["selected_A"]
    assert projected["text"] == raw_item["text"]
    assert projected["locator"] == raw_item["locator"]
    assert projected["document_id"] == raw_item["document_id"]
    assert result["limitations"] == ["source_acl_not_verified", "historical_candidate_not_current_scope"]


def test_projects_historical_ids_only_to_registered_historical_scope():
    result = _validate(_response(_item(
        relation="historical_candidate",
        incident_ids=["unrelated_X", "registered_H"],
    )))

    assert result["items"][0]["incident_ids"] == ["registered_H"]


@pytest.mark.parametrize(
    ("relation", "item_ids", "current_ids", "historical_ids"),
    [
        ("direct", ["registered_H"], ["selected_A"], ["registered_H"]),
        ("historical_candidate", ["selected_A"], ["selected_A"], ["registered_H"]),
    ],
)
def test_rejects_zero_intersection_with_relation_specific_scope(
    relation, item_ids, current_ids, historical_ids,
):
    with pytest.raises(ValueError):
        _validate(
            _response(_item(relation=relation, incident_ids=item_ids)),
            incident_ids=current_ids,
            historical_ids=historical_ids,
        )


def test_keeps_sorted_intersection_for_multiple_current_and_historical_ids():
    direct = _item(document_id="direct", incident_ids=["selected_B", "other", "selected_A"])
    historical = _item(
        document_id="historical",
        relation="historical_candidate",
        incident_ids=["registered_Z", "other", "registered_H"],
    )
    result = _validate(
        _response(direct, historical),
        historical_ids=("registered_H", "registered_Z"),
    )

    assert result["items"][0]["incident_ids"] == ["selected_A", "selected_B"]
    assert result["items"][1]["incident_ids"] == ["registered_H", "registered_Z"]


@pytest.mark.parametrize("bad_ids", [[], ["selected_A", "selected_A"], ["selected_A", 7]])
def test_preserves_existing_required_unique_and_valid_id_checks(bad_ids):
    with pytest.raises(ValueError):
        _validate(_response(_item(incident_ids=bad_ids)))


def test_projection_does_not_claim_to_validate_source_acl_or_text_privacy():
    raw_item = _item(incident_ids=["selected_A", "unrelated_X"])
    raw_item["text"] = "Synthetic text containing an intentionally unreviewed detail"
    raw_item["locator"] = "synthetic://private-looking/locator"
    original = deepcopy(raw_item)

    projected = _validate(_response(raw_item))["items"][0]

    assert projected["incident_ids"] == ["selected_A"]
    assert projected["text"] == original["text"]
    assert projected["locator"] == original["locator"]
    assert projected["document_id"] == original["document_id"]
    assert "source_acl_not_verified" in _validate(_response(raw_item))["limitations"]
