"""Research-only class-specific radial wafer position analysis.

Geometry, inspection and frozen classification status are caller asserted.
This module does not validate real wafer coordinates or production data.
"""
from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter
from typing import Any, Iterable, Mapping

from research.wafer_position_permutation_20261030 import BIN_NAMES, RADIAL_BINS, analyze_wafer_positions

MAX_ROWS, MAX_CLASSES, MAX_PERMUTATIONS = 100_000, 100, 100_000
MAX_WORK_UNITS = 100_000_000
_LABELS = {"confirmed_known_single_label", "pass", "unknown", "rejected", "multi_label", "missing_prediction", "invalid_geometry", "uninspected"}
_LIMITS = ["research/synthetic only; no actual wafer, physical geometry, or ACL validation", "single-label eligibility can induce selection bias", "classifier errors and coordinate-dependent inspection/classification invalidate inference", "radial maxT can miss angular/local patterns", "non-significance is not evidence of randomness, position independence, or cause"]


def analyze_defect_class_positions(rows: Iterable[Mapping[str, Any]], planned_classes: Iterable[str], *,
                                   labeler_position_independent_asserted: bool, permutations: int = 999,
                                   seed: int = 20261030, alpha: float = 0.05) -> dict[str, Any]:
    """Return two distinct class-position estimands with one 2*m Holm family.

    Required row fields: x, y, strata, inspected, label_status, class_id.
    Valid statuses: confirmed_known_single_label, pass, unknown, rejected,
    multi_label, missing_prediction, invalid_geometry, uninspected. Pass has no
    class_id. Invalid/uninspected geometry may use null coordinates. The
    labeler assertion concerns coordinate-blind frozen label generation; it
    does not assert that actual labels and positions are statistically
    independent. A non-significant synthetic result is not proof of randomness.
    """
    if isinstance(permutations, bool) or not isinstance(permutations, int) or not 99 <= permutations <= MAX_PERMUTATIONS:
        raise ValueError("permutations outside allowed range")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be integer")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha outside allowed range")
    if not isinstance(labeler_position_independent_asserted, bool):
        raise ValueError("labeler_position_independent_asserted must be a boolean caller assertion")
    if isinstance(planned_classes, (str, bytes)):
        raise ValueError("planned_classes must be an iterable of class IDs, not a string")
    classes = list(itertools.islice(planned_classes, MAX_CLASSES + 1))
    if not classes or len(classes) > MAX_CLASSES or any(not isinstance(c, str) or not c.strip() for c in classes) or len(set(classes)) != len(classes):
        raise ValueError("planned_classes must be 1 to 100 unique non-empty strings")
    source = list(itertools.islice(rows, MAX_ROWS + 1))
    if len(source) > MAX_ROWS:
        raise ValueError("row limit exceeded")

    inspected: list[dict[str, Any]] = []
    fails: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    geometric_bins: Counter[str] = Counter()
    radial_status_counts: dict[str, Counter[str]] = {name: Counter() for name in BIN_NAMES}
    seen: set[tuple[float, float]] = set()
    for i, row in enumerate(source):
        if not isinstance(row, Mapping) or not {"x", "y", "strata", "inspected", "label_status", "class_id"}.issubset(row):
            raise ValueError(f"row {i} missing required fields or is not a mapping")
        status = row["label_status"]
        if not isinstance(status, str) or status not in _LABELS or not isinstance(row["inspected"], bool):
            raise ValueError(f"row {i} has invalid label/inspection state")
        if (status == "uninspected") != (not row["inspected"]):
            raise ValueError(f"row {i} has conflicting inspection state")
        if status == "invalid_geometry" or status == "uninspected":
            exclusions[status] += 1
            continue
        x, y = row["x"], row["y"]
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError(f"row {i} geometry must be numeric")
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y) or x*x + y*y > 1.0 + 1e-12 or (x, y) in seen:
            raise ValueError(f"row {i} has invalid or duplicate normalized geometry")
        seen.add((x, y))
        b = next((j for j, (_, upper) in enumerate(RADIAL_BINS) if math.hypot(x, y) <= upper), len(BIN_NAMES)-1)
        bin_name = BIN_NAMES[b]
        geometric_bins[bin_name] += 1
        radial_status_counts[bin_name][status] += 1
        common = {"x": x, "y": y, "strata": row["strata"], "bin": bin_name}
        cid = row["class_id"]
        if status == "pass":
            if cid is not None:
                raise ValueError(f"row {i} pass cannot carry a class_id")
            inspected.append({**common, "class_id": None, "pass": True})
        elif status == "confirmed_known_single_label":
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError(f"row {i} confirmed label requires class_id")
            rec = {**common, "class_id": cid, "pass": False}
            inspected.append(rec)
            fails.append(rec)
        else:
            if cid is not None:
                raise ValueError(f"row {i} excluded status cannot carry class_id")
            exclusions[status] += 1

    if not labeler_position_independent_asserted:
        return {"status": "unavailable", "interpretation": "Inferential results unavailable without caller assertion that label generation was frozen and did not use position coordinates.",
                "planned_classes": classes, "estimands": {}, "alpha": float(alpha), "permutations": permutations, "base_seed": seed,
                "coverage": _coverage(source, inspected, fails, exclusions, geometric_bins, radial_status_counts, classes), "limits": _LIMITS}

    work_units = permutations * len(classes) * (len(inspected) + len(fails))
    if work_units > MAX_WORK_UNITS:
        raise ValueError("estimated permutation work exceeds configured MAX_WORK_UNITS")

    tests: dict[str, dict[str, Any]] = {}
    raw_for_holm: dict[str, float] = {}
    untestable: set[str] = set()
    populations = {
        "classified_inspected_die_occurrence": (inspected, "all valid-geometry completed-inspection rows with pass or confirmed known single-label outcome; pass and other known classes are controls"),
        "within_classified_fail_composition": (fails, "confirmed known single-label failures only; other confirmed known classes are controls"),
    }
    for estimand, (population, description) in populations.items():
        results = {}
        for cid in classes:
            binary = [{"x": r["x"], "y": r["y"], "strata": r["strata"],
                       "defect": int(r["class_id"] == cid)} for r in population]
            cseed = _class_seed(seed, estimand, cid)
            result = analyze_wafer_positions(binary, permutations=permutations, seed=cseed, alpha=alpha)
            p = result["p_value"]
            family_key = (estimand, cid)
            raw_for_holm[family_key] = p if p is not None else 1.0
            if p is None:
                untestable.add(family_key)
            bins = [{"bin": b["bin"], "radial_range": b["radial_range"],
                     "target_class_count": b["observed_fail_count"],
                     "eligible_population_count": b["eligible_count"],
                     "target_fraction": b["rate"], "expected_target_count": b["expected_fail_count"],
                     "variance": b["variance"], "standardized_residual": b["standardized_residual"]}
                    for b in result["bins"]]
            result.pop("coverage", None)
            result.pop("bins", None)
            result["bins"] = bins
            result["population_coverage"] = {"eligible_population_count": len(population),
                                                "eligible_population_count_by_radial_bin": _bin_counts(population)}
            result.update({"class_id": cid, "estimand": estimand, "population_definition": description,
                           "target_class_count": sum(r["class_id"] == cid for r in population),
                           "control_count": len(population) - sum(r["class_id"] == cid for r in population),
                           "classified_die_denominator_by_radial_bin": _bin_counts(population),
                           "target_class_count_by_radial_bin": {name: sum(r["class_id"] == cid and r["bin"] == name for r in population) for name in BIN_NAMES},
                           "seed": cseed, "raw_p_value": p,
                           "null_and_exchangeability": "Within caller strata, target-vs-control binary labels are exchangeable over this estimand's eligible inspected positions; eligibility mask and coordinate registration are accurate."})
            results[cid] = result
        tests[estimand] = {"population_definition": description, "class_results": results}
    adjusted = _holm(raw_for_holm)
    for estimand, group in tests.items():
        for cid, result in group["class_results"].items():
            key = (estimand, cid)
            result["holm_adjusted_p_value"] = None if key in untestable else adjusted[key]
            result["holm_reject"] = bool(key not in untestable and adjusted[key] <= alpha)
            if result["status"] != "insufficient":
                result["status"] = "spatial_evidence" if result["holm_reject"] else "no_detected_association_not_random"
                result["interpretation"] = ("Radial class association detected under the stated conditional null; not causal evidence." if result["holm_reject"] else
                    "No association detected at the Holm-adjusted family threshold; this does not establish randomness or position-independence.")
    min_p = 1.0 / (permutations + 1)
    min_holm = min(1.0, min_p * len(raw_for_holm))
    return {"status": "complete", "planned_classes": classes, "estimands": tests, "alpha": float(alpha),
            "holm_family_size": len(raw_for_holm),
            "holm_rule": "Holm adjustment across both estimands and every planned class; untestable p enters as 1 for family ordering while original p and adjusted output remain null",
            "permutations": permutations, "base_seed": seed,
            "minimum_monte_carlo_p": min_p, "minimum_step_down_holm_p_for_first_rank": min_holm,
            "monte_carlo_resolution_allows_first_holm_rejection": min_holm <= alpha,
            "testable_hypothesis_count": sum(result["raw_p_value"] is not None
                for group in tests.values() for result in group["class_results"].values()),
            "max_work_units": MAX_WORK_UNITS, "estimated_work_units": work_units,
            "coverage": _coverage(source, inspected, fails, exclusions, geometric_bins, radial_status_counts, classes),
            "assumptions": ["caller asserts label generation was frozen and did not use position coordinates; this does not assert statistical independence between labels and position", "labels exchangeable within caller strata conditional on each estimand's eligibility", "selection and classifier error can bias associations"], "limits": _LIMITS}


