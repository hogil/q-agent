import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np


PATH = Path(__file__).resolve().parents[1] / "research" / "fbm_mixed_uncertainty_synthetic_20261030.py"
spec = importlib.util.spec_from_file_location("fbm_mixed", PATH)
fbm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fbm
spec.loader.exec_module(fbm)


def test_raw_representation_is_independent_of_classifier_scores():
    g1, q1 = fbm.build_dataset(12, 2, 0.0, .51)
    g2, q2 = fbm.build_dataset(12, 2, 1.0, .99)
    for a, b in zip(g1 + q1, g2 + q2):
        assert np.array_equal(a.truth, b.truth)
        assert fbm._sim(a, a, "raw", .51) == fbm._sim(b, b, "raw", .99)


def test_wafer_contains_a_b_unknown_proxy_and_unrelated_failure():
    g, _ = fbm.build_dataset(20261030, 3)
    for w in g:
        vals = set(np.unique(w.truth))
        assert {1, 2, 3, 4} <= vals


def test_positions_are_generated_independently_of_semantic_type():
    # Every wafer uses the same position generator; re-labeling site truth cannot
    # move sites and generator code receives no semantic class argument.
    g, _ = fbm.build_dataset(3, 3)
    for w in g:
        assert np.count_nonzero(w.truth) == 15
        assert len(np.argwhere(w.truth > 0)) == 15


def test_high_threshold_preserves_unresolved_instead_of_guessing_type():
    g, _ = fbm.build_dataset(4, 1, 0, 1.0)
    w = g[0]
    hard, soft = fbm._features(w, 1.0)
    unresolved = w.observed & (w.truth > 0)
    assert hard[0] == 0 and hard[1] == 0
    assert np.isclose(hard[2], 1.0) and hard[3] == 0
    assert soft[0] + soft[1] > 0  # Soft mode directly uses scores despite threshold=1.


def test_unobserved_is_distinct_from_pass():
    g, _ = fbm.build_dataset(4, 2)
    w = g[0]
    hard, _ = fbm._features(w, .85)
    assert np.any(~w.observed)
    assert np.isclose(hard[4], w.passed.sum() / w.observed.size)
    assert np.isclose(hard[6], (~w.observed).sum() / w.observed.size)


def test_split_identity_and_reproducibility():
    g1, q1 = fbm.build_dataset(55, 2)
    g2, q2 = fbm.build_dataset(55, 2)
    assert not ({w.asset_id for w in g1} & {w.asset_id for w in q1})
    assert [w.asset_id for w in g1] == [w.asset_id for w in g2]
    assert all(np.array_equal(a.truth, b.truth) and np.array_equal(a.scores, b.scores, equal_nan=True)
               for a, b in zip(g1 + q1, g2 + q2))


def test_result_discloses_simulation_and_composition_metric():
    result = fbm.run_experiment(7, 1)
    assert result["claims"]["real_cnn_prediction"] is False
    assert "truth_composition_l1" in result["results"]["raw"]["queries"][0]
    assert set(result["results"]) == set(fbm.REPRESENTATIONS)
    assert result["leakage_audit"]["duplicate_observed_raw_mask_pairs"] == 0
    assert result["leakage_audit"]["gallery_query_asset_id_overlap"] == 0
    assert result["leakage_audit"]["gallery_duplicate_asset_ids"] == 0
    assert result["leakage_audit"]["query_duplicate_asset_ids"] == 0
    assert "common-observed sites only" in result["design"]["raw_spatial_target"]


def test_scores_exist_for_unknown_failures_and_errors_can_be_accepted():
    g, _ = fbm.build_dataset(20261030, 8, error_rate=1.0, abstain_threshold=.85,
                             unknown_high_confidence_mixture_rate=1.0)
    unknown_seen = False
    accepted_unknown = False
    for w in g:
        mask = w.observed & np.isin(w.truth, (3, 4))
        unknown_seen |= bool(mask.any() and np.isfinite(w.scores[:, :, 0][mask]).all())
        hard, _ = fbm._features(w, .85)
        accepted_unknown |= bool(mask.any() and (hard[0] + hard[1] > 0))
    assert unknown_seen and accepted_unknown


def test_semantic_features_are_spatially_pooled():
    g, _ = fbm.build_dataset(33, 2)
    features = fbm._features(g[0], .85)
    assert features[0].shape == (7,)
    assert features[1].shape == (7,)


