import math

import numpy as np
import pytest

from research.fbm_class_position_synthetic_generator_20261102 import generate
from research.fbm_generated_descriptor_baseline_synthetic_20261102 import (
    FAMILY_COUNTS,
    SEED,
    SCHEDULE_ID,
    _cosine,
    oracle_class_position_histogram,
    raw_binary_position_histogram,
    run_baseline,
)
from research.fbm_generated_roster_smoke_synthetic_20261102 import _choose
from research.fbm_separated_relevance_roster_synthetic_20261102 import (
    RosterSample,
    build_rosters,
    create_schedule_manifest,
)
from research.fbm_separated_rank_metrics_synthetic_20261102 import score_separated_rank_metrics


def test_feature_callables_receive_only_array_or_bytes_and_are_metadata_free():
    mask = np.zeros((192, 192), dtype=np.uint8)
    mask[0, 0] = 1
    oracle = np.zeros_like(mask)
    oracle[0, 0] = 2
    raw_feature = raw_binary_position_histogram(mask.tobytes())
    oracle_feature = oracle_class_position_histogram(oracle)
    assert raw_feature.shape == (64,)
    assert oracle_feature.shape == (128,)
    assert raw_feature[0] == 1
    assert oracle_feature[64] == 1


def test_fixed_cohort_same_roster_direct_scores_and_metrics_are_deterministic():
    cohort = generate(SEED, family_counts=FAMILY_COUNTS)
    selected, _ = _choose(cohort)
    roster_samples = [RosterSample(s.sample_id, s.family_id, s.role, s.true_class, s.regime) for s in selected]
    manifest = create_schedule_manifest(roster_samples, SCHEDULE_ID)
    rosters = build_rosters(roster_samples, SCHEDULE_ID, manifest)
    by_id = {s.sample_id: s for s in selected}
    result = run_baseline(samples=cohort)
    assert result["query_count"] == 6
    assert set(result["per_query"]) == set(rosters)

    qid, row = next(iter(result["per_query"].items()))
    assert row["candidate_ids"] == list(rosters[qid]["roster"])
    assert set(row["metrics"]) == {"raw_binary_position_histogram", "oracle_class_position_histogram"}
    q = by_id[qid]
    cid = row["candidate_ids"][0]
    g = by_id[cid]
    expected_raw = _cosine(
        raw_binary_position_histogram(q.raw_array), raw_binary_position_histogram(g.raw_array)
    )
    expected_oracle = _cosine(
        oracle_class_position_histogram(q.id_maps[q.true_class]),
        oracle_class_position_histogram(g.id_maps[g.true_class]),
    )
    for arm, expected in (("raw_binary_position_histogram", expected_raw),
                          ("oracle_class_position_histogram", expected_oracle)):
        metrics_result = row["metrics"][arm]
        assert metrics_result["assertions"]["verified_by_function"] is False
        assert set(metrics_result["ranking"]) == set(row["candidate_ids"])
        relevance = {key: set(rosters[qid][key]) for key in ("class_only", "position_only", "joint")}
        scores = {}
        feature = raw_binary_position_histogram if arm.startswith("raw") else oracle_class_position_histogram
        for candidate_id in row["candidate_ids"]:
            sample = by_id[candidate_id]
            value = sample.raw_array if arm.startswith("raw") else sample.id_maps[sample.true_class]
            query_value = q.raw_array if arm.startswith("raw") else q.id_maps[q.true_class]
            scores[candidate_id] = _cosine(feature(query_value), feature(value))
        direct = score_separated_rank_metrics(
            scores=scores, relevance=relevance, schedule_id=SCHEDULE_ID,
            asserted_class_label_free_blind_ids=True, asserted_encoder_metadata_isolated=True,
        )
        assert metrics_result == direct
        assert math.isclose(scores[cid], expected)
    assert run_baseline(samples=cohort) == result


def test_invalid_feature_arrays_fail_closed():
    with pytest.raises(ValueError):
        raw_binary_position_histogram(np.zeros((191, 192), dtype=np.uint8))
    invalid = np.zeros((192, 192), dtype=np.uint8)
    invalid[0, 0] = 2
    with pytest.raises(ValueError):
        raw_binary_position_histogram(invalid)
    with pytest.raises(ValueError):
        oracle_class_position_histogram(np.zeros((192, 192), dtype=np.uint8))

