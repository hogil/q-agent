import sqlite3

import pytest

from research.fbm_embedding_catalog_20261030 import (
    AuthorizationError, CatalogError, EmbeddingSpec, FBMEmbeddingCatalog,
)


SPEC = EmbeddingSpec("synthetic-model", "a" * 64, "synthetic-preprocess-v1", 2, "raw_fbm")


def make_catalog(tmp_path, authorize=lambda *_: True):
    catalog = FBMEmbeddingCatalog(tmp_path / "identity-gallery", authorize=authorize)
    raw = b"synthetic wafer map bytes"
    catalog.add(asset_id="asset-1", source_revision="rev-1", raw_bytes=raw,
                vector=(1.0, 0.0), spec=SPEC,
                source_time="2026-10-29T08:00:00Z",
                available_at="2026-10-30T08:00:00Z", incident_id="inc-1",
                lot_id="lot-1", wafer_id="wafer-1", actor="reader",
                incident_scope={"inc-1"})
    return catalog, raw


def read(cat, **kwargs):
    defaults = dict(asset_id="asset-1", source_revision="rev-1", representation="raw_fbm",
                    actor="reader", incident_scope={"inc-1"}, as_of="2026-10-30T09:00:00Z")
    defaults.update(kwargs)
    return cat.get_asset(**defaults)


def test_get_asset_returns_source_and_catalog_identity_without_vector(tmp_path):
    cat, raw = make_catalog(tmp_path)
    try:
        asset = read(cat)
        assert asset.raw_bytes == raw
        assert (asset.asset_id, asset.source_revision, asset.representation) == (
            "asset-1", "rev-1", "raw_fbm")
        assert (asset.incident_id, asset.lot_id, asset.wafer_id) == ("inc-1", "lot-1", "wafer-1")
        assert asset.available_at == "2026-10-30T08:00:00.000000Z"
        assert asset.sha256
        assert (asset.model_id, asset.preprocess_version, asset.checkpoint_sha256,
                asset.dimension) == (SPEC.model_id, SPEC.preprocess_version,
                                     SPEC.checkpoint_sha256, 2)
        assert not hasattr(asset, "vector")
        assert cat.get_raw(asset_id="asset-1", source_revision="rev-1", representation="raw_fbm",
                           actor="reader", incident_scope={"inc-1"},
                           as_of="2026-10-30T09:00:00Z") == raw
    finally:
        cat.close()


@pytest.mark.parametrize("kwargs", [
    {"incident_scope": {"inc-other"}},
    {"as_of": "2026-10-30T07:59:59Z"},
])
def test_get_asset_hides_wrong_scope_or_unavailable_as_of(tmp_path, kwargs):
    cat, _ = make_catalog(tmp_path)
    try:
        with pytest.raises(CatalogError):
            read(cat, **kwargs)
    finally:
        cat.close()


def test_get_asset_uses_scope_authorization(tmp_path):
    cat, _ = make_catalog(tmp_path, authorize=lambda actor, incident, op: op == "write")
    try:
        with pytest.raises(AuthorizationError):
            read(cat)
    finally:
        cat.close()


def test_get_asset_detects_tampered_metadata(tmp_path):
    cat, _ = make_catalog(tmp_path)
    try:
        cat._db.execute("UPDATE assets SET model_id=?", ("",))
        cat._db.commit()
        with pytest.raises(CatalogError):
            read(cat)
    finally:
        cat.close()
