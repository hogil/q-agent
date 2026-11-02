import hashlib
import json
from pathlib import Path

from app.cohort_research import ARTIFACT_NAMES, CohortResearchService


def _write_json(root, name, value):
    path = root / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def _write_bytes(root, name, value):
    path = root / name
    path.write_bytes(value)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def _fixture(root):
    native_result = _write_bytes(root, "native-results.json", b'{"saved":"native"}')
    native = _write_json(root, "native-review.json", {
        "status": "ACTUAL_FIXED_ARCHITECTURE_COMPARISON_NO_IMPROVEMENT_NO_PROMOTION",
        "time_utc": "2026-10-26T16:44:17Z", "new_architectures_promoted": False,
        "results": native_result,
        "ensembles": [
            {"unit": "baseline_tst-ensemble", "AP": 0.9324, "supported": 2737},
            {"unit": "channel_tst-ensemble", "AP": 0.9263, "supported": 2737},
        ],
        "coverage": {"total": 4000},
        "channel_minus_baseline_TST_recall_CI95": [-0.063, -0.029],
    })
    maxpool_result = _write_bytes(root, "native-maxpool-results.json", b'{"saved":"maxpool"}')
    maxpool = _write_json(root, "native-maxpool-review.json", {
        "status": "ROOT_LIMITED_PATCHTST_POOLING_GAIN_WITH_FPR_TRADEOFF_NO_PLATFORM_PROMOTION",
        "at_utc": "2026-10-26T17:41:11Z", "result": maxpool_result,
        "production": False,
        "ensembles": {
            "baseline_tst-ensemble": {"AP": 0.9348069661575038, "selective_recall": 0.5094339622641509, "selective_FPR": 0.0029469548133595285},
            "max_tst-ensemble": {"AP": 0.9433193996789694, "selective_recall": 0.5719960278053625, "selective_FPR": 0.005893909626719057},
            "baseline_cnn-ensemble": {"selective_recall": 0.6047666335650447, "selective_FPR": 0.005893909626719057},
        },
        "counts": {"supported": 2025, "total": 3000},
    })
    e5_processes = [_write_json(root, f"e5-process-{i}.json", {
        "started_at_utc": f"2026-10-26T16:0{i}:00Z", "ended_at_utc": f"2026-10-26T16:0{i}:30Z", "exit_code": 0,
    }) for i in (1, 2, 3)]
    e5 = _write_json(root, "e5-review.json", {
        "status": "ACTUAL_CPU_FORMAT_SERVICE_LIMITED_ACCEPTED_NOT_LLM_TOOL_INTEGRATION",
        "reviewed_at_utc": "2026-10-26T16:32:48Z", "LLM_calls": 0, "GPU_models": 0, "production": False,
        "runs": [{"process": ref} for ref in e5_processes],
    })
    v18_process = _write_json(root, "v18-process.json", {
        "started_at_utc": "2026-10-26T15:49:05Z", "ended_at_utc": "2026-10-26T15:58:04Z", "exit_code": 0,
    })
    v18 = _write_json(root, "v18-review.json", {
        "status": "EXECUTION_COMPLETED_QUALITY_PARTIAL_NOT_WHOLEQUESTION_SUCCESS",
        "reviewed_at_utc": "2026-10-26T16:30:51Z", "process": v18_process,
        "LLM_calls": 7, "Tool_calls": 11, "actual_wall_seconds": 533.6,
        "question_entirely_satisfied": False, "general_LLM_quality_established": False,
        "quality_gaps": ["synthetic fact gap"], "raw_answer": "RAW-ROLE-TEXT-MUST-NOT-LEAK",
    })
    v6_process = _write_json(root, "v6-process.json", {
        "started_at_utc": "2026-10-26T15:49:05Z", "ended_at_utc": "2026-10-26T15:57:30Z", "exit_code": 0,
    })
    v6_receipt = _write_bytes(root, "v6-receipt.json", b'{"saved":"v6 receipt"}')
    v6_request = _write_bytes(root, "original-request.json", b'{"saved":"request metadata"}')
    v6 = _write_json(root, "v6-review.json", {
        "status": "ROOT_LIMITED_ACTUAL_V6_RUNTIME_INTEGRATION_ACCEPTED_REPORT_QUALITY_REMAINS_PARTIAL",
        "at_utc": "2026-10-26T17:00:00Z", "process": v6_process, "receipt": v6_receipt,
        "timing": {"observed_wall_reduction_fraction": 0.0536,
                   "observed_generation_reduction_fraction": 0.0754, "same_output_tokens": 1690},
        "calls": [{"same_input_bytes": True, "same_generated_text": True} for _ in range(7)],
        "source_pins_independently_rehashed": 305,
        "wholequestion_quality_accepted": False, "default_backend_changed": False, "production": False,
    })
    v19_process = _write_json(root, "v19-process.json", {
        "started_at_utc": "2026-10-26T16:39:23Z", "ended_at_utc": "2026-10-26T16:43:02Z", "exit_code": 0,
    })
    raw_v19 = _write_bytes(root, "v19-raw.txt", b"RAW-ROLE-TEXT-MUST-NOT-LEAK")
    v19 = _write_json(root, "v19-review.json", {
        "status": "ACTUAL_ARCHIVAL_ANSWER_QUALITY_FAILED_PARTIAL_FORMAT_IMPROVEMENT_ONLY",
        "time_utc": "2026-10-26T16:53:56Z", "process": v19_process, "raw": raw_v19,
        "LLM_calls": 1, "Tool_calls": 0, "wall_seconds": 216.47, "section_chars": 569,
        "cap_saturated": False,
        "quality_failures": ["synthetic factual error"], "wholequestion_satisfied": False,
        "general_LLM_quality_established": False, "production": False,
    })
    archival_review = {
        "status": "ROOT_ACTUAL_14B_ARCHIVAL_CONTENT_FIDELITY_FAILED",
        "at_utc": "2026-10-26T17:53:32Z", "actual": {"wall_seconds": 209.4228852998931, "output_tokens": 416},
        "process": _write_json(root, "archival-process.json", {
            "started_at_utc": "2026-10-26T17:50:00Z", "ended_at_utc": "2026-10-26T17:53:29Z", "exit_code": 0,
        }),
        "model_quality_accepted": False, "wholequestion_satisfied": False, "production": False,
        "specific_content_failures": ["Historical chips mistranslated", "Rates misreported", "forecast status unsupported", "cosine range misreported", "wafer and chip counts conflated"],
    }
    archival = _write_json(root, "archival-review.json", archival_review)
    archival_confirmation = _write_json(root, "archival-confirmation.json", {
        "status": "ROOT_CONFIRMED_SINGLE_CASE_CONTENT_FAIL",
        "reviewed_at_utc": "2026-10-26T18:08:38Z", "ROOT_original_review": archival,
        "larger_model_quality_improvement_established": False, "promotion": False, "production": False,
        "confirmed_findings": archival_review["specific_content_failures"],
    })
    public_result = _write_bytes(root, "public-result.json", b'{"saved":"public result"}')
    public_per_query = _write_bytes(root, "public-per-query.json", b'{"saved":"metrics only"}')
    public_process = _write_json(root, "public-process.json", {
        "started_utc": "2026-10-26T16:34:40Z", "finished_utc": "2026-10-26T16:43:02Z", "exit_code": None,
    })
    public = _write_json(root, "public-review.json", {
        "status": "PUBLIC_RETRIEVAL_METRICS_VERIFIED_WITH_CHILD_EXIT_CODE_CAPTURE_LIMITATION",
        "results": public_result, "per_query_metrics": public_per_query, "process": public_process,
        "scope": "English BEIR SciFact fixed test retrieval only.",
        "metrics": {
            "locked_bm25": {"macro_recall@10": 0.7876, "macro_recall@100": 0.8826, "ndcg@10": 0.6634},
            "e5_cosine": {"macro_recall@10": 0.8066, "macro_recall@100": 0.9250, "ndcg@10": 0.6770},
            "rrf_c60": {"macro_recall@10": 0.8014, "macro_recall@100": 0.9577, "ndcg@10": 0.6899},
        },
        "candidate_union": {"qrel_covered_pairs": 327, "qrel_total_positive_pairs": 339},
        "app_integration": False,
    })
    manifest = {
        "schema_id": "qagent.latest_research_status_sources.v1",
        "created_at_utc": "2026-10-27T01:00:00Z",
        "records": {
            "native_architecture_no_gain": {"review": native, "result": native_result},
            "native_maxpool_tradeoff": {"review": maxpool, "result": maxpool_result},
            "e5_service_smoke": {"review": e5, "execution_receipts": e5_processes},
            "v18_partial_quality": {"review": v18, "process": v18_process},
            "v6_runtime_reuse": {"review": v6, "process": v6_process, "receipt": v6_receipt, "original_request": v6_request},
            "v19_quality_failed": {"review": v19, "process": v19_process, "raw_output": raw_v19},
            "same_evidence_14b_quality_failed": {"review": archival_confirmation, "execution_review": archival},
            "public_retrieval": {"review": public, "result": public_result, "per_query_metrics": public_per_query, "process": public_process},
        },
    }
    status_manifest = _write_json(root, "latest-research-status.json", manifest)
    old_entries = {name: None for name in ARTIFACT_NAMES}
    old_manifest = _write_json(root, "cohort-sources.json", {
        "schema_id": "qagent.cohort_research_sources.v1", "artifacts": old_entries,
    })
    return old_manifest, status_manifest, {
        "native": native, "native_maxpool": maxpool, "archival_confirmation": archival_confirmation,
        "archival_confirmation": archival_confirmation, "archival": archival, "e5": e5, "v18": v18, "v6": v6, "v19": v19, "public": public,
        "native_result": native_result,
    }


