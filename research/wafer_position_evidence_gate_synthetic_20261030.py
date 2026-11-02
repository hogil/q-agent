"""Research-only gate and rank mixer for synthetic wafer position evidence.

The class-position analysis and all provenance passed here are caller-supplied.
`labeler_position_independent_asserted` is an assertion that the label source
was frozen without using position; it is not independently verified. Geometry,
coverage, null/exchangeability assumptions and calibration group provenance are
also assertions. This module checks their declared values and group-list
overlap, not physical lineage, ACLs, immutability, or truth.

Only a Holm-rejected spatial result with matching class/estimand/alpha and
affirmed geometry, coverage and null assumptions can be marked eligible for
applying a caller-asserted frozen spatial weight. No calibration is performed;
this is not a guarantee of benefit, validity, false-alarm control, or cause.
Without that gate and separated calibration groups, the mixer uses weight zero
and returns the supplied position-free ranking. The invariant ranking source
and candidate-universe completeness are caller assertions, not verified here.
"""
from __future__ import annotations

import math
import numbers
from typing import Any, Mapping, Sequence

from research.wafer_defect_class_position_20261030 import MAX_PERMUTATIONS

MIN_PERMUTATIONS = 99


def assess_spatial_evidence(
    analysis: Mapping[str, Any], *, class_id: str, estimand: str, alpha: float,
    labeler_position_independent_asserted: bool,
    geometry_validated_asserted: bool, coverage_adequate_asserted: bool,
    null_assumptions_accepted_asserted: bool,
) -> dict[str, Any]:
    """Assess one result from analyze_defect_class_positions; no labels accepted."""
    if not isinstance(class_id, str) or not class_id or not isinstance(estimand, str) or not estimand:
        raise ValueError("class_id and estimand must be non-empty strings")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be finite and in (0, 1)")
    assertions = (labeler_position_independent_asserted, geometry_validated_asserted,
                  coverage_adequate_asserted, null_assumptions_accepted_asserted)
    if any(not isinstance(v, bool) for v in assertions):
        raise ValueError("all provenance inputs must be explicit boolean assertions")
    try:
        result = analysis["estimands"][estimand]["class_results"][class_id]
    except (KeyError, TypeError):
        return _assessment("insufficient", "missing_result", None, None)
    if not isinstance(result, Mapping):
        return _assessment("insufficient", "invalid_result", None, None)
    p_raw, p_adj = result.get("raw_p_value"), result.get("holm_adjusted_p_value")
    matches = result.get("class_id") == class_id and result.get("estimand") == estimand
    source_alpha = analysis.get("alpha")
    alpha_matches = (not isinstance(source_alpha, bool) and isinstance(source_alpha, (int, float))
                     and math.isfinite(source_alpha) and math.isclose(source_alpha, alpha, rel_tol=0, abs_tol=1e-12))
    p_valid = all(not isinstance(p, bool) and isinstance(p, numbers.Real) and math.isfinite(p) and 0 <= p <= 1 for p in (p_raw, p_adj))
    supported = {"classified_inspected_die_occurrence", "within_classified_fail_composition"}
    planned = analysis.get("planned_classes")
    if (analysis.get("status") != "complete" or not isinstance(planned, list) or class_id not in planned
            or estimand not in supported or not matches or not alpha_matches):
        return _assessment("insufficient", "class_estimand_or_alpha_mismatch", p_adj if p_valid else None, False)
    if result.get("status") == "insufficient" or not p_valid:
        return _assessment("insufficient", "missing_or_insufficient_test", None, False)
    permutations, family_size = analysis.get("permutations"), analysis.get("holm_family_size")
    mc_ok, reject = analysis.get("monte_carlo_resolution_allows_first_holm_rejection"), result.get("holm_reject")
    minimum_p = analysis.get("minimum_monte_carlo_p")
    reported_min_holm = analysis.get("minimum_step_down_holm_p_for_first_rank")
    family_keys = [(e, c) for e in ("classified_inspected_die_occurrence", "within_classified_fail_composition") for c in planned]
    family_values = {}
    family_valid = True
    for e, c in family_keys:
        try:
            item = analysis["estimands"][e]["class_results"][c]
            raw = item.get("raw_p_value")
            if raw is None and item.get("status") == "insufficient":
                family_values[(e, c)] = 1.0
            elif isinstance(raw, numbers.Real) and not isinstance(raw, bool) and math.isfinite(raw) and 0 <= raw <= 1:
                family_values[(e, c)] = raw
            else:
                family_valid = False
        except (KeyError, TypeError, AttributeError):
            family_valid = False
    expected = _holm(family_values) if family_valid and len(family_values) == len(family_keys) else {}
    key = (estimand, class_id)
    holm_matches = key in expected and math.isclose(p_adj, expected[key], rel_tol=0, abs_tol=1e-12)
    min_holm = (min(1.0, minimum_p * family_size) if isinstance(minimum_p, numbers.Real)
                and not isinstance(minimum_p, bool) and math.isfinite(minimum_p)
                and isinstance(family_size, int) and not isinstance(family_size, bool) else None)
    expected_mc = min_holm is not None and min_holm <= alpha
    consistent = (isinstance(minimum_p, numbers.Real) and not isinstance(minimum_p, bool)
        and isinstance(permutations, int) and not isinstance(permutations, bool)
        and MIN_PERMUTATIONS <= permutations <= MAX_PERMUTATIONS
        and math.isclose(minimum_p, 1 / (permutations + 1), rel_tol=0, abs_tol=1e-12)
        and p_raw >= minimum_p
        and p_adj + 1e-12 >= p_raw and holm_matches and family_size == len(family_keys)
        and isinstance(permutations, int) and not isinstance(permutations, bool) and permutations >= 1
        and isinstance(family_size, int) and not isinstance(family_size, bool) and family_size >= 1
        and isinstance(reported_min_holm, numbers.Real) and not isinstance(reported_min_holm, bool)
        and min_holm is not None and math.isclose(reported_min_holm, min_holm, rel_tol=0, abs_tol=1e-12)
        and isinstance(mc_ok, bool) and mc_ok is expected_mc and reject is (p_adj <= alpha)
        and result.get("status") == ("spatial_evidence" if reject else "no_detected_association_not_random"))
    if not consistent or (reject and not mc_ok):
        return _assessment("insufficient", "contradictory_test_or_monte_carlo_metadata", p_adj, False)
    if (not labeler_position_independent_asserted or not geometry_validated_asserted
            or not coverage_adequate_asserted or not null_assumptions_accepted_asserted):
        return _assessment("insufficient", "unverified_label_geometry_coverage_or_null", p_adj, False)
    if result.get("status") != "spatial_evidence" or result.get("holm_reject") is not True or p_adj > alpha:
        return _assessment("uncertain", "no_qualifying_holm_spatial_evidence", p_adj, False)
    return _assessment("spatial_evidence", "holm_adjusted_spatial_evidence_under_asserted_null", p_adj, True)


