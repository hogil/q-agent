"""Synthetic controls for the research-only class-position analyzer.

All generated labels are synthetic source outcomes. They are not predictions
from a trained model and are not evidence about actual wafer behavior.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from research.wafer_defect_class_position_20261030 import analyze_defect_class_positions
from research.wafer_position_permutation_20261030 import BIN_NAMES

SCENARIOS = (
    "uniform_null",
    "center_fail_constant_composition",
    "a_center_b_uniform",
    "a_ring_b_uniform",
    "selective_center_a_rejection",
)
SEEDS = (42, 1, 2, 3, 4)
PLANNED_CLASSES = ("A", "B")
ALPHA = 0.05
PERMUTATIONS = 499
SMOKE_PERMUTATIONS = 99
RADII = (0.10, 0.40, 0.68, 0.91)
ANGLES = 48
STRATUM = "synthetic-wafer"
LABEL_STATUSES = {"confirmed_known_single_label", "pass", "rejected"}


def grid() -> list[tuple[float, float]]:
    """Return the fixed 192 point grid, fully inside four radial bins."""
    return [(radius * math.cos(2 * math.pi * i / ANGLES),
             radius * math.sin(2 * math.pi * i / ANGLES))
            for radius in RADII for i in range(ANGLES)]


def _probabilities(scenario: str, radius: float) -> tuple[float, float, float]:
    """Return source-outcome probabilities (A, B, pass), before label selection."""
    if scenario == "uniform_null":
        return 0.20, 0.20, 0.60
    if scenario == "center_fail_constant_composition":
        fail = 0.65 if radius <= 0.25 else 0.15
        return fail / 2, fail / 2, 1 - fail
    if scenario == "a_center_b_uniform":
        a = 0.45 if radius <= 0.25 else 0.05
        return a, 0.20, 0.80 - a
    if scenario == "a_ring_b_uniform":
        a = 0.45 if 0.55 < radius < 0.82 else 0.05
        return a, 0.20, 0.80 - a
    if scenario == "selective_center_a_rejection":
        return 0.20, 0.20, 0.60
    raise ValueError(f"unknown scenario: {scenario}")


def _label_from_source_outcome(scenario: str, radius: float, outcome: str) -> tuple[str, str | None]:
    """Apply a coordinate-blind label mapping, then scenario-5 selective missingness."""
    if outcome == "pass":
        status, class_id = "pass", None
    else:
        status, class_id = "confirmed_known_single_label", outcome
    # This is deliberately class- and position-dependent selection. The true
    # source outcome is not retained in the analysis row or result artifact.
    if scenario == "selective_center_a_rejection" and radius <= 0.25 and outcome == "A":
        return "rejected", None
    return status, class_id


def _generation_seed(seed: int) -> int:
    material = f"wafer-class-position-controls-v2\0generation\0{seed}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _source_draws(seed: int) -> tuple[float, ...]:
    """Common random numbers shared across scenarios for paired comparison."""
    rng = random.Random(_generation_seed(seed))
    return tuple(rng.random() for _ in grid())


def generate_rows(scenario: str, seed: int) -> list[dict[str, Any]]:
    """Generate analyzer-schema rows only; latent source outcomes are discarded."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    draws = _source_draws(seed)
    rows: list[dict[str, Any]] = []
    for (x, y), draw in zip(grid(), draws):
        radius = math.hypot(x, y)
        p_a, p_b, _ = _probabilities(scenario, radius)
        # B is the first fixed interval for every scenario with position-
        # invariant B probability, preserving B membership under shared draws.
        source_outcome = "B" if draw < p_b else "A" if draw < p_b + p_a else "pass"
        status, class_id = _label_from_source_outcome(scenario, radius, source_outcome)
        rows.append({"x": x, "y": y, "strata": STRATUM, "inspected": True,
                     "label_status": status, "class_id": class_id})
    return rows


