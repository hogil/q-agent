import unittest
from dataclasses import replace
from unittest.mock import patch

import research.fbm_mixed_uncertainty_synthetic_20261030 as source
import research.fbm_mixed_repeated_synthetic_20261030 as repeated
from research.fbm_mixed_repeated_synthetic_20261030 import run_repeated, seed_list


class RepeatedSyntheticTest(unittest.TestCase):
    def test_seed_ranges_are_distinct(self):
        seeds = seed_list()
        self.assertEqual(len(seeds), 8)
        self.assertEqual(len(set(seeds)), 8)
        self.assertEqual([b-a for a, b in zip(seeds, seeds[1:])], [1_000_000] * 7)

    def test_two_seed_smoke_and_determinism(self):
        first = run_repeated(n_seeds=2)
        second = run_repeated(n_seeds=2)
        self.assertEqual(first, second)
        self.assertEqual(first["design"]["seeds"], [20261030, 21261030])
        self.assertEqual(set(first["summaries"]), {"low_noise", "high_noise"})
        for rows in first["seed_results"].values():
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["query_count"], 12)
                self.assertEqual(set(row["representations"]), {"raw", "hard_semantic", "soft_semantic", "raw_plus_hard", "raw_plus_soft"})
                for metrics in row["representations"].values():
                    self.assertIsNotNone(metrics["truth_composition_l1"])
                    self.assertEqual(metrics["spatial_valid_comparisons"] + metrics["spatial_excluded"], 12)

    def test_detects_raw_score_mismatch_across_scenarios(self):
        original = repeated.run_experiment

        def changed_second_scenario(**kwargs):
            result = original(**kwargs)
            if kwargs["error_rate"] == 0.35:
                result["results"]["raw"]["queries"][0]["score"] += 0.001
            return result

        with patch.object(repeated, "run_experiment", side_effect=changed_second_scenario):
            with self.assertRaisesRegex(AssertionError, "raw baseline tuple"):
                run_repeated(n_seeds=1)

    def test_rejects_positive_leakage_audit(self):
        original = repeated.run_experiment

        def leaked(**kwargs):
            result = original(**kwargs)
            result["leakage_audit"]["duplicate_observed_raw_mask_pairs"] = 1
            return result

        with patch.object(repeated, "run_experiment", side_effect=leaked):
            with self.assertRaisesRegex(AssertionError, "leakage audit failed"):
                run_repeated(n_seeds=1)

    def test_detects_duplicate_id_within_gallery_split(self):
        original = source.build_dataset

        def duplicate_gallery_id(*args, **kwargs):
            gallery, queries = original(*args, **kwargs)
            gallery[1] = replace(gallery[1], asset_id=gallery[0].asset_id)
            return gallery, queries

        with patch.object(source, "build_dataset", side_effect=duplicate_gallery_id):
            with self.assertRaisesRegex(AssertionError, "leakage audit failed"):
                run_repeated(n_seeds=1)


if __name__ == "__main__":
    unittest.main()