def _assessment(status: str, reason: str, p_adj: Any, eligible: bool) -> dict[str, Any]:
    return {"status": status, "reason": reason, "holm_adjusted_p_value": p_adj,
            "eligible_for_asserted_frozen_spatial_weight": eligible,
            "claims": ["no randomness or independence claim", "no causal claim", "no calibration was performed; no benefit or validity guarantee"]}


def mix_rankings(
    invariant_ranking: Sequence[str], spatial_ranking: Sequence[str], *,
    requested_spatial_weight: float, class_id: str, estimand: str, alpha: float,
    analysis: Mapping[str, Any], labeler_position_independent_asserted: bool,
    geometry_validated_asserted: bool, coverage_adequate_asserted: bool,
    null_assumptions_accepted_asserted: bool,
    calibration_manifest: Mapping[str, Any],
    query_group_id: str,
    candidate_universe_complete_asserted: bool,
    invariant_position_independent_asserted: bool,
) -> dict[str, Any]:
    """Bounded weighted RRF(k=60); query ID/report/manifest only, never test truth."""
    if isinstance(requested_spatial_weight, bool) or not isinstance(requested_spatial_weight, (int, float)) or not math.isfinite(requested_spatial_weight) or not 0 <= requested_spatial_weight <= 1:
        raise ValueError("requested_spatial_weight must be finite and in [0, 1]")
    invariant = _valid_ranking(invariant_ranking, "invariant_ranking")
    spatial = _valid_ranking(spatial_ranking, "spatial_ranking")
    if len(invariant) != len(spatial) or set(invariant) != set(spatial):
        raise ValueError("rankings must contain the same complete candidate set")
    if not isinstance(candidate_universe_complete_asserted, bool):
        raise ValueError("candidate_universe_complete_asserted must be a boolean caller assertion")
    if not isinstance(invariant_position_independent_asserted, bool):
        raise ValueError("invariant_position_independent_asserted must be a boolean caller assertion")
    if not invariant:
        raise ValueError("rankings must be non-empty")
    gate = assess_spatial_evidence(analysis, class_id=class_id, estimand=estimand, alpha=alpha,
        labeler_position_independent_asserted=labeler_position_independent_asserted,
        geometry_validated_asserted=geometry_validated_asserted,
        coverage_adequate_asserted=coverage_adequate_asserted,
        null_assumptions_accepted_asserted=null_assumptions_accepted_asserted)
    separated = _independent_calibration_groups(calibration_manifest, query_group_id, requested_spatial_weight, class_id, estimand)
    weight = float(requested_spatial_weight) if (gate["eligible_for_asserted_frozen_spatial_weight"] and separated
        and candidate_universe_complete_asserted and invariant_position_independent_asserted) else 0.0
    inv_rank = {candidate: i + 1 for i, candidate in enumerate(invariant)}
    spa_rank = {candidate: i + 1 for i, candidate in enumerate(spatial)}
    scores = {candidate: (1.0-weight)/(60+inv_rank[candidate]) + weight/(60+spa_rank[candidate]) for candidate in invariant}
    # Stable deterministic tie break: invariant rank, then candidate ID.
    order = sorted(invariant, key=lambda c: (-scores[c], inv_rank[c], c))
    return {"ranking": order, "scores": scores, "effective_spatial_weight": weight,
            "gate": gate, "calibration_groups_disjoint_asserted": separated,
            "method": "weighted reciprocal rank fusion, k=60",
            "limits": ["provenance is caller asserted; physical lineage and immutability unverified",
                       "no test truth is read; no benefit, calibration, validity or false-alarm guarantee",
                       "zero spatial weight returns the supplied position-free order",
                       "candidate universe completeness and position-invariant ranking source are caller assertions, not verified",
                       "provenance assertions do not prove corpus identity, lineage, or frozen state"]}