def _run_one(scenario: str, seed: int, permutations: int) -> dict[str, Any]:
    rows = generate_rows(scenario, seed)
    # Scenario 5 intentionally lies about this caller assertion so that the
    # analyzer's ordinary p-values expose the effect of violating selection
    # exchangeability. Its false-assertion safety outcome is recorded too.
    assertion = True
    analysis = analyze_defect_class_positions(
        rows, PLANNED_CLASSES, labeler_position_independent_asserted=assertion,
        permutations=permutations, seed=seed, alpha=ALPHA,
    )
    honest_safety_check = (analyze_defect_class_positions(
        rows, PLANNED_CLASSES, labeler_position_independent_asserted=False,
        permutations=permutations, seed=seed, alpha=ALPHA,
    ) if scenario == "selective_center_a_rejection" else None)
    coverage = analysis["coverage"]
    results = []
    for estimand, population in analysis.get("estimands", {}).items():
        for class_id, result in population["class_results"].items():
            results.append({
                "estimand": estimand, "class_id": class_id,
                "raw_p_value": result.get("raw_p_value"),
                "holm_adjusted_p_value": result.get("holm_adjusted_p_value"),
                "decision": result.get("holm_reject"), "status": result.get("status"),
                "analysis_seed": result.get("seed"),
                "bin_coverage": result.get("classified_die_denominator_by_radial_bin"),
                "bins": result.get("bins"),
            })
    return {
        "scenario": scenario, "generation_base_seed": seed,
        "generation_rng_seed": _generation_seed(seed), "analysis_base_seed": seed,
        "caller_assertion_used": assertion,
        "caller_assertion_truthful": scenario != "selective_center_a_rejection",
        # Synthetic outputs never carry field or deployment authority. The
        # p_value_validity field separately marks scenario 5 as invalid even
        # within the designed simulation because its assertion is knowingly false.
        "inference_authoritative": False,
        "p_value_validity": "invalid_by_designed_exchangeability_violation" if scenario == "selective_center_a_rejection" else "synthetic_design_only",
        "permutations": permutations, "alpha": ALPHA,
        "input_row_count": len(rows), "analysis_input_schema_only": True,
        "input_status_counts": {
            status: sum(row["label_status"] == status for row in rows)
            for status in sorted(LABEL_STATUSES)
        },
        "coverage": coverage,
        "four_class_estimand_results": results,
        "complete_analysis_output": analysis,
        "honest_assertion_safety_check": honest_safety_check,
        "exchangeability_note": (
            "Designed violation: center A labels are selectively rejected based on position and source class; permutation-null exchangeability does not hold."
            if scenario == "selective_center_a_rejection" else
            "Synthetic source outcome probabilities are designed by scenario. The label mapping itself consumes only the source outcome; no trained classifier is represented."
        ),
    }


def run_study(output_dir: Path, *, permutations: int = PERMUTATIONS) -> dict[str, Any]:
    """Write all 25 runs to a new exclusive directory; never overwrite."""
    if permutations < 99:
        raise ValueError("permutations must be >= 99")
    output_dir.mkdir(parents=True, exist_ok=False)
    run_index = []
    for scenario in SCENARIOS:
        for seed in SEEDS:
            record = _run_one(scenario, seed, permutations)
            filename = f"{scenario}__seed-{seed}.json"
            (output_dir / filename).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            run_index.append({"scenario": scenario, "seed": seed, "file": filename,
                              "inference_authoritative": record["inference_authoritative"],
                              "caller_assertion_truthful": record["caller_assertion_truthful"],
                              "p_value_validity": record["p_value_validity"],
                              "input_row_count": record["input_row_count"],
                              "status_counts": record["input_status_counts"],
                              "results": [{k: item[k] for k in ("estimand", "class_id", "analysis_seed", "raw_p_value",
                                                                   "holm_adjusted_p_value", "decision", "status")}
                                          for item in record["four_class_estimand_results"]]})
    summary = {"study": "wafer-class-position-controls-synthetic-20261030",
               "run_count": len(run_index), "scenario_count": len(SCENARIOS),
               "seed_count": len(SEEDS), "permutations": permutations,
               "planned_classes": list(PLANNED_CLASSES), "alpha": ALPHA,
               "runs": run_index,
               "interpretation_limit": "Every output is non-authoritative synthetic smoke only; five paired seeds establish no error-rate, field-validity, operational validity, or novelty claim.",
               "full_run_error_or_retry": "None for this corrected run; earlier invalid pilot and invocation attempts are documented below",
               "pre_run_check_attempts": [
                   {"command": "python -m unittest tests.test_wafer_class_position_controls_synthetic_20261030 -v",
                    "outcome": "failed before tests: ModuleNotFoundError because tests is not an importable package"},
                   {"command": "python -m unittest discover -s tests -p test_wafer_class_position_controls_synthetic_20261030.py -v",
                    "outcome": "4 checks passed; later-added smoke check initially failed only because its expected wording differed"},
                   {"command": "python -m unittest discover -s tests -p test_wafer_class_position_controls_synthetic_20261030.py -v",
                    "outcome": "after correcting the assertion text, all 5 checks passed; 99-permutation smoke passed"},
                   {"command": "python -m unittest discover -s tests -p test_wafer_class_position_controls_synthetic_20261030.py -v",
                    "outcome": "after common-random-number pairing, real analyzer seeds, scenario-5 invalidity, and non-authoritative metadata changes, all 8 checks passed; 99-permutation smoke and false-assertion safety check passed"},
                   {"command": "python research/wafer_class_position_controls_synthetic_20261030.py --output-dir ... --permutations 499",
                    "outcome": "failed before analysis: direct script invocation did not put project root on sys.path; ModuleNotFoundError: research. No output directory was created."},
               ]}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--permutations", type=int, default=PERMUTATIONS)
    args = parser.parse_args()
    result = run_study(args.output_dir, permutations=args.permutations)
    print(json.dumps({"run_count": result["run_count"], "output_dir": str(args.output_dir)}, indent=2))
