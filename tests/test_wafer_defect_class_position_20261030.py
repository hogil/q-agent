import unittest
import json
from unittest.mock import patch

from research import wafer_defect_class_position_20261030 as module
from research.wafer_defect_class_position_20261030 import _holm, _class_seed, analyze_defect_class_positions


def row(x, y, status, cid=None, strata="s", inspected=True):
    return {"x": x, "y": y, "strata": strata, "inspected": inspected, "label_status": status, "class_id": cid}


class ClassPositionTests(unittest.TestCase):
    def run_analysis(self, rows, classes=("A", "B"), **kwargs):
        return analyze_defect_class_positions(rows, classes, labeler_position_independent_asserted=True,
                                              permutations=199, seed=17, **kwargs)

    def test_center_positive_and_two_denominators_differ(self):
        rows = [row(0.05, 0.0, "confirmed_known_single_label", "A"),
                row(0.12, 0.0, "confirmed_known_single_label", "A")]
        rows += [row(0.0, 0.35 + i * 0.01, "confirmed_known_single_label", "B") for i in range(10)]
        rows += [row(-0.3, 0.35 + i * 0.01, "pass") for i in range(8)]
        result = self.run_analysis(rows)
        occ = result["estimands"]["classified_inspected_die_occurrence"]["class_results"]["A"]
        comp = result["estimands"]["within_classified_fail_composition"]["class_results"]["A"]
        self.assertEqual(occ["target_class_count"] + occ["control_count"], 20)
        self.assertEqual(comp["target_class_count"] + comp["control_count"], 12)
        self.assertEqual(occ["bins"][0]["target_class_count"], 2)
        self.assertEqual(comp["bins"][0]["target_class_count"], 2)
        self.assertTrue(json.dumps(result))
        self.assertNotIn("observed_fail_count", json.dumps(result))
        self.assertNotIn("eligible_inspected_die_count", json.dumps(result))

    def test_class_uniform_null_does_not_force_significance(self):
        rows = [row(-0.9 + i * .1, 0.0, "confirmed_known_single_label", "A" if i % 2 == 0 else "B") for i in range(19)]
        result = self.run_analysis(rows)
        for family in result["estimands"].values():
            self.assertNotEqual(family["class_results"]["A"]["status"], "spatial_evidence")

    def test_global_center_fail_concentration_is_not_assigned_to_a(self):
        # Center contains most failures, while the A:B ratio matches the edge.
        rows = [row(.01 + i*.005, 0, "confirmed_known_single_label", "A" if i % 2 == 0 else "B") for i in range(20)]
        rows += [row(-.95 + i*.01, .1, "confirmed_known_single_label", "A" if i % 2 == 0 else "B") for i in range(4)]
        rows += [row(-.5 + i*.01, -.2, "pass") for i in range(12)]
        rows += [row(-.95 + i*.005, -.2, "pass") for i in range(12)]
        out = analyze_defect_class_positions(rows, ["A", "B"], labeler_position_independent_asserted=True, permutations=999, seed=17)
        for cid in ("A", "B"):
            occ = out["estimands"]["classified_inspected_die_occurrence"]["class_results"][cid]
            comp = out["estimands"]["within_classified_fail_composition"]["class_results"][cid]
            self.assertEqual(occ["status"], "spatial_evidence")
            self.assertEqual(comp["status"], "no_detected_association_not_random")
            self.assertEqual(occ["bins"][0]["target_class_count"], 10)
            self.assertEqual(comp["bins"][0]["target_class_count"], 10)
            self.assertEqual(comp["bins"][3]["target_class_count"], 2)
        coverage = out["coverage"]
        self.assertEqual(coverage["confirmed_known_fail_denominator_by_radial_bin"]["center"], 20)
        self.assertEqual(coverage["confirmed_known_fail_denominator_by_radial_bin"]["edge"], 4)

    def test_absolute_uniform_class_b_non_significance_is_not_randomness_claim(self):
        # This fixed synthetic arrangement is a non-detection fixture, not evidence of randomness.
        rows = [row(-.94 + i*.094, 0, "confirmed_known_single_label", "B" if i % 2 == 0 else "A") for i in range(20)]
        rows += [row(-.9 + i*.09, .1, "pass") for i in range(10)]
        out = analyze_defect_class_positions(rows, ["B"], labeler_position_independent_asserted=True, permutations=499, seed=19)
        res = out["estimands"]["classified_inspected_die_occurrence"]["class_results"]["B"]
        self.assertEqual(res["status"], "no_detected_association_not_random")
        self.assertIn("does not establish randomness", res["interpretation"])

    def test_excluded_states_and_pass_are_not_confounded(self):
        rows = [row(.1, 0, "confirmed_known_single_label", "A"), row(.4, 0, "confirmed_known_single_label", "B"), row(.7, 0, "pass")]
        rows += [row(.2 + i*.01, .1, state) for i, state in enumerate(("unknown", "rejected", "multi_label", "missing_prediction"))]
        rows += [row(None, None, "invalid_geometry"), row(None, None, "uninspected", inspected=False)]
        out = self.run_analysis(rows)
        cov = out["coverage"]
        self.assertEqual(cov["pass_count"], 1)
        self.assertEqual(cov["confirmed_known_single_label_fail_count"], 2)
        self.assertEqual(cov["excluded_label_or_geometry_counts"]["unknown"], 1)
        self.assertEqual(cov["inspected_valid_geometry_count"], 7)
        self.assertEqual(cov["classified_inspected_die_count"], 3)
        self.assertEqual(sum(cov["inspected_valid_geometry_by_radial_bin"].values()), 7)
        self.assertEqual(sum(cov["valid_geometry_status_counts"].values(),), cov["inspected_valid_geometry_count"])
        self.assertNotIn("invalid_geometry", cov["valid_geometry_status_counts"])
        self.assertNotIn("uninspected", cov["valid_geometry_status_counts"])
        self.assertIn("invalid_geometry", cov["excluded_label_or_geometry_counts"])
        self.assertIn("uninspected", cov["excluded_label_or_geometry_counts"])
        for bin_name, status_counts in cov["label_status_counts_by_radial_bin"].items():
            self.assertEqual(sum(status_counts.values()), cov["inspected_valid_geometry_by_radial_bin"][bin_name])
            self.assertNotIn("invalid_geometry", status_counts)
            self.assertNotIn("uninspected", status_counts)
        occ = out["estimands"]["classified_inspected_die_occurrence"]["class_results"]["A"]
        comp = out["estimands"]["within_classified_fail_composition"]["class_results"]["A"]
        self.assertEqual(occ["control_count"], 2)
        self.assertEqual(comp["control_count"], 1)

    def test_insufficient_and_holm_known_vector(self):
        self.assertEqual(_holm({"a": .01, "b": .04, "c": .03}), {"a": .03, "c": .06, "b": .06})
        out = self.run_analysis([row(.1, 0, "confirmed_known_single_label", "A")], classes=("A", "B"))
        result = out["estimands"]["within_classified_fail_composition"]["class_results"]["A"]
        self.assertEqual(result["status"], "insufficient")
        self.assertIsNone(result["raw_p_value"])
        self.assertIsNone(result["holm_adjusted_p_value"])
        self.assertEqual(out["holm_family_size"], 4)
        self.assertEqual(out["testable_hypothesis_count"], 0)
        self.assertTrue(out["monte_carlo_resolution_allows_first_holm_rejection"])

    def test_invalid_geometry_and_duplicate_coordinates_rejected(self):
        with self.assertRaises(ValueError):
            self.run_analysis([row(1.1, 0, "pass")])
        with self.assertRaises(ValueError):
            self.run_analysis([row(.2, 0, "pass"), row(.2, 0, "pass")])

    def test_unavailable_without_independence_assertion_and_determinism(self):
        r = [row(.1, 0, "confirmed_known_single_label", "A"), row(.5, 0, "confirmed_known_single_label", "B")]
        unavailable = analyze_defect_class_positions(r, ["A"], labeler_position_independent_asserted=False)
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(analyze_defect_class_positions(r, ["A"], labeler_position_independent_asserted=True, seed=42)["estimands"],
                         analyze_defect_class_positions(r, ["A"], labeler_position_independent_asserted=True, seed=42)["estimands"])
        self.assertEqual(_class_seed(42, "one", "A"), _class_seed(42, "one", "A"))
        self.assertNotEqual(_class_seed(42, "one", "A"), _class_seed(42, "two", "A"))

    def test_iterables_are_bounded_and_work_cap_is_enforced(self):
        def many():
            i = 0
            while True:
                yield row(.1 + i*.000001, 0, "pass")
                i += 1
        with patch.object(module, "MAX_ROWS", 2):
            with self.assertRaisesRegex(ValueError, "row limit"):
                self.run_analysis(many())
        with patch.object(module, "MAX_CLASSES", 2):
            with self.assertRaisesRegex(ValueError, "planned_classes"):
                self.run_analysis([], (str(i) for i in range(1000000)))
        with self.assertRaisesRegex(ValueError, "not a string"):
            self.run_analysis([], "AB")
        with patch.object(module, "MAX_WORK_UNITS", 1):
            with self.assertRaisesRegex(ValueError, "estimated permutation work"):
                self.run_analysis([row(.1, 0, "pass"), row(.5, 0, "pass")])


if __name__ == "__main__":
    unittest.main()
