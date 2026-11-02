"""Bounded, read-only projection of ROOT-reviewed synthetic failure records."""
from pathlib import Path
from typing import Any

try:
    from .cohort_milestone_summary import _bounded, _strings
    from .cohort_milestone_summary_v6 import _proofs
except ImportError:
    from cohort_milestone_summary import _bounded, _strings
    from cohort_milestone_summary_v6 import _proofs


ROOT_REVIEWS = {
    "fullworld_evidence_v11": (
        "actual-evidence-V11-ROOT-failed-partial-review-v1.json",
        "1f970d1e61e5cfcb22ee0dd1d24526d13f42db5c2f527a679574bb3ffc055bc6",
        "ROOT_FAILED_PARTIAL_TOOLS_SUCCEEDED_JUDGE_ROUTER_DISAGREEMENT",
    ),
    "metrology_v2": (
        "actual-metrology-V2-ROOT-failed-review-v1.json",
        "7286b5ba731d266d2fe650453ac1e6a0427fa1d58016bcefac3c92002fc846ef",
        "ROOT_FAILED_INITIAL_ROUTER_GRAMMAR_ZERO_REQUESTS",
    ),
    "groupedq1_v5": (
        "groupedq1-V5-ROOT-rejection-v1.json",
        "b79d02e8a6e2da05141e131baa86b404720d957fdff89226da269dbf0e3e60d4",
        "ROOT_REJECTED_CACHED_NUMERICAL_AND_BF16_SPEED_GATES",
    ),
}
PRIOR_V66_CAPSULE = (
    "qagent-model-lab-v66-publication-capsule-v2.json",
    "39de741a8edaae024311d99444de2f01a03b2ebeb7a09ee65638ec2d11c3f0dc",
)


def _read(ref: dict[str, Any]) -> dict[str, Any]:
    import json

    value = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("ROOT review must be a JSON object")
    return value


def milestone_summary_v6_7(source: dict[str, Any] | None, root: Path,
                           prior_v66: dict[str, Any] | None) -> dict[str, Any] | None:
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_7.v1":
        raise ValueError("unexpected V6.7 publication capsule schema")
    _bounded(source)
    if source.get("status") != "prepared_from_ROOT_reviewed_records" or source.get("synthetic") is not True or source.get("production") is not False:
        raise ValueError("V6.7 must remain a draft sourced from ROOT-reviewed synthetic records")
    if not isinstance(prior_v66, dict) or prior_v66.get("schema_id") != "qagent.skip_research_milestone.v6.6" or prior_v66.get("proof_count") != 3:
        raise ValueError("the three V6.6 proof records must remain available")

    prior_ref = source.get("prior_milestone")
    _proofs({"prior_milestone": prior_ref}, root)
    prior_capsule = _read(prior_ref)
    if (Path(prior_ref["path"]).name != PRIOR_V66_CAPSULE[0]
            or prior_ref.get("sha256", "").lower() != PRIOR_V66_CAPSULE[1]
            or prior_capsule.get("schema_id") != "qagent.model_lab_publication_v6_6.v1"
            or not isinstance(prior_capsule.get("proofs"), dict) or len(prior_capsule["proofs"]) != 3):
        raise ValueError("V6.7 must link to the unchanged V6.6 capsule")

    refs = source.get("root_reviews")
    if not isinstance(refs, dict) or set(refs) != set(ROOT_REVIEWS):
        raise ValueError("exactly three ROOT-reviewed failure records are required")
    _proofs(refs, root)
    reviews = {key: _read(ref) for key, ref in refs.items()}
    for key, (filename, digest, status) in ROOT_REVIEWS.items():
        ref, review = refs[key], reviews[key]
        if Path(ref["path"]).name != filename or ref["sha256"].lower() != digest:
            raise ValueError("ROOT review source pin changed")
        if review.get("status") != status or review.get("reviewed_by") != "ROOT" or review.get("production") is not False:
            raise ValueError("ROOT review status or production boundary changed")

    v11 = reviews["fullworld_evidence_v11"]
    v11_summary = v11.get("summary", {})
    if (v11.get("whole_question_satisfied") is not False or v11.get("general_LLM_quality_established") is not False
            or v11_summary.get("actual_LLM_returns") != 4 or v11_summary.get("Tool_calls") != 11
            or v11_summary.get("evidence_facts") != 9 or v11_summary.get("Answer_executed") is not False
            or v11_summary.get("new_actions") != 0):
        raise ValueError("V11 partial run facts changed")
    findings = v11.get("manual_findings")
    _strings(findings)
    if not any("strict requery validator stopped execution" in item for item in findings):
        raise ValueError("V11 Router/Judge disagreement finding is missing")

    metrology = reviews["metrology_v2"]
    metrology_summary = metrology.get("summary", {})
    if (metrology.get("whole_task_satisfied") is not False or metrology.get("general_LLM_quality_established") is not False
            or metrology_summary.get("actual_LLM_returns") != 1 or metrology_summary.get("output_tokens") != 14
            or metrology_summary.get("supplementary_requests") != 0 or metrology_summary.get("new_intents") != 0
            or metrology_summary.get("new_audit_events") != 0
            or metrology_summary.get("metrology_execution_or_measurements_completed") is not False):
        raise ValueError("Metrology V2 failed-run facts changed")

    grouped = reviews["groupedq1_v5"]
    cached = grouped.get("cached_full_vocabulary_recomputed")
    if (grouped.get("numerical_gate_pass") is not False or grouped.get("speed_gate_pass") is not False
            or grouped.get("candidate_promoted") is not False
            or grouped.get("active_backend_unchanged") != "accepted full-query per-head FP32 V3"
            or not isinstance(cached, list) or len(cached) != 5):
        raise ValueError("GroupedQ V5 must remain rejected and unpromoted")
    failed_steps = sum(row.get("fixed_bounds_pass") is False for row in cached if isinstance(row, dict))
    if failed_steps != 4:
        raise ValueError("GroupedQ V5 cached-logit comparison count changed")
    _strings(source.get("limits"))
    if source.get("trend_raw_points_scope") != "all_3000_calibration_and_confirmation_charts":
        raise ValueError("Trend raw-point denominator scope must include all calibration and confirmation charts")

    result = {
        "schema_id": "qagent.skip_research_milestone.v6.7",
        "status": "prepared_from_ROOT_reviewed_records",
        "synthetic": True,
        "production": False,
        "prior_v66": prior_v66,
        "trend_raw_points_scope": source["trend_raw_points_scope"],
        "reviews": {
            "fullworld_evidence_v11": {
                "status": v11["status"], "llm_returns": 4, "tool_calls": 11, "evidence_facts": 9,
                "answer_executed": False, "new_actions": 0,
                "finding": "Judge requested sandbox_status; Router did not request fresh evidence, so strict requery stopped.",
                "whole_question_satisfied": False, "general_llm_quality_established": False,
            },
            "metrology_v2": {
                "status": metrology["status"], "llm_returns": 1, "output_tokens": 14,
                "json_parse_error": metrology_summary.get("JSON_parse_error"), "requests": 0,
                "new_intents": 0, "new_audit_events": 0, "measurements_completed": False,
                "whole_task_satisfied": False,
            },
            "groupedq1_v5": {
                "status": grouped["status"], "numerical_gate_pass": False, "speed_gate_pass": False,
                "numerical_fail_steps": failed_steps, "candidate_promoted": False,
                "active_backend_unchanged": grouped["active_backend_unchanged"],
            },
        },
        "limits": list(source["limits"]),
    }
    _bounded(result)
    return result