def _service(root, old_manifest, status_manifest):
    return CohortResearchService({
        "enabled": True,
        "artifact_root": str(root),
        "manifest_path": old_manifest["path"],
        "current_status_manifest_path": status_manifest["path"],
        "current_status_manifest_sha256": status_manifest["sha256"],
    })


def test_current_status_projects_eight_reviewed_records_without_raw_role_text(tmp_path):
    old_manifest, status_manifest, _ = _fixture(tmp_path)
    snapshot = _service(tmp_path, old_manifest, status_manifest).snapshot()

    section = snapshot["latest_research_status"]
    assert section["status"] == "available"
    records = {row["id"]: row for row in section["records"]}
    assert set(records) == {"native_architecture_no_gain", "native_maxpool_tradeoff", "e5_service_smoke", "v18_partial_quality", "v6_runtime_reuse", "v19_quality_failed", "same_evidence_14b_quality_failed", "public_retrieval"}
    assert records["native_architecture_no_gain"]["status"] == "accepted_no_promotion"
    assert records["native_architecture_no_gain"]["execution_started_utc"] is None
    assert records["native_architecture_no_gain"]["root_reviewed_utc"] == "2026-10-26T16:44:17Z"
    assert records["native_maxpool_tradeoff"]["status"] == "observed_gain_with_fpr_tradeoff_no_promotion"
    assert records["native_maxpool_tradeoff"]["metrics"]["max_tst_ap"] > records["native_maxpool_tradeoff"]["metrics"]["mean_tst_ap"]
    assert records["native_maxpool_tradeoff"]["metrics"]["max_tst_fpr"] > records["native_maxpool_tradeoff"]["metrics"]["mean_tst_fpr"]
    assert records["native_maxpool_tradeoff"]["metrics"]["max_tst_ap"] == 0.9433193996789694
    assert records["native_maxpool_tradeoff"]["metrics"]["cnn_recall_at_max_fpr"] == 0.6047666335650447
    assert records["e5_service_smoke"]["execution_started_utc"] == "2026-10-26T16:01:00Z"
    assert records["e5_service_smoke"]["execution_ended_utc"] == "2026-10-26T16:03:30Z"
    assert records["e5_service_smoke"]["title"] == "E5 V17 format/source service"
    assert "V17 format" in records["e5_service_smoke"]["status_label"]
    e5_limitation = records["e5_service_smoke"]["limitations"][0]
    assert e5_limitation.startswith("V17 format-filtered delegation/source-receipt는 standalone CPU service smoke에서만 확인했습니다.")
    assert "실제 LLM Tool workflow integration" in e5_limitation
    assert "semantic retrieval quality 평가" in e5_limitation
    assert "E5는 실제 LLM Tool routing에 통합되지 않았고" not in e5_limitation
    assert records["v18_partial_quality"]["status"] == "quality_partial"
    assert records["v6_runtime_reuse"]["status"] == "runtime_limited_acceptance_quality_partial"
    assert records["v6_runtime_reuse"]["root_reviewed_utc"] == "2026-10-26T17:00:00Z"
    assert records["v19_quality_failed"]["status"] == "quality_failed"
    assert records["same_evidence_14b_quality_failed"]["status"] == "quality_failed"
    assert records["same_evidence_14b_quality_failed"]["metrics"]["quality_failure_count"] == 5
    assert records["same_evidence_14b_quality_failed"]["metrics"]["tool_calls"] == 0
    assert records["same_evidence_14b_quality_failed"]["metrics"]["wall_seconds"] == 209.4228852998931
    assert "RAW-ROLE-TEXT-MUST-NOT-LEAK" not in json.dumps(snapshot)
    assert records["public_retrieval"]["status"] == "accepted_limited_retrieval"
    assert records["public_retrieval"]["metrics"]["child_exit_code_available"] is False
    assert records["public_retrieval"]["metrics"]["systems"]["RRF c=60"]["macro_recall@100"] == 0.9577
    assert snapshot["publication_milestone_v69"] is None
    assert "RAW-ROLE-TEXT-MUST-NOT-LEAK" not in json.dumps(snapshot)
    assert "raw_answer" not in json.dumps(snapshot)


