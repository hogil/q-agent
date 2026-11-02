"""Bounded read-only projection of ROOT-accepted V6.4 evidence capsules."""
from __future__ import annotations

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


PROOF_STATUS = {
    "corrected_future135": "ROOT_limited_acceptance_corrected_V4_future135_confirmation",
    "official_numeric_Trend": "ROOT_limited_acceptance_official_Trend_confirmation_arithmetic_only",
    "image_Tools": "ROOT_limited_acceptance_actual_image_asset_and_similarity_Tools",
    "resource_replay_v3": "ROOT_limited_acceptance_context_role_v3_resource_replay_only",
    "local_agent_v5": "ROOT_reviewed_control_flow_completed_task_answer_NOT_accepted",
}


def _finite(value: Any, label: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"{label} outside permitted range")
    return result


def _read_json(ref: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("accepted proof must contain a JSON object")
    return value


def milestone_summary_v6_4(source: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    """Verify the V6.4 ROOT capsule and expose only compact, bounded facts."""
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_4.v1":
        raise ValueError("unexpected V6.4 publication capsule schema")
    _bounded(source)
    if source.get("synthetic") is not True or source.get("production") is not False or source.get("new_actions") != 0:
        raise ValueError("V6.4 is synthetic, nonproduction, and has no new actions")
    if source.get("current_serving_world") != "full-v3" or source.get("corrected_V4_future_model_integrated_in_current_serving") is not False:
        raise ValueError("corrected V4 must remain separate from current serving")
    if source.get("platform_complete") is not False:
        raise ValueError("platform completion is not established")

    proofs = source.get("proofs")
    if not isinstance(proofs, dict) or set(proofs) != set(PROOF_STATUS):
        raise ValueError("exactly five ROOT-accepted V6.4 proofs are required")
    _proofs(proofs, root)
    objects = {key: _read_json(ref) for key, ref in proofs.items()}
    for key, item in objects.items():
        if item.get("status") != PROOF_STATUS[key]:
            raise ValueError(f"unexpected ROOT proof status: {key}")

    future = objects["corrected_future135"]
    future_metrics = future.get("metrics_balanced_normalized_MAE", {})
    tabm = _finite(future_metrics.get("TabM-flat"), "V4 TabM validation metric")
    mlp = _finite(future_metrics.get("MLP-full"), "V4 MLP validation metric")
    if (future.get("selected_on_validation") != "TabM-flat" or future.get("rows") != 3456
            or future.get("calendar_weeks") != 18 or future.get("targets") != 135 or future.get("worlds") != 1
            or future.get("production") is not False or future.get("automatic_promotion") is not False
            or future.get("confirmation_reselection") is not False):
        raise ValueError("corrected V4 confirmation scope or selection changed")
    if future.get("general_LLM_quality_established") is not False or source.get("corrected_V4_future_model_integrated_in_current_serving") is not False:
        raise ValueError("V4 evidence cannot imply general quality or current serving")
    _strings(future.get("limitations"))

    trend = objects["official_numeric_Trend"]
    trend_ap = trend.get("AP", {})
    mixer_ap = _finite(trend_ap.get("hf_patchtsmixer"), "Trend PatchTSMixer AP", maximum=1)
    cnn_ap = _finite(trend_ap.get("cnn1d"), "Trend CNN AP", maximum=1)
    fpr1 = trend.get("mixer_metrics", {}).get("FPR1", {})
    trend_recall = _finite(fpr1.get("recall"), "Trend low-FPR recall", maximum=1)
    if (trend.get("nine_fits") is not True or trend.get("rows") != 4864 or trend.get("production") is not False
            or trend.get("high_performance_established") is not False or trend.get("automatic_promotion") is not False
            or fpr1.get("threshold") is None):
        raise ValueError("official Trend study scope or limitations changed")
    _strings(trend.get("limitations"))

    image = objects["image_Tools"]
    expected_sequence = ["incidents.search", "material.resolve", "image.evidence(list)", "image.evidence(search_unknown)"]
    if (image.get("actual_Tool_sequence") != expected_sequence or image.get("DINO_CPU_forwards") != 1
            or image.get("hits") != 5 or image.get("gallery_rows") != 18720
            or image.get("LLM_calls") != 0 or image.get("MES_commits") != 0
            or image.get("GPU_calls") != 0 or image.get("morphology_registered") is not False
            or image.get("production") is not False):
        raise ValueError("image evidence is limited to the accepted read-only Tool sequence")
    _strings(image.get("limitations"))

    qwen = objects["resource_replay_v3"]
    returns = qwen.get("completed_returns", {})
    if (returns != {"baseline": 3, "bounded": 3, "total": 6} or qwen.get("new_Tool_calls") != 0
            or qwen.get("new_actions") != 0 or qwen.get("external_API_calls") != 0 or qwen.get("production") is not False):
        raise ValueError("V3 cached Qwen replay counts or boundary changed")
    audit_ref = qwen.get("independent_audit")
    if not isinstance(audit_ref, dict):
        raise ValueError("Qwen replay independent audit is required")
    _proofs({"audit": audit_ref}, root)
    audit = _read_json(audit_ref)
    if audit.get("status") != "PASS_receipt_lineage_source_and_return_identity_audit":
        raise ValueError("Qwen replay independent audit must pass")
    _strings(qwen.get("limits"))

    agent = objects["local_agent_v5"]
    if (agent.get("actual_LLM_returns") != 4 or agent.get("actual_new_Tool_calls") != 7
            or agent.get("first_business_tool") != "incidents.search" or agent.get("last_LLM") != "answer"
            or agent.get("new_actions") != 0 or agent.get("compiled_claims") != 0
            or agent.get("task_answer_accepted") is not False or agent.get("production") is not False):
        raise ValueError("V5 local-agent control-flow proof must retain its unaccepted answer boundary")
    if agent.get("general_LLM_quality_established") is not False:
        raise ValueError("one run cannot establish general LLM quality")
    failure = agent.get("failure")
    if not isinstance(failure, str) or not failure:
        raise ValueError("local-agent answer failure must remain visible")

    workflow = [
        {"stage": "Router", "status": "V5 run returned; this single run does not establish general quality"},
        {"stage": "incident DB", "status": "first business Tool", "first_business_tool": agent["first_business_tool"]},
        {"stage": "Tools", "status": f"{agent['actual_new_Tool_calls']} actual Tool calls in the V5 run"},
        {"stage": "Judge", "status": "requested requery was suppressed by contradictory Judge flow"},
        {"stage": "Answer", "status": "returned, but task answer was not accepted"},
    ]
    proof_rows = [
        {"id": key, "status": objects[key]["status"], "sha256": proofs[key]["sha256"], "file": Path(proofs[key]["path"]).name}
        for key in ("corrected_future135", "official_numeric_Trend", "image_Tools", "resource_replay_v3", "local_agent_v5")
    ]
    result = {
        "schema_id": "qagent.skip_research_milestone.v6.4",
        "status": "accepted_limited_publication_only",
        "created_at_utc": source.get("at_utc"),
        "synthetic": True,
        "production": False,
        "new_actions": 0,
        "platform_complete": False,
        "current_serving_world": "full-v3",
        "proof_count": len(proof_rows),
        "proofs": proof_rows,
        "workflow": workflow,
        "workflow_status": "V5 control flow completed, but its task answer was not accepted; the platform remains incomplete.",
        "future135": {"selected_model": "TabM-flat", "confirmation_balanced_normalized_mae": tabm,
            "MLP_confirmation_balanced_normalized_mae": mlp, "rows": 3456, "calendar_weeks": 18,
            "targets": 135, "worlds": 1, "integrated_in_current_serving": False,
            "limits": list(future["limitations"])},
        "numeric_trend": {"fits": 9, "rows": trend["rows"], "patchtsmixer_ap": mixer_ap,
            "cnn1d_ap": cnn_ap, "fpr1_recall": trend_recall, "high_performance_established": False,
            "limits": list(trend["limitations"])},
        "image_tools": {"tool_sequence": expected_sequence, "cpu_forwards": image["DINO_CPU_forwards"],
            "hits": image["hits"], "gallery_rows": image["gallery_rows"],
            "LLM_calls": 0, "MES_commits": 0, "GPU_calls": 0,
            "morphology_registered": False, "limits": list(image["limitations"])},
        "qwen_resource_replay": {"baseline_returns": 3, "bounded_returns": 3, "total_returns": 6,
            "new_Tool_calls": 0, "new_actions": 0, "external_API_calls": 0,
            "limits": list(qwen["limits"])},
        "local_agent_v5": {"LLM_returns": 4, "Tool_calls": 7, "first_business_tool": agent["first_business_tool"],
            "last_LLM": "answer", "new_actions": 0, "compiled_claims": 0,
            "task_answer_accepted": False, "failure": failure},
        "limits": list(source.get("notes", [])) + [
            "Evidence types are separate synthetic/public studies; none establish production or semiconductor performance.",
            "Trend high-sensitivity performance is unresolved; at the validation-calibrated 1% FPR point, recall is low.",
            "Image Tool execution is not a morphology, normality, or cause finding.",
            "V5 Answer is not accepted; the V4 TabM future model is not integrated into current serving.",
        ],
    }
    _bounded(result)
    return result
