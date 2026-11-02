"""Synthetic positive, negative, and boundary tests for FBM search validation."""

from copy import deepcopy

import pytest

from app.fbm_search_contract import validate_fbm_response


QUERY_WAFER = ("INC-CURRENT", "LOT-1", "WAFER-1")
REGISTERED = {QUERY_WAFER, ("INC-CURRENT", "LOT-1", "WAFER-2")}


def _query():
    return dict(incident_id="INC-CURRENT", lot_id="LOT-1", wafer_id="WAFER-1",
                asset_id="ASSET-1", revision="r1", available_at="2026-10-30T12:00:00+09:00")


def _item(**updates):
    value = dict(_query(), wafer_id="WAFER-2", rank=1, similarity=0.8, relation="direct")
    value.update(updates)
    return value


def _response(*items, **updates):
    value = dict(status="OK" if items else "NO_MATCH", as_of="2026-10-30",
                 representation="raw_fbm", query=_query(), items=list(items),
                 model_id="synthetic-model", model_version="1", preprocess_version="p1",
                 checkpoint_sha256="a" * 64, truncated=None)
    value.update(updates)
    return value


def _validate(response, **updates):
    args = dict(query_wafer=QUERY_WAFER, representation="raw_fbm",
                current_incident_ids=["INC-CURRENT"], historical_incident_ids=["INC-OLD"],
                registered_wafers=REGISTERED, as_of="2026-10-30", timezone_name="Asia/Seoul", top_k=5)
    args.update(updates)
    return validate_fbm_response(response, **args)


def test_projects_only_contract_fields_and_records_unverified_boundaries():
    raw = _response(_item(), untrusted_extra="discard")
    result = _validate(raw)
    assert result["items"][0]["rank"] == 1
    assert "untrusted_extra" not in result
    assert result["checkpoint_sha256"] == "a" * 64
    assert result["source_reported_truncated"] is None
    assert "historical_wafer_scope_unverified" in result["limitations"]
    assert "query_exact_self_match_rejected" in result["limitations"]
    assert result["source_query_identity"] == result["query"]


def test_accepts_historical_incident_candidate_without_claiming_wafer_validation():
    result = _validate(_response(_item(incident_id="INC-OLD", relation="historical_candidate")))
    assert result["items"][0]["relation"] == "historical_candidate"


def test_rejects_exact_query_self_match():
    with pytest.raises(ValueError, match="self-match"):
        _validate(_response(_item(wafer_id="WAFER-1")))


def test_allows_same_asset_with_different_asset_id():
    result = _validate(_response(_item(asset_id="ASSET-OTHER")))
    assert result["items"][0]["asset_id"] == "ASSET-OTHER"


def test_allows_same_asset_at_different_revision():
    result = _validate(_response(_item(revision="r2")))
    assert result["items"][0]["revision"] == "r2"


def test_allows_same_asset_revision_on_other_wafer():
    result = _validate(_response(_item(wafer_id="WAFER-2")))
    assert result["items"][0]["wafer_id"] == "WAFER-2"


@pytest.mark.parametrize("truncated", [True, False, None])
def test_preserves_truncated_as_source_assertion(truncated):
    result = _validate(_response(_item(), truncated=truncated))
    assert result["source_reported_truncated"] is truncated


@pytest.mark.parametrize("bad", ["yes", 0, []])
def test_rejects_malformed_truncated(bad):
    with pytest.raises(ValueError):
        _validate(_response(_item(), truncated=bad))


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(status="NO_MATCH"),
    lambda r: r.update(as_of="2026-10-29"),
    lambda r: r.update(representation="other"),
    lambda r: r["query"].update(wafer_id="WAFER-X"),
    lambda r: r["query"].update(available_at="2026-10-31T00:00:00+09:00"),
    lambda r: r["items"][0].update(available_at="2026-10-31T00:00:00+09:00"),
    lambda r: r["items"][0].update(rank=2),
    lambda r: r["items"][0].update(similarity=float("nan")),
    lambda r: r["items"][0].update(similarity=1.01),
    lambda r: r["items"][0].update(relation="direct", wafer_id="WAFER-X"),
    lambda r: r["items"][0].update(incident_id="INC-UNKNOWN", relation="historical_candidate"),
    lambda r: r.update(checkpoint_sha256="A" * 64),
])
def test_fails_closed_on_scope_shape_temporal_score_and_model_mismatch(mutate):
    raw = _response(_item())
    mutate(raw)
    with pytest.raises(ValueError):
        _validate(raw)


def test_no_match_empty_is_valid_and_ok_empty_is_invalid():
    assert _validate(_response())["items"] == []
    with pytest.raises(ValueError):
        _validate(_response(status="OK"))


@pytest.mark.parametrize("rank", [1.0, True, "1"])
def test_rank_must_be_exact_int(rank):
    with pytest.raises(ValueError):
        _validate(_response(_item(rank=rank)))


def test_rejects_overlap_between_current_and_historical_incident_scopes():
    with pytest.raises(ValueError, match="disjoint"):
        _validate(_response(_item()), historical_incident_ids=["INC-CURRENT"])


def test_rank_is_contiguous_and_top_k_is_bounded():
    second = _item(rank=2, wafer_id="WAFER-2", asset_id="ASSET-2")
    out = _validate(_response(_item(), second))
    assert [item["rank"] for item in out["items"]] == [1, 2]
    with pytest.raises(ValueError):
        _validate(_response(_item(), _item(rank=2, wafer_id="WAFER-2", asset_id="ASSET-2")), top_k=1)


def test_rejects_repeated_incident_lot_wafer_asset_revision_identity():
    repeated = _item(rank=2, similarity=0.7)
    with pytest.raises(ValueError, match="duplicate"):
        _validate(_response(_item(), repeated))


def test_rejects_invalid_scope_inputs_and_naive_timestamps():
    for kwargs in (
        {"current_incident_ids": ["INC-CURRENT", "INC-CURRENT"]},
        {"query_wafer": ("INC-CURRENT", "LOT-1", "UNKNOWN")},
        {"registered_wafers": [("INC-CURRENT", "LOT-1")]},
        {"timezone_name": "Not/AZone"},
    ):
        with pytest.raises(ValueError):
            _validate(_response(_item()), **kwargs)
    raw = deepcopy(_response(_item()))
    raw["items"][0]["available_at"] = "2026-10-30T12:00:00"
    with pytest.raises(ValueError):
        _validate(raw)
