import unittest

from research.wafer_position_permutation_20261030 import analyze_wafer_positions


def ring_rows(failing_bins=(), *, per_bin=12, strata="A"):
    rows = []
    radii = (0.12, 0.40, 0.68, 0.92)
    for b, radius in enumerate(radii):
        for i in range(per_bin):
            angle = 2 * 3.141592653589793 * (i + 0.15 * b) / per_bin
            rows.append({"x": radius * __import__("math").cos(angle),
                         "y": radius * __import__("math").sin(angle),
                         "defect": int(b in failing_bins and i < per_bin // 2),
                         "strata": strata})
    return rows


class WaferPositionPermutationTests(unittest.TestCase):
    def test_center_edge_and_ring_signals(self):
        for target in (0, 2, 3):
            rows = ring_rows({target})
            result = analyze_wafer_positions(rows, permutations=199, seed=17)
            self.assertEqual(result["status"], "spatial_evidence")
            self.assertLessEqual(result["p_value"], 0.05)
            self.assertEqual(result["bins"][target]["observed_fail_count"], 6)

    def test_seed_reproducibility_and_finite_sample_p(self):
        rows = ring_rows({0})
        a = analyze_wafer_positions(rows, permutations=199, seed=4)
        b = analyze_wafer_positions(rows, permutations=199, seed=4)
        self.assertEqual(a["p_value"], b["p_value"])
        self.assertEqual(a["exceedances"], b["exceedances"])
        self.assertGreater(a["p_value"], 0)

    def test_random_input_is_not_labeled_as_proof_of_randomness(self):
        rows = ring_rows()
        for i, row in enumerate(rows):
            row["defect"] = int((i * 7 + i // 4) % 5 == 0)
        result = analyze_wafer_positions(rows, permutations=199, seed=9)
        self.assertIn(result["status"], {"spatial_evidence", "no_detected_spatial_evidence"})
        if result["status"] == "no_detected_spatial_evidence":
            self.assertIn("does not establish randomness", result["interpretation"])

    def test_strata_counts_are_preserved_and_expected_values_conditioned(self):
        rows = ring_rows({0}, strata="P1") + ring_rows({3}, strata="P2")
        # Shift coordinates in the second independent stratum to keep die positions unique.
        for i, row in enumerate(rows[48:]):
            row["x"] += 0.00001 * (i + 1)
        result = analyze_wafer_positions(rows, permutations=99, seed=11)
        self.assertEqual(sum(r["observed_fail_count"] for r in result["bins"]), 12)
        self.assertAlmostEqual(sum(r["expected_fail_count"] for r in result["bins"]), 12)
        self.assertIn("exchangeable within caller-supplied strata", result["assumptions"][0])

    def test_validation_insufficient_and_coverage(self):
        invalid_sets = [
            [{"x": float("nan"), "y": 0, "defect": 0, "strata": "A"}],
            [{"x": 1.1, "y": 0, "defect": 0, "strata": "A"}],
            [{"x": 0, "y": 0, "defect": 0, "strata": "A"}] * 2,
            [{"x": 0, "y": 0, "defect": 2, "strata": "A"}],
            [{"x": 0, "y": 0, "defect": 0, "strata": []}],
            [{"x": 0, "y": 0, "defect": 0, "strata": float("nan")}],
            [{"x": 0, "y": 0, "defect": 0, "strata": float("inf")}],
            [{"x": 0, "y": 0, "defect": 0, "strata": ()}],
            [{"x": 0, "y": 0, "defect": 0, "strata": (True,)}],
            [{"x": 0, "y": 0, "defect": 0, "strata": ("",)}],
            [{"x": 0, "y": 0, "defect": 0, "strata": (float("nan"),)}],
        ]
        for rows in invalid_sets:
            with self.assertRaises(ValueError):
                analyze_wafer_positions(rows)
        for rows in ([], ring_rows()[:4], [{**r, "defect": 0} for r in ring_rows()]):
            result = analyze_wafer_positions(rows)
            self.assertEqual(result["status"], "insufficient")
            self.assertIsNone(result["p_value"])
        result = analyze_wafer_positions(ring_rows({0}), permutations=99)
        self.assertEqual(result["coverage"]["eligible_inspected_die_count"], 48)
        self.assertEqual(sum(result["coverage"]["bin_eligible_counts"].values()), 48)

    def test_hand_calculated_hypergeometric_moments_and_boundary_rule(self):
        radii = (0.1, 0.2, 0.4, 0.5, 0.6, 0.7, 0.9, 1.0)
        rows = [{"x": radius, "y": 0.0, "defect": int(i < 2), "strata": "S"}
                for i, radius in enumerate(radii)]
        result = analyze_wafer_positions(rows, permutations=99)
        # N=8, K=2, m=2: E=mK/N=0.5, Var=m*p*(1-p)*(N-m)/(N-1)=9/28.
        self.assertAlmostEqual(result["bins"][0]["expected_fail_count"], 0.5)
        self.assertAlmostEqual(result["bins"][0]["variance"], 9 / 28)
        self.assertEqual(result["bins"][0]["eligible_count"], 2)
        self.assertEqual(result["radial_bin_boundary_rule"],
                         "upper bounds inclusive; a die on a shared boundary belongs to the inner bin")

    def test_parameter_boundaries_and_zero_variance_bins(self):
        for options in ({"permutations": 98}, {"alpha": 0}, {"alpha": 1}, {"alpha": float("nan")}):
            with self.assertRaises(ValueError):
                analyze_wafer_positions(ring_rows({0}), **options)
        # Each stratum has labels confined to one bin: conditional variance is zero everywhere.
        rows = []
        for b, radius in enumerate((0.1, 0.4, 0.7, 0.9)):
            for i in range(2):
                rows.append({"x": radius, "y": i * 0.001, "defect": i, "strata": ("S", b)})
        result = analyze_wafer_positions(rows)
        self.assertEqual(result["status"], "insufficient")
        self.assertIsNone(result["p_value"])
        self.assertTrue(all(item["variance"] == 0 for item in result["bins"]))


if __name__ == "__main__":
    unittest.main()
