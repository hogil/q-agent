"""Hash-checked replay of a saved real OCR candidate through synthetic search."""
from copy import deepcopy
import json

import pytest

from research.pptx_real_ocr_hybrid_smoke_20261030 import DEFAULT_RESULT, SmokeError, load_candidate, run, run_with_scope


def test_saved_real_ocr_candidate_is_revalidated_then_hybrid_searched():
    result = run()
    assert result["status"] == "OK"
    assert result["synthetic_source"] is True
    assert result["ocr_and_search_same_process"] is False
    assert result["ocr_candidate_time"] is None
    assert result["production_rag_acl_verified"] is False
    assert result["synthetic_manifest_and_vector"] is True
    assert result["items"]
    assert "합성" in result["items"][0]["text"]


def test_bad_pptx_hash_is_rejected(tmp_path):
    source_report = json.loads(DEFAULT_RESULT.read_text(encoding="utf-8"))
    report = deepcopy(source_report)
    report["pptx_sha256"] = "0" * 64
    report_path = tmp_path / "result.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(SmokeError, match="source PPTX hash mismatch"):
        load_candidate(report_path)


def test_bad_candidate_image_hash_is_rejected(tmp_path):
    report = json.loads(DEFAULT_RESULT.read_text(encoding="utf-8"))
    report["full_candidates"][0]["image_sha256"] = "0" * 64
    report_path = tmp_path / "result.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(SmokeError, match="embedded image hash mismatch"):
        load_candidate(report_path)


def test_wrong_incident_scope_and_temporal_bounds_are_rejected_by_existing_bridge():
    from datetime import datetime, timezone
    from research.pptx_ocr_hybrid_bridge_synthetic_20261030 import search_bound_pptx
    from research.ocr_temporal_scoped_hybrid_20261030 import ScopedTemporalError
    _, replay = run_with_scope()
    result = search_bound_pptx(chunk=replay["chunk"], vectors=replay["vectors"], artifacts=replay["artifacts"],
        query=replay["query"], query_vector=replay["query_vector"], incident_ids=["INC-WRONG"], as_of=replay["as_of"],
        historical_cutoff_exclusive=replay["cutoff"], analysis_at=replay["analysis_at"], authorize=lambda _: True,
        authorize_document=lambda _: True)
    assert result["status"] == "NO_MATCH"
    assert result["items"] == []
    # Wrong temporal boundaries are rejected by that same scoped bridge.
    with pytest.raises(ScopedTemporalError, match="as_of source boundary"):
        search_bound_pptx(chunk=replay["chunk"], vectors=replay["vectors"], artifacts=replay["artifacts"],
            query=replay["query"], query_vector=replay["query_vector"], incident_ids=replay["source"]["incident_ids"], as_of=replay["as_of"],
            historical_cutoff_exclusive=datetime(2026, 10, 31, tzinfo=timezone.utc),
            analysis_at=replay["analysis_at"], authorize=lambda _: True,
            authorize_document=lambda _: True)
