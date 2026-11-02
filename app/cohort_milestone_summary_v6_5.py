"""Bounded read-only projection of the ROOT-accepted V6.5 evidence capsule."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

try:
    from .cohort_milestone_summary import _bounded, _count, _strings
    from .cohort_milestone_summary_v6 import _proofs
except ImportError:
    from cohort_milestone_summary import _bounded, _count, _strings
    from cohort_milestone_summary_v6 import _proofs


PROOF_STATUS = {
    "original_CSV_Trend": "ROOT_limited_acceptance_original_CSV_Trend_retrospective_benchmark",
    "spread_Trend_V2": "ROOT_limited_acceptance_official_Trend_V2_spread_input_confirmation",
    "actual_ActionV6": "ROOT_limited_acceptance_actual_synthetic_ActionV6_chain",
    "local_RO6": "ROOT_reviewed_actual_RO6_structure_bound_claims_task_coverage_PARTIAL",
    "image_RO7": "ROOT_reviewed_RO7_imageTools_completed_overall_LLM_failed_budget",
}


def _finite(value: Any, label: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"{label} outside permitted range")
    return result


def _read_json(ref: dict[str, Any]) -> dict[str, Any]:
    import json

    value = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("accepted proof must contain a JSON object")
    return value


def _linked_json(artifact: dict[str, Any], names: tuple[str, ...], root: Path) -> dict[str, dict[str, Any]]:
    refs = {name: artifact[name] for name in names if name in artifact}
    if len(refs) != len(names):
        raise ValueError("required linked proof is missing")
    _proofs(refs, root)
    return {name: _read_json(ref) for name, ref in refs.items()}


def milestone_summary_v6_5(source: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    """Verify the V6.5 capsule and expose bounded, separate study facts."""
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_5.v1":
        raise ValueError("unexpected V6.5 publication capsule schema")
    _bounded(source)
    if source.get("synthetic") is not True or source.get("production") is not False:
        raise ValueError("V6.5 records synthetic, nonproduction evidence only")
    _count(source.get("viewer_actions"))
    _count(source.get("recorded_synthetic_action_commits"))
    if source["viewer_actions"] != 0 or source["recorded_synthetic_action_commits"] != 2:
        raise ValueError("viewer actions and saved synthetic commits must remain separate and exact")
    if (source.get("current_serving_world") != "full-v3"
            or source.get("corrected_V4_future_model_integrated_in_current_serving") is not False
            or source.get("platform_complete") is not False):
        raise ValueError("current serving and platform completion must remain unchanged")

    proofs = source.get("proofs")
    if not isinstance(proofs, dict) or set(proofs) != set(PROOF_STATUS):
        raise ValueError("exactly five ROOT-accepted V6.5 proofs are required")
    _proofs(proofs, root)
    objects = {key: _read_json(ref) for key, ref in proofs.items()}
    for key, item in objects.items():
        if item.get("status") != PROOF_STATUS[key]:
            raise ValueError(f"unexpected ROOT proof status: {key}")

    csv = objects["original_CSV_Trend"]
    if (csv.get("retrospective") is not True or csv.get("synthetic") is not True
            or csv.get("production") is not False or csv.get("current_fullworld_Trend_classifier_promoted") is not False
            or csv.get("new_fits") != 9 or csv.get("selected_on_validation") != "cnn1d"
            or csv.get("no_test_reselection") is not True or csv.get("test_rows") != 1500
            or csv.get("test_positive") != 750 or csv.get("unknown") != 0):
        raise ValueError("original CSV Trend must remain a retrospective synthetic test result")
    csv_support = _linked_json(csv, ("scores", "independent_validation", "independent_test"), root)
    methods = csv.get("methods", {})
    if not isinstance(methods, dict) or set(methods) != {"cnn1d", "hf_patchtst", "hf_patchtsmixer"}:
        raise ValueError("CSV retrospective comparison requires exactly the three saved model methods")
    model_rows = []
    for name in ("cnn1d", "hf_patchtst", "hf_patchtsmixer"):
        method = methods[name]
        fixed05 = method.get("fixed05", {})
        times = method.get("fit_seconds")
        if not isinstance(times, list) or len(times) != 3:
            raise ValueError("CSV method fit_seconds must retain the three saved seed runs")
        parameters = method.get("parameters")
        if type(parameters) is not int or parameters <= 0:
            raise ValueError("CSV method parameter count must be a positive integer")
        if fixed05.get("threshold") != 0.5:
            raise ValueError("CSV fixed05 F1 must use the prespecified 0.5 reporting threshold")
        model_rows.append({
            "model": name,
            "selected_on_validation": name == "cnn1d",
            "AP": _finite(method.get("AP"), f"{name} retrospective AP", maximum=1),
            "fixed05_F1": _finite(fixed05.get("F1"), f"{name} F1 at fixed 0.5", maximum=1),
            "parameters": parameters,
            "fit_seconds_min": min(_finite(value, f"{name} seed fit time") for value in times),
            "fit_seconds_max": max(_finite(value, f"{name} seed fit time") for value in times),
        })
    cnn = methods["cnn1d"]
    csv_ap = _finite(cnn.get("AP"), "retrospective CNN1D AP", maximum=1)
    fpr1 = cnn.get("validation_calibrated_FPR1_test", {})
    csv_threshold = _finite(fpr1.get("threshold"), "validation-calibrated threshold", maximum=1)
    csv_test_fpr = _finite(fpr1.get("FPR"), "test FPR", maximum=1)
    if fpr1.get("rows") != 1500 or csv_test_fpr <= 0.01:
        raise ValueError("retrospective test FPR must remain above 1% at the validation-calibrated threshold")
    _strings(csv.get("limitations"))

    spread = objects["spread_Trend_V2"]
    if (spread.get("production") is not False or spread.get("new_fits") != 6
            or spread.get("selected_for_future_serving_design_only") != "B128spread_based_on_validation_only"
            or spread.get("automatic_promotion") is not False or spread.get("current_fullworld_trend_model_changed") is not False):
        raise ValueError("spread Trend V2 remains a validation-selected design candidate only")
    spread_support = _linked_json(spread, ("independent_audit", "fit_audit"), root)
    if (spread_support["independent_audit"].get("status") != "PASS_independent_V2_after_P1_score_arithmetic"
            or spread_support["fit_audit"].get("status") != "PASS_independent_validation_arithmetic_and6_ROOT_processes"):
        raise ValueError("spread Trend independent audits must pass")
    validation_ap = _finite(spread.get("validation_AP", {}).get("B128spread"), "spread V2 validation AP", maximum=1)
    confirmation = spread.get("confirmation", {})
    ap_a = _finite(confirmation.get("A128mean", {}).get("AP"), "A128 confirmation AP", maximum=1)
    ap_b = _finite(confirmation.get("B128spread", {}).get("AP"), "B128 confirmation AP", maximum=1)
    ap_c = _finite(confirmation.get("C512spread", {}).get("AP"), "C512 confirmation AP", maximum=1)
    primary = spread.get("comparisons", {}).get("primary_B_minus_A", {})
    delta = _finite(primary.get("delta_AP"), "primary spread AP difference", minimum=-1, maximum=1)
    ci = primary.get("CI95")
    if not isinstance(ci, list) or len(ci) != 2:
        raise ValueError("primary spread AP comparison requires its saved interval")
    ci = [_finite(value, "primary spread confidence limit", minimum=-1, maximum=1) for value in ci]
    secondary_ci = spread.get("comparisons", {}).get("secondary_C_minus_B", {}).get("CI95")
    if not isinstance(secondary_ci, list) or len(secondary_ci) != 2:
        raise ValueError("secondary C-versus-B interval must remain visible")
    secondary_ci = [_finite(value, "secondary spread confidence limit", minimum=-1, maximum=1) for value in secondary_ci]
    if not (ci[0] <= delta <= ci[1]) or not (secondary_ci[0] <= 0 <= secondary_ci[1]):
        raise ValueError("spread comparison intervals are inconsistent or overstate the secondary result")
    _strings(spread.get("limitations"))

    action = objects["actual_ActionV6"]
    audit_ref = action.get("independent_audit")
    _proofs({"audit": audit_ref}, root)
    audit = _read_json(audit_ref)
    if audit.get("status") != "PASS" or audit.get("source", {}).get("freeze_binding_files") != 154:
        raise ValueError("ActionV6 independent audit must pass and preserve its 154 source bindings")
    if (action.get("synthetic") is not True or action.get("production") is not False
            or action.get("source_DB_or_Yield_rewritten") is not False
            or action.get("general_LLM_quality_established") is not False
            or action.get("viewer_actions") != 0 or action.get("actual_LLM_returns") != 8
            or action.get("actual_synthetic_action_commits") != 2 or action.get("hold_Wafers") != 12
            or action.get("requested_cells") != 624 or action.get("qualified_cells") != 624
            or action.get("recovery_UP_PASS") != 12 or action.get("released_Wafers") != 12
            or action.get("allowed_new_progress") != 12 or action.get("allowed_replay_new_progress") != 0
            or action.get("denied_new_progress") != 0 or action.get("denied_replay_after_release_new_progress") != 0
            or action.get("final_active_holds") != 0 or action.get("final_active_blocks") != 0
            or action.get("final_PASS_cells") != 624 or action.get("final_simulated_progress") != 12
            or action.get("audit_hash_chain_rows") != 7 or action.get("frozen_source_bindings") != 154):
        raise ValueError("ActionV6 synthetic ledger/action limits changed")

    ro6 = objects["local_RO6"]
    if (ro6.get("synthetic") is not True or ro6.get("production") is not False
            or ro6.get("actual_LLM_returns") != 4 or ro6.get("actual_Tool_calls") != 9
            or ro6.get("compiled_claims") != 5 or ro6.get("forecast_executed") is not True
            or ro6.get("current_OUT_feature_queries") != 0 or ro6.get("first_business_Tool") != "incidents.search"
            or ro6.get("last_LLM") != "answer" or ro6.get("task_answer_fully_accepted") is not False
            or ro6.get("new_actions") != 0):
        raise ValueError("RO6 partial task coverage must remain unaccepted")
    ro6_support = _linked_json(ro6, ("independent_audit",), root)
    if ro6_support["independent_audit"].get("status") != "STRUCTURE_AND_BOUND_NUMERIC_CLAIMS_ACCEPTED_TASK_COVERAGE_PARTIAL":
        raise ValueError("RO6 independent audit must preserve its partial coverage state")
    _strings(ro6.get("limitations"))

    ro7 = objects["image_RO7"]
    if (ro7.get("synthetic") is not True or ro7.get("production") is not False
            or ro7.get("actual_LLM_invocations") != 3 or ro7.get("actual_LLM_returns") != 2
            or ro7.get("actual_Tool_results") != 7 or ro7.get("image_list_rows") != 13
            or ro7.get("imaged_Wafers") != 1 or ro7.get("hits") != 5 or ro7.get("DINO_CPU_queries") != 1
            or ro7.get("Judge_Answer_completed") is not False
            or ro7.get("actual_Judge_input_tokens") != 6881 or ro7.get("max_input_tokens") != 6144
            or ro7.get("new_actions") != 0 or ro7.get("morphology_registered") is not False
            or ro7.get("image_retrieval_quality_established") is not False):
        raise ValueError("RO7 image Tool proof must retain its incomplete Judge/Answer boundary")
    ro7_support = _linked_json(ro7, ("independent_audit",), root)
    if ro7_support["independent_audit"].get("status") != "PASS_artifact_audit_imageTools_completed_overallRO7_failed_budget":
        raise ValueError("RO7 independent artifact audit must pass without upgrading Judge/Answer")
    _strings(ro7.get("limitations"))
    _strings(source.get("notes"))

    proof_rows = [
        {"id": key, "status": objects[key]["status"], "sha256": proofs[key]["sha256"], "file": Path(proofs[key]["path"]).name}
        for key in PROOF_STATUS
    ]
    workflow = [
        {"stage": "Router", "ro6": "4 LLM returns", "ro7": "2 returns / 3 invocations"},
        {"stage": "사고 DB", "ro6": "첫 업무 Tool: incidents.search", "ro7": "이미지 전용 proof에는 별도 상태 미기재"},
        {"stage": "Tools", "ro6": "9 calls · 요청 범위 일부", "ro7": "7 results · image listing/retrieval 완료"},
        {"stage": "Judge", "ro6": "검토 후 task coverage partial", "ro7": "미완료 · 입력 6,881 / 한도 6,144 tokens"},
        {"stage": "Answer", "ro6": "반환됐지만 전체 task answer 미수용", "ro7": "미완료 · 반환되지 않음"},
    ]
    result = {
        "schema_id": "qagent.skip_research_milestone.v6.5",
        "status": "accepted_limited_publication_only",
        "created_at_utc": source.get("at_utc"),
        "synthetic": True,
        "production": False,
        "viewer_actions": 0,
        "recorded_synthetic_action_commits": 2,
        "current_serving_world": "full-v3",
        "corrected_V4_future_model_integrated_in_current_serving": False,
        "platform_complete": False,
        "proof_count": len(proof_rows),
        "proofs": proof_rows,
        "workflow": workflow,
        "original_csv_trend": {
            "fits": 9, "selected_model": "cnn1d", "test_rows": 1500, "test_positive": 750,
            "unknown": 0, "retrospective": True, "test_already_exposed": True,
            "cnn1d_ap": csv_ap,
            "model_comparison": model_rows,
            "fpr1_test": {"threshold": csv_threshold, "test_fpr": csv_test_fpr, "rows": fpr1["rows"]},
            "limits": list(csv["limitations"]),
        },
        "spread_trend_v2": {
            "fits": 6, "rows": spread.get("rows"),
            "validation_selected_model": "B128spread_based_on_validation_only",
            "validation_ap": validation_ap,
            "confirmation_ap": {"A128mean": ap_a, "B128spread": ap_b, "C512spread": ap_c},
            "primary_B_minus_A_delta_ap": delta, "primary_B_minus_A_ci95": ci,
            "secondary_C_minus_B_ci95": secondary_ci,
            "automatic_promotion": False, "current_fullworld_trend_model_changed": False,
            "limits": list(spread["limitations"]),
        },
        "action_v6": {
            "root_stages": 9, "actual_LLM_returns": 8, "recorded_synthetic_action_commits": 2,
            "viewer_actions": 0, "hold_wafers": 12, "requested_cells": 624,
            "qualified_cells": 624, "recovery_up_pass": 12, "released_wafers": 12,
            "allowed_new_progress": 12, "allowed_replay_new_progress": 0,
            "denied_new_progress": 0, "denied_replay_after_release_new_progress": 0,
            "final_active_holds": 0, "final_active_blocks": 0, "final_pass_cells": 624,
            "final_simulated_progress": 12, "audit_hash_chain_rows": 7,
            "frozen_source_bindings": 154, "production": False,
            "source_DB_or_Yield_rewritten": False, "limits": list(action["limitations"]),
        },
        "local_RO6": {
            "actual_LLM_returns": 4, "actual_Tool_calls": 9, "compiled_claims": 5,
            "forecast_executed": True, "current_OUT_feature_queries": 0,
            "first_business_Tool": "incidents.search", "last_LLM": "answer",
            "task_answer_fully_accepted": False, "new_actions": 0,
            "limits": list(ro6["limitations"]),
        },
        "image_RO7": {
            "actual_LLM_invocations": 3, "actual_LLM_returns": 2, "actual_Tool_results": 7,
            "image_list_rows": 13, "imaged_Wafers": 1, "hits": 5, "DINO_CPU_queries": 1,
            "judge_answer_completed": False, "judge_input_tokens": 6881, "max_input_tokens": 6144,
            "judge_input_over_budget": True, "new_actions": 0,
            "morphology_registered": False, "image_retrieval_quality_established": False,
            "limits": list(ro7["limitations"]),
        },
        "final_scope_status": {
            "current_serving_world": "full-v3",
            "corrected_V4_future_model_integrated": False,
            "platform_complete": False,
            "synthetic": True,
            "production": False,
            "viewer_actions": 0,
            "recorded_synthetic_action_commits": 2,
        },
        "limits": list(source.get("notes", [])) + [
            "Five distinct saved records are presented separately; no runs or action counts are combined into one successful run.",
            "The CSV Trend test is retrospective with prior test exposure; it is not a new blinded confirmation.",
            "The spread Trend result is a validation-selected synthetic input-design candidate, not a current serving model or real-FAB claim.",
            "ActionV6 commits are isolated synthetic ledger records; the viewer executed zero actions and production MES was not touched.",
            "RO6 task coverage is partial. RO7 image retrieval completed, but Judge and Answer did not.",
        ],
    }
    _bounded(result)
    return result