def test_spatial_iou_uses_common_observations_and_omits_no_coverage():
    g, _ = fbm.build_dataset(18, 2)
    a, b = g[:2]
    a_fail = np.zeros_like(a.fail_mask); a_fail[0, 0] = True
    b_fail = np.zeros_like(b.fail_mask); b_fail[0, 0] = True
    common = np.zeros_like(a.observed); common[0, 0] = True; common[0, 1] = True
    a = fbm.Wafer(a.asset_id, a.split, a.pattern, a.truth, a_fail, common, common & ~a_fail, a.scores)
    b_obs = common.copy(); b_obs[0, 1] = False
    b = fbm.Wafer(b.asset_id, b.split, b.pattern, b.truth, b_fail, b_obs, b_obs & ~b_fail, b.scores)
    assert fbm._spatial_similarity(a, b) == 1.0
    none = np.zeros_like(common)
    c = fbm.Wafer(b.asset_id, b.split, b.pattern, b.truth, b_fail, none, none, b.scores)
    assert fbm._spatial_similarity(a, c) is None


def test_empty_fail_masks_and_no_failure_semantic_signature_are_explicit():
    g, _ = fbm.build_dataset(21, 1)
    w = g[0]
    empty = np.zeros_like(w.fail_mask)
    a = fbm.Wafer(w.asset_id, w.split, w.pattern, np.zeros_like(w.truth), empty,
                   np.ones_like(w.observed), np.ones_like(w.passed), np.full_like(w.scores, np.nan))
    b = fbm.Wafer("other", "gallery", w.pattern, np.zeros_like(w.truth), empty,
                  np.ones_like(w.observed), np.ones_like(w.passed), np.full_like(w.scores, np.nan))
    assert fbm._spatial_similarity(a, b) is None
    hard, soft = fbm._features(a, .85)
    assert np.all(hard[:4] == 0) and np.all(soft[:4] == 0)


def test_missing_failure_scores_are_unavailable_not_abstained_or_unknown():
    g, _ = fbm.build_dataset(39, 1)
    w = g[0]
    scores = w.scores.copy()
    observed_fail = w.observed & w.fail_mask
    scores[observed_fail] = np.nan
    missing = fbm.Wafer(w.asset_id, w.split, w.pattern, w.truth, w.fail_mask,
                        w.observed, w.passed, scores)
    hard, soft = fbm._features(missing, .85)
    assert np.allclose(hard[:3], 0) and hard[3] == 1
    assert np.allclose(soft[:3], 0) and soft[3] == 1


def test_hard_prediction_channels_map_a_and_b_in_correct_directions():
    g, _ = fbm.build_dataset(41, 1)
    w = g[0]
    scores = w.scores.copy()
    fails = np.argwhere(w.observed & w.fail_mask)
    assert len(fails) >= 2
    ya, xa = fails[0]
    yb, xb = fails[1]
    scores[ya, xa] = (.95, .05)  # A wins
    scores[yb, xb] = (.05, .95)  # B wins
    forced = fbm.Wafer(w.asset_id, w.split, w.pattern, w.truth, w.fail_mask,
                       w.observed, w.passed, scores)
    hard, _ = fbm._features(forced, .85)
    assert hard[0] > 0
    assert hard[1] > 0


def test_partially_missing_score_pair_is_unavailable_without_nan_leakage():
    g, _ = fbm.build_dataset(42, 1)
    w = g[0]
    scores = w.scores.copy()
    y, x = np.argwhere(w.observed & w.fail_mask)[0]
    scores[y, x, 0] = .9
    scores[y, x, 1] = np.nan
    partial = fbm.Wafer(w.asset_id, w.split, w.pattern, w.truth, w.fail_mask,
                        w.observed, w.passed, scores)
    hard, soft = fbm._features(partial, .85)
    assert np.all(np.isfinite(hard)) and np.all(np.isfinite(soft))
    assert hard[3] > 0 and soft[3] > 0


def test_per_pattern_bounds_and_bool_rejection():
    fbm.build_dataset(per_pattern=100)
    for bad in (0, 101, True, 1.5):
        try:
            fbm.build_dataset(per_pattern=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid per_pattern: {bad!r}")


def test_leakage_audit_detects_cross_split_and_within_split_duplicate_ids(monkeypatch):
    original = fbm.build_dataset

    def duplicated_dataset(*args, **kwargs):
        gallery, queries = original(*args, **kwargs)
        queries[0] = replace(queries[0], asset_id=gallery[0].asset_id)
        return gallery + [gallery[0]], queries + [queries[0]]

    monkeypatch.setattr(fbm, "build_dataset", duplicated_dataset)
    audit = fbm.run_experiment(71, 1)["leakage_audit"]
    assert audit["gallery_query_asset_id_overlap"] == 1
    assert audit["gallery_duplicate_asset_ids"] == 1
    assert audit["query_duplicate_asset_ids"] == 1
