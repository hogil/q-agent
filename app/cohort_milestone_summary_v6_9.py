"""Hash-pinned bounded projection of reviewed Native METRO and V16 research."""
from pathlib import Path
from typing import Any

try:
    from .cohort_milestone_summary import _bounded, _count, _strings
    from .cohort_milestone_summary_v6 import _proofs
except ImportError:
    from cohort_milestone_summary import _bounded, _count, _strings
    from cohort_milestone_summary_v6 import _proofs

ROOT_REVIEWS = {
    "native_fixed_four": ("native-metro-fixed-four-ROOT-limited-acceptance-v1.json", "51bd183baccf8d8362df7692027091a780199cdde76845d362438c75d5b9ea9d", "ROOT_LIMITED_ACCEPTANCE_NATIVE20_FIXED_FOUR_SYNTHETIC_FITS_AND_POST_P1_CONFIRMATION"),
    "native_metric_audit": ("native-metro-post-P1-ROOT-metric-audit-v1.json", "b3dc75e4ea69777880d411067bffb6887c75f76dc04240596a90a4cf27bf3ba4", "ROOT_POST_P1_INDEPENDENT_METRIC_RECOMPUTATION"),
    "native_observability": ("native-metro-post-P1-observability-ROOT-v1.json", "8936d648e7c9de338d13c94fd1e2565532d339a6de384fcdba2317435f0d2704", "ROOT_POST_P1_DESCRIPTIVE_OBSERVABILITY_AUDIT_NOT_PREDECLARED_PERFORMANCE_TEST"),
    "evidence_v16": ("actual-evidence-V16-ROOT-failed-partial-review-v2.json", "37ba76d82182155745edb283c7c05e159e4ec518985fd6b56040b5f4cc13f960", "ROOT_FAILED_PARTIAL_REVIEW_NO_ANSWER"),
}


def _read(ref: dict[str, Any]) -> dict[str, Any]:
    import json
    value = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("ROOT review must be a JSON object")
    return value


