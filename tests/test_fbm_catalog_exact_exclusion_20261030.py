import hashlib

import pytest

from research.fbm_embedding_catalog_20261030 import CatalogError, EmbeddingSpec, FBMEmbeddingCatalog


def test_exact_asset_revision_exclusion_preserves_other_revision_and_identical_bytes(tmp_path):
    spec = EmbeddingSpec("synthetic", "a" * 64, "p1", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    common = dict(vector=(1, 0), spec=spec, source_time="2026-10-01T00:00:00Z",
        available_at="2026-10-01T00:00:00Z", actor="a", incident_scope=["I"])
    cat.add(asset_id="q", source_revision="r1", raw_bytes=b"query", incident_id="I",
        lot_id="L", wafer_id="W", **common)
    cat.add(asset_id="q", source_revision="r2", raw_bytes=b"query-r2", incident_id="I",
        lot_id="L", wafer_id="W", **common)
    cat.add(asset_id="other", source_revision="r1", raw_bytes=b"query", incident_id="I",
        lot_id="L2", wafer_id="W2", **common)

    response = cat.search(query_vector=(1, 0), spec=spec, actor="a", incident_scope=["I"],
        as_of="2026-10-30", top_k=1, exclude_asset_revision=("q", "r1"))
    assert response.items[0].asset_id == "other"
    assert response.eligible_count == 2
    assert response.truncated is True
    assert {item.asset_id + ":" + item.source_revision for item in cat.search(
        query_vector=(1, 0), spec=spec, actor="a", incident_scope=["I"],
        as_of="2026-10-30", top_k=5, exclude_asset_revision=("q", "r1")).items} == {
            "q:r2", "other:r1"}
    cat.close()


def test_query_only_exclusion_returns_no_match_without_truncation(tmp_path):
    spec = EmbeddingSpec("synthetic", "b" * 64, "p1", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    cat.add(asset_id="q", source_revision="r1", raw_bytes=b"query", vector=(1, 0), spec=spec,
        source_time="2026-10-01T00:00:00Z", available_at="2026-10-01T00:00:00Z",
        incident_id="I", lot_id="L", wafer_id="W", actor="a", incident_scope=["I"])
    response = cat.search(query_vector=(1, 0), spec=spec, actor="a", incident_scope=["I"],
        as_of="2026-10-30", top_k=1, exclude_asset_revision=("q", "r1"))
    assert response.items == ()
    assert response.eligible_count == 0
    assert response.truncated is False
    cat.close()


@pytest.mark.parametrize("value", [7, True, ["q"]])
def test_malformed_asset_id_exclusion_fails_closed(tmp_path, value):
    spec = EmbeddingSpec("synthetic", "d" * 64, "p1", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    with pytest.raises(CatalogError, match="exclude_asset_id"):
        cat.search(query_vector=(1, 0), spec=spec, actor="a", incident_scope=["I"],
            as_of="2026-10-30", top_k=1, exclude_asset_id=value)
    cat.close()


def test_string_asset_id_exclusion_keeps_existing_semantics(tmp_path):
    spec = EmbeddingSpec("synthetic", "e" * 64, "p1", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    for asset_id in ("q", "candidate"):
        cat.add(asset_id=asset_id, source_revision="r1", raw_bytes=asset_id.encode(),
            vector=(1, 0), spec=spec, source_time="2026-10-01T00:00:00Z",
            available_at="2026-10-01T00:00:00Z", incident_id="I", lot_id="L",
            wafer_id=asset_id, actor="a", incident_scope=["I"])
    response = cat.search(query_vector=(1, 0), spec=spec, actor="a", incident_scope=["I"],
        as_of="2026-10-30", top_k=2, exclude_asset_id="q")
    assert [item.asset_id for item in response.items] == ["candidate"]
    cat.close()


@pytest.mark.parametrize("value", [("q",), ("q", ""), ("q", None), ["q", "r1"], "q:r1"])
def test_malformed_exact_exclusion_fails_closed(tmp_path, value):
    spec = EmbeddingSpec("synthetic", "c" * 64, "p1", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    with pytest.raises(CatalogError, match="exclude_asset_revision"):
        cat.search(query_vector=(1, 0), spec=spec, actor="a", incident_scope=["I"],
            as_of="2026-10-30", top_k=1, exclude_asset_revision=value)
    cat.close()
