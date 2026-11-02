"""Synthetic, bounded cross-role binary-mask Jaccard candidate scan.

For each cross-role pair, compare identity and all eight square-grid D4
transforms, retaining the maximum Jaccard score and left-to-right transform.
This is a candidate aid only: the caller supplies a frozen threshold, whose
selection timing and validity this code cannot assess. A hit does not establish
anomaly, leakage, or grounds for automatic rejection. Physical wafer rotation
may be meaningful. The 192x192 and pair-count limits apply only to this small
synthetic experiment, never production data.
"""
from __future__ import annotations

import math
from typing import Iterable

from research.fbm_mask_symmetry_candidates_synthetic_20261102 import _d4, _validated_rows
from research.fbm_split_integrity_synthetic_20261102 import ROLES, MaskRecord


MAX_RECORDS = 64


def find_mask_near_duplicate_candidates(
    records: Iterable[MaskRecord], threshold: float
) -> dict[str, object]:
    """Return bounded cross-role Jaccard comparisons and threshold candidates."""
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be a finite real number in (0, 1]")
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("threshold must be a finite real number in (0, 1]")

    rows = list(records)
    if not rows:
        raise ValueError("records must not be empty")
    if len(rows) > MAX_RECORDS:
        raise ValueError(f"synthetic scan is limited to {MAX_RECORDS} records")
    ids = [r.sample_id for r in rows if isinstance(r, MaskRecord)]
    if len(ids) != len(rows) or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError("every record must be a MaskRecord with a non-empty sample ID")
    if len(ids) != len(set(ids)):
        raise ValueError("sample IDs must be unique")
    for record in rows:
        if record.role not in ROLES:
            raise ValueError(f"{record.sample_id}: unrecognized role")
        _validated_rows(record)

    ordered = sorted(rows, key=lambda r: (r.role, r.sample_id))
    variants = {r.sample_id: dict(_d4(_validated_rows(r))) for r in ordered}
    comparisons = []
    candidates = []
    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            if left.role == right.role:
                continue
            left_bits = left.mask_bytes
            right_bits = right.mask_bytes
            if not any(left_bits) and not any(right_bits):
                comparisons.append({
                    "left": {"role": left.role, "sample_id": left.sample_id},
                    "right": {"role": right.role, "sample_id": right.sample_id},
                    "similarity_status": "indeterminate_both_masks_empty",
                    "max_jaccard": None,
                    "best_transform_left_to_right": None,
                    "candidate": False,
                })
                continue
            best_score = -1.0
            best_transform = "identity"
            for transform_name, transformed in variants[left.sample_id].items():
                intersection = sum(a & b for a, b in zip(transformed, right_bits))
                union = sum(a | b for a, b in zip(transformed, right_bits))
                score = intersection / union if union else 0.0
                if score > best_score:
                    best_score = score
                    best_transform = transform_name
            is_candidate = best_score >= threshold
            comparison = {
                "left": {"role": left.role, "sample_id": left.sample_id},
                "right": {"role": right.role, "sample_id": right.sample_id},
                "similarity_status": "scored",
                "max_jaccard": best_score,
                "best_transform_left_to_right": best_transform,
                "candidate": is_candidate,
            }
            comparisons.append(comparison)
            if is_candidate:
                candidates.append(dict(comparison))
    return {
        "threshold": threshold,
        "threshold_provenance": "caller-provided frozen assertion; selection timing and validity are not evaluated",
        "comparisons": comparisons,
        "candidate_pairs": candidates,
        "candidate_count": len(candidates),
        "interpretation": "candidate only; does not confirm anomaly or leakage and must not trigger automatic rejection; physical wafer rotation may be meaningful",
        "scope": f"synthetic small-input scan only; at most {MAX_RECORDS} records; not for production data",
    }