def _class_seed(seed: int, estimand: str, class_id: str) -> int:
    digest = hashlib.sha256(f"wafer-defect-class-position-v2\0{seed}\0{estimand}\0{class_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _holm(p_values: Mapping[Any, float]) -> dict[Any, float]:
    m = len(p_values)
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    output, running = {}, 0.0
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m-rank)*p))
        output[name] = running
    return output


def _bin_counts(population: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(r["bin"] for r in population)
    return {name: counts[name] for name in BIN_NAMES}


def _coverage(source: list[Any], inspected: list[dict[str, Any]], fails: list[dict[str, Any]], exclusions: Counter[str],
              geometry_bins: Counter[str], radial_status_counts: dict[str, Counter[str]], classes: list[str]) -> dict[str, Any]:
    valid_geometry_statuses = {"unknown", "rejected", "multi_label", "missing_prediction"}
    return {"input_row_count": len(source), "inspected_valid_geometry_count": sum(geometry_bins.values()),
            "classified_inspected_die_count": len(inspected),
            "valid_geometry_status_counts": {"pass": sum(r["pass"] for r in inspected),
                                               "confirmed_known_single_label": len(fails),
                                               **{status: exclusions[status] for status in sorted(valid_geometry_statuses)}},
            "confirmed_known_single_label_fail_count": len(fails), "pass_count": sum(r["pass"] for r in inspected),
            "excluded_label_or_geometry_counts": dict(sorted(exclusions.items())),
            "inspected_valid_geometry_by_radial_bin": {n: geometry_bins[n] for n in BIN_NAMES},
            "label_status_counts_by_radial_bin": {name: {status: radial_status_counts[name][status] for status in (
                "pass", "confirmed_known_single_label", "unknown", "rejected", "multi_label", "missing_prediction")}
                for name in BIN_NAMES},
            "classified_inspected_die_denominator_by_radial_bin": _bin_counts(inspected),
            "confirmed_known_fail_denominator_by_radial_bin": _bin_counts(fails),
            "planned_class_fail_counts": {c: sum(r["class_id"] == c for r in fails) for c in classes},
            "missing_die_denominator_policy": "uninspected rows excluded; never treated as pass or non-target class"}
