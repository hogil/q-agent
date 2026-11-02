from __future__ import annotations

import pytest

from research.fbm_embedding_catalog_20261030 import (
    AuthorizationError, EmbeddingSpec, FBMEmbeddingCatalog,
)
from research.fbm_dual_view_search_20261030 import search_dual_view


RAW = EmbeddingSpec("raw-model", "a" * 64, "raw-v1", 2, "raw_fbm")
OBJ = EmbeddingSpec("obj-model", "b" * 64, "obj-v1", 2, "object_id_yield")
SCOPE = ("SYNTHETIC-INC",)
AS_OF = "2026-10-30T12:00:00Z"
NORMALIZED_AS_OF = "2026-10-30T12:00:00.000000Z"


@pytest.fixture
def cat(tmp_path):
    c = FBMEmbeddingCatalog(tmp_path / "gallery", authorize=lambda *_: True)
    yield c
    c.close()


def add(c, aid, view, *, revision="r1", lot="LOT-SYN", wafer="WAFER-SYN",
        incident="SYNTHETIC-INC", available="2026-10-30T10:00:00Z", vector=(1, 0)):
    spec = RAW if view == "raw_fbm" else OBJ
    c.add(asset_id=aid, source_revision=revision, raw_bytes=f"{aid}-{view}-{revision}".encode(),
          vector=vector, spec=spec, source_time="2026-10-30T09:00:00Z",
          available_at=available, incident_id=incident, lot_id=lot, wafer_id=wafer,
          actor="synthetic-actor", incident_scope=SCOPE)


def search(c, *, raw_spec=RAW, obj_spec=OBJ, top_k=10, scope=SCOPE, as_of=AS_OF):
    return search_dual_view(catalog=c, raw_query_vector=(1, 0), raw_spec=raw_spec,
                            object_query_vector=(1, 0), object_spec=obj_spec,
                            actor="synthetic-actor", incident_scope=scope,
                            as_of=as_of, top_k_per_view=top_k)


def test_normal_pair_uses_rank_fusion_and_marks_provenance(cat):
    add(cat, "asset-1", "raw_fbm")
    add(cat, "asset-1", "object_id_yield")
    out = search(cat)
    assert len(out.items) == 1
    item = out.items[0]
    assert item.pair_status == "paired"
    assert item.raw_fbm and item.object_id_yield
    assert item.raw_fbm.similarity == item.object_id_yield.similarity
    assert item.identity_provenance == item.source_provenance == item.geometry_provenance == "caller_asserted_unverified"
    assert out.actor == "synthetic-actor" and out.incident_scope == SCOPE and out.as_of == NORMALIZED_AS_OF


def test_single_view_top_k_absence_is_unknown(cat):
    add(cat, "raw-only", "raw_fbm")
    out = search(cat)
    assert len(out.items) == 1
    assert out.items[0].pair_status == "not_in_returned_top_k_unknown"
    assert out.items[0].object_id_yield is None


def test_missing_lot_or_wafer_never_pairs(cat):
    add(cat, "asset", "raw_fbm", wafer=None)
    add(cat, "asset", "object_id_yield", wafer=None)
    out = search(cat)
    assert len(out.items) == 2
    assert all(x.pair_status == "not_in_returned_top_k_unknown" for x in out.items)


def test_different_source_revision_stays_separate(cat):
    add(cat, "asset", "raw_fbm", revision="r1")
    add(cat, "asset", "object_id_yield", revision="r2")
    out = search(cat)
    assert len(out.items) == 2
    assert all(x.pair_status != "paired" for x in out.items)


def test_mismatched_incident_or_lot_stays_separate(cat):
    add(cat, "asset", "raw_fbm")
    add(cat, "asset", "object_id_yield", lot="OTHER-LOT")
    out = search(cat)
    assert len(out.items) == 2
    assert all(x.pair_status != "paired" for x in out.items)


def test_as_of_cutoff_excludes_late_view_without_asserting_absence(cat):
    add(cat, "asset", "raw_fbm", available="2026-10-30T10:00:00Z")
    add(cat, "asset", "object_id_yield", available="2026-10-30T13:00:00Z")
    out = search(cat, as_of="2026-10-30T12:00:00Z")
    assert len(out.items) == 1
    assert out.items[0].pair_status == "not_in_returned_top_k_unknown"


