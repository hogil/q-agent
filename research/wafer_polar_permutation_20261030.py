"""Research-only radial plus asserted-orientation angular permutation test.

Synthetic/local inspected-die rows only. An asserted orientation is a caller
claim that notch-based x,y registration is accurate, not a measured validation.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Iterable, Mapping

from research.wafer_position_permutation_20261030 import (
    BIN_NAMES, RADIAL_BINS, _insufficient_result, analyze_wafer_positions,
)

SECTOR_COUNT = 8


def analyze_wafer_polar_positions(
    rows: Iterable[Mapping[str, Any]], *, orientation_asserted: bool = False,
    permutations: int = 999, seed: int = 20261030, alpha: float = 0.05,
) -> dict[str, Any]:
    """Run conditional permutation maxT over radial bins and optionally sectors.

    Angle is atan2(y, x), measured counterclockwise from registered +x. Sectors
    are fixed half-open intervals beginning at -pi; both -pi and +pi map to
    -pi and belong to sector_0;
    the origin has undefined angle and is excluded from angular denominators.
    """
    if type(orientation_asserted) is not bool:
        raise ValueError("orientation_asserted must be bool")
    if not orientation_asserted:
        # Preserve the legacy radial implementation exactly, including RNG stream.
        result = analyze_wafer_positions(rows, permutations=permutations, seed=seed, alpha=alpha)
        result.update({
            "angular_included": False,
            "orientation_asserted": False,
            "angular_exclusion_reason": "orientation_asserted=False; notch-based x,y registration was not asserted",
            "orientation_warning": "If notch-based registration is inaccurate, angular sectors have no meaningful wafer direction.",
        })
        return result

    materialized = list(rows)
    # Delegate strict input and parameter validation to the established implementation.
    base = analyze_wafer_positions(materialized, permutations=permutations, seed=seed, alpha=alpha)
    parsed = []
    for row in materialized:
        x, y = float(row["x"]), float(row["y"])
        radius = math.hypot(x, y)
        radial = next((j for j, (_, upper) in enumerate(RADIAL_BINS) if radius <= upper), len(RADIAL_BINS)-1)
        angle = math.atan2(y, x)
        if angle == math.pi:
            angle = -math.pi
        sector = None if x == 0 and y == 0 else min(SECTOR_COUNT - 1, int((angle + math.pi) / (math.pi / 4)))
        parsed.append((int(row["defect"]), row["strata"], radial, sector))

    family: list[tuple[str, int, list[tuple[int, int]]]] = []
    strata_members: dict[Any, list[int]] = defaultdict(list)
    for i, (_, strata, _, _) in enumerate(parsed):
        strata_members[strata].append(i)
    definitions = [("radial", j, lambda r, j=j: r[2] == j) for j in range(4)]
    definitions += [("angular", j, lambda r, j=j: r[3] == j) for j in range(SECTOR_COUNT)]
    results = []
    moments = {}
    for kind, j, includes in definitions:
        eligible = sum(includes(r) for r in parsed)
        observed = sum(r[0] for r in parsed if includes(r))
        exp = var = 0.0
        for members in strata_members.values():
            N = len(members)
            n = sum(includes(parsed[i]) for i in members)
            K = sum(parsed[i][0] for i in members)
            if N:
                p = K / N
                exp += n * p
                if N > 1:
                    var += n * p * (1-p) * (N-n)/(N-1)
        residual = (observed-exp)/math.sqrt(var) if var > 0 else None
        name = BIN_NAMES[j] if kind == "radial" else f"sector_{j}"
        entry = {"bin": name, "family": kind, "observed_fail_count": observed,
                 "eligible_count": eligible, "rate": observed/eligible if eligible else None,
                 "expected_fail_count": exp, "variance": var,
                 "standardized_residual": residual}
        if kind == "radial":
            entry["radial_range"] = RADIAL_BINS[j]
        else:
            entry["angle_range_radians"] = (-math.pi + j*math.pi/4, -math.pi + (j+1)*math.pi/4)
        results.append(entry)
        moments[(kind, j)] = (exp, var)
        family.append((kind, j, [(i, int(includes(r))) for i, r in enumerate(parsed)]))

    valid = [(kind, j) for kind, j, _ in family if moments[(kind,j)][1] > 0]
    residuals = [abs((sum(r[0] for r in parsed if (r[2] == j if kind == "radial" else r[3] == j)) - moments[(kind,j)][0]) / math.sqrt(moments[(kind,j)][1])) for kind,j in valid]
    observed_stat = max(residuals, default=None)
    labels_have_variation = any(r[0] for r in parsed) and not all(r[0] for r in parsed)
    if not labels_have_variation or observed_stat is None:
        out = dict(base)
        out.update({"bins": results, "observed_max_abs_standardized_residual": observed_stat,
                    "angular_included": True, "orientation_asserted": True,
                    "orientation_warning": "Caller asserted notch-based x,y registration; this is not independently measured or verified. Inaccurate registration makes angular results meaningless.",
                    "angular_sector_boundary_rule": "atan2(y,x), counterclockwise from registered +x; both -pi and +pi are normalized to -pi in sector_0; remaining 8 fixed half-open 45-degree sectors; origin excluded from angular denominator",
                    "coverage": {**base.get("coverage", {}),
                                 "angular_origin_excluded_count": sum(r[3] is None for r in parsed),
                                 "angular_eligible_count": sum(r[3] is not None for r in parsed)},
                    "status": "insufficient", "p_value": None,
                    "limits": list(base.get("limits", [])) + [
                        "single-wafer conditional test; strata exchangeability is assumed",
                        "wafer/Lot multiple-testing adjustment is out of scope",
                        "p > alpha is not evidence of randomness",
                        "research-only; no performance, causal, or internal-data application claim"]})
        return out
    rng = random.Random(seed)
    exceedances = 0
    for _ in range(permutations):
        labels = [r[0] for r in parsed]
        for members in strata_members.values():
            group = [labels[i] for i in members]
            rng.shuffle(group)
            for i, label in zip(members, group):
                labels[i] = label
        stat = 0.0
        for kind,j in valid:
            count = sum(labels[i] for i,r in enumerate(parsed) if (r[2] == j if kind == "radial" else r[3] == j))
            exp,var = moments[(kind,j)]
            stat = max(stat, abs((count-exp)/math.sqrt(var)))
        exceedances += stat >= observed_stat - 1e-12
    p_value = (1+exceedances)/(permutations+1)
    out = dict(base)
    out.update({"status": "spatial_evidence" if p_value <= alpha else "no_detected_spatial_evidence",
                "interpretation": "Radial/angular variation signal under the stated null; this is not causal evidence." if p_value <= alpha else "No radial/angular signal detected at this alpha; this does not establish randomness.",
                "p_value": p_value, "exceedances": exceedances, "bins": results,
                "observed_max_abs_standardized_residual": observed_stat,
                "angular_included": True, "orientation_asserted": True,
                "coverage": {**base.get("coverage", {}),
                             "angular_origin_excluded_count": sum(r[3] is None for r in parsed),
                             "angular_eligible_count": sum(r[3] is not None for r in parsed)},
                "orientation_warning": "Caller asserted notch-based x,y registration; this is not independently measured or verified. Inaccurate registration makes angular results meaningless.",
                "angular_sector_boundary_rule": "atan2(y,x), counterclockwise from registered +x; both -pi and +pi are normalized to -pi in sector_0; remaining 8 fixed half-open 45-degree sectors; origin excluded from angular denominator",
                "statistic_calibration": "maximum absolute standardized residual jointly across all valid radial bins and angular sectors in every permutation; plus-one Monte Carlo p-value",
                "limits": ["single-wafer conditional test; strata exchangeability is assumed", "wafer/Lot multiple-testing adjustment is out of scope", "p > alpha is not evidence of randomness", "research-only; no performance, causal, or internal-data application claim"]})
    return out

