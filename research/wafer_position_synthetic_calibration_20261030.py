from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research" / "wafer_position_permutation_20261030.py"
OUT_ROOT = ROOT / "var" / "fbm-research"
ALPHA = 0.05
PERMUTATIONS = 199
MASTER_SEED = 20261030
WAFER_COUNTS = {"null_uniform": 100, "center": 30, "inner_ring": 30, "edge": 30}
FAIL_COUNT = 20
GRID_STEP = 0.05
STRATUM = "synthetic_all_same_stratum"


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt((p * (1 - p) / n) + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def make_grid() -> list[tuple[float, float, float]]:
    n = round(1 / GRID_STEP)
    points = []
    for iy in range(-n, n + 1):
        for ix in range(-n, n + 1):
            x, y = ix * GRID_STEP, iy * GRID_STEP
            radius = math.hypot(x, y)
            if radius <= 1.0 + 1e-12:
                points.append((x, y, radius))
    return points


def make_rows(points, condition: str, seed: int):
    rng = random.Random(seed)
    eligible = list(range(len(points)))
    if condition == "center":
        pool = [i for i, p in enumerate(points) if p[2] <= 0.25]
    elif condition == "inner_ring":
        pool = [i for i, p in enumerate(points) if 0.25 < p[2] <= 0.55]
    elif condition == "edge":
        pool = [i for i, p in enumerate(points) if 0.82 < p[2] <= 1.0]
    else:
        pool = eligible
    fails = set(rng.sample(pool, FAIL_COUNT))
    return [{"x": x, "y": y, "defect": int(i in fails), "strata": STRATUM}
            for i, (x, y, _) in enumerate(points)]


def derive_domain_seed(wafer_seed: int, domain: str) -> int:
    material = f"{wafer_seed}:{domain}".encode("ascii")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def main():
    spec = importlib.util.spec_from_file_location("wafer_position_permutation_20261030", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    points = make_grid()
    rng = random.Random(MASTER_SEED)
    groups = {}
    wafer_seeds = {}
    wafer_records = {}
    for condition, count in WAFER_COUNTS.items():
        results = []
        wafer_seeds[condition] = []
        wafer_records[condition] = []
        for idx in range(count):
            wafer_seed = rng.randrange(0, 2**63)
            generation_seed = derive_domain_seed(wafer_seed, "generation")
            permutation_seed = derive_domain_seed(wafer_seed, "permutation")
            wafer_seeds[condition].append({"wafer_seed": wafer_seed,
                                           "generation_seed": generation_seed,
                                           "permutation_seed": permutation_seed})
            rows = make_rows(points, condition, generation_seed)
            result = module.analyze_wafer_positions(rows, permutations=PERMUTATIONS,
                                                   seed=permutation_seed, alpha=ALPHA)
            results.append(result)
            wafer_records[condition].append({
                "condition": condition,
                "wafer_seed": wafer_seed,
                "generation_seed": generation_seed,
                "permutation_seed": permutation_seed,
                "status": result["status"],
                "p_value": result["p_value"],
                "exceedances": result.get("exceedances"),
                "observed_max_abs_standardized_residual": result.get("observed_max_abs_standardized_residual"),
                "fail_count": sum(row["defect"] for row in rows),
            })
        n = len(results)
        k = sum(r["status"] == "spatial_evidence" for r in results)
        pvals = [r["p_value"] for r in results if r["p_value"] is not None]
        groups[condition] = {
            "spatial_evidence_count": k, "wafer_count": n, "spatial_evidence_rate": k / n,
            "wilson_95_ci": wilson(k, n),
            "insufficient_count": sum(r["status"] == "insufficient" for r in results),
            "p_value_minimum": min(pvals) if pvals else None,
            "p_value_resolution_minimum_attainable": 1 / (PERMUTATIONS + 1),
            "p_value_resolution_maximum_attainable": 1.0,
            "p_value_resolution_step": 1 / (PERMUTATIONS + 1),
        }
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Synthetic calibration of research-only analyze_wafer_positions; not production validation.",
        "source": {"absolute_path": str(SOURCE), "sha256": source_hash},
        "generator": {"absolute_path": str(Path(__file__).resolve()), "sha256": script_hash},
        "seed_and_conditions": {"master_seed": MASTER_SEED, "per_wafer_seed": "independently drawn from master-seeded RNG", "wafer_seeds": wafer_seeds,
                                "domain_seed_derivation": "first 8 bytes of SHA256(ASCII(f'{wafer_seed}:{domain}')), interpreted unsigned big-endian; domains generation and permutation",
                                "alpha": ALPHA, "permutations": PERMUTATIONS, "wafer_counts": WAFER_COUNTS,
                                "fail_count_per_wafer": FAIL_COUNT, "grid_step": GRID_STEP,
                                "strata": STRATUM, "conditions": ["null_uniform", "center", "inner_ring", "edge"]},
        "synthetic_geometry": {"grid": "Cartesian lattice in unit disk", "step": GRID_STEP,
                               "valid_die_count": len(points), "radius": "hypot(x,y) <= 1 inclusive",
                               "radial_bins": [[0.0, 0.25], [0.25, 0.55], [0.55, 0.82], [0.82, 1.0]],
                               "boundary_rule": "analyze function upper bounds inclusive; shared boundary assigned to inner bin",
                               "failure_sampling": {"null_uniform": "20 distinct valid dies sampled uniformly without replacement",
                                                   "center": "20 distinct dies sampled uniformly from r <= 0.25",
                                                   "inner_ring": "20 distinct dies sampled uniformly from 0.25 < r <= 0.55",
                                                   "edge": "20 distinct dies sampled uniformly from 0.82 < r <= 1.0"}},
        "results": groups,
        "wafer_level_results": wafer_records,
        "prior_result_disposition": {"path": str(OUT_ROOT / "wafer_position_synthetic_calibration_20261030_01" / "results.json"),
                                     "validity": "Invalid for calibration inference: identical wafer_seed initialized generation and permutation RNGs, coupling sampled failures and permutation randomization. Preserved unchanged; do not use its rates or intervals as evidence."},
        "interpretation_limits": [
            "p > alpha is not evidence that failures are random.",
            "The geometry and fail labels are fully synthetic; this calibration does not establish real-data validity.",
            "The repetition counts are small, so rates and intervals are imprecise.",
            "Real within-wafer exchangeability and wafer/Lot dependence are unverified.",
            "Multiple-wafer testing correction is not applied.",
            "Power is unverified for patterns other than the selected uniform, center, inner-ring, and edge patterns."
        ]
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    run = OUT_ROOT / "wafer_position_synthetic_calibration_20261030"
    suffix = 1
    while run.exists():
        run = OUT_ROOT / f"wafer_position_synthetic_calibration_20261030_{suffix:02d}"
        suffix += 1
    run.mkdir()
    (run / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(run), "results": groups}, indent=2))


if __name__ == "__main__":
    main()




