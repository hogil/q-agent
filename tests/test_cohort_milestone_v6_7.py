import hashlib
import json
from pathlib import Path

import pytest

from app import cohort_milestone_summary_v6_7 as v67_module
from app.cohort_milestone_summary_v6_7 import milestone_summary_v6_7


EXPECTED = {
    "fullworld_evidence_v11": ("actual-evidence-V11-ROOT-failed-partial-review-v1.json", "ROOT_FAILED_PARTIAL_TOOLS_SUCCEEDED_JUDGE_ROUTER_DISAGREEMENT"),
    "metrology_v2": ("actual-metrology-V2-ROOT-failed-review-v1.json", "ROOT_FAILED_INITIAL_ROUTER_GRAMMAR_ZERO_REQUESTS"),
    "groupedq1_v5": ("groupedq1-V5-ROOT-rejection-v1.json", "ROOT_REJECTED_CACHED_NUMERICAL_AND_BF16_SPEED_GATES"),
}


def _ref(root: Path, name: str, value: dict) -> dict:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(root: Path, monkeypatch) -> tuple[dict, dict]:
    prior = {"schema_id": "qagent.skip_research_milestone.v6.6", "proof_count": 3,
             "status": "prepared_pending_ROOT_review", "synthetic": True, "production": False,
             "fresh_trend": {"raw_points": 4218861, "charts": 3000}}
    prior_capsule = _ref(root, v67_module.PRIOR_V66_CAPSULE[0], {
        "schema_id": "qagent.model_lab_publication_v6_6.v1", "proofs": {"one": {}, "two": {}, "three": {}},
    })
    monkeypatch.setattr(v67_module, "PRIOR_V66_CAPSULE", (v67_module.PRIOR_V66_CAPSULE[0], prior_capsule["sha256"]))
    prior_ref = prior_capsule
    v11 = _ref(root, EXPECTED["fullworld_evidence_v11"][0], {
        "status": EXPECTED["fullworld_evidence_v11"][1], "reviewed_by": "ROOT", "production": False,
        "whole_question_satisfied": False, "general_LLM_quality_established": False,
        "summary": {"actual_LLM_returns": 4, "Tool_calls": 11, "evidence_facts": 9, "Answer_executed": False,
                    "new_actions": 0, "elapsed_seconds": 305.7372506},
        "manual_findings": ["Judge requested sandbox_status; Router chose no fresh evidence, so the strict requery validator stopped execution."],
    })
    metrology = _ref(root, EXPECTED["metrology_v2"][0], {
        "status": EXPECTED["metrology_v2"][1], "reviewed_by": "ROOT", "production": False,
        "whole_task_satisfied": False, "general_LLM_quality_established": False,
        "summary": {"actual_LLM_returns": 1, "output_tokens": 14, "JSON_parse_error": "Unterminated string",
                    "supplementary_requests": 0, "new_intents": 0, "new_audit_events": 0,
                    "metrology_execution_or_measurements_completed": False},
    })
    grouped = _ref(root, EXPECTED["groupedq1_v5"][0], {
        "status": EXPECTED["groupedq1_v5"][1], "reviewed_by": "ROOT", "production": False,
        "numerical_gate_pass": False, "speed_gate_pass": False, "candidate_promoted": False,
        "active_backend_unchanged": "accepted full-query per-head FP32 V3",
        "cached_full_vocabulary_recomputed": [{"allclose": True, "fixed_bounds_pass": True}] + [
            {"allclose": False, "fixed_bounds_pass": False} for _ in range(4)],
        "timings_recomputed": [{"dtype": "float32"}, {"dtype": "bfloat16"}],
    })
    monkeypatch.setattr(v67_module, "ROOT_REVIEWS", {
        key: (EXPECTED[key][0], ref["sha256"], EXPECTED[key][1])
        for key, ref in (("fullworld_evidence_v11", v11), ("metrology_v2", metrology), ("groupedq1_v5", grouped))
    })
    source = {"schema_id": "qagent.model_lab_publication_v6_7.v1", "status": "prepared_from_ROOT_reviewed_records",
              "synthetic": True, "production": False, "prior_milestone": prior_ref,
              "root_reviews": {"fullworld_evidence_v11": v11, "metrology_v2": metrology, "groupedq1_v5": grouped},
              "trend_raw_points_scope": "all_3000_calibration_and_confirmation_charts",
              "limits": ["Synthetic studies only."]}
    return source, prior


def test_v67_preserves_v66_and_displays_three_root_failures_without_promotion(tmp_path, monkeypatch):
    source, prior = _fixture(tmp_path, monkeypatch)
    result = milestone_summary_v6_7(source, tmp_path, prior)

    assert result["prior_v66"]["proof_count"] == 3
    assert result["trend_raw_points_scope"] == "all_3000_calibration_and_confirmation_charts"
    assert result["reviews"]["fullworld_evidence_v11"]["llm_returns"] == 4
    assert result["reviews"]["fullworld_evidence_v11"]["answer_executed"] is False
    assert result["reviews"]["metrology_v2"]["requests"] == 0
    assert result["reviews"]["groupedq1_v5"]["numerical_fail_steps"] == 4
    assert result["reviews"]["groupedq1_v5"]["candidate_promoted"] is False
    assert result["production"] is False


def test_v67_rejects_wrong_root_review_status_or_promoted_candidate(tmp_path, monkeypatch):
    source, prior = _fixture(tmp_path, monkeypatch)
    path = Path(source["root_reviews"]["groupedq1_v5"]["path"])
    proof = json.loads(path.read_text(encoding="utf-8"))
    proof["candidate_promoted"] = True
    path.write_text(json.dumps(proof), encoding="utf-8")
    source["root_reviews"]["groupedq1_v5"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    ref = source["root_reviews"]["groupedq1_v5"]
    v67_module.ROOT_REVIEWS["groupedq1_v5"] = (
        EXPECTED["groupedq1_v5"][0], ref["sha256"], EXPECTED["groupedq1_v5"][1]
    )
    with pytest.raises(ValueError, match="GroupedQ V5 must remain rejected and unpromoted"):
        milestone_summary_v6_7(source, tmp_path, prior)
