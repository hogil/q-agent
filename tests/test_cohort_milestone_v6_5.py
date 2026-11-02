import hashlib
import json
from pathlib import Path

import pytest

from app.cohort_milestone_summary_v6_5 import milestone_summary_v6_5
from app.cohort_research import ARTIFACT_NAMES, CohortResearchService


def _write(root: Path, name: str, value: dict) -> dict:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(tmp_path: Path) -> dict:
    csv_scores = _write(tmp_path, "csv-scores.json", {"status": "saved"})
    csv_validation = _write(tmp_path, "csv-validation.json", {"status": "saved"})
    csv_test = _write(tmp_path, "csv-test.json", {"status": "saved"})
    spread_audit = _write(tmp_path, "spread-audit.json", {"status": "PASS_independent_V2_after_P1_score_arithmetic"})
    spread_fit_audit = _write(tmp_path, "spread-fit-audit.json", {"status": "PASS_independent_validation_arithmetic_and6_ROOT_processes"})
    action_audit = _write(tmp_path, "action-audit.json", {"status": "PASS", "source": {"freeze_binding_files": 154}})
    ro6_audit = _write(tmp_path, "ro6-audit.json", {"status": "STRUCTURE_AND_BOUND_NUMERIC_CLAIMS_ACCEPTED_TASK_COVERAGE_PARTIAL"})
    ro7_audit = _write(tmp_path, "ro7-audit.json", {"status": "PASS_artifact_audit_imageTools_completed_overallRO7_failed_budget"})
    artifacts = {
        "original_CSV_Trend": {
            "status": "ROOT_limited_acceptance_original_CSV_Trend_retrospective_benchmark",
            "retrospective": True, "synthetic": True, "production": False,
            "current_fullworld_Trend_classifier_promoted": False, "new_fits": 9,
            "selected_on_validation": "cnn1d", "no_test_reselection": True,
            "test_rows": 1500, "test_positive": 750, "unknown": 0,
            "scores": csv_scores, "independent_validation": csv_validation, "independent_test": csv_test,
            "methods": {
                "cnn1d": {"AP": 0.9995179579, "fixed05": {"threshold": 0.5, "F1": 0.9886}, "parameters": 83458, "fit_seconds": [59.18, 44.14, 93.05], "validation_calibrated_FPR1_test": {"threshold": 0.3178586794, "FPR": 0.0186666667, "rows": 1500}},
                "hf_patchtst": {"AP": 0.99869, "fixed05": {"threshold": 0.5, "F1": 0.9818}, "parameters": 71426, "fit_seconds": [23.59, 21.38, 12.47]},
                "hf_patchtsmixer": {"AP": 0.999642, "fixed05": {"threshold": 0.5, "F1": 0.9879}, "parameters": 51894, "fit_seconds": [22.11, 24.19, 24.22]},
            },
            "limitations": ["historically exposed synthetic test"],
        },
        "spread_Trend_V2": {
            "status": "ROOT_limited_acceptance_official_Trend_V2_spread_input_confirmation",
            "production": False, "new_fits": 6,
            "selected_for_future_serving_design_only": "B128spread_based_on_validation_only",
            "automatic_promotion": False, "current_fullworld_trend_model_changed": False,
            "independent_audit": spread_audit, "fit_audit": spread_fit_audit,
            "validation_AP": {"B128spread": 0.9281205440},
            "confirmation": {"A128mean": {"AP": 0.2938296598}, "B128spread": {"AP": 0.9358417354}, "C512spread": {"AP": 0.9497401987}},
            "comparisons": {"primary_B_minus_A": {"delta_AP": 0.6420120755, "CI95": [0.5809, 0.6912]}, "secondary_C_minus_B": {"CI95": [-0.0022, 0.0324]}},
            "limitations": ["synthetic independent families"],
        },
        "actual_ActionV6": {
            "status": "ROOT_limited_acceptance_actual_synthetic_ActionV6_chain",
            "synthetic": True, "production": False, "viewer_actions": 0,
            "actual_LLM_returns": 8, "actual_synthetic_action_commits": 2, "hold_Wafers": 12,
            "requested_cells": 624, "qualified_cells": 624, "recovery_UP_PASS": 12,
            "released_Wafers": 12, "allowed_new_progress": 12, "allowed_replay_new_progress": 0,
            "denied_new_progress": 0, "denied_replay_after_release_new_progress": 0,
            "final_active_holds": 0, "final_active_blocks": 0, "final_PASS_cells": 624,
            "final_simulated_progress": 12, "audit_hash_chain_rows": 7, "frozen_source_bindings": 154,
            "independent_audit": action_audit,
            "source_DB_or_Yield_rewritten": False, "general_LLM_quality_established": False,
            "limitations": ["isolated synthetic MES ledger"],
        },
        "local_RO6": {
            "status": "ROOT_reviewed_actual_RO6_structure_bound_claims_task_coverage_PARTIAL",
            "actual_LLM_returns": 4, "actual_Tool_calls": 9, "compiled_claims": 5,
            "forecast_executed": True, "current_OUT_feature_queries": 0,
            "first_business_Tool": "incidents.search", "last_LLM": "answer",
            "task_answer_fully_accepted": False, "production": False, "synthetic": True,
            "new_actions": 0, "independent_audit": ro6_audit, "limitations": ["overall requested coverage is partial"],
        },
        "image_RO7": {
            "status": "ROOT_reviewed_RO7_imageTools_completed_overall_LLM_failed_budget",
            "actual_LLM_invocations": 3, "actual_LLM_returns": 2, "actual_Tool_results": 7,
            "image_list_rows": 13, "imaged_Wafers": 1, "hits": 5, "DINO_CPU_queries": 1,
            "Judge_Answer_completed": False, "actual_Judge_input_tokens": 6881, "max_input_tokens": 6144,
            "new_actions": 0, "morphology_registered": False,
            "image_retrieval_quality_established": False, "production": False, "synthetic": True,
            "independent_audit": ro7_audit, "limitations": ["Judge and Answer did not complete"],
        },
    }
    proofs = {key: _write(tmp_path, f"{key}.json", value) for key, value in artifacts.items()}
    return {
        "schema_id": "qagent.model_lab_publication_v6_5.v1", "at_utc": "2026-10-26T08:40:26Z",
        "proofs": proofs, "synthetic": True, "production": False,
        "viewer_actions": 0, "recorded_synthetic_action_commits": 2,
        "current_serving_world": "full-v3",
        "corrected_V4_future_model_integrated_in_current_serving": False,
        "platform_complete": False,
        "notes": ["Five limited, separate evidence records."],
    }


