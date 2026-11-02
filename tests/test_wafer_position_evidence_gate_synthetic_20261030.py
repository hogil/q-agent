import unittest

from research.wafer_position_evidence_gate_synthetic_20261030 import assess_spatial_evidence, mix_rankings
from research.wafer_defect_class_position_20261030 import analyze_defect_class_positions
from research.wafer_defect_class_position_20261030 import MAX_PERMUTATIONS


def analysis(*, status="spatial_evidence", p=.01, reject=True, cid="A", estimand="classified_inspected_die_occurrence", alpha=.05):
    raw = p
    adjusted = min(1, 2 * raw)
    results = {}
    for e in ("classified_inspected_die_occurrence", "within_classified_fail_composition"):
        results[e] = {"class_results": {"A": {
            "status": ("spatial_evidence" if adjusted <= alpha else "no_detected_association_not_random"),
            "class_id": "A", "estimand": e, "raw_p_value": raw,
            "holm_adjusted_p_value": adjusted, "holm_reject": adjusted <= alpha,
            "population_coverage": {"eligible_population_count": 20},
        }}}
    selected = results.get(estimand, {}).get("class_results", {}).get(cid)
    if selected is not None:
        selected.update(status=status, holm_adjusted_p_value=adjusted, holm_reject=reject)
    return {"status": "complete", "planned_classes": ["A"], "alpha": alpha,
        "permutations": 999, "holm_family_size": 2, "minimum_monte_carlo_p": 1/1000,
        "minimum_step_down_holm_p_for_first_rank": 2/1000,
        "monte_carlo_resolution_allows_first_holm_rejection": 2/1000 <= alpha,
        "estimands": results}


ASSERTIONS = dict(labeler_position_independent_asserted=True, geometry_validated_asserted=True,
                  coverage_adequate_asserted=True, null_assumptions_accepted_asserted=True)
MANIFEST = {"provenance_asserted": True, "calibration_groups": ["wafer-1", "wafer-2"],
            "evaluation_groups": ["wafer-3"], "frozen_before_evaluation_asserted": True,
            "selected_weight": .7, "selected_class_id": "A",
            "selected_estimand": "classified_inspected_die_occurrence", "rrf_k": 60}