def test_scope_authorization_failure_returns_no_partial_result(tmp_path):
    c = FBMEmbeddingCatalog(tmp_path / "denied", authorize=lambda actor, incident, op: incident == SCOPE[0] and op == "write")
    try:
        add(c, "asset", "raw_fbm")
        with pytest.raises(AuthorizationError):
            search(c)
    finally:
        c.close()


def test_bad_spec_representation_fails_before_search(cat):
    with pytest.raises(ValueError, match="spec representations"):
        search(cat, raw_spec=OBJ)


def test_per_view_top_k_truncation_is_reported(cat):
    for i in range(3):
        add(cat, f"asset-{i}", "raw_fbm")
    out = search(cat, top_k=1)
    assert out.raw_fbm_truncated and out.raw_fbm_eligible_count == 3
    assert out.object_id_yield_eligible_count == 0
    assert out.top_k_per_view == 1
    assert "approximate" in " ".join(out.limitations)


def test_model_preprocess_mismatch_yields_no_cross_spec_candidates(cat):
    add(cat, "asset", "raw_fbm")
    bad_obj = EmbeddingSpec("wrong-model", "b" * 64, "obj-v1", 2, "object_id_yield")
    out = search(cat, obj_spec=bad_obj)
    assert len(out.items) == 1
    assert out.items[0].pair_status == "not_in_returned_top_k_unknown"


def test_research_namespace_import_is_supported():
    from research.fbm_dual_view_search_20261030 import search_dual_view as package_import
    assert package_import is search_dual_view


def test_timezone_offsets_for_same_instant_produce_same_cutoff(cat):
    add(cat, "asset", "raw_fbm")
    utc = search(cat, as_of="2026-10-30T12:00:00Z")
    offset = search(cat, as_of="2026-10-30T14:00:00+02:00")
    assert len(utc.items) == len(offset.items) == 1
    assert utc.items[0].raw_fbm.as_of == offset.items[0].raw_fbm.as_of
    assert utc.as_of == offset.as_of == NORMALIZED_AS_OF
    assert utc.as_of == utc.items[0].raw_fbm.as_of == offset.items[0].raw_fbm.as_of


@pytest.mark.parametrize("cutoff", ["2026-10-30", "2026-10-30T12:00:00"])
def test_date_only_and_naive_cutoffs_are_rejected(cat, cutoff):
    with pytest.raises(ValueError, match="timezone-aware datetime"):
        search(cat, as_of=cutoff)


def test_string_scope_is_rejected_instead_of_split_into_characters(cat):
    with pytest.raises(ValueError, match="not a string"):
        search(cat, scope="SYNTHETIC-INC")


def test_one_shot_scope_iterable_is_shared_by_both_searches(cat, monkeypatch):
    add(cat, "asset", "raw_fbm")
    add(cat, "asset", "object_id_yield")
    original = cat.search
    observed = []

    def record_scope(**kwargs):
        observed.append(kwargs["incident_scope"])
        return original(**kwargs)

    monkeypatch.setattr(cat, "search", record_scope)
    out = search_dual_view(catalog=cat, raw_query_vector=(1, 0), raw_spec=RAW,
                           object_query_vector=(1, 0), object_spec=OBJ,
                           actor="synthetic-actor", incident_scope=(x for x in SCOPE),
                           as_of=AS_OF, top_k_per_view=5)
    assert out.items[0].pair_status == "paired"
    assert observed == [SCOPE, SCOPE]


def test_second_view_failure_does_not_return_first_view_result(cat, monkeypatch):
    from research.fbm_dual_view_search_20261030 import search_dual_view

    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AuthorizationError("synthetic denied")
        class Response:
            items = ()
            eligible_count = 0
            truncated = False
        return Response()

    monkeypatch.setattr(cat, "search", fail_second)
    with pytest.raises(AuthorizationError, match="synthetic denied"):
        search_dual_view(catalog=cat, raw_query_vector=(1, 0), raw_spec=RAW,
                         object_query_vector=(1, 0), object_spec=OBJ,
                         actor="synthetic-actor", incident_scope=SCOPE,
                         as_of=AS_OF, top_k_per_view=5)
