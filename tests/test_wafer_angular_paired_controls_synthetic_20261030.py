import unittest

from research.wafer_angular_paired_controls_synthetic_20261030 import run_experiment
from research.wafer_polar_permutation_20261030 import analyze_wafer_polar_positions


class WaferAngularPairedControlsSyntheticTests(unittest.TestCase):
    def test_paired_runs_keep_coordinates_and_radial_defect_counts(self):
        result = run_experiment(seed=41, permutations=99)
        self.assertTrue(result["coordinates_identical"])
        self.assertTrue(result["radial_defect_counts_identical"])
        self.assertEqual(result["observed_denominators"], {"angular_cluster": 512, "angular_balanced": 512})
        self.assertEqual(result["observed_radial_defect_counts"]["angular_cluster"], {
            "center": 16, "inner_ring": 16, "outer_ring": 16, "edge": 16,
        })
        for case in result["analyses"].values():
            self.assertEqual(case["radial"]["permutations"], 99)
            self.assertIsNotNone(case["radial"]["p_value"])
            self.assertEqual(case["polar_orientation_asserted"]["permutations"], 99)
            self.assertIsNotNone(case["polar_orientation_asserted"]["p_value"])
            self.assertFalse(case["polar_orientation_unasserted"]["angular_included"])
            self.assertEqual(case["radial"]["p_value"], case["polar_orientation_unasserted"]["p_value"])

    def test_origin_is_excluded_and_pi_boundary_maps_to_sector_zero(self):
        rows = [
            {"x": 0.0, "y": 0.0, "defect": 1, "strata": "s"},
            {"x": -0.7, "y": 0.0, "defect": 0, "strata": "s"},
            {"x": 0.7, "y": 0.0, "defect": 1, "strata": "s"},
        ]
        result = analyze_wafer_polar_positions(rows, orientation_asserted=True, permutations=99)
        self.assertEqual(result["coverage"]["angular_origin_excluded_count"], 1)
        self.assertEqual(result["coverage"]["angular_eligible_count"], 2)
        sector0 = next(row for row in result["bins"] if row["bin"] == "sector_0")
        self.assertEqual(sector0["eligible_count"], 1)
        self.assertEqual(sector0["observed_fail_count"], 0)

    def test_negative_pi_boundary_and_orientation_disabled(self):
        rows = [
            {"x": -0.7, "y": -0.0, "defect": 1, "strata": "s"},
            {"x": 0.7, "y": 0.0, "defect": 0, "strata": "s"},
        ]
        polar = analyze_wafer_polar_positions(rows, orientation_asserted=True, permutations=99)
        sector0 = next(row for row in polar["bins"] if row["bin"] == "sector_0")
        self.assertEqual(sector0["eligible_count"], 1)
        self.assertEqual(sector0["observed_fail_count"], 1)

        disabled = analyze_wafer_polar_positions(rows, orientation_asserted=False, permutations=99)
        self.assertFalse(disabled["angular_included"])
        self.assertFalse(disabled["orientation_asserted"])
        self.assertEqual(disabled["bins"], analyze_wafer_polar_positions(
            rows, orientation_asserted=False, permutations=99
        )["bins"])


if __name__ == "__main__":
    unittest.main()