def _valid_ranking(values: Sequence[str], name: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a candidate sequence")
    out = list(values)
    if any(not isinstance(v, str) or not v for v in out) or len(set(out)) != len(out):
        raise ValueError(f"{name} must contain unique non-empty candidate IDs (ranks 1..N)")
    return out


def _independent_calibration_groups(manifest: Mapping[str, Any], query_group_id: str,
                                    requested_weight: float, class_id: str, estimand: str) -> bool:
    if (not isinstance(manifest, Mapping) or manifest.get("provenance_asserted") is not True
            or manifest.get("frozen_before_evaluation_asserted") is not True
            or manifest.get("selected_weight") != requested_weight
            or manifest.get("selected_class_id") != class_id or manifest.get("selected_estimand") != estimand
            or manifest.get("rrf_k") != 60 or not isinstance(query_group_id, str) or not query_group_id):
        return False
    calibration = manifest.get("calibration_groups")
    evaluation = manifest.get("evaluation_groups")
    if not _group_list(calibration) or not _group_list(evaluation):
        return False
    return set(calibration).isdisjoint(evaluation) and query_group_id in evaluation and query_group_id not in calibration


def _group_list(value: Any) -> bool:
    return (isinstance(value, (list, tuple, set)) and len(value) > 0
            and all(isinstance(x, str) and x for x in value)
            and len(set(value)) == len(value))


def _holm(values: Mapping[Any, float]) -> dict[Any, float]:
    ordered = sorted(values.items(), key=lambda item: item[1])
    adjusted, running, size = {}, 0.0, len(ordered)
    for i, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (size - i) * p))
        adjusted[key] = running
    return adjusted
