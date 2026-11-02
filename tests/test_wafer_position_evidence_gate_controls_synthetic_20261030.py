import unittest

from research.wafer_class_position_controls_synthetic_20261030 import SCENARIOS
from research.wafer_position_evidence_gate_controls_synthetic_20261030 import (
    run_experiment, run_one,
)


class EvidenceGateControlsSyntheticTests(unittest.TestCase):
    def test_all_scenarios_connect_rows_analyzer_and_gate(self):
        result = run_experiment(seeds=(42,), permutations=99)
        self.assertEqual(result["run_count"], len(SCENARIOS))
        for run in result["runs"]:
            self.assertEqual(run["input_row_count"], 192)
            self.assertEqual(len(run["results"]), 4)
            self.assertIn("classified_inspected_die_occurrence", run["estimand_denominators"])
            self.assertIn("within_classified_fail_composition", run["estimand_denominators"])
            for item in run["results"]:
                self.assertIn("gate_status", item)
                self.assertIn("gate_reason", item)
                self.assertIn("raw_p_value", item)
                self.assertIn("holm_adjusted_p_value", item)

    def test_selective_rejection_is_ineligible_and_explicit(self):
        run = run_one("selective_center_a_rejection", 42, 99)
        self.assertFalse(run["assertions"]["labeler_position_independent_asserted_input"])
        self.assertFalse(run["assertions"]["label_independence_assertion_truthful_by_design"])
        self.assertFalse(run["assertions"]["coverage_adequate_asserted"])
        self.assertTrue(all(item["gate_status"] == "insufficient" for item in run["results"]))
        self.assertTrue(all(item["gate_reason"] == "missing_result" for item in run["results"]))
        self.assertTrue(all(item["raw_p_value"] is None for item in run["results"]))

    def test_coverage_assertion_changes_only_for_selective_rejection(self):
        for scenario in SCENARIOS:
            run = run_one(scenario, 42, 99)
            expected = scenario != "selective_center_a_rejection"
            self.assertIs(run["assertions"]["coverage_adequate_asserted"], expected)
            if expected:
                self.assertTrue(all(item["gate_status"] != "insufficient" for item in run["results"]))

    def test_occurrence_and_composition_have_distinct_denominators(self):
        run = run_one("center_fail_constant_composition", 42, 99)
        occ = run["estimand_denominators"]["classified_inspected_die_occurrence"]
        comp = run["estimand_denominators"]["within_classified_fail_composition"]
        self.assertNotEqual(occ, comp)

    def test_small_permutation_count_rejected(self):
        with self.assertRaises(ValueError):
            run_one("uniform_null", 42, 98)


if __name__ == "__main__":
    unittest.main()
