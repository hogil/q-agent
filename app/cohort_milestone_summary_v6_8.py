"""Hash-pinned, bounded read-only projection of four ROOT-reviewed synthetic records."""
from pathlib import Path
from typing import Any

try:
    from .cohort_milestone_summary import _bounded, _count, _strings
    from .cohort_milestone_summary_v6 import _proofs
except ImportError:
    from cohort_milestone_summary import _bounded, _count, _strings
    from cohort_milestone_summary_v6 import _proofs


ROOT_REVIEWS = {
    "native_phase_a": (
        "native-metro-phase-A-ROOT-limited-acceptance-v1.json",
        "a2fecd4104311b1b17f28cb746af6d66bb6c41beddcfd45447304667b0e0154e",
        "ROOT_LIMITED_ACCEPTANCE_V4_METADATA_MASK_ONLY",
    ),
    "mht_standalone": (
        "skip-history-format-ROOT-limited-acceptance-v1.json",
        "5fcc570bedd27c2c3ac8b526b25e74091bb11d00733430133e1536d4eb0209d5",
        "ROOT_LIMITED_ACCEPTANCE_EXACT_DEFAULT_RANKING_AND_RETURNED_MHT_SOURCE_READ",
    ),
    "evidence_v15_1": (
        "actual-evidence-V15-1-ROOT-partial-quality-review-v1.json",
        "088f814e18b0f64b81c6bd0276ed39a0c85bfa30c75661f7d746aa9c108d1604",
        "ROOT_PARTIAL_TRACE_COMPLETED_FORECAST_OMITTED_AND_KOREAN_NARRATIVE_FAILED",
    ),
    "metrology_policy_v5": (
        "actual-metrology-policy-V5-ROOT-denied-flow-review-v1.json",
        "7c70031a6c7d06187f80a00420b6e399dca5fbf89e014354eaf4131761eed931",
        "ROOT_DENIED_ALL_FACTS_APPROVED_BUT_INVENTED_HISTORICAL_POLICY_REQUIREMENT",
    ),
}


def _read(ref: dict[str, Any]) -> dict[str, Any]:
    import json

    value = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("ROOT review must be a JSON object")
    return value


