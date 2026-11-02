"""Read-only, bounded projection of ROOT-accepted V6.3 evidence capsules."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from .cohort_milestone_summary import _bounded, _count, _strings
    from .cohort_milestone_summary_v6 import _proofs
except ImportError:
    from cohort_milestone_summary import _bounded, _count, _strings
    from cohort_milestone_summary_v6 import _proofs


PROOF_KEYS = {
    "qwen_role_replay", "synthetic_tools_mes", "public_bloodmnist", "sem_v2", "qwen_load_mode"
}
PROOF_STATUS = {
    "qwen_role_replay": "ROOT_limited_acceptance_bounded_resource_replay_only",
    "synthetic_tools_mes": "ROOT_limited_acceptance_actual_synthetic_Tools_and_dummy_MES_only",
    "public_bloodmnist": "ROOT_limited_acceptance_public_BloodMNIST_fixed_benchmark",
    "sem_v2": "ROOT_limited_acceptance_SEM_v2_synthetic_proxy_confirmation_and_control",
    "qwen_load_mode": "ROOT_limited_acceptance_4B_load_mode_probe_only",
}
GIB = 1024 ** 3


def _false(value: Any, message: str) -> None:
    if value is not False:
        raise ValueError(message)


def _positive_int(value: Any, message: str) -> int:
    _count(value)
    if value <= 0:
        raise ValueError(message)
    return value


def _positive_bytes(value: Any, message: str) -> int:
    if type(value) is not int or value <= 0 or value > 10**15:
        raise ValueError(message)
    return value


def _finite(value: Any, message: str, *, low: float | None = None, high: float | None = None) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(message)
    result = float(value)
    if (low is not None and result < low) or (high is not None and result > high):
        raise ValueError(message)
    return result


def _json_ref(name: str, descriptor: Any, root: Path) -> dict[str, Any]:
    _proofs({name: descriptor}, root)
    return json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))


def _trace_first_tool(descriptor: Any, tools_proof: dict[str, Any], root: Path) -> str:
    if not isinstance(descriptor, dict) or set(descriptor) != {"path", "sha256", "source_proof"}:
        raise ValueError("workflow trace descriptor shape invalid")
    trace = Path(descriptor["path"])
    if not trace.is_absolute() or not trace.resolve().is_relative_to(root.resolve()) or trace.suffix.lower() != ".jsonl":
        raise ValueError("workflow trace must be an allowlisted lab JSONL asset")
    if descriptor["source_proof"] != "synthetic_tools_mes.collect":
        raise ValueError("workflow trace must be bound to accepted Tools proof")
    collect = tools_proof.get("collect")
    if not isinstance(collect, dict) or set(collect) != {"path", "sha256"}:
        raise ValueError("accepted Tools proof does not bind its collect report")
    collect_report = _json_ref("collect report", collect, root)
    linked = collect_report.get("call_journal")
    if linked != {"path": descriptor["path"], "sha256": descriptor["sha256"]}:
        raise ValueError("workflow trace descriptor differs from accepted collect report")
    if not trace.is_file() or trace.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("workflow trace missing or oversized")
    digest = hashlib.sha256()
    with trace.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != descriptor["sha256"].lower():
        raise ValueError("workflow trace hash mismatch")
    with trace.open("r", encoding="utf-8") as stream:
        first_line = stream.readline(1024 * 1024)
    if not first_line:
        raise ValueError("workflow trace is empty")
    first = json.loads(first_line)
    if first.get("tool") != "incidents.search" or first.get("result", {}).get("tool") != "incidents.search":
        raise ValueError("incident-first business Tool requirement failed")
    return "incidents.search"


def milestone_summary_v6_3(source: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    """Validate the new publication capsule and project five bounded ROOT proofs."""
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_3.v1":
        raise ValueError("unexpected V6.3 publication capsule schema")
    _bounded(source)
    if source.get("status") != "ROOT_limited_acceptance_component_bundle":
        raise ValueError("V6.3 ROOT acceptance bundle required")
    if source.get("synthetic") is not True or source.get("production") is not False:
        raise ValueError("synthetic, nonproduction publication required")
    if source.get("new_actions") != 0 or type(source.get("new_actions")) is not int:
        raise ValueError("publication contains no actions")
    _false(source.get("new_full_local_agent_run_completed"), "new full Router-to-Answer run must remain unclaimed")
    proofs = source.get("proofs")
    if not isinstance(proofs, dict) or set(proofs) != PROOF_KEYS:
        raise ValueError("exactly five ROOT acceptance capsules are required")
    _proofs(proofs, root)
    objects = {key: _json_ref(key, ref, root) for key, ref in proofs.items()}
    for key, item in objects.items():
        if item.get("status") != PROOF_STATUS[key]:
            raise ValueError(f"unexpected ROOT proof status: {key}")

    qwen = objects["qwen_role_replay"]
    if qwen.get("completed_returns") != {"baseline": 2, "bounded": 3, "total": 5}:
        raise ValueError("Qwen replay completion counts changed")
    _false(qwen.get("baseline_answer_completed"), "baseline Answer remains unfinished")
    if qwen.get("bounded_all_three_archive_text_and_tokens_identical") is not True:
        raise ValueError("bounded replay identity audit required")
    for key in ("new_Tool_calls", "new_actions", "external_API_calls"):
        if qwen.get(key) != 0 or type(qwen.get(key)) is not int:
            raise ValueError("historical replay must have zero new Tools/actions/API calls")
    _false(qwen.get("general_LLM_quality_established"), "general LLM quality is not established")
    qwen_resources = qwen.get("resources", {})
    bounded_reserved = _finite(qwen_resources.get("bounded_peak_reserved_gib"), "Qwen replay peak reserved memory invalid", low=0)
    baseline_crossing = _finite(qwen_resources.get("baseline_abort_observed_reserved_gib"), "Qwen baseline cap sample invalid", low=0)
    if not isinstance(qwen.get("limits"), list) or not qwen["limits"]:
        raise ValueError("Qwen replay limitations required")
    role_latency = qwen.get("instrumented_common_role_latency", {})
    latency_summary = {}
    for role in ("router", "judge"):
        latency = role_latency.get(role, {})
        baseline_seconds = _finite(latency.get("baseline_seconds"), "Qwen baseline role latency invalid", low=0)
        bounded_seconds = _finite(latency.get("bounded_seconds"), "Qwen bounded role latency invalid", low=0)
        if latency.get("direction") != "slower" or bounded_seconds <= baseline_seconds:
            raise ValueError("instrumented common roles must retain slower direction")
        latency_summary[role] = {"baseline_seconds": baseline_seconds, "bounded_seconds": bounded_seconds}

    tools = objects["synthetic_tools_mes"]
    if tools.get("actual_dispatches") != 25 or type(tools.get("actual_dispatches")) is not int:
        raise ValueError("the accepted scripted Tool dispatch count must remain 25")
    names = tools.get("unique_Tool_names")
    if not isinstance(names, list) or len(names) != 13 or len(set(names)) != 13:
        raise ValueError("accepted 13-tool registry count required")
    if tools.get("LLM_calls") != 0 or type(tools.get("LLM_calls")) is not int:
        raise ValueError("scripted Tool proof must remain separate from LLM execution")
    _false(tools.get("production"), "dummy MES proof cannot claim production")
    _false(tools.get("source_DB_or_Yield_rewrite"), "source DB/Yield rewrite is not allowed")
    actions = tools.get("actions", {})
    hold = actions.get("HOLD_BLOCK_DISPATCH_REQUEST_METROLOGY", {})
    release = actions.get("RELEASE_UNBLOCK", {})
    if hold.get("wafers") != 12 or hold.get("transactions") != 1 or release.get("wafers") != 12 or release.get("transactions") != 1:
        raise ValueError("accepted dummy HOLD/RELEASE receipts differ from expected scope")
    mes_state = tools.get("current_dummy_MES_state", {})
    if mes_state.get("active_holds") != 0 or mes_state.get("active_blocks") != 0:
        raise ValueError("dummy MES must show no active HOLD or dispatch block after release")
    _positive_int(mes_state.get("transactions"), "dummy MES transaction count invalid")
    seed = _json_ref("dummy qualification seed", tools.get("dummy_qualification_seed"), root)
    if seed.get("status") != "explicit_dummy_state_seeded" or seed.get("source_DB_or_Yield_rewrite") is not False:
        raise ValueError("seeded dummy qualification evidence must remain explicit")
    first_business_tool = _trace_first_tool(source.get("workflow_trace"), tools, root)

    blood = objects["public_bloodmnist"]
    if blood.get("public_dataset") != "BloodMNIST" or blood.get("selected_arm_frozen") != "CNN":
        raise ValueError("fixed public BloodMNIST validation selection required")
    test_rows = _positive_int(blood.get("test_rows"), "BloodMNIST test row count invalid")
    _false(blood.get("production"), "public benchmark is not production")
    _false(blood.get("FAB_validation"), "public benchmark is not FAB validation")
    _false(blood.get("clinical_validation"), "public benchmark is not clinical validation")
    pretest = _json_ref("BloodMNIST validation selection gate", blood.get("validation_selection_gate"), root)
    prediction_gate = _json_ref("BloodMNIST prediction-before-label gate", blood.get("predictions_before_labels_gate"), root)
    audit = _json_ref("BloodMNIST independent arithmetic audit", blood.get("independent_audit"), root)
    if pretest.get("test_images_opened") is not False or pretest.get("test_labels_opened") is not False:
        raise ValueError("validation selection must precede test images and labels")
    if prediction_gate.get("test_labels_opened") is not False or prediction_gate.get("status") != "ROOT_all_six_predictions_accepted_before_test_labels":
        raise ValueError("BloodMNIST predictions must be frozen before test labels")
    if audit.get("status") != "PASS_independent_saved_array_recomputation":
        raise ValueError("independent BloodMNIST arithmetic audit required")
    blood_metrics = blood.get("metrics", {})
    audit_metrics = audit.get("metrics", {})
    metrics = {}
    for arm, audit_arm in (("CNN", "CNN-ensemble"), ("DINO", "DINO-ensemble")):
        row = blood_metrics.get(arm, {})
        checked = audit_metrics.get(audit_arm, {})
        auc = _finite(row.get("macro_auc"), "BloodMNIST AUC invalid", low=0, high=1)
        accuracy = _finite(row.get("accuracy"), "BloodMNIST accuracy invalid", low=0, high=1)
        if auc != checked.get("macro_auc") or accuracy != checked.get("accuracy"):
            raise ValueError("BloodMNIST display metrics differ from independent audit")
        metrics[arm] = {"macro_auc": auc, "accuracy": accuracy}

    sem = objects["sem_v2"]
    if sem.get("families") != ["single", "all13"] or sem.get("seeds") != [17, 29]:
        raise ValueError("SEM comparison arms/seeds changed")
    _false(sem.get("real_SEM_validation"), "synthetic SEM proxy cannot claim real-SEM validation")
    _false(sem.get("production"), "synthetic SEM proxy cannot claim production")
    candidate = sem.get("selected_serving_candidate", {})
    if candidate.get("arm") != "all13" or candidate.get("seeds") != [17, 29] or candidate.get("registered") is not False:
        raise ValueError("SEM serving candidate must remain unregistered and validation selected")
    evaluation = _json_ref("SEM confirmation evaluation", sem.get("evaluation"), root)
    sem_audit = _json_ref("SEM independent arithmetic audit", sem.get("independent_audit"), root)
    gate = _json_ref("SEM prediction-before-label gate", sem.get("prediction_before_label_gate"), root)
    if sem_audit.get("status") != "passed_source_provenance_and_arithmetic_recompute":
        raise ValueError("independent SEM saved-array audit required")
    if gate.get("status") != "ROOT_accepted4_image_predictions_before_confirmation_label_read" or gate.get("labels_parsed_by_ROOT_before_gate") is not False or gate.get("OUT_values_read") is not False:
        raise ValueError("SEM prediction-before-label gate required")
    reports = evaluation.get("reports")
    if not isinstance(reports, list) or len(reports) != 4 or evaluation.get("threshold") != 0.5:
        raise ValueError("SEM four-model fixed-threshold evaluation required")
    aps = []
    threshold_errors = False
    for row in reports:
        aps.append(_finite(row.get("local_AP"), "SEM local AP invalid", low=0, high=1))
        aps.append(_finite(row.get("repetition_AP"), "SEM repetition AP invalid", low=0, high=1))
        aps.append(_finite(row.get("planned13_any_local_AP"), "SEM planned-area AP invalid", low=0, high=1))
        for field in ("TP", "FP", "FN"):
            if not isinstance(row.get(field), list) or len(row[field]) != 2:
                raise ValueError("SEM threshold confusion counts must cover both targets")
            for value in row[field]:
                _count(value)
                if field in ("FP", "FN") and value > 0:
                    threshold_errors = True
    if not threshold_errors:
        raise ValueError("SEM fixed-threshold false positives/negatives must remain visible")
    local_mark = sem.get("local_mark_control", {})
    local_models = local_mark.get("models")
    if not isinstance(local_models, list) or len(local_models) != 4 or local_mark.get("validation_rows") != 3640:
        raise ValueError("SEM local-mark validation ablation scope invalid")
    if any(row.get("control_local_positive_rate_at_fixed_threshold") != 0.0 or row.get("threshold") != 0.5 for row in local_models):
        raise ValueError("SEM local-mark input-dependence control changed")
    sem_summary = {
        "confirmation_rows": _positive_int(sem.get("confirmation_rows"), "SEM confirmation row count invalid"),
        "confirmation_wafers": _positive_int(sem.get("confirmation_wafers"), "SEM confirmation wafer count invalid"),
        "planned_sites": _positive_int(sem.get("planned_sites"), "SEM planned-site count invalid"),
        "unobserved_chips_per_wafer": _positive_int(sem.get("unobserved_chips_per_wafer"), "SEM unknown-chip count invalid"),
        "families": list(sem["families"]), "seeds": list(sem["seeds"]),
        "local_ap_min": min(aps), "local_ap_max": max(aps), "threshold": evaluation["threshold"],
        "fixed_threshold_errors_present": threshold_errors,
        "local_mark_validation_rows": local_mark["validation_rows"],
        "local_mark_control_positive_rate": 0.0,
        "serving_registered": False,
        "limits": list(sem.get("limits", [])),
    }

    loadmode = objects["qwen_load_mode"]
    _false(loadmode.get("production"), "load-only result cannot claim production")
    _false(loadmode.get("inference_quality_established"), "load-only probe is not inference quality")
    if loadmode.get("generations") != 0 or loadmode.get("explicit_forwards") != 0:
        raise ValueError("load-mode probe must contain no generation or forward calls")
    load_audit = _json_ref("Qwen load-mode arithmetic audit", loadmode.get("independent_audit"), root)
    if load_audit.get("status") != "PASS_stdlib_receipt_and_175_source_pin_audit" or load_audit.get("freeze", {}).get("mismatches") != 0:
        raise ValueError("independent Qwen load-mode audit required")
    modes = loadmode.get("modes", {})
    if set(modes) != {"async0-baseline-01", "async1-sequential-01"}:
        raise ValueError("both fixed Qwen load-mode runs are required")
    peak_alloc = {}
    postload_alloc = {}
    process_peak_rss = {}
    for run_id, item in modes.items():
        counters = item.get("counters", {})
        for field in ("allocated_bytes", "peak_allocated_bytes", "peak_reserved_bytes", "process_peak_rss_bytes"):
            _positive_bytes(counters.get(field), f"Qwen memory counter missing: {field}")
        peak_alloc[run_id] = round(counters["peak_allocated_bytes"] / GIB, 3)
        postload_alloc[run_id] = round(counters["allocated_bytes"] / GIB, 3)
        process_peak_rss[run_id] = round(counters["process_peak_rss_bytes"] / GIB, 3)
    return {
        "schema_id": "qagent.skip_research_milestone.v6.3",
        "status": "accepted_limited_publication_only",
        "created_at_utc": source.get("created_at_utc"),
        "synthetic": True,
        "production": False,
        "new_actions": 0,
        "new_full_local_agent_run_completed": False,
        "proof_count": len(proofs),
        "proofs": [
            {"id": key, "status": objects[key]["status"], "sha256": proofs[key]["sha256"], "file": Path(proofs[key]["path"]).name}
            for key in ("qwen_role_replay", "synthetic_tools_mes", "public_bloodmnist", "sem_v2", "qwen_load_mode")
        ],
        "workflow": [
            {"stage": "Router", "status": "not run in the scripted 25-Tool proof"},
            {"stage": "incident DB", "status": "first business Tool in accepted scripted trace", "first_business_tool": first_business_tool},
            {"stage": "Tools", "status": "25 scripted typed dispatches; separate from Qwen replay"},
            {"stage": "Judge", "status": "not connected in the scripted 25-Tool proof"},
            {"stage": "Answer", "status": "not connected in the scripted 25-Tool proof"},
        ],
        "workflow_status": "new full local Router-to-Answer execution has not been run; the historical Qwen replay is a separate experiment",
        "qwen_role_replay": {
            "completed_returns": 5, "baseline_returns": 2, "bounded_returns": 3,
            "baseline_answer_completed": False,
            "bounded_text_and_tokens_identical": True,
            "bounded_peak_reserved_gib": bounded_reserved,
            "baseline_first_cap_crossing_observed_gib": baseline_crossing,
            "instrumented_common_role_latency": latency_summary,
            "new_tool_calls": 0, "new_actions": 0,
            "limits": list(qwen["limits"]),
        },
        "tools_mes": {
            "dispatches": tools["actual_dispatches"], "tool_name_count": len(names),
            "first_business_tool": first_business_tool, "llm_calls": 0,
            "hold_wafer_count": hold["wafers"], "release_wafer_count": release["wafers"],
            "active_holds_after_release": mes_state["active_holds"], "active_blocks_after_release": mes_state["active_blocks"],
            "transactions": mes_state["transactions"],
            "qualification_pass_basis": "explicitly seeded dummy administrative evidence",
            "dispatch_admission_controller_verified": False,
            "production": False, "limits": list(tools.get("limits", [])),
        },
        "bloodmnist": {
            "public_dataset": "BloodMNIST", "selected_arm": blood["selected_arm_frozen"], "test_rows": test_rows,
            "metrics": metrics, "independent_arithmetic_audit": True,
            "production": False, "FAB_validation": False, "clinical_validation": False,
            "limits": list(blood.get("limits", [])),
        },
        "sem_v2": sem_summary,
        "qwen_load_mode": {
            "mode": "load only; no generation/forward",
            "peak_allocated_gib": peak_alloc,
            "postload_allocated_gib": postload_alloc,
            "process_peak_rss_gib": process_peak_rss,
            "comparison_claim": "two single fixed-order measurements; descriptive only, not causal",
            "inference_quality_established": False,
            "limits": list(loadmode.get("limits", [])),
        },
        "limits": list(source.get("limits", [])),
    }
