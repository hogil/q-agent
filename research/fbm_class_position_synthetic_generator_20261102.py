"""Synthetic binary fail-mask proxy for class/position counterfactuals.

This is not a reproduction of field-measured raw FBM. It creates deterministic
192x192 binary masks in memory, with no model calls, training, or site data.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any

import numpy as np

VERSION = "1.0.0"
SOURCE_ID = "fbm-class-position-synthetic-20261102"
SIZE = 192
FAIL_COUNT = 20
CLASSES = ("A", "B")
REGIMES = ("center", "ring", "position_neutral")
ROLES = ("pilot", "development", "gallery", "query", "holdout")
ROLE_FAMILY_COUNT = 1
DEFAULT_FAMILY_COUNTS = {role: ROLE_FAMILY_COUNT for role in ROLES}
MAX_FAMILIES_PER_ROLE_REGIME = 32
POSITION_DEFINITION = {
    "center": "10 fail pixels have normalized radius <= 0.25; remaining 10 are outside that band.",
    "ring": "10 fail pixels have normalized radius in [0.45, 0.65]; remaining 10 are outside that band.",
    "position_neutral": "20 distinct pixels sampled uniformly from the usable disk, independent of class; no radial quota.",
    "geometry": "192x192 grid; center=(95.5,95.5); usable disk radius=86; candidate coordinates [8,183].",
    "boundary": "Synthetic occupancy definitions only; not measured wafer/FBM coordinates or raw sensor data.",
}
LIMITATIONS = (
    "Binary synthetic fail-mask proxy, not field-measured raw FBM; no real-data validity or performance claim. "
    "A/B are counterfactual sample classes sharing one mask lineage, not a claim that a family has an invariant class. "
    "Existing roster rejects duplicate family IDs, so the paired A/B samples must not both be represented as roster entries."
)


def _derive(seed: int, *parts: object) -> int:
    payload = "|".join((str(seed), *(str(x) for x in parts))).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _positions(seed: int, role: str, regime: str, replicate: int) -> tuple[tuple[int, int], ...]:
    rng = random.Random(_derive(seed, role, regime, replicate, "mask"))
    c, radius = (SIZE - 1) / 2, 86
    points: set[tuple[int, int]] = set()
    band = (0.0, .25) if regime == "center" else (.45, .65)
    while len(points) < FAIL_COUNT:
        x, y = rng.randrange(8, SIZE - 8), rng.randrange(8, SIZE - 8)
        if (x-c)**2 + (y-c)**2 > radius**2:
            continue
        r = math.hypot(y-c, x-c) / (SIZE / 2)
        in_band = band[0] <= r <= band[1]
        if regime == "position_neutral" or (in_band == (len(points) < 10)):
            points.add((y, x))
    return tuple(sorted(points))


def _opaque_id(rng: random.Random, used: set[str]) -> str:
    while True:
        value = rng.getrandbits(128).to_bytes(16, "big").hex()
        if value not in used:
            used.add(value)
            return value


@dataclass(frozen=True)
class Sample:
    sample_id: str
    master_seed: int
    family_id: str
    role: str
    regime: str
    true_class: str
    fail_mask: np.ndarray
    raw_array: np.ndarray
    id_maps: dict[str, np.ndarray]
    metadata: dict[str, Any]


def _validated_family_counts(family_counts: dict[str, int] | None) -> dict[str, int]:
    if family_counts is None:
        return dict(DEFAULT_FAMILY_COUNTS)
    if not isinstance(family_counts, dict) or set(family_counts) != set(ROLES):
        raise ValueError(f"family_counts must contain exactly these roles: {ROLES}")
    counts: dict[str, int] = {}
    for role in ROLES:
        value = family_counts[role]
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_FAMILIES_PER_ROLE_REGIME:
            raise ValueError(f"family count for {role} must be an integer in [1, {MAX_FAMILIES_PER_ROLE_REGIME}]")
        counts[role] = value
    return counts


def generate(seed: int = 20261102, *, family_counts: dict[str, int] | None = None) -> list[Sample]:
    """Generate deterministic role/regime cohorts; default is 30 samples."""
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    counts = _validated_family_counts(family_counts)
    result: list[Sample] = []
    used_ids: set[str] = set()
    for role in ROLES:
        for regime in REGIMES:
            for replicate in range(counts[role]):
                family = f"family-{_derive(seed, role, regime, replicate, 'family'):016x}"
                coords = _positions(seed, role, regime, replicate)
                mask = np.zeros((SIZE, SIZE), dtype=np.bool_)
                for y, x in coords:
                    mask[y, x] = True
                rng = random.Random(_derive(seed, role, regime, replicate, "opaque-ids"))
                a_coords = set(rng.sample(list(coords), 10))
                a_map = np.zeros((SIZE, SIZE), dtype=np.uint8)
                for p in coords:
                    a_map[p] = 1 if p in a_coords else 2
                b_map = np.zeros_like(a_map)
                b_map[mask] = 3 - a_map[mask]
                mapping = {"A": a_map, "B": b_map}
                for cls in CLASSES:
                    idmap = mapping[cls]
                    sample_id = _opaque_id(rng, used_ids)
                    result.append(Sample(
                        sample_id, seed, family, role, regime, cls,
                        mask.copy(), mask.astype(np.uint8), {"A": a_map.copy(), "B": b_map.copy()},
                        {"mask_hash": hashlib.sha256(mask.tobytes()).hexdigest(),
                         "id_map_hash": hashlib.sha256(idmap.tobytes()).hexdigest(),
                         "class_pair_complement": True,
                         "family_semantics": "shared mask lineage across counterfactual A/B sample classes; class is sample-level, not family-invariant",
                         "position_definition": POSITION_DEFINITION[regime],
                         "limitations": LIMITATIONS},
                    ))
    validate(result)
    return result


def manifest(seed: int = 20261102, *, family_counts: dict[str, int] | None = None) -> dict[str, Any]:
    counts = _validated_family_counts(family_counts)
    samples = generate(seed, family_counts=counts)
    return {
        "source_id": SOURCE_ID, "version": VERSION, "seed": seed,
        "shape": [SIZE, SIZE], "fail_count": FAIL_COUNT,
        "family_counts_per_role_regime": counts,
        "roles": list(ROLES), "regimes": list(REGIMES), "classes": list(CLASSES),
        "position_definition": POSITION_DEFINITION, "limitations": LIMITATIONS,
        "roster_constraint": "Roster rejects duplicate family IDs; do not include both counterfactual A/B samples as roster entries.",
        "samples": [{"sample_id": s.sample_id, "family_id": s.family_id, "role": s.role,
                     "regime": s.regime, "true_class": s.true_class,
                     "mask_hash": s.metadata["mask_hash"], "id_map_hash": s.metadata["id_map_hash"]}
                    for s in samples],
    }


def validate(samples: list[Sample]) -> None:
    if not samples or len(samples) % 2:
        raise ValueError("cohort must contain complete A/B pairs")
    if len({s.sample_id for s in samples}) != len(samples):
        raise ValueError("sample IDs must be unique")
    groups: dict[str, list[Sample]] = {}
    role_masks: dict[str, set[str]] = {role: set() for role in ROLES}
    role_family_regime_counts = {(role, regime): 0 for role in ROLES for regime in REGIMES}
    for s in samples:
        if s.role not in ROLES or s.regime not in REGIMES or s.true_class not in CLASSES:
            raise ValueError("invalid sample metadata")
        if s.fail_mask.shape != (SIZE, SIZE) or int(s.fail_mask.sum()) != FAIL_COUNT:
            raise ValueError("invalid fail mask shape/count")
        if not np.array_equal(s.raw_array, s.fail_mask.astype(np.uint8)):
            raise ValueError("raw proxy differs from fail mask")
        role_masks[s.role].add(s.metadata["mask_hash"])
        groups.setdefault(s.family_id, []).append(s)
    for family, pair in groups.items():
        if pair:
            role_family_regime_counts[(pair[0].role, pair[0].regime)] += 1
    for role in ROLES:
        values = {role_family_regime_counts[(role, regime)] for regime in REGIMES}
        if 0 in values or len(values) != 1:
            raise ValueError("each role must have the same positive family count in every regime")
    if any(role_masks[a] & role_masks[b] for i, a in enumerate(ROLES) for b in ROLES[i+1:]):
        raise ValueError("exact mask leakage across roles")
    if len(groups) < len(ROLES) * len(REGIMES):
        raise ValueError("family identity must be role/regime scoped")
    for family, pair in groups.items():
        if len(pair) != 2 or {s.true_class for s in pair} != set(CLASSES):
            raise ValueError(f"family must contain exactly A/B counterfactual samples: {family}")
        a, b = sorted(pair, key=lambda s: s.true_class)
        if a.role != b.role or a.regime != b.regime:
            raise ValueError("counterfactual pair metadata mismatch")
        if a.fail_mask.tobytes() != b.fail_mask.tobytes() or a.raw_array.tobytes() != b.raw_array.tobytes():
            raise ValueError("counterfactual pair masks differ")
        if not np.array_equal(a.id_maps["A"], b.id_maps["A"]) or not np.array_equal(a.id_maps["B"], b.id_maps["B"]):
            raise ValueError("counterpart ID-map source bytes differ")
        if not np.all(a.id_maps["A"][a.fail_mask] + a.id_maps["B"][a.fail_mask] == 3):
            raise ValueError("A/B ID maps are not complements")
        if any(int((s.id_maps[s.true_class] == label).sum()) != 10 for s in pair for label in (1, 2)):
            raise ValueError("each sample must have 10:10 known A/B labels")

