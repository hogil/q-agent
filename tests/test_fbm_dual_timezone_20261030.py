from __future__ import annotations

import pytest

from research.fbm_embedding_catalog_20261030 import EmbeddingSpec, FBMEmbeddingCatalog
from research.fbm_dual_view_search_20261030 import search_dual_view


RAW = EmbeddingSpec("raw", "a" * 64, "v1", 2, "raw_fbm")
OBJ = EmbeddingSpec("obj", "b" * 64, "v1", 2, "object_id_yield")


def test_local_date_cutoff_shared_by_views_and_exclusive_at_next_midnight(tmp_path, monkeypatch):
    catalog = FBMEmbeddingCatalog(tmp_path / "gallery", authorize=lambda *_: True)
    try:
        def add(asset, view, when):
            spec = RAW if view == "raw_fbm" else OBJ
            catalog.add(asset_id=asset, source_revision="r1", raw_bytes=f"{asset}-{view}".encode(),
                        vector=(1, 0), spec=spec, source_time=when, available_at=when,
                        incident_id="SYN-1", lot_id="L1", wafer_id="W1",
                        actor="actor", incident_scope=("SYN-1",))

        add("last-microsecond", "raw_fbm", "2026-10-30T14:59:59.999999Z")
        add("last-microsecond", "object_id_yield", "2026-10-30T14:59:59.999999Z")
        add("next-midnight", "raw_fbm", "2026-10-30T15:00:00Z")
        add("next-midnight", "object_id_yield", "2026-10-30T15:00:00Z")
        original = catalog.search
        calls = []

        def observed(**kwargs):
            calls.append((kwargs["as_of"], kwargs["timezone_name"]))
            return original(**kwargs)

        monkeypatch.setattr(catalog, "search", observed)
        out = search_dual_view(catalog=catalog, raw_query_vector=(1, 0), raw_spec=RAW,
                               object_query_vector=(1, 0), object_spec=OBJ, actor="actor",
                               incident_scope=("SYN-1",), as_of="2026-10-30",
                               timezone_name="Asia/Seoul", top_k_per_view=10)
        assert calls == [("2026-10-30", "Asia/Seoul")] * 2
        assert out.raw_fbm_eligible_count == out.object_id_yield_eligible_count == 1
        assert len(out.items) == 1 and out.items[0].pair_status == "paired"
        assert out.items[0].raw_fbm.asset_id == out.items[0].object_id_yield.asset_id == "last-microsecond"
        assert out.items[0].raw_fbm.as_of == out.items[0].object_id_yield.as_of == "2026-10-30T15:00:00.000000Z"
    finally:
        catalog.close()


def test_date_only_without_timezone_and_invalid_timezone_fail_closed(tmp_path):
    catalog = FBMEmbeddingCatalog(tmp_path / "gallery", authorize=lambda *_: True)
    try:
        args = dict(catalog=catalog, raw_query_vector=(1, 0), raw_spec=RAW,
                    object_query_vector=(1, 0), object_spec=OBJ, actor="actor",
                    incident_scope=("SYN-1",), as_of="2026-10-30", top_k_per_view=2)
        with pytest.raises(ValueError, match="timezone-aware datetime"):
            search_dual_view(**args)
        with pytest.raises(ValueError, match="valid IANA timezone"):
            search_dual_view(**args, timezone_name="Not/AZone")
    finally:
        catalog.close()


def test_aware_timestamp_keeps_instant_semantics_even_with_timezone_name(tmp_path):
    catalog = FBMEmbeddingCatalog(tmp_path / "gallery", authorize=lambda *_: True)
    try:
        out = search_dual_view(catalog=catalog, raw_query_vector=(1, 0), raw_spec=RAW,
                               object_query_vector=(1, 0), object_spec=OBJ, actor="actor",
                               incident_scope=("SYN-1",), as_of="2026-10-30T12:00:00Z",
                               timezone_name="Asia/Seoul", top_k_per_view=2)
        assert out.as_of == "2026-10-30T12:00:00.000000Z"
    finally:
        catalog.close()
