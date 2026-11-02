import importlib.util
from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1]
               / "research/fbm_type_position_synthetic_20261030.py")
SPEC = importlib.util.spec_from_file_location("fbm_type_position_synthetic_20261030", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FBMTypePositionSyntheticTests(unittest.TestCase):
    def test_type_is_not_used_to_generate_positions_and_unknown_is_distinct(self):
        a = MODULE._make_wafer("a", "query", "upper", "A", 1234)
        b = MODULE._make_wafer("b", "query", "upper", "B", 1234)
        unknown = MODULE._make_wafer("u", "query", "upper", "UNKNOWN", 1234)
        np.testing.assert_array_equal(a.defect_mask, b.defect_mask)
        np.testing.assert_array_equal(b.defect_mask, unknown.defect_mask)
        self.assertEqual(set(np.unique(a.chip_id_map[a.defect_mask])), {MODULE.ID_VALUES["A"]})
        self.assertEqual(set(np.unique(b.chip_id_map[b.defect_mask])), {MODULE.ID_VALUES["B"]})
        self.assertEqual(set(np.unique(unknown.chip_id_map[unknown.defect_mask])),
                         {MODULE.ID_VALUES["UNKNOWN"]})
        self.assertFalse(np.shares_memory(a.defect_mask, a.yield_mask))
        self.assertTrue(np.array_equal(unknown.defect_mask, unknown.yield_mask))
        self.assertLess(MODULE._cosine(MODULE._id_yield_features(a),
                                      MODULE._id_yield_features(b)), 1.0)

    def test_dataset_is_reproducible_disjoint_and_has_no_duplicate_raw_masks(self):
        gallery, queries = MODULE.build_dataset(seed=777, per_cell=2)
        gallery2, queries2 = MODULE.build_dataset(seed=777, per_cell=2)
        self.assertEqual([w.asset_id for w in gallery], [w.asset_id for w in gallery2])
        for w1, w2 in zip(gallery + queries, gallery2 + queries2):
            np.testing.assert_array_equal(w1.defect_mask, w2.defect_mask)
        self.assertFalse({w.asset_id for w in gallery} & {w.asset_id for w in queries})
        hashes = [np.packbits(w.defect_mask).tobytes() for w in gallery + queries]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertTrue(all(w.asset_id.startswith(f"{w.split}-") for w in gallery + queries))
        self.assertTrue(all(not any(label in w.asset_id for label in MODULE.PATTERNS + MODULE.TYPES)
                            for w in gallery + queries))

    def test_asset_id_is_search_metadata_not_a_classifier_feature(self):
        gallery, queries = MODULE.build_dataset(seed=979, per_cell=1)
        self.assertEqual(MODULE.run_experiment(seed=979, per_cell=1)["design"]["defect_type_controls_position"],
                         False)
        q, g = queries[0], gallery[0]
        changed_q = replace(q, asset_id="query-opaque-replaced")
        changed_g = replace(g, asset_id="gallery-opaque-replaced")
        np.testing.assert_array_equal(MODULE._id_yield_features(q),
                                      MODULE._id_yield_features(changed_q))
        self.assertEqual(MODULE._score("raw_only", q, g), MODULE._score("raw_only", changed_q, changed_g))
        self.assertEqual(MODULE._score("oracle_id_yield_only", q, g),
                         MODULE._score("oracle_id_yield_only", changed_q, changed_g))

    def test_expected_hit_for_ties_is_order_independent_and_exact_score_only(self):
        ranking = [
            {"asset_id": "opaque-0", "pattern": "other", "score": 0.9},
            {"asset_id": "opaque-a", "pattern": "target", "score": 0.8},
            {"asset_id": "opaque-b", "pattern": "other", "score": 0.8},
            {"asset_id": "opaque-c", "pattern": "other", "score": 0.8},
        ]
        # One correct among three at the Top-3 boundary, with two slots:
        # 1 - C(2,2)/C(3,2) = 2/3.
        self.assertEqual(MODULE._expected_hit_at_k(ranking, "pattern", "target", 1), 0.0)
        self.assertAlmostEqual(MODULE._expected_hit_at_k(ranking, "pattern", "target", 3), 2 / 3)
        self.assertAlmostEqual(MODULE._expected_hit_at_k(list(reversed(ranking)), "pattern", "target", 3),
                               2 / 3)
        # Adjacent but non-equal floats are separate score groups, not a tie.
        almost = [
            {"asset_id": "opaque-x", "pattern": "other", "score": 0.8},
            {"asset_id": "opaque-y", "pattern": "target", "score": float(np.nextafter(0.8, 1.0))},
        ]
        self.assertEqual(MODULE._expected_hit_at_k(almost, "pattern", "target", 1), 1.0)

    def test_run_records_three_views_pattern_and_type_metrics(self):
        result = MODULE.run_experiment(seed=881, per_cell=1)
        self.assertFalse(result["claims"]["cnn_prediction"])
        self.assertIn("oracle synthetic", result["oracle_annotation"])
        self.assertIn("upper-bound/wiring sanity check", result["oracle_annotation"])
        self.assertIn("not oracle knowledge", result["design"]["unknown_id"])
        self.assertIn("independent contribution is not evaluated", result["design"]["yield_mask_limitation"])
        self.assertIn("not classifier features", result["design"]["search_input_metadata"])
        self.assertEqual(result["leakage_audit"]["gallery_query_asset_id_overlap"], 0)
        self.assertEqual(result["leakage_audit"]["duplicate_raw_mask_pairs_across_distinct_wafers"], 0)
        self.assertEqual(set(result["results"]), set(MODULE.REPRESENTATIONS))
        for report in result["results"].values():
            self.assertEqual(report["pattern_metrics"]["queries"], len(MODULE.PATTERNS) * len(MODULE.TYPES))
            self.assertEqual(report["defect_type_metrics"]["queries"], len(MODULE.PATTERNS) * len(MODULE.TYPES))
            self.assertEqual(len(report["queries"]), len(MODULE.PATTERNS) * len(MODULE.TYPES))
            self.assertIn("expected_top1_hit_rate", report["pattern_metrics"])
            self.assertIn("expected_top3_hit_rate", report["defect_type_metrics"])
            self.assertTrue(all(len(row["ranking"]) == len(MODULE.PATTERNS) * len(MODULE.TYPES)
                                for row in report["queries"]))
            self.assertTrue(all(row["query_asset_id"].startswith("query-")
                                and all(hit["asset_id"].startswith("gallery-") for hit in row["ranking"])
                                for row in report["queries"]))


if __name__ == "__main__":
    unittest.main()
