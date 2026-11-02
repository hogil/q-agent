"""Research-only radial wafer-position permutation test on synthetic/local inputs.

Rows must represent dies whose inspection was actually performed. Missing dies
are absent and therefore never enter a denominator. This module does not
establish causation or production readiness.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Iterable, Mapping


# Fixed before examining labels: center, inner/middle ring, outer ring, edge.
RADIAL_BINS = ((0.0, 0.25), (0.25, 0.55), (0.55, 0.82), (0.82, 1.0))
BIN_NAMES = ("center", "inner_ring", "outer_ring", "edge")


def analyze_wafer_positions(
    rows: Iterable[Mapping[str, Any]],
    *,
    permutations: int = 999,
    seed: int = 20261030,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Test a single wafer for radial fail-rate variation conditional on strata.

    Required row fields: x, y (normalized coordinates in the unit disk),
    defect (numeric 0/1, including 0.0/1.0 or bool), and strata (a non-empty
    string, integer, finite float, or non-empty tuple of those scalar types;
    booleans are not valid strata). Radial upper boundaries are inclusive, so
    a die exactly on a shared boundary belongs to the inner bin.
    """
    if isinstance(permutations, bool) or not isinstance(permutations, int) or permutations < 99:
        raise ValueError("permutations must be an integer >= 99")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be finite and between 0 and 1")

    materialized = list(rows)
    parsed: list[tuple[float, float, int, Any]] = []
    seen: set[tuple[float, float]] = set()
    for index, row in enumerate(materialized):
        if not isinstance(row, Mapping):
            raise ValueError(f"row {index} must be a mapping")
        if not all(key in row for key in ("x", "y", "defect", "strata")):
            raise ValueError(f"row {index} requires x, y, defect, and strata")
        x, y, defect, strata = row["x"], row["y"], row["defect"], row["strata"]
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError(f"row {index} coordinates must be numeric")
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"row {index} coordinates must be finite")
        if x * x + y * y > 1.0 + 1e-12:
            raise ValueError(f"row {index} lies outside the normalized wafer disk")
        point = (x, y)
        if point in seen:
            raise ValueError(f"duplicate die coordinate at row {index}")
        seen.add(point)
        if isinstance(defect, bool):
            defect = int(defect)
        if defect not in (0, 1) or isinstance(defect, float) and not math.isfinite(defect):
            raise ValueError(f"row {index} defect must be binary 0/1")
        def valid_stratum_scalar(value: Any) -> bool:
            if isinstance(value, bool):
                return False
            if isinstance(value, str):
                return bool(value.strip())
            if isinstance(value, int):
                return True
            if isinstance(value, float):
                return math.isfinite(value)
            return False

        if isinstance(strata, tuple):
            strata_valid = bool(strata) and all(valid_stratum_scalar(value) for value in strata)
        else:
            strata_valid = valid_stratum_scalar(strata)
        if not strata_valid:
            raise ValueError(f"row {index} strata must be a non-empty string, integer, finite float, or non-empty tuple of these (excluding booleans)")
        try:
            hash(strata)
        except TypeError as exc:
            raise ValueError(f"row {index} strata must be hashable") from exc
        parsed.append((x, y, int(defect), strata))

    counts = [[0, 0] for _ in BIN_NAMES]  # observed failures, eligible dies
    strata_members: dict[Any, list[tuple[int, int]]] = defaultdict(list)
    for i, (x, y, defect, strata) in enumerate(parsed):
        radius = math.hypot(x, y)
        bin_index = next((j for j, (_, upper) in enumerate(RADIAL_BINS) if radius <= upper), None)
        if bin_index is None:
            # Numerical boundary tolerance for the disk edge.
            bin_index = len(RADIAL_BINS) - 1
        counts[bin_index][0] += defect
        counts[bin_index][1] += 1
        strata_members[strata].append((i, bin_index))

    bin_results = []
    variances = [0.0] * len(BIN_NAMES)
    expected = [0.0] * len(BIN_NAMES)
    for j, name in enumerate(BIN_NAMES):
        obs, eligible = counts[j]
        exp = var = 0.0
        for members in strata_members.values():
            n = sum(b == j for _, b in members)
            N = len(members)
            K = sum(parsed[i][2] for i, _ in members)
            if N:
                p = K / N
                exp += n * p
                if N > 1:
                    var += n * p * (1 - p) * (N - n) / (N - 1)
        expected[j], variances[j] = exp, var
        bin_results.append({"bin": name, "radial_range": RADIAL_BINS[j], "observed_fail_count": obs,
                            "eligible_count": eligible, "rate": obs / eligible if eligible else None,
                            "expected_fail_count": exp, "variance": var,
                            "standardized_residual": (obs - exp) / math.sqrt(var) if var > 0 else None})

    observed_stat = max((abs((counts[j][0] - expected[j]) / math.sqrt(variances[j]))
                         for j in range(len(BIN_NAMES)) if variances[j] > 0), default=None)
    if not parsed or not any(row[2] for row in parsed) or all(row[2] for row in parsed) or observed_stat is None:
        return _insufficient_result(bin_results, permutations, seed, alpha, len(parsed), observed_stat)

    rng = random.Random(seed)
    exceedances = 0
    for _ in range(permutations):
        permuted_counts = [0] * len(BIN_NAMES)
        for members in strata_members.values():
            labels = [parsed[i][2] for i, _ in members]
            rng.shuffle(labels)
            for (_, b), label in zip(members, labels):
                permuted_counts[b] += label
        perm_stat = max((abs((permuted_counts[j] - expected[j]) / math.sqrt(variances[j]))
                         for j in range(len(BIN_NAMES)) if variances[j] > 0), default=0.0)
        exceedances += perm_stat >= observed_stat - 1e-12
    p_value = (1 + exceedances) / (permutations + 1)
    return {
        "status": "spatial_evidence" if p_value <= alpha else "no_detected_spatial_evidence",
        "interpretation": ("Radial variation signal under the stated null; this is not causal evidence." if p_value <= alpha
                           else "No radial signal detected at this alpha; this does not establish randomness."),
        "p_value": p_value, "alpha": float(alpha), "observed_max_abs_standardized_residual": observed_stat,
        "permutations": permutations, "seed": seed, "exceedances": exceedances,
        "bins": bin_results, "coverage": {"eligible_inspected_die_count": len(parsed),
                                              "bin_eligible_counts": {r["bin"]: r["eligible_count"] for r in bin_results},
                                              "missing_die_denominator_policy": "excluded; input contains inspected dies only"},
        "assumptions": ["labels are exchangeable within caller-supplied strata",
                        "the full eligible mask and coordinate registration are accurate",
                        "defect clustering or position-dependent inspection can violate exchangeability"],
        "limits": ["one-wafer radial test only", "wafer/Lot multiple-testing adjustment is out of scope",
                   "angle/orientation is excluded because notch/registration is unverified",
                   "narrow/boundary-crossing rings and angular/local patterns may be missed",
                   "Monte Carlo tail precision depends on permutation count",
                   "no continuous-wafer or Ripley analysis", "research-only; no production/ACL application claim"],
        "statistic_calibration": "maximum absolute standardized residual across all four pre-fixed bins in every permutation",
        "radial_bin_boundary_rule": "upper bounds inclusive; a die on a shared boundary belongs to the inner bin",
    }


def _insufficient_result(bins: list[dict[str, Any]], permutations: int, seed: int,
                         alpha: float, n: int, statistic: float | None) -> dict[str, Any]:
    return {"status": "insufficient", "interpretation": "Insufficient variation for a valid permutation p-value.",
            "p_value": None, "alpha": float(alpha), "observed_max_abs_standardized_residual": statistic,
            "permutations": permutations, "seed": seed, "bins": bins,
            "coverage": {"eligible_inspected_die_count": n,
                         "bin_eligible_counts": {r["bin"]: r["eligible_count"] for r in bins},
                         "missing_die_denominator_policy": "excluded; input contains inspected dies only"},
            "assumptions": ["labels are exchangeable within caller-supplied strata",
                            "the full eligible mask and coordinate registration are accurate",
                            "defect clustering or position-dependent inspection can violate exchangeability"],
            "limits": ["wafer/Lot multiple-testing adjustment is out of scope",
                       "Monte Carlo tail precision depends on permutation count",
                       "research-only; no production/ACL application claim"]}
