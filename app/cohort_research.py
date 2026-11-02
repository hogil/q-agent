"""Read-only, hash-pinned summary of isolated synthetic cohort research artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from .cohort_milestone_summary import milestone_summary as _milestone_summary
    from .cohort_milestone_summary_v6 import milestone_summary_v6 as _milestone_summary_v6
    from .cohort_milestone_summary_v6_1 import milestone_summary_v6_1 as _milestone_summary_v6_1
    from .cohort_milestone_summary_v6_2 import milestone_summary_v6_2 as _milestone_summary_v6_2
    from .cohort_milestone_summary_v6_3 import milestone_summary_v6_3 as _milestone_summary_v6_3
    from .cohort_milestone_summary_v6_4 import milestone_summary_v6_4 as _milestone_summary_v6_4
    from .cohort_milestone_summary_v6_5 import milestone_summary_v6_5 as _milestone_summary_v6_5
    from .cohort_milestone_summary_v6_6 import milestone_summary_v6_6 as _milestone_summary_v6_6
    from .cohort_milestone_summary_v6_7 import milestone_summary_v6_7 as _milestone_summary_v6_7
    from .cohort_milestone_summary_v6_8 import milestone_summary_v6_8 as _milestone_summary_v6_8
    from .cohort_milestone_summary_v6_9 import milestone_summary_v6_9 as _milestone_summary_v6_9
except ImportError:
    from cohort_milestone_summary import milestone_summary as _milestone_summary
    from cohort_milestone_summary_v6 import milestone_summary_v6 as _milestone_summary_v6
    from cohort_milestone_summary_v6_1 import milestone_summary_v6_1 as _milestone_summary_v6_1
    from cohort_milestone_summary_v6_2 import milestone_summary_v6_2 as _milestone_summary_v6_2
    from cohort_milestone_summary_v6_3 import milestone_summary_v6_3 as _milestone_summary_v6_3
    from cohort_milestone_summary_v6_4 import milestone_summary_v6_4 as _milestone_summary_v6_4
    from cohort_milestone_summary_v6_5 import milestone_summary_v6_5 as _milestone_summary_v6_5
    from cohort_milestone_summary_v6_6 import milestone_summary_v6_6 as _milestone_summary_v6_6
    from cohort_milestone_summary_v6_7 import milestone_summary_v6_7 as _milestone_summary_v6_7
    from cohort_milestone_summary_v6_8 import milestone_summary_v6_8 as _milestone_summary_v6_8
    from cohort_milestone_summary_v6_9 import milestone_summary_v6_9 as _milestone_summary_v6_9


SCHEMA_ID = "qagent.cohort_research_snapshot.v1"
MANIFEST_SCHEMA_ID = "qagent.cohort_research_sources.v1"
ARTIFACT_NAMES = (
    "current_run", "tool_report", "manual_review", "grounded_audit", "mes_verification",
    "confirm3_results", "confirm3_metric_check", "confirm3_prior_holdout_addendum",
    "public_cnn_test", "public_dino_test", "numeric_trend", "rejected_doc_review", "accepted_doc_review", "milestone_v5", "milestone_v6", "milestone_v6_1", "milestone_v6_2", "milestone_v6_3", "milestone_v6_4", "milestone_v6_5", "milestone_v6_6", "milestone_v6_7", "milestone_v6_8", "milestone_v6_9",
)
MAX_JSON_BYTES = 12 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _json_object(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"artifact exceeds JSON size limit: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"artifact must contain a JSON object: {path.name}")
    return value


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _artifact_entry(name: str, entry: Any, root: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if entry is None:
        return None, {"name": name, "sha256": None, "availability": "pending"}
    if not isinstance(entry, dict) or set(entry) - {"path", "sha256"} or not {"path", "sha256"} <= set(entry):
        raise ValueError(f"invalid manifest entry: {name}")
    raw_path, expected = entry["path"], entry["sha256"]
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"artifact path must be absolute: {name}")
    path = Path(raw_path)
    if not path.is_absolute():
        raise ValueError(f"artifact path must be absolute: {name}")
    resolved = path.resolve(strict=False)
    if not _within(resolved, root):
        raise ValueError(f"artifact path escapes configured root: {name}")
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected):
        raise ValueError(f"invalid SHA256 in manifest: {name}")
    if not resolved.exists():
        return None, {"name": name, "sha256": None, "availability": "pending"}
    if not resolved.is_file() or resolved.suffix.lower() != ".json":
        raise ValueError(f"only allowlisted JSON artifacts can be read: {name}")
    actual = _sha256(resolved)
    if actual.lower() != expected.lower():
        raise ValueError(f"artifact SHA256 mismatch: {name}")
    return _json_object(resolved), {"name": name, "sha256": actual, "availability": "verified"}


def _scope(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    return {
        "status": source.get("status"), "scope_id": source.get("cohort_id"),
        "relation": source.get("relation"), "wafer_count": _number(source.get("wafer_count")),
        "lot_count": _number(source.get("lot_count")), "anchor_run_count": _number(source.get("anchor_run_count")),
        "window": source.get("scope") if isinstance(source.get("scope"), dict) else None,
    }


def _trend_summary(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if source is None:
        return None
    results = source.get("results")
    if not isinstance(results, dict):
        results = {}
    summaries: dict[str, Any] = {}
    inference_flags: list[bool] = []
    for cohort_name in ("current", "past_reference"):
        rows = results.get(cohort_name)
        if not isinstance(rows, list):
            summaries[cohort_name] = None
            continue
        items = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            groups = row.get("groups") if isinstance(row.get("groups"), list) else []
            timepoints = sum(len(g.get("time_series", [])) for g in groups if isinstance(g, dict) and isinstance(g.get("time_series"), list))
            model = row.get("model")
            if isinstance(model, dict) and isinstance(model.get("inference_executed"), bool):
                inference_flags.append(model["inference_executed"])
            items.append({"step": row.get("step"), "item": row.get("item"), "status": row.get("status"),
                          "groups": len(groups), "timepoints": timepoints, "unit": row.get("unit")})
        summaries[cohort_name] = items
    inference = all(inference_flags) if inference_flags else None
    return {"status": source.get("status"), "as_of": source.get("as_of"),
            "current_scope": _scope(source.get("scopes", {}).get("current")),
            "reference_scope": _scope(source.get("scopes", {}).get("past_reference")),
            "model_inference_executed": inference,
            "outcome_queries": _number(source.get("database_outcome_reads")), "series": summaries,
            "llm_calls": _number(source.get("service_llm_calls")),
            "production_actions": source.get("production_actions")}


def _build_snapshot(src: Mapping[str, dict[str, Any] | None], provenance: list[dict[str, Any]]) -> dict[str, Any]:
    run = src.get("current_run")
    report = src.get("tool_report")
    manual = src.get("manual_review")
    audit = src.get("grounded_audit")
    mes = src.get("mes_verification")
    checks = manual.get("source_checks", {}) if isinstance(manual, dict) else {}
    counts = run.get("scope_counts", {}) if isinstance(run, dict) else {}
    tracks = report.get("tracks", {}) if isinstance(report, dict) else {}
    chronic = tracks.get("chronic_cohort", {}) if isinstance(tracks, dict) else {}
    acute = tracks.get("acute_event", {}) if isinstance(tracks, dict) else {}
    if not isinstance(chronic, dict): chronic = {}
    if not isinstance(acute, dict): acute = {}
    current_n = _number((chronic.get("scope") or {}).get("wafer_count"))
    if current_n is None: current_n = _number(counts.get("current"))
    reference_n = _number((chronic.get("reference") or {}).get("wafer_count"))
    if reference_n is None: reference_n = _number(counts.get("past_reference"))
    event_obj = acute.get("event") if isinstance(acute.get("event"), dict) else None
    event_n = _number(event_obj.get("wafer_count")) if event_obj else _number(counts.get("acute_event"))
    event_intersection = _number(checks.get("acute_event_intersection_n"))
    down = checks.get("current_DOWN_matched_subset") if isinstance(checks, dict) else None
    if not isinstance(down, dict): down = {}
    current_metro = checks.get("current_METRO_step_diagonal") if isinstance(checks, dict) else None
    step_sampling = None
    if isinstance(current_metro, dict):
        step_sampling = []
        for step, observed in current_metro.items():
            n = _number(observed)
            step_sampling.append({"step": step, "observed_n": n, "total_n": current_n,
                "coverage": (n / current_n) if n is not None and current_n not in (None, 0) else None})
    pred = (chronic.get("future_cohort_prediction") or {}) if isinstance(chronic.get("future_cohort_prediction"), dict) else {}
    pred_rows = pred.get("predictions") if isinstance(pred.get("predictions"), list) else []
    yield_row = next((x for x in pred_rows if isinstance(x, dict) and x.get("target") == "future_cohort_yield"), None)
    if yield_row is None:
        fallback = checks.get("future_Yield_prediction") if isinstance(checks, dict) else None
        yield_row = {"point": fallback.get("point"), "unit": fallback.get("unit")} if isinstance(fallback, dict) else None
    future_yield = None if yield_row is None else {"point": _number(yield_row.get("point")), "unit": yield_row.get("unit"),
        "outcome_observed": False if isinstance(checks.get("future_Yield_prediction"), dict) and checks["future_Yield_prediction"].get("observed_OUT_or_chip_label") is False else None,
        "calibrated_interval": pred.get("calibrated_interval"),
        "outcome_queries": _number(pred.get("outcome_queries"))}
    future_signatures = [{"target": x.get("target"), "point": _number(x.get("point")), "unit": x.get("unit")}
        for x in pred_rows if isinstance(x, dict) and x.get("target") != "future_cohort_yield"] or None

    execution_action = run.get("action_execution") if isinstance(run, dict) else None
    if not isinstance(execution_action, dict) and isinstance(audit, dict): execution_action = audit.get("action_execution")
    if not isinstance(execution_action, dict): execution_action = None
    receipts = execution_action.get("receipts") if execution_action and isinstance(execution_action.get("receipts"), list) else None
    same_actions = None if execution_action is None else {
        "status": execution_action.get("status", "not_supplied"), "receipt_count": len(receipts) if receipts is not None else None,
        "new_actions_executed": execution_action.get("new_actions_executed"),
        "actions_recorded": execution_action.get("actions_recorded"),
        "production_execution": False if execution_action.get("new_actions_executed") is False else None,
    }

    router = run.get("router") if isinstance(run, dict) else None
    judge = run.get("judge") if isinstance(run, dict) else None
    answer = run.get("answer") if isinstance(run, dict) else None
    trace = run.get("trace") if isinstance(run, dict) and isinstance(run.get("trace"), list) else []
    role_traces = [{"role": t.get("role"), "input_tokens": _number(t.get("input_tokens")),
                    "output_tokens": _number(t.get("output_tokens")), "elapsed_ms": _number(t.get("elapsed_ms"))}
                   for t in trace if isinstance(t, dict)]
    review_verdict = manual.get("verdict") if isinstance(manual, dict) else None
    manual_findings = manual.get("manual_findings") if isinstance(manual, dict) and isinstance(manual.get("manual_findings"), list) else None
    judge_decision = judge.get("decision") if isinstance(judge, dict) else None
    requested = router.get("requested_tools") if isinstance(router, dict) else None
    judge_requested = judge.get("requested_tools") if isinstance(judge, dict) else None
    summary = answer.get("summary") if isinstance(answer, dict) else None
    answer_display = run.get("answer_display") if isinstance(run, dict) and isinstance(run.get("answer_display"), dict) else {}
    limitations = answer_display.get("limitations") if isinstance(answer_display.get("limitations"), list) else None
    limitation_ids = answer.get("limitation_ids") if isinstance(answer, dict) and isinstance(answer.get("limitation_ids"), list) else None
    budget_stop = run.get("budget_stop") if isinstance(run, dict) else None
    same_asof = report.get("as_of") if isinstance(report, dict) else None
    source_checks_scope = checks.get("scope_counts", {}) if isinstance(checks, dict) else {}

    mes_counts = mes.get("counts") if isinstance(mes, dict) and isinstance(mes.get("counts"), dict) else None
    independent_mes = None if mes is None else {
        "counts": {key: _number(mes_counts.get(key)) for key in ("inventory", "holds", "dispatch_blocks", "metrology_requests", "receipts")} if mes_counts else None,
        "unaffected_wafer_count": _number(mes.get("unaffected_wafer_count")),
        "source_warehouse_unchanged": mes.get("source_warehouse_unchanged"),
        "experiment_label": mes.get("schema_id"), "synthetic": mes.get("synthetic"),
        "production_actions_executed": mes.get("production_actions_executed"),
    }

    forecast_source = src.get("confirm3_results")
    metric_check = src.get("confirm3_metric_check")
    addendum = src.get("confirm3_prior_holdout_addendum")
    pooled = forecast_source.get("pooled", {}) if isinstance(forecast_source, dict) else {}
    v1 = pooled.get("primary_v1", {}) if isinstance(pooled, dict) else {}
    v4 = pooled.get("selected_v4", {}) if isinstance(pooled, dict) else {}
    delta = forecast_source.get("paired_delta", {}) if isinstance(forecast_source, dict) else {}
    forecast = None if forecast_source is None else {
        "raw_mae": {"v1": _number(v1.get("macro_raw_mae")), "v4": _number(v4.get("macro_raw_mae"))},
        "normalized_mae": {"v1": _number(v1.get("macro_normalized_mae")), "v4": _number(v4.get("macro_normalized_mae"))},
        "delta_ci95": delta.get("hierarchical_moving_block_bootstrap_ci95"),
        "yield_exact": metric_check.get("yield_predictions_exactly_equal") if isinstance(metric_check, dict) else None,
        "family3_regressed": metric_check.get("family3_regression_preserved") if isinstance(metric_check, dict) else None,
        "prior_holdout_informed": addendum.get("composition_informed_by_prior_holdout_metrics") if isinstance(addendum, dict) else None,
        "limits": ["synthetic generator family only", "three fresh seeds", "candidate composition was informed by prior holdout metrics",
                   "not independently selected", "not site validation"] if forecast_source.get("synthetic") is True else None,
    }

    cnn_source = src.get("public_cnn_test")
    cnn = None
    cnn_same_test = None
    if isinstance(cnn_source, dict):
        m = cnn_source.get("metrics", {})
        asl = m.get("asl", {}) if isinstance(m, dict) else {}
        prior = cnn_source.get("prior_test_exposure", {})
        cnn_same_test = bool(prior.get("independent_confirmation") is False)
        cnn = {"macro_ap": _number(asl.get("macro_ap")), "macro_f1": _number(asl.get("macro_f1")),
               "reported_reference_loss": "asl", "metrics_by_loss": {key: {"macro_ap": _number(val.get("macro_ap")),
               "macro_f1": _number(val.get("macro_f1"))} for key, val in m.items() if isinstance(val, dict)},
               "public_dataset": True, "site_validation": False}
    dino_source = src.get("public_dino_test")
    dino = None
    dino_same_test = None
    if isinstance(dino_source, dict):
        candidates = dino_source.get("evaluated_selected_candidates", [])
        linear = next((x for x in candidates if x.get("arm") == "frozen_linear"), None)
        fine = next((x for x in candidates if x.get("arm") == "last2_finetune"), None)
        def _two_metrics(row):
            if not isinstance(row, dict): return None
            metric = row.get("metrics", {})
            return {"seed": row.get("seed"), "macro_ap": _number(metric.get("macro_ap")), "macro_f1": _number(metric.get("macro_f1"))}
        dino = {"linear": _two_metrics(linear), "finetuned": _two_metrics(fine), "public_dataset": True,
                "site_validation": False, "pretraining_overlap_verified": dino_source.get("pretraining_overlap_verified")}
        dino_same_test = dino_source.get("same_official_test_split_previously_seen")

    doc = src.get("rejected_doc_review")
    document_review = None if doc is None else {"status": doc.get("status"),
        "issues": [f"{x.get('kind')}: {x.get('evidence')}" for x in doc.get("issues", []) if isinstance(x, dict)],
        "accepted_for_demo": doc.get("rag_index_acceptance") is True and not str(doc.get("status", "")).startswith("rejected")}
    accepted_doc = src.get("accepted_doc_review")
    accepted_document_review = None
    if isinstance(accepted_doc, dict):
        document_rows = accepted_doc.get("documents")
        rows = [row for row in document_rows if isinstance(row, dict)] if isinstance(document_rows, list) else []
        format_counts: dict[str, int] = {}
        for row in rows:
            fmt, corpus_name = row.get("format"), row.get("corpus")
            if isinstance(fmt, str) and isinstance(corpus_name, str):
                key = f"{fmt}/{corpus_name}"
                format_counts[key] = format_counts.get(key, 0) + 1
        visual_source = accepted_doc.get("actual_parent_visual_review")
        visual_rows = [row for row in visual_source if isinstance(row, dict)] if isinstance(visual_source, list) else []
        individually_reviewed = [row for row in visual_rows
                                  if "contact" not in str(row.get("path", "")).lower()]
        accepted_document_review = {
            "status": accepted_doc.get("status"),
            "accepted_for_descriptive_synthetic_rag": accepted_doc.get("status") == "accepted_for_descriptive_synthetic_rag",
            "distinct_case_count": len({row.get("source_case_id") for row in rows if isinstance(row.get("source_case_id"), str)}),
            "document_count": len(rows), "format_corpus_counts": format_counts,
            "manifest_sha256": accepted_doc.get("manifest_sha256"),
            "individually_reviewed_page_count": len(individually_reviewed),
            "review_findings": accepted_doc.get("visual_findings") if isinstance(accepted_doc.get("visual_findings"), list) else [],
            "visual_review_limits": accepted_doc.get("limitations") if isinstance(accepted_doc.get("limitations"), list) else [],
        }
    trend = _trend_summary(src.get("numeric_trend"))

    current_source = chronic.get("scope") if isinstance(chronic.get("scope"), dict) else None
    reference_source = chronic.get("reference") if isinstance(chronic.get("reference"), dict) else None
    event_source = acute.get("event") if isinstance(acute.get("event"), dict) else None
    current_scope = _scope(current_source)
    reference_scope = _scope(reference_source)
    event_scope = _scope(event_source)
    if current_scope is None and (current_n is not None or isinstance(run, dict)):
        current_scope = {"status": run.get("status") if isinstance(run, dict) else None, "scope_id": None,
                         "relation": "current_exposure", "wafer_count": current_n, "lot_count": None,
                         "anchor_run_count": None, "window": None}
    if reference_scope is None and reference_n is not None:
        reference_scope = {"status": None, "scope_id": None, "relation": "past_reference_not_current",
                           "wafer_count": reference_n, "lot_count": None, "anchor_run_count": None, "window": None}
    if event_scope is None and event_n is not None:
        event_scope = {"status": None, "scope_id": None, "relation": "event_exposure",
                       "wafer_count": event_n, "lot_count": None, "anchor_run_count": None, "window": None}
    event_intersection_scope = {"wafer_count": event_intersection, "current_denominator": _number(down.get("denominator"))}
    manual_status = review_verdict if isinstance(review_verdict, dict) else None
    accepted_for_demo = bool(manual_status and manual_status.get("workflow") == "no material workflow gaps"
        and judge_decision not in ("need_evidence", "blocked") and (document_review or {}).get("accepted_for_demo") is not False)
    tool_calls = report.get("tool_calls") if isinstance(report, dict) and isinstance(report.get("tool_calls"), list) else None
    model_calls = _number(run.get("model_calls")) if isinstance(run, dict) else None
    return {
        "schema_id": SCHEMA_ID, "synthetic": bool(report.get("synthetic")) if isinstance(report, dict) else None,
        "status": run.get("status") if isinstance(run, dict) else "pending", "source_as_of": same_asof,
        "scopes": {
            "current": current_scope, "reference": reference_scope, "event": event_scope,
            "intersection": event_intersection_scope if event_intersection is not None else None,
            "current_down_matched": {"matched_n": _number(down.get("matched_n")), "denominator": _number(down.get("denominator"))} if down else None,
            "risk_floor": _number(down.get("risk_floor")) if down else None,
            "step_sampling": step_sampling, "future_cohort_yield": future_yield,
            "future_signature_rates": future_signatures,
            "outcome_queries": _number(run.get("current_outcome_queries")) if isinstance(run, dict) else None,
            "first_business_tool": report.get("first_business_tool") if isinstance(report, dict) else (run.get("first_business_tool") if isinstance(run, dict) else None),
            "tool_call_count": len(tool_calls) if tool_calls is not None else None,
        },
        "llm": {"status": run.get("status") if isinstance(run, dict) else None, "model_calls": model_calls,
            "judge_decision": judge_decision, "router_requested_tools": requested,
            "requested_tools": judge_requested, "summary": summary,
            "limitations": limitations, "limitation_ids": limitation_ids, "manual_review_status": manual_status,
            "manual_findings": manual_findings,
            "accepted_for_demo": accepted_for_demo, "role_traces": role_traces,
            "budget_stop": budget_stop, "cause_status": answer.get("cause_status") if isinstance(answer, dict) else None},
        "action_execution": same_actions,
        "independent_mes": independent_mes,
        "forecast": forecast,
        "public_benchmarks": {"cnn": cnn, "dino": dino,
            "same_test_seen": bool(cnn_same_test and dino_same_test) if cnn_same_test is not None and dino_same_test is not None else None,
            "site_validation": False if cnn is not None or dino is not None else None},
        "numeric_trend": trend,
        "document_review": document_review,
        "accepted_document_review": accepted_document_review,
        "provenance": {"artifacts": provenance},
    }


try:
    from . import cohort_saved_status_v5 as _saved_status_v5
except ImportError:
    import cohort_saved_status_v5 as _saved_status_v5
CURRENT_STATUS_SCHEMA_ID_V3 = _saved_status_v5.SCHEMA
CURRENT_STATUS_SCHEMA_ID_V4 = _saved_status_v5.SCHEMA_V4
CURRENT_STATUS_RECORDS_V5_ADDED = _saved_status_v5.RECORDS
_saved_v5_contract = _saved_status_v5.contract

CURRENT_STATUS_SCHEMA_ID = "qagent.latest_research_status_sources.v1"
CURRENT_STATUS_SCHEMA_ID_V2 = "qagent.latest_research_status_sources.v2"
CURRENT_STATUS_RECORDS = (
    ("native_architecture_no_gain", "Native METRO architecture comparison"),
    ("native_maxpool_tradeoff", "Native METRO max pooling comparison"),
    ("e5_service_smoke", "E5 V17 format/source service"),
    ("v18_partial_quality", "V18 role-cost-fidelity run"),
    ("v6_runtime_reuse", "V6 runtime reuse · same partial-quality case"),
    ("v19_quality_failed", "V19 archival answer run"),
    ("same_evidence_14b_quality_failed", "Same-evidence 14B archival answer"),
    ("public_retrieval", "Public SciFact retrieval"),
)
CURRENT_STATUS_RECORDS_V2 = CURRENT_STATUS_RECORDS + (
    ("v23_answer_plan_partial", "V23 archival answer · partial quality"),
    ("workbench_c_partial_stopped", "Workbench C · partial answer, service stopped"),
    ("public_nab_nativeconv_tradeoff", "Public NAB native convolution comparison"),
)
CURRENT_STATUS_RECORDS_V4 = CURRENT_STATUS_RECORDS_V2 + CURRENT_STATUS_RECORDS_V5_ADDED + (_saved_status_v5.METRO_FINAL_RECORD,)


def _current_unavailable_record(record_id: str, title: str, reason: str) -> dict[str, Any]:
    return {
        "id": record_id, "title": title, "status": "unavailable",
        "status_label": "근거 확인 불가", "reason_code": reason,
        "execution_started_utc": None, "execution_ended_utc": None, "root_reviewed_utc": None,
        "summary": "등록된 최신 근거의 파일 또는 SHA256을 확인할 수 없습니다.",
        "limitations": ["이전 성공 기록으로 대체하지 않았습니다."],
        "review_source_sha256": None, "metrics": None,
    }


def _current_pin(entry: Any, root: Path, *, read_json: bool) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise ValueError("invalid current status source reference")
    raw_path, expected = entry["path"], entry["sha256"]
    if not isinstance(raw_path, str) or not raw_path or not Path(raw_path).is_absolute():
        raise ValueError("current status source path must be absolute")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("current status source SHA256 is invalid")
    path = Path(raw_path).resolve(strict=False)
    if not _within(path, root):
        raise ValueError("current status source escapes artifact root")
    if not path.is_file():
        raise ValueError("current status source is missing")
    if read_json and (path.suffix.lower() != ".json" or path.stat().st_size > MAX_JSON_BYTES):
        raise ValueError("current status JSON source is invalid or too large")
    actual = _sha256(path)
    if actual.lower() != expected.lower():
        raise ValueError("current status source SHA256 mismatch")
    return (_json_object(path) if read_json else None), actual


def _same_current_pin(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict) or set(left) != {"path", "sha256"} or set(right) != {"path", "sha256"}:
        return False
    try:
        return (Path(left["path"]).resolve(strict=False) == Path(right["path"]).resolve(strict=False)
                and isinstance(left["sha256"], str) and isinstance(right["sha256"], str)
                and left["sha256"].lower() == right["sha256"].lower())
    except (TypeError, OSError, ValueError):
        return False


def _review_contains_current_pin(review: dict[str, Any], ref: Any) -> bool:
    sources = review.get("sources")
    return isinstance(sources, list) and any(_same_current_pin(source, ref) for source in sources)


def _audit_source_ref(audit: dict[str, Any], filename: str) -> dict[str, str] | None:
    sources = audit.get("sources")
    if not isinstance(sources, list):
        return None
    for source in sources:
        if isinstance(source, dict) and Path(str(source.get("path", ""))).name == filename:
            ref = {"path": source.get("path"), "sha256": source.get("sha256")}
            if _same_current_pin(ref, source):
                return ref
    return None


def _utc_value(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _process_interval(processes: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    starts, ends = [], []
    for process in processes:
        started = _utc_value(process.get("started_at_utc") or process.get("started_utc"))
        ended = _utc_value(process.get("ended_at_utc") or process.get("finished_utc"))
        if started is not None: starts.append(started)
        if ended is not None: ends.append(ended)
    if not starts or not ends:
        return None, None
    return starts[0], ends[-1]


def _current_record_base(record_id: str, title: str, status: str, status_label: str,
                         review: dict[str, Any], review_sha: str, summary: str,
                         limitation: str, execution: list[dict[str, Any]] | None = None,
                         metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    started, ended = _process_interval(execution or [])
    return {
        "id": record_id, "title": title, "status": status, "status_label": status_label,
        "execution_started_utc": started, "execution_ended_utc": ended,
        "root_reviewed_utc": _utc_value(review.get("reviewed_at_utc") or review.get("time_utc") or review.get("at_utc")),
        "summary": summary, "limitations": [limitation],
        "review_source_sha256": review_sha, "metrics": metrics,
    }


def _project_current_record(record_id: str, title: str, refs: Any, root: Path) -> dict[str, Any]:
    if not isinstance(refs, dict):
        raise ValueError("current status record references are invalid")
    if record_id == "native_architecture_no_gain":
        if set(refs) != {"review", "result"}: raise ValueError("native status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "ACTUAL_FIXED_ARCHITECTURE_COMPARISON_NO_IMPROVEMENT_NO_PROMOTION": raise ValueError("native review status mismatch")
        if review.get("new_architectures_promoted") is not False: raise ValueError("native promotion flag mismatch")
        if not _same_current_pin(review.get("results"), refs["result"]): raise ValueError("native result binding mismatch")
        _current_pin(refs["result"], root, read_json=False)
        ensembles = review.get("ensembles")
        if not isinstance(ensembles, list): raise ValueError("native ensemble summary is missing")
        baseline = next((row for row in ensembles if isinstance(row, dict) and row.get("unit") == "baseline_tst-ensemble"), None)
        channel = next((row for row in ensembles if isinstance(row, dict) and row.get("unit") == "channel_tst-ensemble"), None)
        coverage, ci = review.get("coverage"), review.get("channel_minus_baseline_TST_recall_CI95")
        ci_is_numeric_pair = (isinstance(ci, list) and len(ci) == 2
                              and all(_number(value) is not None for value in ci))
        ci_is_interval_pair = (isinstance(ci, list) and len(ci) == 2
                               and all(isinstance(interval, list) and len(interval) == 2
                                       and all(_number(value) is not None for value in interval) for interval in ci))
        if not isinstance(baseline, dict) or not isinstance(channel, dict) or not isinstance(coverage, dict) or not (ci_is_numeric_pair or ci_is_interval_pair):
            raise ValueError("native metrics summary is malformed")
        values = [_number(baseline.get("AP")), _number(channel.get("AP")), _number(baseline.get("supported")),
                  _number(coverage.get("total"))]
        if any(value is None for value in values): raise ValueError("native metrics are invalid")
        ci_projection = [_number(value) for value in ci] if ci_is_numeric_pair else [[_number(value) for value in interval] for interval in ci]
        metrics = {"baseline_tst_ap": values[0], "channel_tst_ap": values[1], "support": values[2],
                   "total": values[3], "channel_minus_baseline_recall_ci95": ci_projection}
        return _current_record_base(record_id, title, "accepted_no_promotion", "ROOT 승인 · 개선/승격 없음",
            review, review_sha, "고정 native METRO 비교에서 새 architecture를 승격하지 않았습니다.",
            "이 비교의 결과이며 일반적인 architecture 우열이나 production 권고가 아닙니다.", metrics=metrics)

    if record_id == "native_maxpool_tradeoff":
        if set(refs) != {"review", "result"}: raise ValueError("native maxpool references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if (review.get("status") != "ROOT_LIMITED_PATCHTST_POOLING_GAIN_WITH_FPR_TRADEOFF_NO_PLATFORM_PROMOTION"
                or review.get("production") is not False):
            raise ValueError("native maxpool review status mismatch")
        if not _same_current_pin(review.get("result"), refs["result"]): raise ValueError("native maxpool result binding mismatch")
        _current_pin(refs["result"], root, read_json=False)
        ensembles = review.get("ensembles")
        if not isinstance(ensembles, dict): raise ValueError("native maxpool metrics missing")
        mean = ensembles.get("baseline_tst-ensemble")
        maximum = ensembles.get("max_tst-ensemble")
        cnn = ensembles.get("baseline_cnn-ensemble")
        counts = review.get("counts")
        if not all(isinstance(row, dict) for row in (mean, maximum, cnn)) or not isinstance(counts, dict):
            raise ValueError("native maxpool metric rows are invalid")
        metrics = {
            "mean_tst_ap": _number(mean.get("AP")), "max_tst_ap": _number(maximum.get("AP")),
            "mean_tst_recall": _number(mean.get("selective_recall")), "max_tst_recall": _number(maximum.get("selective_recall")),
            "mean_tst_fpr": _number(mean.get("selective_FPR")), "max_tst_fpr": _number(maximum.get("selective_FPR")),
            "cnn_recall_at_max_fpr": _number(cnn.get("selective_recall")), "support": _number(counts.get("supported")),
        }
        if any(value is None for value in metrics.values()): raise ValueError("native maxpool metric mismatch")
        return _current_record_base(record_id, title, "observed_gain_with_fpr_tradeoff_no_promotion",
            "고정 비교 관측 · FPR tradeoff · 승격 없음", review, review_sha,
            "Max pooling에서 AP와 recall이 올랐지만 관측 FPR도 높았습니다. 같은 FPR의 CNN recall은 더 높았습니다.",
            "고정된 합성 METRO 비교 한 건이며 일반화나 production 승격 근거가 아닙니다.", metrics=metrics)

    if record_id == "e5_service_smoke":
        if set(refs) != {"review", "execution_receipts"}: raise ValueError("E5 status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "ACTUAL_CPU_FORMAT_SERVICE_LIMITED_ACCEPTED_NOT_LLM_TOOL_INTEGRATION": raise ValueError("E5 review status mismatch")
        runs, processes = review.get("runs"), refs["execution_receipts"]
        if not isinstance(runs, list) or len(runs) != 3 or not isinstance(processes, list) or len(processes) != 3:
            raise ValueError("E5 smoke run count mismatch")
        loaded = []
        for run, process_ref in zip(runs, processes):
            if not isinstance(run, dict) or not _same_current_pin(run.get("process"), process_ref): raise ValueError("E5 process binding mismatch")
            process, _ = _current_pin(process_ref, root, read_json=True)
            loaded.append(process)
        if review.get("LLM_calls") != 0 or review.get("GPU_models") != 0 or review.get("production") is not False:
            raise ValueError("E5 smoke scope mismatch")
        metrics = {"cpu_smoke_runs": 3, "llm_calls": 0, "gpu_models": 0}
        return _current_record_base(record_id, title, "accepted_limited_service_smoke", "ROOT 제한 승인 · V17 format CPU service smoke",
            review, review_sha, "V17의 format-filtered delegation/source-receipt 세 가지 smoke case를 제한적으로 확인했습니다.",
            "V17 format-filtered delegation/source-receipt는 standalone CPU service smoke에서만 확인했습니다. 실제 LLM Tool workflow integration이나 semantic retrieval quality 평가는 아닙니다.",
            execution=loaded, metrics=metrics)

    if record_id == "v18_partial_quality":
        if set(refs) != {"review", "process"}: raise ValueError("V18 status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "EXECUTION_COMPLETED_QUALITY_PARTIAL_NOT_WHOLEQUESTION_SUCCESS": raise ValueError("V18 review status mismatch")
        if not _same_current_pin(review.get("process"), refs["process"]): raise ValueError("V18 process binding mismatch")
        process, _ = _current_pin(refs["process"], root, read_json=True)
        if review.get("question_entirely_satisfied") is not False or review.get("general_LLM_quality_established") is not False:
            raise ValueError("V18 quality status mismatch")
        gaps = review.get("quality_gaps")
        if not isinstance(gaps, list): raise ValueError("V18 quality gap count missing")
        metrics = {"llm_calls": _number(review.get("LLM_calls")), "tool_calls": _number(review.get("Tool_calls")),
                   "wall_seconds": _number(review.get("actual_wall_seconds")), "quality_gap_count": len(gaps)}
        return _current_record_base(record_id, title, "quality_partial", "실행 완료 · 품질 일부 미충족",
            review, review_sha, "실행은 완료됐지만 전체 질문을 충족하지 못했고 일반 LLM 품질은 확립되지 않았습니다.",
            "실제 Answer 문장이나 개별 source text는 표시하지 않습니다.", execution=[process], metrics=metrics)

    if record_id == "v6_runtime_reuse":
        if set(refs) != {"review", "process", "receipt", "original_request"}: raise ValueError("V6 status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "ROOT_LIMITED_ACTUAL_V6_RUNTIME_INTEGRATION_ACCEPTED_REPORT_QUALITY_REMAINS_PARTIAL": raise ValueError("V6 review status mismatch")
        if not _same_current_pin(review.get("process"), refs["process"]) or not _same_current_pin(review.get("receipt"), refs["receipt"]):
            raise ValueError("V6 source binding mismatch")
        process, _ = _current_pin(refs["process"], root, read_json=True)
        _current_pin(refs["receipt"], root, read_json=False)
        _current_pin(refs["original_request"], root, read_json=False)
        timing = review.get("timing")
        calls = review.get("calls")
        if (not isinstance(timing, dict) or review.get("wholequestion_quality_accepted") is not False
                or review.get("default_backend_changed") is not False or review.get("production") is not False
                or not isinstance(calls, list) or len(calls) != 7
                or any(not isinstance(call, dict) or call.get("same_input_bytes") is not True
                       or call.get("same_generated_text") is not True for call in calls)
                or review.get("source_pins_independently_rehashed") != 305):
            raise ValueError("V6 quality or scope mismatch")
        metrics = {key: _number(timing.get(key)) for key in (
            "observed_wall_reduction_fraction", "observed_generation_reduction_fraction", "same_output_tokens")}
        if any(value is None for value in metrics.values()): raise ValueError("V6 timing metrics are invalid")
        metrics["matched_call_count"] = len(calls)
        return _current_record_base(record_id, title, "runtime_limited_acceptance_quality_partial",
            "단일 비교 수용 · 답변 품질은 부분 충족", review, review_sha,
            "동일한 단일 7-call 사례에서 role runtime 경로를 확인했습니다.",
            "관측된 한 사례의 시간 차이이며 반복 통제 timing benchmark나 답변 품질 개선을 뜻하지 않습니다.",
            execution=[process], metrics=metrics)

    if record_id == "v19_quality_failed":
        if set(refs) != {"review", "process", "raw_output"}: raise ValueError("V19 status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "ACTUAL_ARCHIVAL_ANSWER_QUALITY_FAILED_PARTIAL_FORMAT_IMPROVEMENT_ONLY": raise ValueError("V19 review status mismatch")
        if not _same_current_pin(review.get("process"), refs["process"]) or not _same_current_pin(review.get("raw"), refs["raw_output"]):
            raise ValueError("V19 source binding mismatch")
        process, _ = _current_pin(refs["process"], root, read_json=True)
        _current_pin(refs["raw_output"], root, read_json=False)
        failures = review.get("quality_failures")
        if (review.get("wholequestion_satisfied") is not False
                or review.get("general_LLM_quality_established") is not False
                or review.get("cap_saturated") is not False
                or review.get("production") is not False or not isinstance(failures, list)):
            raise ValueError("V19 quality failure summary mismatch")
        metrics = {"llm_calls": _number(review.get("LLM_calls")), "tool_calls": _number(review.get("Tool_calls")),
                   "wall_seconds": _number(review.get("wall_seconds")), "section_chars": _number(review.get("section_chars")),
                   "quality_failure_count": len(failures)}
        return _current_record_base(record_id, title, "quality_failed", "품질 실패 · 보관 Answer",
            review, review_sha, "보관 Answer 검토에서 사실 오류가 확인됐고 전체 질문을 충족하지 못했습니다.",
            "보관 Answer는 현재 조사 결과가 아니며 원문은 표시하지 않습니다.", execution=[process], metrics=metrics)

    if record_id == "same_evidence_14b_quality_failed":
        if set(refs) != {"review", "execution_review"}: raise ValueError("14B archival references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "ROOT_CONFIRMED_SINGLE_CASE_CONTENT_FAIL": raise ValueError("14B confirmation status mismatch")
        if review.get("larger_model_quality_improvement_established") is not False or review.get("promotion") is not False or review.get("production") is not False:
            raise ValueError("14B confirmation scope mismatch")
        if not _same_current_pin(review.get("ROOT_original_review"), refs["execution_review"]):
            raise ValueError("14B execution review binding mismatch")
        execution_review, _ = _current_pin(refs["execution_review"], root, read_json=True)
        if (execution_review.get("status") != "ROOT_ACTUAL_14B_ARCHIVAL_CONTENT_FIDELITY_FAILED"
                or execution_review.get("model_quality_accepted") is not False
                or execution_review.get("wholequestion_satisfied") is not False
                or execution_review.get("production") is not False):
            raise ValueError("14B execution review scope mismatch")
        process_ref = execution_review.get("process")
        process, _ = _current_pin(process_ref, root, read_json=True)
        actual = execution_review.get("actual")
        findings = review.get("confirmed_findings")
        if not isinstance(actual, dict) or not isinstance(findings, list) or len(findings) != 5:
            raise ValueError("14B reviewed summary is incomplete")
        metrics = {"wall_seconds": _number(actual.get("wall_seconds")),
                   "output_tokens": _number(actual.get("output_tokens")),
                   "quality_failure_count": len(findings), "tool_calls": 0}
        if any(value is None for value in metrics.values()): raise ValueError("14B summary metrics invalid")
        return _current_record_base(record_id, title, "quality_failed", "단일 archival Answer · 내용 정확성 실패",
            review, review_sha,
            "한 건의 archival Answer에서 874개 tested chip을 chamber로 표현하고, 6개 signature rate와 coverage를 잘못 요약했습니다.",
            "추가 Tool 호출 없는 단일 답변 사례입니다. 더 큰 모델의 일반 품질 개선이나 현재 조사 완료를 뜻하지 않습니다.",
            execution=[process], metrics=metrics)

    if record_id == "public_retrieval":
        if set(refs) != {"review", "result", "per_query_metrics", "process"}: raise ValueError("public retrieval references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "PUBLIC_RETRIEVAL_METRICS_VERIFIED_WITH_CHILD_EXIT_CODE_CAPTURE_LIMITATION": raise ValueError("public retrieval review status mismatch")
        for key in ("result", "per_query_metrics", "process"):
            review_key = "results" if key == "result" else key
            if not _same_current_pin(review.get(review_key), refs[key]): raise ValueError("public retrieval source binding mismatch")
        _current_pin(refs["result"], root, read_json=False)
        _current_pin(refs["per_query_metrics"], root, read_json=False)
        process, _ = _current_pin(refs["process"], root, read_json=True)
        raw_metrics = review.get("metrics")
        if not isinstance(raw_metrics, dict): raise ValueError("public retrieval metrics missing")
        metrics = {}
        for key, label in (("locked_bm25", "BM25"), ("e5_cosine", "E5"), ("rrf_c60", "RRF c=60")):
            row = raw_metrics.get(key)
            if not isinstance(row, dict): raise ValueError("public retrieval metric row missing")
            values = {name: _number(row.get(source)) for name, source in (
                ("macro_recall@10", "macro_recall@10"), ("macro_recall@100", "macro_recall@100"),
                ("ndcg@10", "ndcg@10"))}
            if any(value is None for value in values.values()): raise ValueError("public retrieval metrics are invalid")
            metrics[label] = values
        if review.get("app_integration") is not False: raise ValueError("public retrieval scope mismatch")
        process_limit = review.get("process_limitation")
        child_exit_available = process.get("exit_code") is not None
        return _current_record_base(record_id, title, "accepted_limited_retrieval", "지표 제한 승인 · public retrieval",
            review, review_sha, "영문 BEIR SciFact test에서 BM25, E5 cosine, RRF 지표를 비교했습니다.",
            "공개 retrieval-only 결과이며 Q-Agent/FAB/LLM answer 품질을 뜻하지 않습니다.",
            execution=[process], metrics={"systems": metrics, "query_count": 300, "positive_qrel_pairs": 339,
                                          "candidate_union_pairs": 327,
                                          "child_exit_code_available": child_exit_available,
                                          "process_limitation_recorded": isinstance(process_limit, str)})

    if record_id == "v23_answer_plan_partial":
        if set(refs) != {"review", "evidence"}: raise ValueError("V23 status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "LIMITED_EXECUTION_AND_SOURCE_FIDELITY_ACCEPTED_QUALITY_GAPS_REMAIN":
            raise ValueError("V23 root review status mismatch")
        if not _review_contains_current_pin(review, refs["evidence"]): raise ValueError("V23 evidence is not bound by ROOT review")
        evidence, _ = _current_pin(refs["evidence"], root, read_json=True)
        if evidence.get("status") != "CODE_SELECTION_FIDELITY_PASS_UNREVIEWED_INTERPRETATION_FAIL_TASK_PARTIAL":
            raise ValueError("V23 evidence status mismatch")
        execution = evidence.get("resources_process")
        fidelity = evidence.get("code_fidelity")
        section = review.get("V23")
        summary = section.get("actual") if isinstance(section, dict) else None
        model_quality = section.get("model_quality") if isinstance(section, dict) else None
        if (not isinstance(execution, dict) or execution.get("process_exit") != 0
                or execution.get("process_source_pins_unchanged") is not True
                or not isinstance(fidelity, dict) or fidelity.get("selected_tables") != 8
                or fidelity.get("checked_cells") != 134 or fidelity.get("derived_operand_checks") != 12
                or fidelity.get("question_fulfillment") != "unverified"
                or not isinstance(summary, str)
                or "0 tool/db calls" not in summary.lower()
                or not isinstance(model_quality, str) or not model_quality.startswith("FAIL_PARTIAL")):
            raise ValueError("V23 reviewed summary fields mismatch")
        metrics = {"wall_seconds": _number(execution.get("elapsed_seconds")),
                   "input_tokens": _number(execution.get("input_tokens")),
                   "output_tokens": _number(execution.get("output_tokens")),
                   "selected_tables": _number(fidelity.get("selected_tables")),
                   "checked_cells": _number(fidelity.get("checked_cells")),
                   "derived_operand_count": _number(fidelity.get("derived_operand_checks")),
                   "tool_calls": 0}
        if any(value is None for value in metrics.values()): raise ValueError("V23 metrics invalid")
        return _current_record_base(record_id, title, "quality_partial", "실행 완료 · Answer 품질 미충족",
            review, review_sha, summary,
            "단일 archival Answer 사례입니다. 질문 충족과 일반 LLM 품질은 확립되지 않았으며 raw role text는 표시하지 않습니다.",
            metrics=metrics)

    if record_id == "workbench_c_partial_stopped":
        if set(refs) != {"review", "evidence"}: raise ValueError("Workbench C status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "LIMITED_EXECUTION_AND_SOURCE_FIDELITY_ACCEPTED_QUALITY_GAPS_REMAIN":
            raise ValueError("Workbench C root review status mismatch")
        if not _review_contains_current_pin(review, refs["evidence"]): raise ValueError("Workbench C evidence is not bound by ROOT review")
        evidence, _ = _current_pin(refs["evidence"], root, read_json=True)
        if evidence.get("status") != "ACTUAL_UI_C_TRACE_INTEGRATION_PASS_LIMITED_RAW_SEMANTICS_FAIL_TASK_PARTIAL":
            raise ValueError("Workbench C evidence status mismatch")
        integration, fidelity, process = evidence.get("integration"), evidence.get("fidelity"), evidence.get("process")
        section = review.get("Workbench_C")
        summary = section.get("actual") if isinstance(section, dict) else None
        service_state = section.get("service_state") if isinstance(section, dict) else None
        model_quality = section.get("model_quality") if isinstance(section, dict) else None
        if (not isinstance(integration, dict) or integration.get("first_business_incidentDB") is not True
                or integration.get("external_API_calls") != 0 or integration.get("production") is not False
                or integration.get("zero_new_MES") is not True
                or not isinstance(fidelity, dict) or fidelity.get("no_general_quality_or_causal_prompt_gain_claim") is not True
                or not isinstance(process, dict) or process.get("wrapper_exit") != 0
                or process.get("survivors") != [] or process.get("resource_abort") is not None
                or not isinstance(summary, str) or not isinstance(service_state, str)
                or "stopped" not in service_state.lower()
                or not isinstance(model_quality, str) or not model_quality.startswith("FAIL_PARTIAL")):
            raise ValueError("Workbench C reviewed summary fields mismatch")
        metrics = {"wall_seconds": _number(process.get("elapsed_seconds")),
                   "llm_calls": _number(len(integration.get("LLM_roles", []))),
                   "tool_calls": _number(len(integration.get("call_metadata_only", []))),
                   "new_mes_calls": 0, "external_api_calls": 0}
        if any(value is None for value in metrics.values()): raise ValueError("Workbench C metrics invalid")
        return _current_record_base(record_id, title, "quality_partial_service_stopped",
            "부분 실행 · Answer 품질 미충족 · 서비스 중지", review, review_sha, summary,
            "선택 대기 scope가 남았고 답변에 의미 오류가 있었습니다. 프로세스 정리 완료 상태이며 서비스는 현재 중지되어 있습니다. raw role text는 표시하지 않습니다.",
            metrics=metrics)

    if record_id == "public_nab_nativeconv_tradeoff":
        if set(refs) != {"review", "evidence"}: raise ValueError("public NAB status references differ")
        review, review_sha = _current_pin(refs["review"], root, read_json=True)
        if review.get("status") != "LIMITED_EXECUTION_AND_SOURCE_FIDELITY_ACCEPTED_QUALITY_GAPS_REMAIN":
            raise ValueError("public NAB root review status mismatch")
        if not _review_contains_current_pin(review, refs["evidence"]): raise ValueError("public NAB evidence is not bound by ROOT review")
        evidence, _ = _current_pin(refs["evidence"], root, read_json=True)
        if evidence.get("status") != "INDEPENDENT_ARITHMETIC_MATCHED_RECEIPT":
            raise ValueError("public NAB independent audit status mismatch")
        public = review.get("Public_NAB")
        raw, mean = (public.get("raw_patch"), public.get("paano_mean")) if isinstance(public, dict) else (None, None)
        if not isinstance(raw, dict) or not isinstance(mean, dict) or public.get("promotion") is not False:
            raise ValueError("public NAB review summary mismatch")
        rows = evidence.get("metrics")
        by_name = {row.get("method"): row for row in rows if isinstance(row, dict)} if isinstance(rows, list) else {}
        expected_rows = (("raw_patch_k3", raw), ("paano_mean17_29", mean))
        metrics: dict[str, Any] = {}
        for source_name, row in expected_rows:
            audited = by_name.get(source_name)
            if not isinstance(audited, dict): raise ValueError("public NAB audited method missing")
            for key in ("AP", "AUC", "standardized_pAUC_max_fpr0.01", "TP", "FP", "FN", "TN"):
                value = _number(row.get(key)); audit_value = _number(audited.get(key))
                if value is None or audit_value is None or value != audit_value:
                    raise ValueError("public NAB root-review and independent metrics differ")
                metrics[f"{source_name}_{key.lower().replace('.', '_').replace('@', '_')}"] = value
        raw_ap = metrics.get("raw_patch_k3_ap"); mean_ap = metrics.get("paano_mean17_29_ap")
        raw_pauc = metrics.get("raw_patch_k3_standardized_pauc_max_fpr0_01")
        mean_pauc = metrics.get("paano_mean17_29_standardized_pauc_max_fpr0_01")
        raw_fp = metrics.get("raw_patch_k3_fp"); mean_fp = metrics.get("paano_mean17_29_fp")
        decision = public.get("decision")
        if (raw_ap is None or mean_ap is None or raw_pauc is None or mean_pauc is None
                or raw_fp is None or mean_fp is None or not (raw_ap > mean_ap and raw_pauc > mean_pauc and raw_fp > mean_fp)
                or not isinstance(decision, str) or public.get("promotion") is not False):
            raise ValueError("public NAB tradeoff/no-promotion assertion failed")
        return _current_record_base(record_id, title, "limited_negative_public_result",
            "공개 비교 · 승격 없음 · 오탐 tradeoff", review, review_sha,
            "한 공개 시계열에서 raw Patch가 PaAno mean보다 AP와 낮은 FPR 구간 지표는 높았지만 FP가 크게 많았습니다.",
            "단일 public NAB series의 이상 탐지 비교이며 official NAB score, SOTA, FAB 또는 미래 1% FPR 보장이 아닙니다.",
            metrics=metrics)

    raise ValueError("unknown current status record")


def _latest_research_status(path: Path, expected_sha256: Any, root: Path) -> dict[str, Any]:
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        reason = "manifest_sha_invalid"
    else:
        reason = "manifest_unavailable"
    try:
        resolved = path.resolve(strict=False)
        if not _within(resolved, root) or not resolved.is_file(): raise ValueError("manifest unavailable")
        if resolved.stat().st_size > MAX_JSON_BYTES or _sha256(resolved).lower() != expected_sha256.lower():
            raise ValueError("manifest hash or size mismatch")
        manifest = _json_object(resolved)
        schema_id = manifest.get("schema_id")
        if schema_id == CURRENT_STATUS_SCHEMA_ID:
            expected_records = CURRENT_STATUS_RECORDS
        elif schema_id == CURRENT_STATUS_SCHEMA_ID_V2:
            expected_records = CURRENT_STATUS_RECORDS_V2
        elif schema_id == CURRENT_STATUS_SCHEMA_ID_V3:
            expected_records = CURRENT_STATUS_RECORDS_V2 + CURRENT_STATUS_RECORDS_V5_ADDED
        elif schema_id == CURRENT_STATUS_SCHEMA_ID_V4:
            expected_records = CURRENT_STATUS_RECORDS_V4
        else:
            raise ValueError("current status manifest schema mismatch")
        records = manifest.get("records")
        expected_ids = {record_id for record_id, _ in expected_records}
        if not isinstance(records, dict) or set(records) != expected_ids:
            return {"status": "unavailable", "reason_code": "record_set_mismatch",
                    "created_at_utc": None,
                    "records": [_current_unavailable_record(record_id, title, "record_set_mismatch")
                                for record_id, title in expected_records],
                    "record_set_verified": False}
        output = []
        for record_id, title in expected_records:
            try:
                if schema_id == CURRENT_STATUS_SCHEMA_ID_V3 and record_id in dict(CURRENT_STATUS_RECORDS_V5_ADDED):
                    output.append(_saved_status_v5.project(record_id, title, records[record_id], root, _current_pin, _utc_value))
                elif schema_id == CURRENT_STATUS_SCHEMA_ID_V4 and record_id in dict(CURRENT_STATUS_RECORDS_V5_ADDED):
                    output.append(_saved_status_v5.project(record_id, title, records[record_id], root, _current_pin, _utc_value))
                elif schema_id == CURRENT_STATUS_SCHEMA_ID_V4 and record_id == _saved_status_v5.METRO_FINAL_RECORD[0]:
                    output.append(_saved_status_v5.project_metro_final(record_id, title, records[record_id], root, _current_pin, _utc_value))
                else:
                    output.append(_project_current_record(record_id, title, records[record_id], root))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                output.append(_current_unavailable_record(record_id, title, "source_missing_or_hash_mismatch"))
        available = sum(row["status"] != "unavailable" for row in output)
        return {"status": "available" if available == len(output) else "partial_unavailable" if available else "unavailable",
                "created_at_utc": _utc_value(manifest.get("created_at_utc")), "records": output,
                "record_set_verified": True}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "unavailable", "reason_code": reason,
                "created_at_utc": None, "records": [], "record_set_verified": False}


class CohortResearchService:
    """Read only the backend-configured, hash-pinned allowlist beneath artifact_root."""

    def __init__(self, options: Mapping[str, Any]):
        if not isinstance(options, Mapping) or options.get("enabled") is not True:
            raise ValueError("cohort research service must be explicitly enabled")
        root_value, manifest_value = options.get("artifact_root"), options.get("manifest_path")
        if not isinstance(root_value, str) or not isinstance(manifest_value, str):
            raise ValueError("artifact_root and manifest_path are required backend options")
        self._root = Path(root_value).resolve(strict=True)
        self._manifest_path = Path(manifest_value).resolve(strict=True)
        if not self._root.is_dir() or not _within(self._manifest_path, self._root) or not self._manifest_path.is_file():
            raise ValueError("manifest must be an existing file beneath artifact_root")
        self._current_status_configured = (
            "current_status_manifest_path" in options or "current_status_manifest_sha256" in options
        )
        status_path = options.get("current_status_manifest_path")
        self._current_status_manifest_path = (
            Path(status_path).resolve(strict=False) if isinstance(status_path, str) and status_path else None
        )
        self._current_status_manifest_sha256 = options.get("current_status_manifest_sha256")

    def snapshot(self) -> dict[str, Any]:
        manifest = _json_object(self._manifest_path)
        if manifest.get("schema_id") != MANIFEST_SCHEMA_ID:
            raise ValueError("unexpected cohort research manifest schema")
        entries = manifest.get("artifacts")
        if not isinstance(entries, dict) or set(entries) - set(ARTIFACT_NAMES):
            raise ValueError("manifest contains invalid artifact names")
        sources: dict[str, dict[str, Any] | None] = {}
        provenance: list[dict[str, Any]] = []
        for name in ARTIFACT_NAMES:
            value, record = _artifact_entry(name, entries.get(name), self._root)
            sources[name] = value
            provenance.append(record)
        snapshot = _build_snapshot(sources, provenance)
        snapshot["milestone"] = _milestone_summary(sources.get("milestone_v5"), self._root)
        snapshot["current_milestone"] = _milestone_summary_v6(sources.get("milestone_v6"), self._root)
        snapshot["completion_milestone"] = _milestone_summary_v6_1(sources.get("milestone_v6_1"), self._root)
        snapshot["confirmation_milestone"] = _milestone_summary_v6_2(sources.get("milestone_v6_2"), self._root)
        snapshot["publication_milestone"] = _milestone_summary_v6_3(sources.get("milestone_v6_3"), self._root)
        snapshot["publication_milestone_v64"] = _milestone_summary_v6_4(sources.get("milestone_v6_4"), self._root)
        snapshot["publication_milestone_v65"] = _milestone_summary_v6_5(sources.get("milestone_v6_5"), self._root)
        snapshot["publication_milestone_v66"] = _milestone_summary_v6_6(sources.get("milestone_v6_6"), self._root)
        snapshot["publication_milestone_v67"] = _milestone_summary_v6_7(
            sources.get("milestone_v6_7"), self._root, snapshot["publication_milestone_v66"]
        )
        snapshot["publication_milestone_v68"] = _milestone_summary_v6_8(sources.get("milestone_v6_8"), self._root)
        snapshot["publication_milestone_v69"] = _milestone_summary_v6_9(sources.get("milestone_v6_9"), self._root)
        if self._current_status_configured:
            status_path = self._current_status_manifest_path or (self._root / "__missing_current_status_manifest__.json")
            snapshot["latest_research_status"] = _latest_research_status(
                status_path, self._current_status_manifest_sha256, self._root
            )
        return snapshot
