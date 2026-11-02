from __future__ import annotations

from research.fbm_dual_model_catalog_smoke_20261030 import run


def test_persisted_model_vectors_replay_through_scoped_dual_view_search():
    result = run()
    assert result["status"] == "pass"
    assert result["vector_mode"] == "persisted_cached_vectors_no_current_process_inference"
    assert result["representations"] == ["object_id_yield", "raw_fbm"]
    assert all(result["checks"].values())
    assert len(set(result["source_png_sha256"].values())) == 2
    assert any("no retrieval accuracy" in item for item in result["limitations"])
    assert any("same-vector self-match; distinct query image inference not tested" in item
               for item in result["limitations"])