def test_new_review_hash_mismatch_marks_only_that_record_unavailable(tmp_path):
    old_manifest, status_manifest, source_refs = _fixture(tmp_path)
    Path(source_refs["native_maxpool"]["path"]).write_text("tampered", encoding="utf-8")
    snapshot = _service(tmp_path, old_manifest, status_manifest).snapshot()
    records = {row["id"]: row for row in snapshot["latest_research_status"]["records"]}
    assert records["native_maxpool_tradeoff"]["status"] == "unavailable"
    assert records["native_maxpool_tradeoff"].get("metrics") is None
    assert records["same_evidence_14b_quality_failed"]["status"] == "quality_failed"


def test_changed_source_hash_is_unavailable_and_never_falls_back_to_prior_success(tmp_path):
    old_manifest, status_manifest, source_refs = _fixture(tmp_path)
    Path(source_refs["v19"]["path"]).write_text("tampered", encoding="utf-8")
    snapshot = _service(tmp_path, old_manifest, status_manifest).snapshot()

    records = {row["id"]: row for row in snapshot["latest_research_status"]["records"]}
    assert records["v19_quality_failed"]["status"] == "unavailable"
    assert records["v19_quality_failed"].get("metrics") is None
    assert records["v18_partial_quality"]["status"] == "quality_partial"


def test_missing_or_mismatched_current_manifest_returns_explicit_unavailable(tmp_path):
    old_manifest, status_manifest, _ = _fixture(tmp_path)
    missing = dict(status_manifest, path=str(tmp_path / "missing.json"))
    snapshot = _service(tmp_path, old_manifest, missing).snapshot()
    assert snapshot["latest_research_status"]["status"] == "unavailable"
    assert all(row["status"] == "unavailable" for row in snapshot["latest_research_status"]["records"])

    mismatched = dict(status_manifest, sha256="0" * 64)
    snapshot = _service(tmp_path, old_manifest, mismatched).snapshot()
    assert snapshot["latest_research_status"]["status"] == "unavailable"
    assert all(row["status"] == "unavailable" for row in snapshot["latest_research_status"]["records"])

