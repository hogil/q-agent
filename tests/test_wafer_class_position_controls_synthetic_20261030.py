import unittest

from research import wafer_class_position_controls_synthetic_20261030 as study
from research.wafer_defect_class_position_20261030 import analyze_defect_class_positions


class SyntheticClassPositionControlsTests(unittest.TestCase):
    def test_fixed_grid_is_unique_inside_unit_disk_and_covers_all_bins(self):
        points = study.grid()
        self.assertEqual(len(points), 192)
        self.assertEqual(len(set(points)), len(points))
        self.assertTrue(all(x * x + y * y <= 1 for x, y in points))
        radii = {round((x * x + y * y) ** 0.5, 2) for x, y in points}
        self.assertEqual(radii, {0.10, 0.40, 0.68, 0.91})

    def test_source_probability_design_invariants(self):
        for radius in (0.10, 0.40, 0.68, 0.91):
            probs = study._probabilities("uniform_null", radius)
            self.assertEqual(probs, (0.20, 0.20, 0.60))
            self.assertAlmostEqual(sum(probs), 1.0)
            center_fail = study._probabilities("center_fail_constant_composition", radius)
            fail = center_fail[0] + center_fail[1]
            self.assertAlmostEqual(center_fail[0] / fail, 0.5)
            self.assertAlmostEqual(center_fail[1] / fail, 0.5)
            self.assertAlmostEqual(sum(center_fail), 1.0)
        for scenario in ("a_center_b_uniform", "a_ring_b_uniform"):
            for radius in (0.10, 0.40, 0.68, 0.91):
                a, b, passed = study._probabilities(scenario, radius)
                self.assertEqual(b, 0.20)
                self.assertAlmostEqual(a + b + passed, 1.0)
        # Position-dependent, class-dependent label selection is explicit.
        self.assertEqual(study._label_from_source_outcome("selective_center_a_rejection", .10, "A"), ("rejected", None))
        self.assertEqual(study._label_from_source_outcome("selective_center_a_rejection", .40, "A"),
                         ("confirmed_known_single_label", "A"))
        self.assertEqual(study._label_from_source_outcome("selective_center_a_rejection", .10, "B"),
                         ("confirmed_known_single_label", "B"))

    def test_generation_is_deterministic_and_has_only_accepted_schema(self):
        first = study.generate_rows("a_center_b_uniform", 42)
        self.assertEqual(first, study.generate_rows("a_center_b_uniform", 42))
        self.assertEqual(len(first), 192)
        expected = {"x", "y", "strata", "inspected", "label_status", "class_id"}
        self.assertTrue(all(set(row) == expected for row in first))
        self.assertTrue(all(row["label_status"] in study.LABEL_STATUSES for row in first))
        self.assertFalse(any("true" in key or "latent" in key or "source_outcome" in key
                             for row in first for key in row))

    def test_common_draws_and_b_membership_are_paired_except_center_fail_design(self):
        draws = study._source_draws(42)
        self.assertEqual(draws, study._source_draws(42))
        # All scenarios use the same base uniforms at each fixed grid position.
        self.assertEqual(len(draws), len(study.grid()))
        scenarios = ("uniform_null", "a_center_b_uniform", "a_ring_b_uniform",
                     "selective_center_a_rejection")
        for seed in study.SEEDS:
            b_memberships = []
            for scenario in scenarios:
                rows = study.generate_rows(scenario, seed)
                b_memberships.append({(row["x"], row["y"]) for row in rows
                                      if row["label_status"] == "confirmed_known_single_label"
                                      and row["class_id"] == "B"})
                b_probs = {study._probabilities(scenario, (x * x + y * y) ** .5)[1]
                           for x, y in study.grid()}
                self.assertEqual(b_probs, {0.20})
            self.assertTrue(all(membership == b_memberships[0] for membership in b_memberships[1:]))
        self.assertEqual(study._probabilities("center_fail_constant_composition", .10)[1], .325)
        self.assertEqual(study._probabilities("center_fail_constant_composition", .91)[1], .075)

    def test_report_exposes_four_test_family_and_zero_bin_coverage_for_no_data(self):
        empty = analyze_defect_class_positions(
            [], ("A", "B"), labeler_position_independent_asserted=True,
            permutations=99, seed=42, alpha=.05,
        )
        self.assertEqual(empty["holm_family_size"], 4)
        self.assertEqual(empty["testable_hypothesis_count"], 0)
        self.assertEqual(empty["coverage"]["input_row_count"], 0)
        for group in empty["estimands"].values():
            for result in group["class_results"].values():
                self.assertEqual(result["status"], "insufficient")
                self.assertIsNone(result["raw_p_value"])
                self.assertIsNone(result["holm_adjusted_p_value"])
                self.assertEqual(result["classified_die_denominator_by_radial_bin"],
                                 {name: 0 for name in ("center", "inner_ring", "outer_ring", "edge")})
        self.assertIn("insufficient", " ".join(
            result["status"] for group in empty["estimands"].values()
            for result in group["class_results"].values()))

    def test_99_permutation_single_run_smoke(self):
        record = study._run_one("uniform_null", 42, 99)
        self.assertEqual(record["input_row_count"], 192)
        self.assertFalse(record["inference_authoritative"])
        self.assertTrue(record["caller_assertion_truthful"])
        self.assertEqual(record["p_value_validity"], "synthetic_design_only")
        self.assertEqual(record["complete_analysis_output"]["holm_family_size"], 4)
        self.assertEqual(len(record["four_class_estimand_results"]), 4)
        self.assertTrue(all("raw_p_value" in item and "holm_adjusted_p_value" in item
                            and "status" in item for item in record["four_class_estimand_results"]))
        self.assertEqual(record["coverage"]["input_row_count"], 192)
        self.assertIn("no trained classifier", record["exchangeability_note"])

    def test_all_scenarios_are_non_authoritative_and_separate_validity_scope(self):
        for scenario in study.SCENARIOS:
            with self.subTest(scenario=scenario):
                record = study._run_one(scenario, 42, 99)
                self.assertFalse(record["inference_authoritative"])
                self.assertEqual(record["caller_assertion_truthful"],
                                 scenario != "selective_center_a_rejection")
                self.assertEqual(record["p_value_validity"],
                                 "invalid_by_designed_exchangeability_violation"
                                 if scenario == "selective_center_a_rejection" else "synthetic_design_only")

    def test_scenario_five_is_marked_invalid_and_honest_assertion_is_unavailable(self):
        record = study._run_one("selective_center_a_rejection", 42, 99)
        self.assertFalse(record["caller_assertion_truthful"])
        self.assertFalse(record["inference_authoritative"])
        self.assertEqual(record["p_value_validity"], "invalid_by_designed_exchangeability_violation")
        self.assertEqual(record["honest_assertion_safety_check"]["status"], "unavailable")
        self.assertEqual(record["complete_analysis_output"]["holm_family_size"], 4)
        for estimand, group in record["complete_analysis_output"]["estimands"].items():
            for cid, result in group["class_results"].items():
                summary = next(item for item in record["four_class_estimand_results"]
                               if item["estimand"] == estimand and item["class_id"] == cid)
                self.assertEqual(summary["analysis_seed"], result["seed"])


if __name__ == "__main__":
    unittest.main()
