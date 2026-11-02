import hashlib
import json
from pathlib import Path

import pytest

from app.cohort_milestone_summary_v6_3 import milestone_summary_v6_3


def _write_json(path: Path, value: dict) -> dict:
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(tmp_path: Path):
    trace_path = tmp_path / "calls.jsonl"
    trace_path.write_text(json.dumps({"tool": "incidents.search", "result": {"tool": "incidents.search"}}) + "\n", encoding="utf-8")
    workflow_trace = {"path": str(trace_path), "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(), "source_proof": "synthetic_tools_mes.collect"}
    collect_ref = _write_json(tmp_path / "collect.json", {"call_journal": {"path": workflow_trace["path"], "sha256": workflow_trace["sha256"]}})
    seed_ref = _write_json(tmp_path / "dummy-seed.json", {"status": "explicit_dummy_state_seeded", "source_DB_or_Yield_rewrite": False})
    qwen = {
        "status": "ROOT_limited_acceptance_bounded_resource_replay_only",
        "completed_returns": {"baseline": 2, "bounded": 3, "total": 5},
        "baseline_answer_completed": False,
        "bounded_all_three_archive_text_and_tokens_identical": True,
        "resources": {"bounded_peak_reserved_gib": 7.35, "baseline_abort_observed_reserved_gib": 15.49},
        "instrumented_common_role_latency": {"router": {"baseline_seconds": 14.0, "bounded_seconds": 30.0, "direction": "slower"}, "judge": {"baseline_seconds": 33.0, "bounded_seconds": 46.0, "direction": "slower"}},
        "new_Tool_calls": 0, "new_actions": 0, "external_API_calls": 0,
        "general_LLM_quality_established": False, "limits": ["replay only"],
    }
    tools = {
        "status": "ROOT_limited_acceptance_actual_synthetic_Tools_and_dummy_MES_only",
        "actual_dispatches": 25, "unique_Tool_names": [f"tool.{n}" for n in range(13)],
        "actions": {"HOLD_BLOCK_DISPATCH_REQUEST_METROLOGY": {"wafers": 12, "transactions": 1}, "RELEASE_UNBLOCK": {"wafers": 12, "transactions": 1}},
        "current_dummy_MES_state": {"active_holds": 0, "active_blocks": 0, "transactions": 2},
        "LLM_calls": 0, "source_DB_or_Yield_rewrite": False, "production": False,
        "dummy_qualification_seed": seed_ref, "collect": collect_ref, "limits": ["scripted only"],
    }
    blood_metrics = {"CNN": {"macro_auc": 0.9976, "accuracy": 0.9555}, "DINO": {"macro_auc": 0.9908, "accuracy": 0.9049}}
    blood_audit_ref = _write_json(tmp_path / "blood-audit.json", {"status": "PASS_independent_saved_array_recomputation", "metrics": {"CNN-ensemble": blood_metrics["CNN"], "DINO-ensemble": blood_metrics["DINO"]}})
    blood_pretest_ref = _write_json(tmp_path / "blood-pretest.json", {"test_images_opened": False, "test_labels_opened": False})
    blood_prediction_ref = _write_json(tmp_path / "blood-prediction-gate.json", {"status": "ROOT_all_six_predictions_accepted_before_test_labels", "test_labels_opened": False})
    blood = {
        "status": "ROOT_limited_acceptance_public_BloodMNIST_fixed_benchmark", "public_dataset": "BloodMNIST",
        "selected_arm_frozen": "CNN", "test_rows": 3421,
        "metrics": blood_metrics, "independent_audit": blood_audit_ref,
        "validation_selection_gate": blood_pretest_ref, "predictions_before_labels_gate": blood_prediction_ref,
        "production": False, "FAB_validation": False, "clinical_validation": False,
        "limits": ["public benchmark only"],
    }
    evaluation = {"threshold": 0.5, "reports": [{"local_AP": 1.0, "repetition_AP": 1.0, "planned13_any_local_AP": 1.0, "rows": 4680, "wafers": 360, "TP": [10, 11], "FP": [0, 2], "FN": [1, 0]} for _ in range(4)]}
    evaluation_ref = _write_json(tmp_path / "sem-evaluation.json", evaluation)
    sem_audit_ref = _write_json(tmp_path / "sem-audit.json", {"status": "passed_source_provenance_and_arithmetic_recompute"})
    sem_gate_ref = _write_json(tmp_path / "sem-gate.json", {"status": "ROOT_accepted4_image_predictions_before_confirmation_label_read", "labels_parsed_by_ROOT_before_gate": False, "OUT_values_read": False})
    sem = {
        "status": "ROOT_limited_acceptance_SEM_v2_synthetic_proxy_confirmation_and_control",
        "evaluation": evaluation_ref, "independent_audit": sem_audit_ref, "prediction_before_label_gate": sem_gate_ref,
        "confirmation_rows": 4680, "confirmation_wafers": 360,
        "planned_sites": 13, "unobserved_chips_per_wafer": 19,
        "selected_serving_candidate": {"arm": "all13", "seeds": [17, 29], "registered": False},
        "families": ["single", "all13"], "seeds": [17, 29],
        "local_mark_control": {"validation_rows": 3640, "models": [{"threshold": 0.5, "control_local_positive_rate_at_fixed_threshold": 0.0} for _ in range(4)]},
        "real_SEM_validation": False, "production": False, "limits": ["procedural proxy only"],
    }
    loadmode = {
        "status": "ROOT_limited_acceptance_4B_load_mode_probe_only",
        "modes": {"async0-baseline-01": {"counters": {"allocated_bytes": 2674211840, "peak_allocated_bytes": 7880762368, "peak_reserved_bytes": 7954497536, "process_peak_rss_bytes": 8994316288}}, "async1-sequential-01": {"counters": {"allocated_bytes": 2678488064, "peak_allocated_bytes": 2717372416, "peak_reserved_bytes": 2720006144, "process_peak_rss_bytes": 8993062912}}},
        "generations": 0, "explicit_forwards": 0, "production": False,
        "inference_quality_established": False, "limits": ["load only"],
    }
    load_audit_ref = _write_json(tmp_path / "load-audit.json", {"status": "PASS_stdlib_receipt_and_175_source_pin_audit", "freeze": {"mismatches": 0}})
    loadmode["independent_audit"] = load_audit_ref
    proof_values = {"qwen_role_replay": qwen, "synthetic_tools_mes": tools, "public_bloodmnist": blood, "sem_v2": sem, "qwen_load_mode": loadmode}
    proofs = {key: _write_json(tmp_path / f"{key}.json", value) for key, value in proof_values.items()}
    source = {"schema_id": "qagent.model_lab_publication_v6_3.v1", "status": "ROOT_limited_acceptance_component_bundle", "synthetic": True, "production": False, "new_actions": 0, "new_full_local_agent_run_completed": False, "proofs": proofs, "workflow_trace": workflow_trace}
    return source


def test_v63_summary_keeps_experiments_separate_and_workflow_vertical(tmp_path):
    source = _fixture(tmp_path)
    summary = milestone_summary_v6_3(source, tmp_path)

    assert summary["new_full_local_agent_run_completed"] is False
    assert [row["stage"] for row in summary["workflow"]] == ["Router", "incident DB", "Tools", "Judge", "Answer"]
    assert summary["workflow"][1]["first_business_tool"] == "incidents.search"
    assert summary["tools_mes"]["dispatches"] == 25
    assert summary["tools_mes"]["llm_calls"] == 0
    assert summary["tools_mes"]["active_holds_after_release"] == 0
    assert summary["qwen_role_replay"]["completed_returns"] == 5
    assert summary["bloodmnist"]["selected_arm"] == "CNN"
    assert summary["bloodmnist"]["test_rows"] == 3421
    assert summary["sem_v2"]["unobserved_chips_per_wafer"] == 19
    assert summary["sem_v2"]["threshold"] == 0.5
    assert summary["qwen_load_mode"]["peak_allocated_gib"]["async0-baseline-01"] == pytest.approx(7.34, abs=0.02)
    assert summary["qwen_load_mode"]["peak_allocated_gib"]["async1-sequential-01"] == pytest.approx(2.53, abs=0.02)


def test_v63_summary_rejects_changed_root_proof_bytes(tmp_path):
    source = _fixture(tmp_path)
    proof_path = Path(source["proofs"]["qwen_role_replay"]["path"])
    proof_path.write_text(proof_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        milestone_summary_v6_3(source, tmp_path)


def test_v63_summary_rejects_non_incident_first_tool(tmp_path):
    source = _fixture(tmp_path)
    trace_path = Path(source["workflow_trace"]["path"])
    trace_path.write_text(json.dumps({"tool": "material.resolve", "result": {"tool": "material.resolve"}}) + "\n", encoding="utf-8")
    source["workflow_trace"]["sha256"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    tools_ref = source["proofs"]["synthetic_tools_mes"]
    tools_path = Path(tools_ref["path"])
    tools = json.loads(tools_path.read_text(encoding="utf-8"))
    collect_path = Path(tools["collect"]["path"])
    collect = json.loads(collect_path.read_text(encoding="utf-8"))
    collect["call_journal"]["sha256"] = source["workflow_trace"]["sha256"]
    collect_path.write_text(json.dumps(collect), encoding="utf-8")
    tools["collect"]["sha256"] = hashlib.sha256(collect_path.read_bytes()).hexdigest()
    tools_path.write_text(json.dumps(tools), encoding="utf-8")
    tools_ref["sha256"] = hashlib.sha256(tools_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="incident-first"):
        milestone_summary_v6_3(source, tmp_path)
