import unittest
import math

import numpy as np

from research import fbm_paired_factorial_synthetic_20261030 as study


class PairedFactorialSyntheticTests(unittest.TestCase):
    def test_five_seeds_are_24_samples_with_balanced_cells_and_lineage_safe_splits(self):
        for seed in study.SEEDS:
            samples = study.generate(seed)
            self.assertEqual(len(samples), 24)
            self.assertEqual({s.master_seed for s in samples}, {seed})
            for regime in study.REGIMES:
                for cls in ("A", "B"):
                    for split in study.SPLITS:
                        cell = [s for s in samples if (s.regime, s.wafer_class, s.split) == (regime, cls, split)]
                        self.assertEqual(len(cell), 2)
            group_splits = {}
            for s in samples:
                group_splits.setdefault(s.lineage_group_id, set()).add(s.split)
            self.assertTrue(all(len(v) == 1 for v in group_splits.values()))

    def test_counterparts_share_masks_and_every_label_view_is_paired(self):
        samples = study.generate(42)
        groups = {}
        for s in samples:
            groups.setdefault(s.lineage_group_id, []).append(s)
        self.assertEqual(len(groups), 12)
        for pair in groups.values():
            self.assertEqual(len(pair), 2)
            self.assertEqual(pair[0].metadata["mask_hash"], pair[1].metadata["mask_hash"])
            for s in pair:
                self.assertEqual(set(s.label_maps_by_policy), set(study.LABEL_POLICIES))
                self.assertEqual(set(s.object_id_arrays_by_policy), set(study.LABEL_POLICIES))
                for policy, labels in s.label_maps_by_policy.items():
                    self.assertEqual(int((labels == study.KNOWN_A).sum()), 10, policy)
                    self.assertEqual(int((labels == study.KNOWN_B).sum()), 10, policy)
                self.assertEqual(int(s.fail_mask.sum()), 20)
                self.assertTrue(np.array_equal(s.raw_array.astype(bool), s.fail_mask))
                self.assertTrue(np.all(s.known_label_map[s.fail_mask] > 0))
                self.assertEqual(set(np.unique(s.known_label_map[s.fail_mask])), {1, 2})

    def test_coupled_target_assignment_shuffle_marginals_and_random_regime(self):
        center = (study.SIZE - 1) / 2
        checked_random_ring_counts = []
        for seed in study.SEEDS:
            samples = study.generate(seed)
            groups = {}
            for s in samples:
                groups.setdefault(s.lineage_group_id, []).append(s)
            for regime in ("center", "ring"):
                for group in (pair for pair in groups.values() if pair[0].regime == regime):
                    a, b = sorted(group, key=lambda item: item.wafer_class)
                    target = study._target_positions(a.metadata["positions_yx"], regime)
                    self.assertEqual(len(target), 10)
                    self.assertEqual(sum(a.label_maps_by_policy["spatial_coupled"][p] == study.KNOWN_A for p in target), 10)
                    self.assertEqual(sum(b.label_maps_by_policy["spatial_coupled"][p] == study.KNOWN_A for p in target), 0)
                    for policy in study.LABEL_POLICIES:
                        for sample in (a, b):
                            labels = sample.label_maps_by_policy[policy]
                            self.assertEqual(sum(labels[p] == study.KNOWN_A for p in sample.metadata["positions_yx"]), 10)
                            self.assertEqual(sum(labels[p] == study.KNOWN_B for p in sample.metadata["positions_yx"]), 10)
                        # Counterpart maps have equal A/B histograms and opposite labels coordinate-wise.
                        self.assertTrue(all(a.label_maps_by_policy[policy][p] != b.label_maps_by_policy[policy][p]
                                            for p in a.metadata["positions_yx"]))
            for pair in (pair for pair in groups.values() if pair[0].regime == "random"):
                sample = pair[0]
                self.assertEqual(len(study._target_positions(sample.metadata["positions_yx"], "random")), 0)
                ring_count = sum(.45 <= math.hypot(y - center, x - center) / (study.SIZE / 2) <= .65
                                 for y, x in sample.metadata["positions_yx"])
                checked_random_ring_counts.append(ring_count)
        self.assertGreaterEqual(len(checked_random_ring_counts), 20)
        self.assertGreater(len(set(checked_random_ring_counts)), 1)
        self.assertTrue(any(count != 10 for count in checked_random_ring_counts))

    def test_policy_metadata_matches_generator_assignments(self):
        sample = study.generate(42)[0]
        note = sample.metadata["policy_note"]
        self.assertIn("class A assigns A to all 10 target defects and B to all 10 outside", note)
        self.assertIn("class B is the exact complement", note)
        self.assertIn("seed-paired within-wafer permutation", note)
        self.assertIn("uniform 10-of-20 assignment", note)
        self.assertIn("deliberately encodes the target class/position", sample.metadata["leakage_note"])
        self.assertIn("no real wafer generalization", sample.metadata["leakage_note"])

    def test_noise_and_reject_are_exact_shared_unknown_preserving_draws(self):
        clean = study.generate(1)
        noisy = study.generate(1, error_rate=.2, reject_rate=.2)
        by_id = {s.sample_id: s for s in clean}
        for s in noisy:
            orig = by_id[s.sample_id]
            self.assertTrue(np.array_equal(orig.metadata["positions_yx"], s.metadata["positions_yx"]))
            self.assertEqual(len(s.metadata["rejected_coordinates_yx"]), 4)
            self.assertEqual(len(s.metadata["flipped_coordinates_yx"]), 4)
            self.assertTrue(np.all(s.known_label_map[s.reject_mask] == 0))
            self.assertTrue(np.all(s.object_id_array[s.reject_mask] == study.UNKNOWN_REJECT))
            self.assertEqual(int(s.known_label_map[s.fail_mask].sum() > 0), 1)
        groups = {}
        for s in noisy:
            groups.setdefault(s.lineage_group_id, []).append(s)
        for pair in groups.values():
            self.assertEqual(pair[0].metadata["rejected_coordinates_yx"], pair[1].metadata["rejected_coordinates_yx"])
            self.assertEqual(pair[0].metadata["flipped_coordinates_yx"], pair[1].metadata["flipped_coordinates_yx"])

    def test_invalid_inputs_and_determinism(self):
        first = study.generate(42)
        second = study.generate(42)
        self.assertEqual([s.metadata["mask_hash"] for s in first], [s.metadata["mask_hash"] for s in second])
        self.assertTrue(all(np.array_equal(a.object_id_array, b.object_id_array) for a, b in zip(first, second)))
        with self.assertRaises(ValueError):
            study.generate(13)
        with self.assertRaises(ValueError):
            study.generate(42, error_rate=.1)


if __name__ == "__main__":
    unittest.main()