def _review_fields(reviews: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for key, review in reviews.items():
        rows.append({"id": key, "path": review["_ref"]["path"], "sha256": review["_ref"]["sha256"], "status": review["status"]})
    return rows


def milestone_summary_v6_8(source: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_8.v1":
        raise ValueError("unexpected V6.8 publication capsule schema")
    _bounded(source)
    if (source.get("status") != "prepared_from_ROOT_reviewed_records" or source.get("synthetic") is not True
            or source.get("production") is not False or source.get("general_LLM_quality_established") is not False):
        raise ValueError("V6.8 synthetic draft boundary cannot be promoted")

    refs = source.get("root_reviews")
    if not isinstance(refs, dict) or set(refs) != set(ROOT_REVIEWS):
        raise ValueError("exactly four ROOT-reviewed records are required")
    _proofs(refs, root)
    reviews: dict[str, dict[str, Any]] = {}
    for key, (filename, digest, status) in ROOT_REVIEWS.items():
        ref = refs[key]
        review = _read(ref)
        _bounded(review)
        if Path(ref["path"]).name != filename or ref["sha256"].lower() != digest:
            raise ValueError("ROOT review source pin changed")
        if (review.get("status") != status or review.get("reviewed_by") != "ROOT"
                or review.get("synthetic") is not True or review.get("production") is not False
                or review.get("general_LLM_quality_established") is True):
            raise ValueError("ROOT review status or synthetic boundary changed")
        review["_ref"] = ref
        reviews[key] = review

    native = reviews["native_phase_a"]
    native_counts = native.get("counts", {})
    if (native_counts.get("samples") != 14812 or native_counts.get("contexts") != 768
            or native_counts.get("point_records") != 770224 or native.get("SQL_references_passed") != 12
            or native.get("actual_numeric_model_training") is not False or native.get("live_Tool_enabled") is not False):
        raise ValueError("Native Phase A limited-acceptance facts changed")

    mht = reviews["mht_standalone"]
    mht_summary = mht.get("summary", {})
    if (mht_summary.get("default_cases_exact") != 4 or mht_summary.get("default_matches_compared") != 32
            or mht_summary.get("MHT_queries") != 3 or mht_summary.get("source_read_calls") != 3
            or mht_summary.get("distinct_MHT_documents") != 2 or "MiniLM" not in mht.get("scope", "")):
        raise ValueError("MHT standalone retrieval facts changed")
    _strings(mht.get("limits"))

    evidence = reviews["evidence_v15_1"]
    evidence_summary = evidence.get("summary", {})
    forecast = evidence.get("actual_forecast", {})
    language = evidence.get("language_check", {})
    if (evidence.get("whole_question_satisfied") is not False or evidence_summary.get("actual_LLM_returns") != 7
            or evidence_summary.get("Tool_calls") != 11 or evidence_summary.get("evidence_facts") != 9
            or evidence_summary.get("approved_facts") != 7 or evidence_summary.get("Answer_last") is not True
            or evidence_summary.get("new_actions") != 0 or forecast.get("Judge_approved") is not False
            or forecast.get("Answer_claim_included") is not False or language.get("Hangul_characters") != 0):
        raise ValueError("Evidence V15.1 partial-run facts changed")

    metrology = reviews["metrology_policy_v5"]
    metrology_summary = metrology.get("summary", {})
    judge = metrology.get("Judge", {})
    approved = judge.get("approved_fact_choices", {})
    if (metrology.get("whole_task_satisfied") is not False or metrology_summary.get("actual_LLM_returns") != 4
            or metrology_summary.get("approved_fact_count") != 7 or metrology_summary.get("new_request_cells") != 0
            or metrology_summary.get("new_request_wafers") != 0 or metrology_summary.get("new_actions") != 0
            or judge.get("decision") != "reject" or len(approved) != 7 or not all(value is True for value in approved.values())):
        raise ValueError("Metrology policy V5 denied-run facts changed")
    finding = metrology.get("finding")
    if not isinstance(finding, str) or "historical" not in finding.lower() or "policy" not in finding.lower():
        raise ValueError("Metrology policy V5 review finding is missing")

    excluded = source.get("excluded")
    _strings(excluded)
    if excluded != ["V16 results are outside this snapshot's review scope"]:
        raise ValueError("V16 must remain outside the reviewed snapshot scope")

    proof_refs = _review_fields(reviews)
    result = {
        "schema_id": "qagent.skip_research_milestone.v6.8",
        "status": "prepared_from_ROOT_reviewed_records",
        "synthetic": True,
        "production": False,
        "general_LLM_quality_established": False,
        "proof_count": 4,
        "proofs": proof_refs,
        "native_phase_a": {
            "status": native["status"], "samples": native_counts["samples"],
            "contexts": native_counts["contexts"], "point_records": native_counts["point_records"],
            "sql_references_passed": native["SQL_references_passed"], "model_training": False,
            "limits": ["Metadata and sampling-mask review only; no observed numeric or OUT values were read.",
                       "No synthetic anomaly labels, numeric model fit, calibration, or live Tool was established."],
        },
        "mht_standalone": {
            "status": mht["status"], "default_cases_exact": mht_summary["default_cases_exact"],
            "default_matches_compared": mht_summary["default_matches_compared"],
            "mht_queries": mht_summary["MHT_queries"], "source_read_calls": mht_summary["source_read_calls"],
            "distinct_mht_documents": mht_summary["distinct_MHT_documents"], "standalone_only": True,
            "e5_federation_connected": False,
            "limits": ["Standalone oldbank MiniLM adapter; not registered in the active E5 federated workflow.",
                       "MHT source view is limited to the first HTML MIME body.",
                       "Probe cases are not general retrieval-accuracy validation."],
        },
        "evidence_v15_1": {
            "status": evidence["status"], "llm_returns": evidence_summary["actual_LLM_returns"],
            "tool_calls": evidence_summary["Tool_calls"], "evidence_facts": evidence_summary["evidence_facts"],
            "approved_facts": evidence_summary["approved_facts"], "answer_last": evidence_summary["Answer_last"],
            "new_actions": evidence_summary["new_actions"], "forecast_included": False,
            "hangul_characters": language["Hangul_characters"], "whole_question_satisfied": False,
            "limits": ["Forecast lookup ran but Judge withheld it from the final claim.",
                       "One synthetic question; no general LLM quality benchmark."],
        },
        "metrology_policy_v5": {
            "status": metrology["status"], "llm_returns": metrology_summary["actual_LLM_returns"],
            "approved_fact_count": metrology_summary["approved_fact_count"], "judge_decision": "reject",
            "finding": finding, "new_request_cells": metrology_summary["new_request_cells"],
            "new_request_wafers": metrology_summary["new_request_wafers"],
            "new_actions": metrology_summary["new_actions"], "whole_task_satisfied": False,
            "limits": ["No plan was approved and no rejection was bypassed.",
                       "Single synthetic case; no general LLM quality benchmark."],
        },
        "limits": ["Independent synthetic records; not a unified product acceptance.",
                   "Production behavior and general LLM quality are not established.",
                   "V16 results are outside this reviewed snapshot's scope."],
    }
    _bounded(result)
    for key in ("samples", "contexts", "point_records", "sql_references_passed"):
        _count(result["native_phase_a"][key])
    return result