class EvidenceGateTests(unittest.TestCase):
    def assess(self, a=None, **kwargs):
        return assess_spatial_evidence(analysis() if a is None else a, class_id="A",
            estimand="classified_inspected_die_occurrence", alpha=.05, **(ASSERTIONS | kwargs))

    def mix(self, a=None, **kwargs):
        return mix_rankings(["x", "y", "z"], ["z", "y", "x"], requested_spatial_weight=.7,
            class_id="A", estimand="classified_inspected_die_occurrence", alpha=.05,
            analysis=analysis() if a is None else a, calibration_manifest=MANIFEST,
            query_group_id="wafer-3", candidate_universe_complete_asserted=True,
            invariant_position_independent_asserted=True,
            **(ASSERTIONS | kwargs))

    def test_p_above_alpha_is_uncertain(self):
        out = self.assess(analysis(p=.06, reject=False, status="no_detected_association_not_random"))
        self.assertEqual(out["status"], "uncertain")
        self.assertFalse(out["eligible_for_asserted_frozen_spatial_weight"])

    def test_low_p_without_holm_status_agreement_fails(self):
        for a in (analysis(status="no_detected_association_not_random", p=.001, reject=True),
                  analysis(status="spatial_evidence", p=.001, reject=False)):
            self.assertEqual(self.assess(a)["status"], "insufficient")

    def test_missing_geometry_or_position_blind_label_assertion_abstains(self):
        for key in ("geometry_validated_asserted", "labeler_position_independent_asserted"):
            self.assertEqual(self.assess(**{key: False})["status"], "insufficient")

    def test_class_or_estimand_mismatch_abstains(self):
        wrong_class = analysis()
        wrong_class["planned_classes"] = ["B"]
        self.assertEqual(self.assess(wrong_class)["status"], "insufficient")
        self.assertEqual(assess_spatial_evidence(analysis(), class_id="A", estimand="other", alpha=.05,
            **ASSERTIONS)["status"], "insufficient")

    def test_missing_result_and_selection_assertion_abstain(self):
        self.assertEqual(self.assess({})["status"], "insufficient")
        self.assertEqual(self.assess(labeler_position_independent_asserted=False)["status"], "insufficient")

    def test_candidate_sets_and_ranks_are_validated(self):
        with self.assertRaises(ValueError):
            mix_rankings(["x", "y"], ["x"], requested_spatial_weight=.5, class_id="A",
                estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
                calibration_manifest=MANIFEST, query_group_id="wafer-3", candidate_universe_complete_asserted=True, invariant_position_independent_asserted=True, **ASSERTIONS)
        with self.assertRaises(ValueError):
            mix_rankings(["x", "x"], ["x", "y"], requested_spatial_weight=.5, class_id="A",
                estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
                calibration_manifest=MANIFEST, query_group_id="wafer-3", candidate_universe_complete_asserted=True, invariant_position_independent_asserted=True, **ASSERTIONS)

    def test_tie_order_is_reproducible(self):
        a = mix_rankings(["b", "a"], ["a", "b"], requested_spatial_weight=.5, class_id="A",
            estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
            calibration_manifest=MANIFEST, query_group_id="wafer-3", candidate_universe_complete_asserted=True, invariant_position_independent_asserted=True, **ASSERTIONS)
        b = mix_rankings(["b", "a"], ["a", "b"], requested_spatial_weight=.5, class_id="A",
            estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
            calibration_manifest=MANIFEST, query_group_id="wafer-3", candidate_universe_complete_asserted=True, invariant_position_independent_asserted=True, **ASSERTIONS)
        self.assertEqual(a["ranking"], b["ranking"])

    def test_overlapping_calibration_groups_force_zero_weight(self):
        manifest = {"provenance_asserted": True, "calibration_groups": ["same"], "evaluation_groups": ["same"]}
        out = mix_rankings(["x", "y"], ["y", "x"], requested_spatial_weight=.8, class_id="A",
            estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
            calibration_manifest=manifest, query_group_id="same", candidate_universe_complete_asserted=True, invariant_position_independent_asserted=True, **ASSERTIONS)
        self.assertEqual(out["effective_spatial_weight"], 0)

    def test_zero_weight_preserves_position_free_order_exactly(self):
        out = self.mix(analysis(p=.9, reject=False, status="no_detected_association_not_random"))
        self.assertEqual(out["effective_spatial_weight"], 0)
        self.assertEqual(out["ranking"], ["x", "y", "z"])

    def test_valid_evidence_and_disjoint_groups_enable_only_bounded_weight(self):
        out = self.mix()
        self.assertEqual(out["effective_spatial_weight"], .7)
        self.assertEqual(set(out["ranking"]), {"x", "y", "z"})

    def test_no_result_makes_no_cause_claim(self):
        out = self.assess(analysis(status="no_detected_association_not_random", p=.8, reject=False))
        self.assertIn("no causal claim", out["claims"])
        self.assertIn("no randomness or independence claim", out["claims"])

    def test_candidate_universe_must_be_asserted_complete(self):
        out = mix_rankings(["x", "y"], ["y", "x"], requested_spatial_weight=.7, class_id="A",
            estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
            calibration_manifest=MANIFEST, query_group_id="wafer-3", candidate_universe_complete_asserted=False,
            invariant_position_independent_asserted=True,
            **ASSERTIONS)
        self.assertEqual(out["effective_spatial_weight"], 0)

    def test_manifest_freeze_selection_and_query_group_contract(self):
        for key, value in (("selected_weight", .6), ("selected_class_id", "B"),
                           ("selected_estimand", "other"), ("rrf_k", 10),
                           ("frozen_before_evaluation_asserted", False)):
            bad = dict(MANIFEST, **{key: value})
            out = mix_rankings(["x", "y"], ["y", "x"], requested_spatial_weight=.7, class_id="A",
                estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
                calibration_manifest=bad, query_group_id="wafer-3", candidate_universe_complete_asserted=True,
                invariant_position_independent_asserted=True,
                **ASSERTIONS)
            self.assertEqual(out["effective_spatial_weight"], 0)
        out = mix_rankings(["x", "y"], ["y", "x"], requested_spatial_weight=.7, class_id="A",
            estimand="classified_inspected_die_occurrence", alpha=.05, analysis=analysis(),
            calibration_manifest=MANIFEST, query_group_id="wafer-1", candidate_universe_complete_asserted=True,
            invariant_position_independent_asserted=True,
            **ASSERTIONS)
        self.assertEqual(out["effective_spatial_weight"], 0)

    def test_holm_family_and_monte_carlo_metadata_tampering_abstains(self):
        base = analysis()
        base["estimands"]["classified_inspected_die_occurrence"]["class_results"]["A"]["raw_p_value"] = .5
        # The selected adjusted p is now inconsistent with the reconstructed family Holm value.
        self.assertEqual(self.assess(base)["status"], "insufficient")
        for field, value in (("holm_family_size", 3), ("minimum_monte_carlo_p", .02),
                             ("minimum_step_down_holm_p_for_first_rank", .01),
                             ("permutations", 1999),
                             ("permutations", 39),
                             ("permutations", MAX_PERMUTATIONS + 1),
                             ("monte_carlo_resolution_allows_first_holm_rejection", False)):
            tampered = analysis()
            tampered[field] = value
            self.assertEqual(self.assess(tampered)["status"], "insufficient")
        too_small = analysis(p=.0001)
        self.assertEqual(self.assess(too_small)["status"], "insufficient")

    def test_real_analyzer_synthetic_output_compatible_for_normal_and_insufficient(self):
        rows = [
            {"x": .1, "y": 0., "strata": "s", "inspected": True, "label_status": "confirmed_known_single_label", "class_id": "A"},
            {"x": -.4, "y": 0., "strata": "s", "inspected": True, "label_status": "confirmed_known_single_label", "class_id": "B"},
            {"x": .8, "y": 0., "strata": "s", "inspected": True, "label_status": "pass", "class_id": None},
        ]
        report = analyze_defect_class_positions(rows, ["A", "B"], labeler_position_independent_asserted=True,
            permutations=99, seed=31)
        result = assess_spatial_evidence(report, class_id="A", estimand="classified_inspected_die_occurrence",
            alpha=report["alpha"], **ASSERTIONS)
        self.assertIn(result["status"], {"uncertain", "insufficient"})
        for field, value in (("minimum_monte_carlo_p", report["minimum_monte_carlo_p"] * 2),
                             ("minimum_step_down_holm_p_for_first_rank", .99),
                             ("monte_carlo_resolution_allows_first_holm_rejection", not report["monte_carlo_resolution_allows_first_holm_rejection"])):
            altered = dict(report)
            altered[field] = value
            checked = assess_spatial_evidence(altered, class_id="A", estimand="classified_inspected_die_occurrence",
                alpha=report["alpha"], **ASSERTIONS)
            self.assertEqual(checked["status"], "insufficient", field)
        insufficient = analyze_defect_class_positions([rows[0]], ["A"], labeler_position_independent_asserted=True,
            permutations=99, seed=31)
        out = assess_spatial_evidence(insufficient, class_id="A", estimand="within_classified_fail_composition",
            alpha=insufficient["alpha"], **ASSERTIONS)
        self.assertEqual(out["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
