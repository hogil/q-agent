"""Fail-closed split integrity checks for synthetic FBM fixtures.

This audits cross-role family/ancestry and exact binary mask duplication only.
Rotation/reflection duplicates, near-duplicate geometry, lineage completeness,
and dataset authenticity remain unverified. The 192x192 mask contract is for
the current synthetic encoder experiment only, not a field-data guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable


ROLES = ("pilot", "development", "gallery", "query", "holdout")
MASK_SHAPE = (192, 192)


@dataclass(frozen=True)
class MaskRecord:
    sample_id: str
    family_id: str
    role: str
    mask_bytes: bytes
    shape: tuple[int, int]
    dtype: str
    ancestry: tuple[str, ...] = ()
    derived_ancestry: tuple[str, ...] = ()
    claimed_mask_sha256: str | None = None


def _mask_digest(record: MaskRecord) -> str:
    if not isinstance(record.mask_bytes, bytes):
        raise ValueError(f"{record.sample_id}: mask_bytes must be bytes")
    if record.shape != MASK_SHAPE or record.dtype != "uint8":
        raise ValueError(f"{record.sample_id}: mask must be uint8 with shape {MASK_SHAPE}")
    if len(record.mask_bytes) != MASK_SHAPE[0] * MASK_SHAPE[1]:
        raise ValueError(f"{record.sample_id}: mask byte length does not match shape")
    if any(value not in (0, 1) for value in record.mask_bytes):
        raise ValueError(f"{record.sample_id}: mask bytes must contain only 0/1")
    payload = b"uint8|192x192|" + record.mask_bytes
    digest = hashlib.sha256(payload).hexdigest()
    if record.claimed_mask_sha256 is not None and record.claimed_mask_sha256 != digest:
        raise ValueError(f"{record.sample_id}: claimed mask hash disagrees with mask bytes")
    return digest


def validate_split_integrity(records: Iterable[MaskRecord]) -> dict[str, object]:
    """Reject cross-role family, supplied ancestry, or exact-mask leakage.

    Exact duplicates within one role are allowed: paired variants may reuse a
    mask within a family. All five roles must be represented before cross-role
    comparisons are reported. Ancestry tokens are compared by exact string
    equality; no prefix or transform-name inference is performed.
    """
    rows = list(records)
    if not rows:
        raise ValueError("records must not be empty")
    ids = [r.sample_id for r in rows]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("sample IDs must be non-empty and unique")
    if any(not isinstance(r, MaskRecord) for r in rows):
        raise ValueError("every record must be a MaskRecord")
    if any(r.role not in ROLES for r in rows):
        raise ValueError("every record must have one recognized role")
    present_roles = tuple(role for role in ROLES if any(r.role == role for r in rows))
    missing_roles = tuple(role for role in ROLES if role not in present_roles)
    if missing_roles:
        raise ValueError(f"missing required roles: {', '.join(missing_roles)}")
    role_families: dict[str, set[str]] = {role: set() for role in ROLES}
    role_ancestry: dict[str, set[str]] = {role: set() for role in ROLES}
    role_masks: dict[str, set[str]] = {role: set() for role in ROLES}
    for r in rows:
        if not isinstance(r.family_id, str) or not r.family_id:
            raise ValueError(f"{r.sample_id}: missing family ID")
        if not isinstance(r.ancestry, tuple) or not isinstance(r.derived_ancestry, tuple):
            raise ValueError(f"{r.sample_id}: ancestry must be tuples of non-empty strings")
        ancestry = (r.family_id, *r.ancestry, *r.derived_ancestry)
        if any(not isinstance(item, str) or not item for item in ancestry):
            raise ValueError(f"{r.sample_id}: ancestry must contain non-empty strings")
        role_families[r.role].add(r.family_id)
        role_ancestry[r.role].update(ancestry)
        role_masks[r.role].add(_mask_digest(r))
    checked_pairs = []
    for i, left in enumerate(present_roles):
        for right in present_roles[i + 1:]:
            checked_pairs.append((left, right))
            if role_families[left] & role_families[right]:
                raise ValueError(f"family leakage across {left}/{right}")
            if role_ancestry[left] & role_ancestry[right]:
                raise ValueError(f"ancestry leakage across {left}/{right}")
            if role_masks[left] & role_masks[right]:
                raise ValueError(f"exact mask duplicate across {left}/{right}")
    return {
        "roles_present": list(present_roles),
        "cross_role_pairs_checked": [list(pair) for pair in checked_pairs],
        "sample_count": len(rows),
        "near_duplicate_audit": "not_implemented; no justified metric/threshold",
        "rotation_reflection_duplicate_audit": "not_implemented",
        "lineage_completeness": "unverified caller-supplied exact ancestry tokens only; shared roots are not inferred from prefixes",
        "dataset_authenticity": "unverified synthetic inputs",
        "mask_shape_scope": "192x192 uint8 binary mask applies only to current synthetic encoder experiment; not guaranteed for field data",
    }