def milestone_summary_v6_9(source: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    if source is None:
        return None
    if not isinstance(source, dict) or source.get("schema_id") != "qagent.model_lab_publication_v6_9.v1":
        raise ValueError("unexpected V6.9 publication capsule schema")
    _bounded(source)
    if (source.get("status") != "prepared_from_ROOT_reviewed_records" or source.get("synthetic") is not True
            or source.get("production") is not False or source.get("promotion") is not False
            or source.get("general_LLM_quality_established") is not False):
        raise ValueError("V6.9 synthetic draft boundary cannot be promoted")
    refs = source.get("root_reviews")
    if not isinstance(refs, dict) or set(refs) != set(ROOT_REVIEWS):
        raise ValueError("exactly four ROOT-reviewed records are required")
    _proofs(refs, root)
    reviews = {}
    for key, (filename, digest, status) in ROOT_REVIEWS.items():
        ref = refs[key]
        review = _read(ref)
        _bounded(review)
        if Path(ref["path"]).name != filename or ref["sha256"].lower() != digest:
            raise ValueError("ROOT review source pin changed")
        if (review.get("status") != status
                or (key != "native_observability" and review.get("reviewed_by") != "ROOT")
                or review.get("production", True) is not False
                or (review.get("synthetic") is not True and review.get("synthetic_only") is not True)):
            raise ValueError("ROOT review status or synthetic boundary changed")
        review["_ref"] = ref
        reviews[key] = review

    native = reviews["native_fixed_four"]
    counts, metrics = native.get("counts", {}), native.get("ensemble_metrics", {})
    fits = native.get("fits", [])
    if (len(fits) != 4 or {row.get("family") for row in fits} != {"hf_patchtst", "cnn1d"}
            or {row.get("seed") for row in fits} != {17, 29}
            or counts.get("fresh_CONF") != 2000 or counts.get("CONF_supported") != 1361
            or counts.get("CONF_supported_positive") != 678 or counts.get("CONF_supported_normal") != 683
            or native.get("input") != "128 numeric UTC bins x20 explicit feature/mask channels; no image conversion"
            or native.get("live_Tool_activated") is not False or native.get("current_question_LLM_quality_pass") is not False):
        raise ValueError("fixed Native METRO source facts changed")
    for family, fp, upper in (("hf_patchtst", 1, 0.006926621659938263), ("cnn1d", 3, 0.01131290044698999)):
        row = metrics.get(family, {})
        if (row.get("FP") != fp or row.get("normal_supported") != 683
                or abs(row.get("one_sided95_CP_upper_selective_FPR", -1) - upper) > 1e-12):
            raise ValueError("Native METRO confirmation metric changed")

    audit = reviews["native_metric_audit"]
    if audit.get("AP_AUC_FP_counts_recomputed_exact") is not True:
        raise ValueError("independent Native metric audit is missing")
    observability = reviews["native_observability"]
    _strings(observability.get("limits"))
    if "NOT_PREDECLARED_PERFORMANCE_TEST" not in observability.get("status", ""):
        raise ValueError("post-hoc descriptive observability boundary changed")
    v16 = reviews["evidence_v16"]
    totals = v16.get("totals", {})
    if (v16.get("wall_limit_seconds") != 600 or v16.get("actual_abort_elapsed_seconds", 0) < 600
            or totals.get("returned_calls") != 6 or v16.get("answer_generation_called") is not True
            or v16.get("answer_raw_returned") is not False or v16.get("question_quality_pass") is not False
            or v16.get("semantic_improvement_established") is not False):
        raise ValueError("V16 failed partial-run facts changed")
    _strings(source.get("limits"))
    proofs = [{"id": key, "path": reviews[key]["_ref"]["path"], "sha256": reviews[key]["_ref"]["sha256"],
               "status": reviews[key]["status"]} for key in reviews]
    result = {
        "schema_id": "qagent.skip_research_milestone.v6.9", "status": "prepared_from_ROOT_reviewed_records",
        "synthetic": True, "production": False, "promotion": False, "general_LLM_quality_established": False,
        "proof_count": len(proofs), "proofs": proofs,
        "native_fixed_four": {
            "status": native["status"], "input": native["input"], "fits": 4,
            "fresh_conf": counts["fresh_CONF"], "supported": counts["CONF_supported"],
            "supported_positive": counts["CONF_supported_positive"], "supported_normal": counts["CONF_supported_normal"],
            "promotion": False,
            "families": {family: {"average_precision": metrics[family]["AP"], "auc": metrics[family]["AUC"],
                "selective_recall": metrics[family]["selective_recall"], "unconditional_recall": metrics[family]["unconditional_recall"],
                "false_positives": metrics[family]["FP"], "normal_supported": metrics[family]["normal_supported"],
                "one_sided95_cp_upper_selective_fpr": metrics[family]["one_sided95_CP_upper_selective_FPR"]}
                for family in ("hf_patchtst", "cnn1d")},
            "limits": ["Synthetic fixed confirmation sample; conditional metrics are not production guarantees.",
                       "CNN scored higher in this comparison; no family or seed was promoted.",
                       "CP bounds are pointwise and conditional on supported synthetic normal episodes.",
                       "No pretrained foundation model, live Tool, or production acceptance is established."],
        },
        "native_metric_audit": {"status": audit["status"], "recomputed_exact": True},
        "native_observability": {"status": observability["status"], "posthoc_descriptive_only": True, "limits": observability["limits"]},
        "evidence_v16": {"status": v16["status"], "wall_limit_seconds": v16["wall_limit_seconds"],
            "actual_elapsed_seconds": v16["actual_abort_elapsed_seconds"], "llm_returns": totals["returned_calls"],
            "answer_generation_called": True, "answer_raw_returned": False, "question_quality_pass": False,
            "semantic_improvement_established": False,
            "limits": ["The 600-second wall limit elapsed before an Answer raw return.",
                       "No final answer quality or semantic improvement can be assessed.",
                       "Shorter prompts did not establish quality success."]},
        "weighted_v3": {"status": "source_preparing", "trained": False}, "limits": list(source["limits"]),
    }
    _bounded(result)
    for key in ("fits", "fresh_conf", "supported", "supported_positive", "supported_normal"):
        _count(result["native_fixed_four"][key])
    return result
