import hashlib
import json
from pathlib import Path

import pytest

from app import cohort_milestone_summary_v6_8 as v68_module
from app.cohort_milestone_summary_v6_8 import milestone_summary_v6_8


def _write(root: Path, name: str, value: dict) -> dict:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(root: Path, monkeypatch) -> dict:
    records = {
        "native_phase_a": ("native.json", {
            "status": "ROOT_LIMITED_ACCEPTANCE_V4_METADATA_MASK_ONLY", "reviewed_by": "ROOT", "synthetic": True, "production": False,
            "general_LLM_quality_established": False,
            "counts": {"samples": 14812, "contexts": 768, "point_records": 770224}, "SQL_references_passed": 12,
            "actual_numeric_model_training": False, "live_Tool_enabled": False,
        }),
        "mht_standalone": ("mht.json", {
            "status": "ROOT_LIMITED_ACCEPTANCE_EXACT_DEFAULT_RANKING_AND_RETURNED_MHT_SOURCE_READ", "reviewed_by": "ROOT", "synthetic": True, "production": False,
            "general_LLM_quality_established": False,
            "scope": "Standalone configured oldbank MiniLM optional format adapter only",
            "summary": {"default_cases_exact": 4, "default_matches_compared": 32, "MHT_queries": 3, "source_read_calls": 3, "distinct_MHT_documents": 2},
            "limits": ["Standalone oldbank MiniLM adapter only", "No active E5 federation registration"],
        }),
        "evidence_v15_1": ("evidence.json", {
            "status": "ROOT_PARTIAL_TRACE_COMPLETED_FORECAST_OMITTED_AND_KOREAN_NARRATIVE_FAILED", "reviewed_by": "ROOT", "synthetic": True, "production": False,
            "whole_question_satisfied": False, "general_LLM_quality_established": False,
            "summary": {"actual_LLM_returns": 7, "Tool_calls": 11, "evidence_facts": 9, "approved_facts": 7, "Answer_last": True, "new_actions": 0},
            "actual_forecast": {"Judge_approved": False, "Answer_claim_included": False},
            "language_check": {"field": "narrative_ko", "Hangul_characters": 0},
        }),
        "metrology_policy_v5": ("metrology.json", {
            "status": "ROOT_DENIED_ALL_FACTS_APPROVED_BUT_INVENTED_HISTORICAL_POLICY_REQUIREMENT", "reviewed_by": "ROOT", "synthetic": True, "production": False,
            "whole_task_satisfied": False, "general_LLM_quality_established": False,
            "summary": {"actual_LLM_returns": 4, "approved_fact_count": 7, "new_request_cells": 0, "new_request_wafers": 0, "new_actions": 0},
            "Judge": {"decision": "reject", "approved_fact_choices": {"A_SCOPE": True, "A_NATIVE": True, "A_UNIT": True, "A_RISK": True, "A_POLICY": True, "F1": True, "F2": True}},
            "finding": "Invented mandatory historical-factory-policy condition; no bypass.",
        }),
    }
    refs, expected = {}, {}
    for key, (filename, value) in records.items():
        refs[key] = _write(root, filename, value)
        expected[key] = (filename, refs[key]["sha256"], value["status"])
    monkeypatch.setattr(v68_module, "ROOT_REVIEWS", expected)
    return {
        "schema_id": "qagent.model_lab_publication_v6_8.v1", "status": "prepared_from_ROOT_reviewed_records",
        "synthetic": True, "production": False, "general_LLM_quality_established": False,
        "root_reviews": refs, "excluded": ["V16 results are outside this snapshot's review scope"],
    }


def test_v68_projects_four_hash_verified_records_without_completion_claims(tmp_path, monkeypatch):
    result = milestone_summary_v6_8(_fixture(tmp_path, monkeypatch), tmp_path)

    assert result["proof_count"] == 4
    assert result["native_phase_a"]["samples"] == 14812
    assert result["native_phase_a"]["sql_references_passed"] == 12
    assert result["mht_standalone"]["default_matches_compared"] == 32
    assert result["mht_standalone"]["distinct_mht_documents"] == 2
    assert result["mht_standalone"]["e5_federation_connected"] is False
    assert result["evidence_v15_1"]["forecast_included"] is False
    assert result["evidence_v15_1"]["hangul_characters"] == 0
    assert result["metrology_policy_v5"]["new_request_cells"] == 0
    assert result["metrology_policy_v5"]["judge_decision"] == "reject"
    assert result["synthetic"] is True and result["production"] is False
    assert result["general_LLM_quality_established"] is False
    assert result["limits"][-1] == "V16 results are outside this reviewed snapshot's scope."


def test_v68_rejects_tampered_review_hash_and_promoted_quality(tmp_path, monkeypatch):
    source = _fixture(tmp_path, monkeypatch)
    path = Path(source["root_reviews"]["mht_standalone"]["path"])
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="proof hash mismatch"):
        milestone_summary_v6_8(source, tmp_path)

    source = _fixture(tmp_path, monkeypatch)
    source["general_LLM_quality_established"] = True
    with pytest.raises(ValueError, match="synthetic draft boundary"):
        milestone_summary_v6_8(source, tmp_path)

    source = _fixture(tmp_path, monkeypatch)
    source["excluded"] = ["V16 status unavailable"]
    with pytest.raises(ValueError, match="V16 must remain outside the reviewed snapshot scope"):
        milestone_summary_v6_8(source, tmp_path)


def test_v68_service_projects_optional_manifest_entry_without_replacing_v67(tmp_path, monkeypatch):
    from app.cohort_research import ARTIFACT_NAMES, CohortResearchService

    source = _fixture(tmp_path, monkeypatch)
    capsule = _write(tmp_path, "capsule-v68.json", source)
    artifacts = {name: None for name in ARTIFACT_NAMES}
    artifacts["milestone_v6_7"] = None
    artifacts["milestone_v6_8"] = capsule
    manifest = _write(tmp_path, "sources-v68.json", {
        "schema_id": "qagent.cohort_research_sources.v1", "artifacts": artifacts,
    })
    snapshot = CohortResearchService({
        "enabled": True, "artifact_root": str(tmp_path), "manifest_path": manifest["path"],
    }).snapshot()

    assert snapshot["publication_milestone_v67"] is None
    assert snapshot["publication_milestone_v68"]["proof_count"] == 4
