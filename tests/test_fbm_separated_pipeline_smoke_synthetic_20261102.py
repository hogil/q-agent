import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import fbm_separated_pipeline_smoke_synthetic_20261102 as pipeline


def test_synthetic_pipeline_wires_split_schedule_rosters_and_three_metrics():
    result = pipeline.run_smoke()

    assert result["status"] == "synthetic_pipeline_smoke_only"
    assert result["scores_are_fixed_synthetic_values"] is True
    assert result["model_called_or_trained"] is False
    assert result["split_audit"]["sample_count"] == 5
    assert result["symmetry_candidate_audit"]["candidate_count"] == 0
    assert len(result["schedule_manifest"]["assignments"]) == 2
    assert len(json.dumps(result["schedule_manifest"])) > 0
    assert len(result["rosters"]) == 2
    for query_id, roster in result["rosters"].items():
        assert len(roster["roster"]) == 12
        assert len(roster["class_only"]) == 6
        assert len(roster["position_only"]) == 6
        assert len(roster["joint"]) == 3
        assert set(result["rank_metrics"][query_id]["metrics"]) == {
            "class_only", "position_only", "joint"
        }
    # For q0, g00-g02 are the same-class/same-position cell and receive
    # scores 11, 10, 9; all other roster IDs receive lower scores.
    q0_roster = set(result["rosters"]["q0"]["roster"])
    q0_ranking = result["rank_metrics"]["q0"]["ranking"]
    assert set(q0_ranking) == q0_roster
    assert len(q0_ranking) == 12
    assert q0_ranking[:3] == ["g00", "g01", "g02"]
    q0_metrics = result["rank_metrics"]["q0"]["metrics"]
    assert q0_metrics["class_only"]["hit_at_3"] == 1.0
    assert q0_metrics["class_only"]["recall_at_3"] == 0.5
    assert q0_metrics["position_only"]["hit_at_3"] == 1.0
    assert q0_metrics["position_only"]["recall_at_3"] == 0.5
    assert q0_metrics["joint"]["hit_at_3"] == 1.0
    assert q0_metrics["joint"]["recall_at_3"] == 1.0
    assert result["assertions"]["metadata_lineage"].startswith("caller assertion")
    assert "encoder boundary and freeze" in result["unverified"]
    assert not any(key in result for key in ("research_ready", "evidence_valid"))


@pytest.mark.parametrize(
    "contamination", ["exact_duplicate", "family_leakage", "ancestry_leakage"]
)
def test_split_contamination_fails_before_rank_metrics(monkeypatch, contamination):
    def forbidden_metrics(**kwargs):
        pytest.fail("rank metrics must not run after split audit failure")

    monkeypatch.setattr(pipeline, "score_separated_rank_metrics", forbidden_metrics)
    with pytest.raises(ValueError, match="leakage|duplicate"):
        pipeline.run_smoke(**{contamination: True})


def test_rotated_cross_role_mask_is_candidate_warning_and_metrics_continue(monkeypatch):
    metric_calls = []
    original_metrics = pipeline.score_separated_rank_metrics

    def tracking_metrics(**kwargs):
        metric_calls.append(kwargs)
        return original_metrics(**kwargs)

    monkeypatch.setattr(pipeline, "score_separated_rank_metrics", tracking_metrics)
    result = pipeline.run_smoke(symmetry_candidate=True)

    assert result["split_audit"]["sample_count"] == 5
    warning = result["symmetry_candidate_audit"]
    assert warning["candidate_count"] == 1
    pair = warning["candidate_pairs"][0]
    assert {pair["left"]["role"], pair["right"]["role"]} == {
        "pilot", "development"
    }
    assert "rotations" in warning["comparison"]
    assert "candidate only" in warning["interpretation"]
    assert "no automatic rejection" in warning["interpretation"]
    assert len(metric_calls) == 2
    assert set(result["rank_metrics"]) == {"q0", "q1"}


def test_one_pixel_noise_is_jaccard_demo_warning_without_rejecting_metrics(monkeypatch):
    metric_calls = []
    original_metrics = pipeline.score_separated_rank_metrics

    def tracking_metrics(**kwargs):
        metric_calls.append(kwargs)
        return original_metrics(**kwargs)

    monkeypatch.setattr(pipeline, "score_separated_rank_metrics", tracking_metrics)
    result = pipeline.run_smoke(jaccard_demo=True)

    # The exact D4 checker cannot match the additional pixel, but the bounded
    # Jaccard demo can flag its rotated near-match at the illustrative cutoff.
    assert result["symmetry_candidate_audit"]["candidate_count"] == 0
    warning = result["jaccard_demo_audit"]
    assert warning["threshold"] == 0.90
    assert "not evaluated" in warning["threshold_provenance"]
    assert warning["candidate_count"] == 1
    pair = warning["candidate_pairs"][0]
    assert pair["max_jaccard"] == pytest.approx(20 / 21)
    assert pair["candidate"] is True
    assert "must not trigger automatic rejection" in warning["interpretation"]
    assert len(metric_calls) == 2
    assert set(result["rank_metrics"]) == {"q0", "q1"}


def test_synthetic_artifact_preflight_reports_limited_fake_artifact_validation():
    result = pipeline.run_smoke(artifact_preflight=True)
    report = result["artifact_preflight"]

    assert report["valid"] is True
    assert report["artifact_created_at_utc"] == "2026-11-01T00:00:00Z"
    assert report["cutoff_utc"] == "2026-11-01T00:00:00Z"
    assert len(report["expected_sha256"]) == 4
    assert "does not establish a trusted pre-evaluation freeze" in report["manifest_provenance"]
    assert report["model_use"].startswith("fake artifact bytes only")
    assert "not established" in report["encoder_metadata_isolation"]


@pytest.mark.parametrize(
    "failure, message", [
        ("missing", "all and only required artifact roles"),
        ("tampered", "SHA-256 mismatch"),
        ("after_cutoff", "after cutoff"),
    ],
)
def test_invalid_synthetic_artifact_preflight_fails_before_metrics(
    monkeypatch, failure, message
):
    def forbidden_metrics(**kwargs):
        pytest.fail("rank metrics must not run after artifact preflight failure")

    monkeypatch.setattr(pipeline, "score_separated_rank_metrics", forbidden_metrics)
    with pytest.raises(ValueError, match=message):
        pipeline.run_smoke(artifact_preflight=True, artifact_failure=failure)
