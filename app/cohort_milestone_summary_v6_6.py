"""Bounded V6.6 projection of separately ROOT-reviewed synthetic studies."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .cohort_milestone_summary import _bounded, _strings
    from .cohort_milestone_summary_v6 import _proofs
except ImportError:
    from cohort_milestone_summary import _bounded, _strings
    from cohort_milestone_summary_v6 import _proofs


ROOT_STATUSES = {
    "fresh_trend_calibration": "ROOT_ACCEPTED_LIMITED_FRESH_SYNTHETIC_CALIBRATION_STUDY",
    "fullworld_evidence_v10": "ROOT_PARTIAL_RETRIEVAL_CONTRACT_AND_LLM_SEMANTIC_ERRORS",
    "capacity_8192": "approved",
}
PENDING_STATUSES = {
    "fullworld_evidence_v11": "failed_pending_ROOT_capsule",
    "metrology_v2": "failed_pending_ROOT_capsule",
    "code_performance_v5": "pending_ROOT_capsule",
}


def _read(ref: dict[str, Any]) -> dict[str, Any]:
    import json

    value = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("proof reference must contain a JSON object")
    return value


def _links(proof: dict[str, Any], names: tuple[str, ...], root: Path) -> dict[str, dict[str, Any]]:
    refs = {name: proof[name] for name in names if name in proof}
    if len(refs) != len(names):
        raise ValueError("required ROOT proof references are missing")
    _proofs(refs, root)
    return {name: _read(ref) for name, ref in refs.items()}


def milestone_summary_v6_6(source: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_6.v1":
        raise ValueError("unexpected V6.6 publication capsule schema")
    _bounded(source)
    if (source.get("status") != "prepared_pending_ROOT_review" or source.get("synthetic") is not True
            or source.get("production") is not False):
        raise ValueError("V6.6 must remain a synthetic draft pending ROOT review")
    if (source.get("current_serving_world") != "full-v3"
            or source.get("corrected_V4_integrated") is not False
            or source.get("platform_complete") is not False):
        raise ValueError("serving scope and platform status cannot be upgraded")

    proof_refs = source.get("proofs")
    if not isinstance(proof_refs, dict) or set(proof_refs) != set(ROOT_STATUSES):
        raise ValueError("exactly three ROOT proof records are required")
    _proofs(proof_refs, root)
    proofs = {key: _read(ref) for key, ref in proof_refs.items()}
    for key, proof in proofs.items():
        if proof.get("status") != ROOT_STATUSES[key]:
            if key == "fullworld_evidence_v10":
                raise ValueError("V10 partial status must remain explicit")
            raise ValueError(f"unexpected ROOT proof status for {key}")

    trend = proofs["fresh_trend_calibration"]
    if (trend.get("approved_by") != "ROOT" or trend.get("automatic_model_promotion") is not False
            or trend.get("production") is not False or trend.get("primary_family") != "cnn1d"):
        raise ValueError("fresh Trend study must remain limited, nonproduction, and nonpromoted")
    trend_links = _links(trend, ("scores", "arithmetic_audit"), root)
    scores = trend_links["scores"]
    audit = trend_links["arithmetic_audit"]
    if (scores.get("status") != "FRESH_CONFIRMATION_SCORED_NO_RECALIBRATION"
            or scores.get("rows") != 2000 or scores.get("normal_rows") != 1000
            or scores.get("fault_rows") != 1000
            or scores.get("fresh_synthetic_transfer_not_oldCSV_reproduction") is not True
            or scores.get("physical_or_production_validation") is not False):
        raise ValueError("fresh Trend confirmation population or study boundary changed")
    dataset = audit.get("dataset", {})
    raw_index = dataset.get("raw_index", {})
    counts = raw_index.get("partition_counts", {})
    cal_count = counts.get("calibration", {}).get("normal")
    confirmation = counts.get("confirmation", {})
    if (raw_index.get("charts") != 3000 or raw_index.get("total_raw_rows") != 4218861
            or cal_count != 1000
            or sum(value for key, value in confirmation.items() if type(value) is int) != 2000):
        raise ValueError("fresh Trend calibration/confirmation dataset totals changed")
    op = trend.get("primary_operating_points", {})
    fresh = op.get("fresh_exact_order", {})
    old = op.get("frozen_old_validation_FPR1", {})
    fixed = op.get("fixed05", {})
    cnn_audit = audit.get("confirmation", {}).get("CNN_old_vs_fresh", {})
    upper = fresh.get("normal_FPR_one_sided95_upper", fresh.get("normal_FPR_one_sided95_upper_beta"))
    if (old.get("FPR") != 0.018 or old.get("recall") != 0.996
            or fresh.get("FPR") != 0.006 or fresh.get("recall") != 0.988
            or fixed.get("threshold") != 0.5 or fixed.get("FPR") != fresh.get("FPR")
            or fixed.get("recall") != fresh.get("recall")
            or cnn_audit.get("fixed05_confusion_matches_fresh") is not True
            or audit.get("confirmation", {}).get("AP_threshold_invariant") is not True
            or type(upper) not in (int, float) or upper <= 0.01):
        raise ValueError("fresh Trend thresholds, fixed-0.5 comparison, or uncertainty guard changed")
    _strings(trend.get("limits"))

    v10 = proofs["fullworld_evidence_v10"]
    if (v10.get("reviewed_by") != "ROOT" or v10.get("whole_question_satisfied") is not False
            or v10.get("general_LLM_quality_established") is not False or v10.get("production") is not False):
        raise ValueError("V10 must remain ROOT-reviewed partial and nonproduction")
    v10_audit = _links(v10, ("independent_audit",), root)["independent_audit"]
    if v10_audit.get("verdict", {}).get("status") != "partial":
        raise ValueError("V10 independent audit must remain partial")
    summary = v10.get("summary", {})
    audit_runtime = v10_audit.get("runtime", {})
    if (summary.get("actual_LLM_returns") != 6 or summary.get("Tool_calls") != 11
            or summary.get("history_retrieved") is not False or summary.get("E5_loaded") is not False
            or summary.get("forecast_executed") is not True
            or summary.get("forecast_Judge_approved") is not False or summary.get("new_actions") != 0
            or audit_runtime.get("actual_LLM_returns") != summary["actual_LLM_returns"]
            or audit_runtime.get("actual_dispatched_Tools") != summary["Tool_calls"]
            or audit_runtime.get("elapsed_seconds") is None):
        raise ValueError("V10 retrieval, forecast, or action boundary changed")
    history_words = v10_audit.get("history", {}).get("unicode_word_occurrences")
    if history_words != 67 or v10_audit.get("history", {}).get("metadata_search_executed") is not False:
        raise ValueError("V10 history failure must remain pre-retrieval")
    manual = v10.get("Root_manual_findings")
    _strings(manual)
    if not any("History67wordoccurrences exceeded both frozen64 limits" in item for item in manual):
        raise ValueError("V10 root review must retain the bounded-history failure")

    capacity = proofs["capacity_8192"]
    if (capacity.get("approved_by") != "ROOT" or capacity.get("8192_accepted") is not True
            or capacity.get("candidate_backend_accepted") is not True
            or capacity.get("input_capacity") != 8192 or capacity.get("output_capacity") != 1200
            or capacity.get("approval_scope") != "8192_numerical_prefill_capacity_only_no_decode_or_business_quality"
            or capacity.get("production") is not False):
        raise ValueError("8192 capacity proof must remain limited to numerical prefill")
    capacity_audit = _links(capacity, ("independent_actual_audit",), root)["independent_actual_audit"]
    if capacity_audit.get("overall_status") != "PASS_INDEPENDENT_NUMERICAL_AUDIT_ROOT_FINAL_ACCEPTANCE_PENDING":
        raise ValueError("capacity audit status is not the expected numerical-only audit")
    _strings(capacity.get("limits_of_claim"))

    pending = source.get("pending_studies")
    if not isinstance(pending, list) or len(pending) != len(PENDING_STATUSES):
        raise ValueError("exactly three pending study placeholders are required")
    pending_by_id = {row.get("id"): row for row in pending if isinstance(row, dict)}
    if set(pending_by_id) != set(PENDING_STATUSES):
        raise ValueError("pending study identifiers changed")
    for key, status in PENDING_STATUSES.items():
        row = pending_by_id[key]
        if row.get("status") != status or row.get("result") is not None:
            raise ValueError("pending studies cannot be promoted or assigned results")
        if not isinstance(row.get("summary"), str) or len(row["summary"]) > 200:
            raise ValueError("pending study note must be bounded text")

    result = {
        "schema_id": "qagent.skip_research_milestone.v6.6",
        "status": "prepared_pending_ROOT_review",
        "created_at_utc": source.get("created_at_utc"),
        "synthetic": True,
        "production": False,
        "proof_count": len(proof_refs),
        "proofs": [
            {"id": key, "status": proofs[key]["status"], "sha256": proof_refs[key]["sha256"],
             "file": Path(proof_refs[key]["path"]).name}
            for key in ROOT_STATUSES
        ],
        "fresh_trend": {
            "charts": 3000, "raw_points": 4218861, "calibration_normal_charts": 1000,
            "confirmation_charts": 2000, "primary_model": trend["primary_family"],
            "primary_ap": trend["primary_AP"], "old_threshold_fpr": old["FPR"],
            "old_threshold_recall": old["recall"], "fresh_threshold_fpr": fresh["FPR"],
            "fresh_threshold_recall": fresh["recall"], "fixed05_fpr": fixed["FPR"],
            "fixed05_recall": fixed["recall"], "upper_95_fpr": upper,
            "fixed05_same_as_fresh_decisions": True,
            "old_csv_reproduction": False, "automatic_promotion": False,
            "limits": list(trend["limits"]),
        },
        "v10_partial": {
            "elapsed_seconds": round(float(audit_runtime["elapsed_seconds"]), 2),
            "actual_LLM_returns": summary["actual_LLM_returns"],
            "tool_calls": summary["Tool_calls"], "history_retrieved": summary["history_retrieved"],
            "history_query_word_occurrences": history_words,
            "history_query_word_limit": 64,
            "E5_loaded": summary["E5_loaded"], "forecast_executed": summary["forecast_executed"],
            "forecast_Judge_approved": summary["forecast_Judge_approved"], "new_actions": summary["new_actions"],
            "root_manual_findings": list(manual), "whole_question_satisfied": False,
            "general_LLM_quality_established": False,
        },
        "capacity": {
            "input_tokens": capacity["input_capacity"], "output_tokens": capacity["output_capacity"],
            "numerical_prefill_only": True, "generation_or_quality_validated": False,
            "limits": list(capacity["limits_of_claim"]),
        },
        "pending_studies": [
            {"id": key, "status": pending_by_id[key]["status"], "summary": pending_by_id[key]["summary"], "result": None}
            for key in PENDING_STATUSES
        ],
        "current_serving_world": source["current_serving_world"],
        "corrected_V4_integrated": False,
        "platform_complete": False,
        "limits": list(source.get("notes", [])),
    }
    _bounded(result)
    return result
