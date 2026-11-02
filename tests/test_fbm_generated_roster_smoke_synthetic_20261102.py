from dataclasses import replace

import pytest

from research import fbm_class_position_synthetic_generator_20261102 as generator
from research import fbm_generated_roster_smoke_synthetic_20261102 as smoke


def test_generated_66_sample_cohort_roundtrips_into_balanced_rosters():
    result = smoke.run_smoke()
    assert result["generated_sample_count"] == 66
    assert result["role_sample_counts"] == {
        "development": 6, "gallery": 36, "holdout": 6, "pilot": 6, "query": 12,
    }
    assert result["selected_role_sample_counts"] == {"gallery": 18, "query": 6}
    assert len(result["cohort_id_audit"]) == 66
    assert {row["role"] for row in result["cohort_id_audit"]} == {
        "pilot", "development", "gallery", "query", "holdout",
    }
    assert all(len(row["sample_id_hash"]) == 64 for row in result["cohort_id_audit"])
    assert result["schedule_manifest_json_roundtrip_validated"] is True
    assert len(result["selection_audit"]["gallery"]["center"]) == 6
    assert len(result["selection_audit"]["query"]["ring"]) == 2
    for selected in result["selection_audit"]["gallery"].values():
        assert [item["selected_class"] for item in selected].count("A") == 3
        assert [item["selected_class"] for item in selected].count("B") == 3
    for selected in result["selection_audit"]["query"].values():
        assert {item["selected_class"] for item in selected} == {"A", "B"}
    assert len(result["schedule_manifest"]["assignments"]) == 6
    for check in result["query_roster_checks"].values():
        assert set(check["cell_counts"].values()) == {3}
        assert check["candidate_count"] == 12
        assert check["relevance_counts"] == {"class_only": 6, "position_only": 6, "joint": 3}
    assert "caller assertion" in result["opaque_id_randomness"]
    assert "never encoder input" in result["audit_artifact_scope"]
    assert "blinded-evaluator input" in result["audit_artifact_scope"]
    assert "no real FBM" in result["limitation"]


def test_cross_role_family_leakage_fails_before_roster_creation(monkeypatch):
    samples = generator.generate(smoke.SEED, family_counts=smoke.FAMILY_COUNTS)
    gallery_sample = next(sample for sample in samples if sample.role == "gallery")
    contaminated = [
        sample if sample.role != "query" else sample
        for sample in samples
    ]
    query_sample = next(sample for sample in contaminated if sample.role == "query")
    contaminated[contaminated.index(query_sample)] = __import__("dataclasses").replace(
        query_sample, family_id=gallery_sample.family_id,
    )
    roster_called = False

    def fail_if_called(*args, **kwargs):
        nonlocal roster_called
        roster_called = True
        raise AssertionError("roster creation must not run after split validation fails")

    monkeypatch.setattr(smoke, "create_schedule_manifest", fail_if_called)
    with pytest.raises(ValueError, match="family leakage across"):
        smoke.run_smoke(samples=contaminated)
    assert not roster_called


def test_choose_rejects_non_ab_family_pair_with_value_error():
    samples = generator.generate(smoke.SEED, family_counts=smoke.FAMILY_COUNTS)
    target = next(sample for sample in samples if sample.role == "gallery" and sample.regime == "center")
    malformed = [
        replace(sample, true_class="A") if sample.family_id == target.family_id else sample
        for sample in samples
    ]
    with pytest.raises(ValueError, match="exactly one A/B pair"):
        smoke._choose(malformed)
