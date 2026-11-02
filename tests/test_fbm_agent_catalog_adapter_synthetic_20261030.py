import hashlib

import pytest

from research.fbm_embedding_catalog_20261030 import EmbeddingSpec, FBMEmbeddingCatalog
from research.fbm_agent_catalog_adapter_synthetic_20261030 import SyntheticFBMAgentCatalogAdapter
from app.fbm_search_contract import validate_fbm_response


def test_callback_adapter_searches_actual_catalog_and_maps_views(tmp_path):
    raw = EmbeddingSpec("synthetic", "a" * 64, "p1", 2, "raw_fbm")
    obj = EmbeddingSpec("synthetic", "a" * 64, "p1", 2, "object_id_yield")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    query_bytes = b"query"; digest = hashlib.sha256(query_bytes).hexdigest()
    for rep, spec, vector in (("raw_fbm", raw, (1, 0)), ("object_id_yield", obj, (0, 1))):
        cat.add(asset_id="q", source_revision="r1", raw_bytes=query_bytes, vector=vector,
            spec=spec, source_time="2026-10-01T00:00:00.000000Z", available_at="2026-10-01T00:00:00.000000Z",
            incident_id="C", lot_id="L", wafer_id="W", actor="a", incident_scope=["C"])
        cat.add(asset_id="c2", source_revision="r1", raw_bytes=b"current-other-" + rep.encode(), vector=vector,
            spec=spec, source_time="2026-10-02T00:00:00.000000Z", available_at="2026-10-02T00:00:00.000000Z",
            incident_id="C", lot_id="L2", wafer_id="W2", actor="a", incident_scope=["C"])
        cat.add(asset_id="h", source_revision="r1", raw_bytes=b"candidate-" + rep.encode(), vector=vector,
            spec=spec, source_time="2026-10-02T00:00:00.000000Z", available_at="2026-10-02T00:00:00.000000Z",
            incident_id="H", lot_id="LH", wafer_id="WH", actor="a", incident_scope=["H"])
        cat.add(asset_id="h2", source_revision="r1", raw_bytes=b"candidate-2-" + rep.encode(), vector=vector,
            spec=spec, source_time="2026-10-03T00:00:00Z", available_at="2026-10-03T00:00:00Z",
            incident_id="H", lot_id="LH2", wafer_id="WH2", actor="a", incident_scope=["H"])
    def resolver(identity, rep):
        return {"asset_id": "q", "revision": "r1", "raw_bytes": query_bytes,
                "incident_id": "C", "lot_id": "L", "wafer_id": "W",
                "available_at": "2026-10-01T00:00:00.000000Z", "sha256": digest, "synthetic_only": True}
    resolver.synthetic_only = True
    adapter = SyntheticFBMAgentCatalogAdapter(catalog=cat, specs={"raw_fbm": raw,
        "object_id_yield": obj}, model_version="synthetic-v1", query_resolver=resolver,
        encoder=lambda b, spec: (1, 0) if spec.representation == "raw_fbm" else (0, 1),
        timezone_name="UTC")
    common = dict(actor="a", incident_ids=["C"], historical_incident_ids=["H"],
        query_wafer={"incident_id": "C", "lot_id": "L", "wafer_id": "W"}, as_of="2026-10-30", top_k=2)
    left = adapter(**common, representation="raw_fbm")
    right = adapter(**common, representation="object_id_yield_fbm")
    assert any(item["relation"] == "historical_candidate" for item in left["items"])
    assert all(item["similarity"] == 1 for item in left["items"] + right["items"])
    assert all(item["asset_id"] != "q" for item in left["items"] + right["items"])
    assert left["representation"] == "raw_fbm"
    assert right["representation"] == "object_id_yield_fbm"
    assert right["items"]
    assert left["model_version"] == "synthetic-v1"
    assert left["truncated"] is True
    assert any(item["incident_id"] == "C" and item["wafer_id"] == "W2" for item in left["items"])
    validated = validate_fbm_response(left, query_wafer=("C", "L", "W"),
        representation="raw_fbm", current_incident_ids=["C"], historical_incident_ids=["H"],
        registered_wafers=[("C", "L", "W"), ("C", "L2", "W2")],
        as_of="2026-10-30", timezone_name="UTC", top_k=2)
    assert validated["source_reported_truncated"] is True
    cat.close()


