"""Paired synthetic control for radial versus polar wafer tests.

This experiment only relocates synthetic labels on identical wafer coordinates.
It does not establish real-world performance, independence, orientation, or novelty.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.wafer_polar_permutation_20261030 import analyze_wafer_polar_positions
from research.wafer_position_permutation_20261030 import (
    BIN_NAMES, RADIAL_BINS, analyze_wafer_positions,
)


def build_paired_rows(seed: int = 20261030) -> dict[str, Any]:
    """Build cluster and angularly balanced labels on exactly the same dies."""
    rng = random.Random(seed)
    radii = (0.12, 0.40, 0.68, 0.91)
    rows_by_case = {"angular_cluster": [], "angular_balanced": []}
    all_coords = []
    for radial_index, radius in enumerate(radii):
        for sector in range(8):
            sector_angles = [-math.pi + (sector + (k + 0.5) / 16) * math.pi / 4 for k in range(16)]
            for angle in sector_angles:
                all_coords.append((radius * math.cos(angle), radius * math.sin(angle), radial_index, sector))

    for radial_index in range(4):
        items = [item for item in all_coords if item[2] == radial_index]
        cluster_indices = [i for i, item in enumerate(items) if item[3] in (3, 4)]
        cluster_selected = set(rng.sample(cluster_indices, 16))
        balanced_selected = set()
        for sector in range(8):
            candidates = [i for i, item in enumerate(items) if item[3] == sector]
            balanced_selected.update(rng.sample(candidates, 2))
        for case, selected in (("angular_cluster", cluster_selected), ("angular_balanced", balanced_selected)):
            for i, (x, y, _, _) in enumerate(items):
                rows_by_case[case].append({"x": x, "y": y, "defect": int(i in selected), "strata": "synthetic-wafer"})

    return {
        "seed": seed,
        "strata": ["synthetic-wafer"],
        "paired_design": "same coordinate/wafer/radial-bin die identities; only binary labels are relocated",
        "rows": rows_by_case,
    }


def run_experiment(seed: int = 20261030, permutations: int = 999) -> dict[str, Any]:
    paired = build_paired_rows(seed)
    outcomes = {}
    radial_counts = {}
    for case, rows in paired["rows"].items():
        counts = [0] * len(BIN_NAMES)
        for row in rows:
            radius = math.hypot(row["x"], row["y"])
            bin_index = next(i for i, (_, upper) in enumerate(RADIAL_BINS) if radius <= upper)
            counts[bin_index] += row["defect"]
        radial_counts[case] = dict(zip(BIN_NAMES, counts))
        outcomes[case] = {
            "radial": analyze_wafer_positions(rows, permutations=permutations, seed=seed),
            "polar_orientation_asserted": analyze_wafer_polar_positions(
                rows, orientation_asserted=True, permutations=permutations, seed=seed),
            "polar_orientation_unasserted": analyze_wafer_polar_positions(
                rows, orientation_asserted=False, permutations=permutations, seed=seed),
        }
    coordinates_equal = [
        [(r["x"], r["y"]) for r in paired["rows"][case]]
        for case in ("angular_cluster", "angular_balanced")
    ][0] == [
        (r["x"], r["y"]) for r in paired["rows"]["angular_balanced"]
    ]
    radial_equal = radial_counts["angular_cluster"] == radial_counts["angular_balanced"]
    return {
        "experiment": "paired synthetic radial versus polar controls",
        "seed": seed,
        "permutations": permutations,
        "strata": paired["strata"],
        "paired_design": paired["paired_design"],
        "coordinates_identical": coordinates_equal,
        "radial_defect_counts_identical": radial_equal,
        "observed_radial_defect_counts": radial_counts,
        "observed_denominators": {case: len(rows) for case, rows in paired["rows"].items()},
        "analyses": outcomes,
        "analysis_note": "Each p-value is from the corresponding existing permutation function; no significance outcome is prescribed.",
        "interpretation_limits": [
            "Synthetic same-wafer label relocation only; not actual performance evidence, independent replication, or orientation validation.",
            "Radial and polar tests use different statistic families: radial-only max residual versus joint radial-and-angular maxT.",
            "Selective interpretation after comparing cases or families is not confirmatory; multiplicity across this study is not adjusted.",
            "The random angularly balanced allocation is one seeded realization, not evidence of universal test power or calibration.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--permutations", type=int, default=999)
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.seed, args.permutations), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