def test_v65_projection_keeps_studies_and_action_counts_separate(tmp_path):
    summary = milestone_summary_v6_5(_fixture(tmp_path), tmp_path)

    assert summary["proof_count"] == 5
    assert summary["viewer_actions"] == 0
    assert summary["recorded_synthetic_action_commits"] == 2
    assert summary["action_v6"]["actual_LLM_returns"] == 8
    assert summary["local_RO6"]["actual_LLM_returns"] == 4
    assert summary["image_RO7"]["actual_LLM_returns"] == 2
    assert summary["image_RO7"]["actual_LLM_invocations"] == 3
    assert summary["current_serving_world"] == "full-v3"
    assert summary["platform_complete"] is False


def test_v65_projection_preserves_retrospective_test_and_incomplete_ro7(tmp_path):
    summary = milestone_summary_v6_5(_fixture(tmp_path), tmp_path)

    assert summary["original_csv_trend"]["test_already_exposed"] is True
    assert summary["original_csv_trend"]["fpr1_test"]["test_fpr"] == pytest.approx(0.0186666667)
    methods = summary["original_csv_trend"]["model_comparison"]
    assert [row["model"] for row in methods] == ["cnn1d", "hf_patchtst", "hf_patchtsmixer"]
    assert [row["selected_on_validation"] for row in methods] == [True, False, False]
    assert methods[0]["fixed05_F1"] == pytest.approx(0.9886)
    assert methods[1]["fit_seconds_min"] == pytest.approx(12.47)
    assert summary["image_RO7"]["judge_answer_completed"] is False
    assert summary["image_RO7"]["judge_input_over_budget"] is True
    assert summary["workflow"][-1]["stage"] == "Answer"
    assert summary["workflow"][-1]["ro7"] == "미완료 · 반환되지 않음"


def test_v65_projection_rejects_viewer_action_or_platform_completion_upgrade(tmp_path):
    source = _fixture(tmp_path)
    source["viewer_actions"] = 1

    with pytest.raises(ValueError, match="viewer actions"):
        milestone_summary_v6_5(source, tmp_path)

    source = _fixture(tmp_path)
    source["platform_complete"] = True
    with pytest.raises(ValueError, match="platform completion"):
        milestone_summary_v6_5(source, tmp_path)


def test_v65_projection_rejects_unexpected_csv_method_or_threshold(tmp_path):
    source = _fixture(tmp_path)
    csv_ref = source["proofs"]["original_CSV_Trend"]
    csv_path = Path(csv_ref["path"])
    csv = json.loads(csv_path.read_text(encoding="utf-8"))
    csv["methods"].pop("hf_patchtst")
    csv_path.write_text(json.dumps(csv), encoding="utf-8")
    csv_ref["sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="exactly the three saved model methods"):
        milestone_summary_v6_5(source, tmp_path)


def test_cohort_research_service_loads_v65_manifest_entry(tmp_path):
    source = _fixture(tmp_path)
    capsule_ref = _write(tmp_path, "capsule-v65.json", source)
    artifacts = {name: None for name in ARTIFACT_NAMES}
    artifacts["milestone_v6_5"] = capsule_ref
    manifest = _write(tmp_path, "cohort-dashboard-sources-v4.json", {
        "schema_id": "qagent.cohort_research_sources.v1",
        "artifacts": artifacts,
    })

    snapshot = CohortResearchService({
        "enabled": True, "artifact_root": str(tmp_path), "manifest_path": manifest["path"],
    }).snapshot()

    assert snapshot["publication_milestone_v65"]["proof_count"] == 5
    assert snapshot["publication_milestone_v65"]["viewer_actions"] == 0

