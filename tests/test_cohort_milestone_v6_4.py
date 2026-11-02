import hashlib
import json
from pathlib import Path

import pytest

from app.cohort_milestone_summary_v6_4 import milestone_summary_v6_4


def _write(root: Path, name: str, value: dict) -> dict:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(tmp_path: Path) -> dict:
    audit_ref = _write(tmp_path, "qwen-audit.json", {
        "status": "PASS_receipt_lineage_source_and_return_identity_audit",
    })
    proof_values = {
        "corrected_future135": {
            "status": "ROOT_limited_acceptance_corrected_V4_future135_confirmation",
            "metrics_balanced_normalized_MAE": {"TabM-flat": 0.3793482145777956, "MLP-full": 0.39766896006279384},
            "selected_on_validation": "TabM-flat", "rows": 3456, "calendar_weeks": 18, "targets": 135,
            "worlds": 1, "production": False, "automatic_promotion": False, "confirmation_reselection": False,
            "general_LLM_quality_established": False, "limitations": ["one synthetic world"],
        },
        "official_numeric_Trend": {
            "status": "ROOT_limited_acceptance_official_Trend_confirmation_arithmetic_only",
            "nine_fits": True, "rows": 4864, "production": False, "high_performance_established": False,
            "automatic_promotion": False, "AP": {"hf_patchtsmixer": 0.3118752034630171, "cnn1d": 0.24500011149843562},
            "mixer_metrics": {"FPR1": {"recall": 0.10185185185185185, "threshold": 0.646655430396398}},
            "limitations": ["confirmation sensitivity unresolved"],
        },
        "image_Tools": {
            "status": "ROOT_limited_acceptance_actual_image_asset_and_similarity_Tools",
            "actual_Tool_sequence": ["incidents.search", "material.resolve", "image.evidence(list)", "image.evidence(search_unknown)"],
            "DINO_CPU_forwards": 1, "hits": 5, "gallery_rows": 18720,
            "LLM_calls": 0, "MES_commits": 0, "GPU_calls": 0,
            "morphology_registered": False, "production": False, "limitations": ["retrieval only"],
        },
        "resource_replay_v3": {
            "status": "ROOT_limited_acceptance_context_role_v3_resource_replay_only",
            "completed_returns": {"baseline": 3, "bounded": 3, "total": 6}, "new_Tool_calls": 0,
            "new_actions": 0, "external_API_calls": 0, "production": False, "limits": ["cached replay only"],
            "independent_audit": audit_ref,
        },
        "local_agent_v5": {
            "status": "ROOT_reviewed_control_flow_completed_task_answer_NOT_accepted",
            "actual_LLM_returns": 4, "actual_new_Tool_calls": 7, "first_business_tool": "incidents.search",
            "last_LLM": "answer", "new_actions": 0, "compiled_claims": 0,
            "task_answer_accepted": False, "production": False, "general_LLM_quality_established": False,
            "failure": "forecast was omitted after contradictory Judge flow", 
        },
    }
    proofs = {key: _write(tmp_path, f"{key}.json", value) for key, value in proof_values.items()}
    return {
        "schema_id": "qagent.model_lab_publication_v6_4.v1", "at_utc": "2026-10-26T07:15:48Z",
        "synthetic": True, "production": False, "new_actions": 0, "proofs": proofs,
        "current_serving_world": "full-v3", "corrected_V4_future_model_integrated_in_current_serving": False,
        "platform_complete": False, "notes": ["separate studies"],
    }


def test_v64_projection_preserves_stage_order_and_limitations(tmp_path):
    summary = milestone_summary_v6_4(_fixture(tmp_path), tmp_path)

    assert [row["stage"] for row in summary["workflow"]] == ["Router", "incident DB", "Tools", "Judge", "Answer"]
    assert summary["workflow"][1]["first_business_tool"] == "incidents.search"
    assert summary["future135"]["confirmation_balanced_normalized_mae"] == pytest.approx(0.3793482145777956)
    assert summary["future135"]["integrated_in_current_serving"] is False
    assert summary["numeric_trend"]["fpr1_recall"] == pytest.approx(0.10185185185185185)
    assert summary["qwen_resource_replay"]["total_returns"] == 6
    assert summary["local_agent_v5"]["task_answer_accepted"] is False
    assert summary["proof_count"] == 5


def test_v64_projection_rejects_answer_quality_upgrade(tmp_path):
    source = _fixture(tmp_path)
    path = Path(source["proofs"]["local_agent_v5"]["path"])
    proof = json.loads(path.read_text(encoding="utf-8"))
    proof["task_answer_accepted"] = True
    path.write_text(json.dumps(proof), encoding="utf-8")
    source["proofs"]["local_agent_v5"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="unaccepted answer boundary"):
        milestone_summary_v6_4(source, tmp_path)


def test_v64_projection_rejects_tampered_root_proof(tmp_path):
    source = _fixture(tmp_path)
    path = Path(source["proofs"]["official_numeric_Trend"]["path"])
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        milestone_summary_v6_4(source, tmp_path)
