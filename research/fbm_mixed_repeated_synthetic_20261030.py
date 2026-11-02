#!/usr/bin/env python3
"""Repeated-seed descriptive extension of the mixed FBM synthetic probe."""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

try:
    from research.fbm_mixed_uncertainty_synthetic_20261030 import run_experiment
except ModuleNotFoundError:  # direct script execution places research/ on sys.path
    from fbm_mixed_uncertainty_synthetic_20261030 import run_experiment

BASE_SEED = 20261030
SEED_STEP = 1_000_000
N_SEEDS = 8
PER_PATTERN = 3
THRESHOLD = 0.85
SCENARIOS = (
    {"name": "low_noise", "error_rate": 0.05, "unknown_high_confidence_mixture_rate": 0.1},
    {"name": "high_noise", "error_rate": 0.35, "unknown_high_confidence_mixture_rate": 0.5},
)
REPS = ("raw", "hard_semantic", "soft_semantic", "raw_plus_hard", "raw_plus_soft")


def seed_list(base_seed: int = BASE_SEED, n_seeds: int = N_SEEDS) -> list[int]:
    if n_seeds < 1 or base_seed < 0:
        raise ValueError("base_seed must be nonnegative and n_seeds positive")
    seeds = [base_seed + i * SEED_STEP for i in range(n_seeds)]
    ranges = [(s, s + 3 * 10_000 + (PER_PATTERN - 1) * 100 + 100_000) for s in seeds]
    if len(set(seeds)) != len(seeds) or any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:])):
        raise ValueError("seed generation ranges overlap")
    return seeds


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n_seeds": 0, "mean": None, "sd": None, "median": None, "min": None, "max": None}
    return {"n_seeds": len(values), "mean": float(np.mean(values)),
            "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "median": float(np.median(values)), "min": float(np.min(values)), "max": float(np.max(values))}


def run_repeated(base_seed: int = BASE_SEED, n_seeds: int = N_SEEDS) -> dict[str, Any]:
    seeds = seed_list(base_seed, n_seeds)
    scenario_rows: dict[str, list[dict[str, Any]]] = {}
    raw_identity: dict[int, list[tuple[Any, ...]]] = {}
    for scenario in SCENARIOS:
        per_seed = []
        for seed in seeds:
            result = run_experiment(seed=seed, per_pattern=PER_PATTERN, error_rate=scenario["error_rate"],
                                    abstain_threshold=THRESHOLD,
                                    unknown_high_confidence_mixture_rate=scenario["unknown_high_confidence_mixture_rate"])
            reps = result["results"]
            leakage = result["leakage_audit"]
            audit_fields = ("gallery_query_asset_id_overlap", "gallery_duplicate_asset_ids",
                            "query_duplicate_asset_ids", "duplicate_observed_raw_mask_pairs")
            if any(leakage[key] != 0 for key in audit_fields):
                raise AssertionError(f"leakage audit failed for {scenario['name']} seed={seed}: {leakage}")
            ids = {rep: [x["query_asset_id"] for x in reps[rep]["queries"]] for rep in REPS}
            if any(ids[rep] != ids["raw"] for rep in REPS):
                raise AssertionError(f"query IDs differ among representations, seed={seed}")
            raw_rows = reps["raw"]["queries"]
            raw_fingerprint = [(x["query_asset_id"], x["top_asset_id"], x["score"],
                                x["truth_composition_l1"], x["spatial_similarity"]) for x in raw_rows]
            if scenario["name"] == SCENARIOS[0]["name"]:
                raw_identity[seed] = raw_fingerprint
            else:
                if raw_identity.get(seed) != raw_fingerprint:
                    raise AssertionError(f"raw baseline tuple or query order differs across scenarios, seed={seed}")
            by_rep = {}
            for rep in REPS:
                rows = reps[rep]["queries"]
                l1 = [float(x["truth_composition_l1"]) for x in rows]
                spatial = [float(x["spatial_similarity"]) for x in rows if x["spatial_similarity"] is not None]
                by_rep[rep] = {"query_count": len(rows), "truth_composition_l1": float(np.mean(l1)) if l1 else None,
                               "spatial_iou_common_observed": float(np.mean(spatial)) if spatial else None,
                               "spatial_valid_comparisons": len(spatial), "spatial_excluded": len(rows)-len(spatial)}
            per_seed.append({"seed": seed, "query_count": len(ids["raw"]), "leakage_audit": leakage,
                             "raw_cross_scenario_identity_match": True, "representations": by_rep})
        scenario_rows[scenario["name"]] = per_seed

    summaries = {}
    for scenario, rows in scenario_rows.items():
        summaries[scenario] = {}
        for rep in REPS:
            l1 = [r["representations"][rep]["truth_composition_l1"] for r in rows]
            spatial = [r["representations"][rep]["spatial_iou_common_observed"] for r in rows
                       if r["representations"][rep]["spatial_iou_common_observed"] is not None]
            diffs = [r["representations"][rep]["truth_composition_l1"] - r["representations"]["raw"]["truth_composition_l1"] for r in rows]
            spatial_diffs = [(r["representations"][rep]["spatial_iou_common_observed"] - r["representations"]["raw"]["spatial_iou_common_observed"])
                             for r in rows if r["representations"][rep]["spatial_iou_common_observed"] is not None
                             and r["representations"]["raw"]["spatial_iou_common_observed"] is not None]
            summaries[scenario][rep] = {"truth_composition_l1_seed_mean": _summary(l1),
                "paired_l1_difference_vs_raw_seed": _summary(diffs),
                "common_observed_spatial_iou_seed_mean": _summary(spatial),
                "paired_spatial_iou_difference_vs_raw_seed": _summary(spatial_diffs)}

    return {"status": "descriptive_synthetic_monte_carlo_complete", "scope": "CPU NumPy synthetic retrieval only",
        "design": {"base_seed": base_seed, "seed_step": SEED_STEP, "seeds": seeds, "seed_count": len(seeds),
            "per_pattern": PER_PATTERN, "gallery_wafers": 12, "query_wafers": 12, "threshold": THRESHOLD,
            "scenarios": list(SCENARIOS), "representations": list(REPS), "analysis_unit": "seed-level mean; query observations share galleries and are not independent replicates",
            "estimands": "seed mean truth-composition L1 (lower preferred) and common-observed spatial IoU; paired seed-level difference from raw",
            "pairing": "representations use identical query IDs and gallery/query data within each seed and scenario",
            "missing_policy": "None spatial comparisons omitted only from spatial estimand; counts reported; no imputation"},
        "claims": {"confidence_intervals": False, "p_values": False, "statistical_significance": False,
            "real_performance_or_novelty": False, "interpretation": "descriptive Monte Carlo, limited to this generator and settings"},
        "seed_results": scenario_rows, "summaries": summaries,
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__},
        "limitations": ["Synthetic masks and scores only; no learned model, GPU, or internal data.",
            "Eight seeds are descriptive simulation draws, not independent real-world wafers.",
            "The generators' class-channel and correctness semantics constrain interpretation."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-seed", type=int, default=BASE_SEED)
    parser.add_argument("--n-seeds", type=int, default=N_SEEDS)
    parser.add_argument("--output", type=Path, default=Path("var/fbm-mixed-repeated-20261030/results.json"))
    args = parser.parse_args()
    payload = run_repeated(args.base_seed, args.n_seeds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "seed_count": payload["design"]["seed_count"],
                      "scenarios": list(payload["summaries"])}, indent=2))


if __name__ == "__main__":
    main()
