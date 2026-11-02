import hashlib
import json
from pathlib import Path

import pytest

from app.cohort_milestone_summary_v6_6 import milestone_summary_v6_6


def _write(root: Path, name: str, value: dict) -> dict:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(root: Path) -> dict:
    trend_scores = _write(root, "trend-scores.json", {
        "status": "FRESH_CONFIRMATION_SCORED_NO_RECALIBRATION", "rows": 2000,
        "normal_rows": 1000, "fault_rows": 1000,
        "fresh_synthetic_transfer_not_oldCSV_reproduction": True,
        "physical_or_production_validation": False,
    })
    trend_audit = _write(root, "trend-audit.json", {
        "dataset": {"raw_index": {"charts": 3000, "total_raw_rows": 4218861,
            "partition_counts": {"calibration": {"normal": 1000},
                "confirmation": {"normal": 1000, "mean_shift": 200, "standard_deviation": 200,
                    "spike": 200, "drift": 200, "context": 200}}}},
        "confirmation": {"CNN_old_vs_fresh": {"fixed05_confusion_matches_fresh": True},
            "AP_threshold_invariant": True},
    })
    trend = _write(root, "trend.json", {
        "status": "ROOT_ACCEPTED_LIMITED_FRESH_SYNTHETIC_CALIBRATION_STUDY",
        "approved_by": "ROOT", "automatic_model_promotion": False, "production": False,
        "primary_family": "cnn1d", "primary_AP": 0.9995863815850362,
        "primary_operating_points": {
            "fresh_exact_order": {"threshold": 0.49471992750962573, "FPR": 0.006, "recall": 0.988,
                "normal_FPR_one_sided95_upper": 0.011807823},
            "frozen_old_validation_FPR1": {"threshold": 0.3178586793753008, "FPR": 0.018, "recall": 0.996},
            "fixed05": {"threshold": 0.5, "FPR": 0.006, "recall": 0.988},
        },
        "scores": trend_scores, "arithmetic_audit": trend_audit,
        "limits": ["synthetic only", "upper bound exceeds one percent"],
    })
    v10_audit = _write(root, "v10-audit.json", {
        "verdict": {"status": "partial"},
        "runtime": {"actual_LLM_returns": 6, "actual_dispatched_Tools": 11, "elapsed_seconds": 429.82},
        "history": {"unicode_word_occurrences": 67, "metadata_search_executed": False},
    })
    v10 = _write(root, "v10.json", {
        "status": "ROOT_PARTIAL_RETRIEVAL_CONTRACT_AND_LLM_SEMANTIC_ERRORS", "reviewed_by": "ROOT",
        "summary": {"actual_LLM_returns": 6, "Tool_calls": 11, "history_retrieved": False,
                    "E5_loaded": False, "forecast_executed": True, "forecast_Judge_approved": False,
                    "new_actions": 0},
        "whole_question_satisfied": False, "general_LLM_quality_established": False, "production": False,
        "independent_audit": v10_audit,
        "Root_manual_findings": ["History67wordoccurrences exceeded both frozen64 limits, beforemetadata retrieval/E5; originalsource notread.", "forecast omitted"],
    })
    capacity_audit = _write(root, "capacity-audit.json", {
        "overall_status": "PASS_INDEPENDENT_NUMERICAL_AUDIT_ROOT_FINAL_ACCEPTANCE_PENDING",
    })
    capacity = _write(root, "capacity.json", {
        "status": "approved", "approved_by": "ROOT", "approval_scope": "8192_numerical_prefill_capacity_only_no_decode_or_business_quality",
        "8192_accepted": True, "candidate_backend_accepted": True, "input_capacity": 8192,
        "output_capacity": 1200, "limits_of_claim": ["No decoding", "No answer quality"], "production": False,
        "independent_actual_audit": capacity_audit,
    })
    return {
        "schema_id": "qagent.model_lab_publication_v6_6.v1", "status": "prepared_pending_ROOT_review",
        "synthetic": True, "production": False, "proofs": {
            "fresh_trend_calibration": trend, "fullworld_evidence_v10": v10, "capacity_8192": capacity,
        },
        "pending_studies": [
            {"id": "fullworld_evidence_v11", "status": "failed_pending_ROOT_capsule", "summary": "No result published."},
            {"id": "metrology_v2", "status": "failed_pending_ROOT_capsule", "summary": "No result published."},
            {"id": "code_performance_v5", "status": "pending_ROOT_capsule", "summary": "No result published."},
        ],
        "current_serving_world": "full-v3", "corrected_V4_integrated": False, "platform_complete": False,
    }


def test_v66_summary_keeps_three_studies_and_pending_items_separate(tmp_path):
    result = milestone_summary_v6_6(_fixture(tmp_path), tmp_path)

    assert result["proof_count"] == 3
    assert result["fresh_trend"]["old_threshold_fpr"] == pytest.approx(0.018)
    assert result["fresh_trend"]["fresh_threshold_fpr"] == pytest.approx(0.006)
    assert result["fresh_trend"]["upper_95_fpr"] == pytest.approx(0.011807823)
    assert result["v10_partial"]["actual_LLM_returns"] == 6
    assert result["v10_partial"]["history_retrieved"] is False
    assert result["v10_partial"]["history_query_word_occurrences"] == 67
    assert result["capacity"]["input_tokens"] == 8192
    assert [row["status"] for row in result["pending_studies"]] == [
        "failed_pending_ROOT_capsule", "failed_pending_ROOT_capsule", "pending_ROOT_capsule"
    ]
    assert result["platform_complete"] is False
    assert result["current_serving_world"] == "full-v3"


def test_v66_rejects_missing_or_wrong_status_proof(tmp_path):
    source = _fixture(tmp_path)
    source["proofs"].pop("capacity_8192")
    with pytest.raises(ValueError, match="exactly three ROOT proof records"):
        milestone_summary_v6_6(source, tmp_path)

    source = _fixture(tmp_path)
    proof_ref = source["proofs"]["fullworld_evidence_v10"]
    proof_path = Path(proof_ref["path"])
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["status"] = "passed"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    proof_ref["sha256"] = hashlib.sha256(proof_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="V10 partial status must remain explicit"):
        milestone_summary_v6_6(source, tmp_path)


def test_v66_rejects_pending_study_being_promoted(tmp_path):
    source = _fixture(tmp_path)
    source["pending_studies"][1]["status"] = "accepted"
    with pytest.raises(ValueError, match="pending studies cannot be promoted"):
        milestone_summary_v6_6(source, tmp_path)


def test_cohort_service_reads_v66_without_removing_historical_entries(tmp_path):
    from app.cohort_research import ARTIFACT_NAMES, CohortResearchService

    capsule = _write(tmp_path, "capsule-v66.json", _fixture(tmp_path))
    artifacts = {name: None for name in ARTIFACT_NAMES}
    artifacts["milestone_v6_6"] = capsule
    manifest = _write(tmp_path, "sources-v5.json", {
        "schema_id": "qagent.cohort_research_sources.v1", "artifacts": artifacts,
    })
    snapshot = CohortResearchService({
        "enabled": True, "artifact_root": str(tmp_path), "manifest_path": manifest["path"],
    }).snapshot()

    assert snapshot["publication_milestone_v66"]["proof_count"] == 3
    assert snapshot["publication_milestone_v65"] is None
