"""Find cross-role exact mask matches under square-grid D4 transforms.

This detects equality only after exact 90-degree rotations and reflections.
It does not establish general near-duplicates or actual ancestry. Wafer
orientation may carry meaning, so a hit is not a confirmed leakage, automatic
rejection, or causal claim. The 192x192 contract applies only to this synthetic
experiment, not to field data.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from typing import Iterable

from research.fbm_split_integrity_synthetic_20261102 import MASK_SHAPE, ROLES, MaskRecord


@dataclass(frozen=True)
class _ValidatedMask:
    record: MaskRecord
    rows: tuple[bytes, ...]


def _validated_rows(record: MaskRecord) -> tuple[bytes, ...]:
    if not isinstance(record, MaskRecord):
        raise ValueError("every record must be a MaskRecord")
    if not isinstance(record.sample_id, str) or not record.sample_id:
        raise ValueError("sample IDs must be non-empty strings")
    if record.role not in ROLES:
        raise ValueError(f"{record.sample_id}: unrecognized role")
    if record.shape != MASK_SHAPE or record.dtype != "uint8":
        raise ValueError(f"{record.sample_id}: mask must be uint8 with shape {MASK_SHAPE}")
    if not isinstance(record.mask_bytes, bytes) or len(record.mask_bytes) != MASK_SHAPE[0] * MASK_SHAPE[1]:
        raise ValueError(f"{record.sample_id}: mask byte length does not match shape")
    if any(value not in (0, 1) for value in record.mask_bytes):
        raise ValueError(f"{record.sample_id}: mask bytes must contain only 0/1")
    width = MASK_SHAPE[1]
    return tuple(record.mask_bytes[i:i + width] for i in range(0, len(record.mask_bytes), width))


def _d4(rows: tuple[bytes, ...]) -> tuple[tuple[str, bytes], ...]:
    n = len(rows)
    variants = []
    for reflected in (False, True):
        current = rows if not reflected else tuple(row[::-1] for row in rows)
        for turns in range(4):
            name = ("identity", "rot90", "rot180", "rot270")[turns]
            if reflected:
                name += "_then_flip_lr"
            variants.append((name, b"".join(current)))
            current = tuple(bytes(current[n - 1 - col][row] for col in range(n)) for row in range(n))
    return tuple(variants)


def find_mask_symmetry_candidates(records: Iterable[MaskRecord]) -> dict[str, object]:
    """Return deterministic cross-role pairs whose masks are D4-equivalent."""
    rows = list(records)
    if not rows:
        raise ValueError("records must not be empty")
    ids = [r.sample_id for r in rows if isinstance(r, MaskRecord)]
    if len(ids) != len(rows) or len(ids) != len(set(ids)):
        raise ValueError("sample IDs must be non-empty and unique")
    validated = [_ValidatedMask(record, _validated_rows(record)) for record in rows]
    groups: dict[str, list[tuple[_ValidatedMask, dict[str, bytes]]]] = defaultdict(list)
    for item in validated:
        transforms = dict(_d4(item.rows))
        canonical = min(transforms.values())
        digest = hashlib.sha256(b"uint8|192x192|d4|" + canonical).hexdigest()
        groups[digest].append((item, transforms))

    candidates = []
    transform_names = tuple(name for name, _ in _d4(validated[0].rows))
    for digest in sorted(groups):
        group = sorted(groups[digest], key=lambda pair: (pair[0].record.sample_id, pair[0].record.role))
        for i, (left, left_transforms) in enumerate(group):
            for right, right_transforms in group[i + 1:]:
                if left.record.role == right.record.role:
                    continue
                # The pair is ordered by sample_id; transforms are applied to left.
                equal_transforms = [name for name in transform_names
                                    if left_transforms[name] == right.record.mask_bytes]
                if min(left_transforms.values()) != min(right_transforms.values()):
                    continue
                if not equal_transforms:
                    continue
                candidates.append({
                    "left": {"role": left.record.role, "sample_id": left.record.sample_id},
                    "right": {"role": right.record.role, "sample_id": right.record.sample_id},
                    "canonical_sha256": digest,
                    "matching_transforms_left_to_right": equal_transforms,
                })
    candidates.sort(key=lambda c: (c["left"]["role"], c["left"]["sample_id"],
                                   c["right"]["role"], c["right"]["sample_id"],
                                   c["canonical_sha256"]))
    return {
        "candidate_pairs": candidates,
        "candidate_count": len(candidates),
        "comparison": "exact byte equality under 90-degree rotations and left-right reflections only",
        "interpretation": "candidate only; does not establish ancestry or leakage; wafer orientation may carry meaning; no automatic rejection or causal claim",
        "mask_shape_scope": "192x192 uint8 binary mask applies only to this synthetic experiment; not guaranteed for field data",
        "near_duplicate_audit": "not_implemented",
    }
