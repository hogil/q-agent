import hashlib
import json
from pathlib import Path

import pytest

from app import cohort_milestone_summary_v6_9 as v69_module
from app.cohort_milestone_summary_v6_9 import milestone_summary_v6_9


def _write(root: Path, name: str, value: dict) -> dict:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(root: Path, monkeypatch) -> dict:
    native = {
        "status": "ROOT_LIMITED_ACCEPTANCE_NATIVE20_FIXED_FOUR_SYNTHETIC_FITS_AND_POST_P1_CONFIRMATION",
        "reviewed_by": "ROOT", "synthetic": True, "production": False,
        "counts": {"fresh_CONF": 2000, "CONF_supported": 1361, "CONF_supported_positive": 678, "CONF_supported_normal": 683},
        "fits": [{"family": "hf_patchtst", "seed": 17}, {"family": "hf_patchtst", "seed": 29},
                 {"family": "cnn1d", "seed": 17}, {"family": "cnn1d", "seed": 29}],
        "input": "128 numeric UTC bins x20 explicit feature/mask channels; no image conversion",
        "ensemble_metrics": {
            "hf_patchtst": {"AP": .9344084686123246, "AUC": .9265301010205713, "selective_recall": .3687315634218289,
                            "unconditional_recall": .25, "FP": 1, "normal_supported": 683,
                            "one_sided95_CP_upper_selective_FPR": .006926621659938263},
            "cnn1d": {"AP": .9469621475440011, "AUC": .9406336784185679, "selective_recall": .6032448377581121,
                      "unconditional_recall": .409, "FP": 3, "normal_supported": 683,
                      "one_sided95_CP_upper_selective_FPR": .01131290044698999},
        },
        "live_Tool_activated": False, "current_question_LLM_quality_pass": False,
        "limits": ["CNN scored higher in this fixed comparison; no family/seed was promoted after confirmation."],
    }
    audit = {"status": "ROOT_POST_P1_INDEPENDENT_METRIC_RECOMPUTATION", "reviewed_by": "ROOT", "synthetic": True, "production": False,
             "AP_AUC_FP_counts_recomputed_exact": True}
    observability = {"status": "ROOT_POST_P1_DESCRIPTIVE_OBSERVABILITY_AUDIT_NOT_PREDECLARED_PERFORMANCE_TEST",
                     "synthetic_only": True, "production": False,
                     "limits": ["Post-hoc descriptive accounting only; thresholds, weights, population and future experiment objective remain unchanged."]}
    v16 = {"status": "ROOT_FAILED_PARTIAL_REVIEW_NO_ANSWER", "reviewed_by": "ROOT", "synthetic_only": True, "production": False,
           "actual_abort_elapsed_seconds": 600.0330158001743, "wall_limit_seconds": 600,
           "totals": {"returned_calls": 6}, "answer_generation_called": True, "answer_raw_returned": False,
           "question_quality_pass": False, "semantic_improvement_established": False}
    records = {
        "native_fixed_four": ("native.json", native),
        "native_metric_audit": ("metric.json", audit),
        "native_observability": ("observability.json", observability),
        "evidence_v16": ("v16.json", v16),
    }
    refs, expected = {}, {}
    for key, (filename, value) in records.items():
        refs[key] = _write(root, filename, value)
        expected[key] = (filename, refs[key]["sha256"], value["status"])
    monkeypatch.setattr(v69_module, "ROOT_REVIEWS", expected)
    return {"schema_id": "qagent.model_lab_publication_v6_9.v1", "status": "prepared_from_ROOT_reviewed_records",
            "synthetic": True, "production": False, "promotion": False, "general_LLM_quality_established": False,
            "root_reviews": refs, "limits": ["Weighted V3 remains source preparing; no fit result is included."]}


def test_v69_projects_fixed_native_metrics_and_v16_failure_without_promotion(tmp_path, monkeypatch):
    result = milestone_summary_v6_9(_fixture(tmp_path, monkeypatch), tmp_path)
    assert result["native_fixed_four"]["fresh_conf"] == 2000
    assert result["native_fixed_four"]["supported"] == 1361
    assert result["native_fixed_four"]["families"]["cnn1d"]["false_positives"] == 3
    assert result["native_fixed_four"]["families"]["cnn1d"]["one_sided95_cp_upper_selective_fpr"] == pytest.approx(.0113129, abs=1e-7)
    assert result["native_fixed_four"]["families"]["hf_patchtst"]["one_sided95_cp_upper_selective_fpr"] == pytest.approx(.0069266, abs=1e-7)
    assert result["native_fixed_four"]["promotion"] is False
    assert result["evidence_v16"]["llm_returns"] == 6
    assert result["evidence_v16"]["answer_raw_returned"] is False
    assert result["synthetic"] is True and result["production"] is False
    assert result["general_LLM_quality_established"] is False


def test_v69_rejects_hash_drift_or_claim_boundary_changes(tmp_path, monkeypatch):
    source = _fixture(tmp_path, monkeypatch)
    path = Path(source["root_reviews"]["evidence_v16"]["path"])
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="proof hash mismatch"):
        milestone_summary_v6_9(source, tmp_path)

    source = _fixture(tmp_path, monkeypatch)
    source["promotion"] = True
    with pytest.raises(ValueError, match="draft boundary"):
        milestone_summary_v6_9(source, tmp_path)