def test_rejects_query_identity_scope_and_cutoff_errors(tmp_path):
    spec = EmbeddingSpec("synthetic", "b" * 64, "p1", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    cat.add(asset_id="q", source_revision="r", raw_bytes=b"q", vector=(1, 0), spec=spec,
        source_time="2026-10-01T00:00:00.000000Z", available_at="2026-10-01T00:00:00.000000Z",
        incident_id="C", lot_id="L", wafer_id="W", actor="a", incident_scope=["C"])
    def resolver(identity, rep):
        return {"asset_id": "q", "revision": "r", "raw_bytes": b"wrong",
                "incident_id": "C", "lot_id": "L", "wafer_id": "W",
                "available_at": "2026-10-01T00:00:00.000000Z", "sha256": hashlib.sha256(b"wrong").hexdigest(),
                "synthetic_only": True}
    resolver.synthetic_only = True
    adapter = SyntheticFBMAgentCatalogAdapter(catalog=cat,
        specs={"raw_fbm": spec, "object_id_yield": EmbeddingSpec("synthetic", "c" * 64, "p1", 2, "object_id_yield")},
        model_version="v1", query_resolver=resolver, encoder=lambda *_: (1, 0), timezone_name="Asia/Seoul")
    args = dict(actor="a", incident_ids=["C"], historical_incident_ids=[],
        query_wafer={"incident_id": "C", "lot_id": "L", "wafer_id": "W"},
        representation="raw_fbm", as_of="2026-10-30", top_k=2)
    with pytest.raises(ValueError, match="identity/metadata"):
        adapter(**args)
    def wrong_wafer(identity, rep):
        return {"asset_id": "q", "revision": "r", "raw_bytes": b"q",
                "incident_id": "C", "lot_id": "L-other", "wafer_id": "W-other",
                "available_at": "2026-10-01T00:00:00.000000Z", "sha256": hashlib.sha256(b"q").hexdigest(),
                "synthetic_only": True}
    wrong_wafer.synthetic_only = True
    adapter.query_resolver = wrong_wafer
    with pytest.raises(ValueError, match="identity does not match"):
        adapter(**args)
    with pytest.raises(ValueError, match="disjoint"):
        adapter(**{**args, "historical_incident_ids": ["C"]})
    adapter.query_resolver = resolver
    with pytest.raises(ValueError, match="unavailable"):
        adapter(**{**args, "as_of": "2026-09-30"})
    cat.close()


def test_resolver_assertions_must_match_catalog_record_and_spec(tmp_path):
    raw = EmbeddingSpec("synthetic", "e" * 64, "p1", 2, "raw_fbm")
    obj = EmbeddingSpec("synthetic", "f" * 64, "p1", 2, "object_id_yield")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    def add(asset_id, raw_bytes, spec, lot, wafer, available):
        cat.add(asset_id=asset_id, source_revision="r", raw_bytes=raw_bytes, vector=(1, 0), spec=spec,
            source_time="2026-10-01T00:00:00.000000Z", available_at=available,
            incident_id="C", lot_id=lot, wafer_id=wafer, actor="a", incident_scope=["C"])
    add("q", b"q", raw, "L", "W", "2026-10-01T00:00:00.000000Z")
    add("other-wafer", b"w", raw, "L2", "W2", "2026-10-01T00:00:00.000000Z")
    add("other-model", b"m", EmbeddingSpec("different", "e" * 64, "p1", 2, "raw_fbm"),
        "L", "W", "2026-10-01T00:00:00.000000Z")

    def make_adapter(asset_id, raw_bytes, available, *, source_tuple=("C", "L", "W")):
        def resolver(identity, rep):
            return {"incident_id": source_tuple[0], "lot_id": source_tuple[1],
                "wafer_id": source_tuple[2], "asset_id": asset_id, "revision": "r",
                "raw_bytes": raw_bytes, "available_at": available,
                "sha256": hashlib.sha256(raw_bytes).hexdigest(), "synthetic_only": True}
        resolver.synthetic_only = True
        return SyntheticFBMAgentCatalogAdapter(catalog=cat, specs={"raw_fbm": raw, "object_id_yield": obj},
            model_version="v1", query_resolver=resolver, encoder=lambda *_: (1, 0), timezone_name="UTC")

    args = dict(actor="a", incident_ids=["C"], historical_incident_ids=[],
        query_wafer={"incident_id": "C", "lot_id": "L", "wafer_id": "W"},
        representation="raw_fbm", as_of="2026-10-30", top_k=2)
    with pytest.raises(ValueError, match="identity/metadata"):
        make_adapter("other-wafer", b"w", "2026-10-01T00:00:00.000000Z")(**args)
    with pytest.raises(ValueError, match="identity/metadata"):
        make_adapter("q", b"q", "2026-10-02T00:00:00.000000Z")(**args)
    with pytest.raises(ValueError, match="embedding metadata"):
        make_adapter("other-model", b"m", "2026-10-01T00:00:00.000000Z")(**args)
    cat.close()


def test_rejects_untrusted_resolver_and_scope_overlap(tmp_path):
    spec = EmbeddingSpec("synthetic", "d" * 64, "p", 2, "raw_fbm")
    cat = FBMEmbeddingCatalog(tmp_path / "cat", authorize=lambda *_: True)
    with pytest.raises(ValueError, match="synthetic_only"):
        SyntheticFBMAgentCatalogAdapter(catalog=cat, specs={"raw_fbm": spec,
            "object_id_yield": EmbeddingSpec("synthetic", "d" * 64, "p", 2, "object_id_yield")},
            model_version="v", query_resolver=lambda *_: {}, encoder=lambda *_: (1, 0), timezone_name="UTC")
    cat.close()
