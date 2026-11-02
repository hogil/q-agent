"""Deterministic, in-memory synthetic FBM factorial data generator.

This creates research fixtures only. It does not run a model or represent
observed CNN, wafer, or yield behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random
from typing import Any

import numpy as np

VERSION = "1.0.0"
SOURCE_ID = "fbm-paired-factorial-synthetic-20261030"
SEEDS = (42, 1, 2, 3, 4)
REGIMES = ("center", "ring", "random")
SPLITS = ("gallery", "query")
LABEL_POLICIES = ("spatial_coupled", "marginal_shuffle", "position_independent_random")
SIZE = 192
DEFECT_COUNT = 20
KNOWN_A, KNOWN_B, UNKNOWN_REJECT = 1, 2, 0
# Fixed representation palette. Values are codes, not learned embeddings.
OBJECT_ID_PALETTE = {"unknown_reject": 0, "A": 1, "B": 2, "background": 3}
CLASS_LEAKAGE_NOTE = (
    "Wafer class is metadata used to assign A/B labels. Raw occupancy does not encode class; "
    "object-ID is a synthetic oracle label channel and deliberately encodes the target class/position "
    "in center/ring stress controls; it is not a CNN prediction and supports no real wafer generalization."
)


def _seed(*parts: object) -> int:
    msg = "|".join(map(str, parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(msg).digest()[:8], "big")


def _die_positions(seed: int, group_id: str, regime: str) -> tuple[tuple[int, int], ...]:
    """20 deterministic points: center/ring use 10 target + 10 outside; random has no ring quota."""
    rng = random.Random(_seed(seed, group_id, "occupancy"))
    center, radius = 95.5, 86
    pts: set[tuple[int, int]] = set()
    if regime == "random":
        while len(pts) < DEFECT_COUNT:
            x, y = rng.randrange(8, SIZE - 8), rng.randrange(8, SIZE - 8)
            if (x - center) ** 2 + (y - center) ** 2 <= radius ** 2:
                pts.add((y, x))
        return tuple(sorted(pts))
    target_radius = (0.0, 0.25) if regime == "center" else (0.45, 0.65)
    while sum(target_radius[0] <= math.hypot(y - center, x - center) / (SIZE / 2) <= target_radius[1]
              for y, x in pts) < 10:
        x, y = rng.randrange(8, SIZE - 8), rng.randrange(8, SIZE - 8)
        if (x - center) ** 2 + (y - center) ** 2 <= radius ** 2:
            r = math.hypot(y - center, x - center) / (SIZE / 2)
            if target_radius[0] <= r <= target_radius[1]:
                pts.add((y, x))
    while len(pts) < DEFECT_COUNT:
        x, y = rng.randrange(8, SIZE - 8), rng.randrange(8, SIZE - 8)
        r = math.hypot(y - center, x - center) / (SIZE / 2)
        if (x - center) ** 2 + (y - center) ** 2 <= radius ** 2 and not target_radius[0] <= r <= target_radius[1]:
            pts.add((y, x))
    return tuple(sorted(pts))


def _mask_hash(positions: tuple[tuple[int, int], ...]) -> str:
    return hashlib.sha256(repr(positions).encode()).hexdigest()


def _target_positions(positions: tuple[tuple[int, int], ...], regime: str) -> set[tuple[int, int]]:
    if regime == "random":
        return set()
    center = (SIZE - 1) / 2
    radii = [math.hypot(y - center, x - center) / (SIZE / 2) for y, x in positions]
    if regime == "center":
        candidates = [i for i, r in enumerate(radii) if r <= 0.25]
    else:
        candidates = [i for i, r in enumerate(radii) if 0.45 <= r <= 0.65]
    # Occupancy generation reserves ten target-stratum points. In the coupled
    # view, class A receives all ten as A and class B receives them as B; the
    # counterpart labels are complements, preserving A:B = 10:10 per sample.
    if len(candidates) < 10:
        candidates = sorted(range(len(positions)), key=lambda i: (radii[i], positions[i]))
    else:
        candidates = sorted(candidates, key=lambda i: positions[i])
    return {positions[i] for i in candidates[:10]}


def _labels(positions: tuple[tuple[int, int], ...], *, seed: int, group_id: str,
            class_id: str, regime: str, policy: str) -> tuple[dict[tuple[int, int], int], int]:
    if policy not in LABEL_POLICIES:
        raise ValueError(f"unknown label policy: {policy}")
    ordered = sorted(positions)
    if regime == "random":
        rng = random.Random(_seed(seed, group_id, "coupled-random-labels"))
        rng.shuffle(ordered)
        coupled_a = set(ordered[:10])
    else:
        coupled_a = _target_positions(positions, regime)
    if policy == "spatial_coupled":
        selected_a = coupled_a
        retries = 0
    else:
        policy_rng = random.Random(_seed(seed, group_id, policy + "-permutation"))
        # Shuffle the coupled label vector for marginal_shuffle; the independent
        # control draws a uniform 10-of-20 assignment directly.
        if policy == "marginal_shuffle":
            label_vector = [KNOWN_A if p in coupled_a else KNOWN_B for p in ordered]
            policy_rng.shuffle(label_vector)
            selected_a = {p for p, label in zip(ordered, label_vector) if label == KNOWN_A}
        else:
            shuffled = list(positions)
            policy_rng.shuffle(shuffled)
            selected_a = set(shuffled[:10])
        retries = 0
        if policy in ("marginal_shuffle", "position_independent_random"):
            while selected_a == coupled_a and retries < 100:
                if policy == "marginal_shuffle":
                    policy_rng.shuffle(label_vector)
                    selected_a = {p for p, label in zip(ordered, label_vector) if label == KNOWN_A}
                else:
                    policy_rng.shuffle(shuffled)
                    selected_a = set(shuffled[:10])
                retries += 1
            if selected_a == coupled_a:
                raise RuntimeError(f"label permutation retry limit reached for {group_id}")
    # Counterpart labels are strict complements under every policy.
    if class_id == "B":
        selected_a = set(positions) - selected_a
    labels = {p: (KNOWN_A if p in selected_a else KNOWN_B) for p in positions}
    return labels, retries


@dataclass(frozen=True)
class Sample:
    sample_id: str
    source_id: str
    generator_version: str
    master_seed: int
    lineage_group_id: str
    split: str
    wafer_class: str
    regime: str
    label_policy: str
    noise_error_rate: float
    reject_rate: float
    inspected_die_mask: np.ndarray
    fail_mask: np.ndarray
    known_label_map: np.ndarray
    reject_mask: np.ndarray
    raw_array: np.ndarray
    object_id_array: np.ndarray
    yield_array: np.ndarray
    label_maps_by_policy: dict[str, np.ndarray]
    object_id_arrays_by_policy: dict[str, np.ndarray]
    metadata: dict[str, Any]


def generate(seed: int = 42, *, error_rate: float = 0.0, reject_rate: float = 0.0) -> list[Sample]:
    """Return 24 paired samples for one seed, without writing files or using external assets."""
    if seed not in SEEDS:
        raise ValueError(f"seed must be one of {SEEDS}")
    if error_rate not in (0.0, 0.2) or reject_rate not in (0.0, 0.2):
        raise ValueError("error_rate and reject_rate must each be 0.0 or 0.2")
    samples: list[Sample] = []
    inspected = np.zeros((SIZE, SIZE), dtype=np.bool_)
    yy, xx = np.ogrid[:SIZE, :SIZE]
    inspected[((yy - 95.5) ** 2 + (xx - 95.5) ** 2) <= 95.5 ** 2] = True
    for regime in REGIMES:
        for split in SPLITS:
            for replicate in range(2):
                group_id = f"s{seed}-{regime}-{split}-g{replicate}"
                positions = _die_positions(seed, group_id, regime)
                pos_hash = _mask_hash(positions)
                for class_id in ("A", "B"):
                    sample_id = f"{group_id}-{class_id}"
                    fail = np.zeros((SIZE, SIZE), dtype=np.bool_)
                    for y, x in positions:
                        fail[y, x] = True
                    policy_labels: dict[str, dict[tuple[int, int], int]] = {}
                    shuffle_retry_counts: dict[str, int] = {}
                    for policy in LABEL_POLICIES:
                        policy_labels[policy], shuffle_retry_counts[policy] = _labels(
                            positions, seed=seed, group_id=group_id, class_id=class_id,
                            regime=regime, policy=policy)
                    # Error/reject draws are shared by group counterpart and all arms.
                    noise_rng = random.Random(_seed(seed, group_id, "noise-reject"))
                    coords = list(positions)
                    noise_rng.shuffle(coords)
                    n_reject = round(reject_rate * DEFECT_COUNT)
                    rejected = set(coords[:n_reject])
                    eligible = [p for p in positions if p not in rejected]
                    n_flip = round(error_rate * DEFECT_COUNT)
                    flipped = set(noise_rng.sample(eligible, n_flip)) if n_flip else set()
                    reject_mask = np.zeros((SIZE, SIZE), dtype=np.bool_)
                    id_maps: dict[str, np.ndarray] = {}
                    known_maps: dict[str, np.ndarray] = {}
                    for policy, labels in policy_labels.items():
                        id_map = np.full((SIZE, SIZE), OBJECT_ID_PALETTE["background"], dtype=np.uint8)
                        known = np.zeros((SIZE, SIZE), dtype=np.uint8)
                        for p in positions:
                            value = labels[p]
                            if p in flipped:
                                value = KNOWN_B if value == KNOWN_A else KNOWN_A
                            if p in rejected:
                                id_map[p] = UNKNOWN_REJECT
                            else:
                                known[p] = value
                                id_map[p] = value
                        id_maps[policy] = id_map
                        known_maps[policy] = known
                    for p in positions:
                        if p in rejected:
                            reject_mask[p] = True
                    raw = fail.astype(np.uint8)
                    yield_arr = np.where(inspected, 1, 255).astype(np.uint8)
                    yield_arr[fail] = 0
                    samples.append(Sample(
                        sample_id=sample_id, source_id=SOURCE_ID, generator_version=VERSION,
                        master_seed=seed, lineage_group_id=group_id, split=split,
                        wafer_class=class_id, regime=regime, label_policy="spatial_coupled",
                        noise_error_rate=error_rate, reject_rate=reject_rate,
                        inspected_die_mask=inspected.copy(), fail_mask=fail,
                        known_label_map=known_maps["spatial_coupled"], reject_mask=reject_mask,
                        raw_array=raw, object_id_array=id_maps["spatial_coupled"], yield_array=yield_arr,
                        label_maps_by_policy=known_maps, object_id_arrays_by_policy=id_maps,
                        metadata={
                            "mask_hash": pos_hash, "positions_yx": positions,
                            "shuffle_retries_by_policy": shuffle_retry_counts,
                            "noise_rng_seed": _seed(seed, group_id, "noise-reject"),
                            "rejected_coordinates_yx": tuple(sorted(rejected)),
                            "flipped_coordinates_yx": tuple(sorted(flipped)),
                            "palette": dict(OBJECT_ID_PALETTE),
                            "leakage_note": CLASS_LEAKAGE_NOTE,
                            "claim_limit": "synthetic generator output; no real CNN or yield claim",
                            "target_definition": "gallery relevance is same (wafer_class, regime), across distinct lineage groups",
                            "split_rule": "lineage group assigned to one split before label views; gallery/query groups disjoint",
                            "policy_note": (
                                "spatial_coupled: for center/ring, class A assigns A to all 10 target defects and B to all 10 outside, "
                                "class B is the exact complement; random regime uses a position-independent paired permutation. "
                                "marginal_shuffle: seed-paired within-wafer permutation of the coupled A positions, redraw if identical, "
                                "then class B is the complement. position_independent_random: independent uniform 10-of-20 assignment, "
                                "redraw if identical to coupled, then class B is the complement. All are views of the same mask."
                            ),
                        },
                    ))
    validate(samples)
    return samples


def validate(samples: list[Sample]) -> None:
    """Enforce cohort size, paired lineage, mask consistency, and split isolation."""
    if len(samples) != 24:
        raise ValueError(f"expected 24 samples, got {len(samples)}")
    groups: dict[str, list[Sample]] = {}
    for s in samples:
        groups.setdefault(s.lineage_group_id, []).append(s)
        if s.fail_mask.shape != (SIZE, SIZE) or s.raw_array.shape != (SIZE, SIZE):
            raise ValueError("unexpected array shape")
        if np.any(s.fail_mask & ~s.inspected_die_mask):
            raise ValueError("fail outside inspected area")
        if int(s.fail_mask.sum()) != DEFECT_COUNT:
            raise ValueError("wrong fail count")
        if not np.array_equal(s.raw_array.astype(bool), s.fail_mask):
            raise ValueError("raw representation does not match fail mask")
        if np.any(s.reject_mask & (s.known_label_map != 0)):
            raise ValueError("rejected labels must remain unknown")
    for gid, pair in groups.items():
        if len(pair) != 2 or {s.wafer_class for s in pair} != {"A", "B"}:
            raise ValueError(f"lineage group must contain A/B counterparts: {gid}")
        a, b = sorted(pair, key=lambda s: s.wafer_class)
        if a.split != b.split or a.regime != b.regime:
            raise ValueError("counterparts crossed split/regime")
        if a.metadata["mask_hash"] != b.metadata["mask_hash"]:
            raise ValueError("counterpart occupancy masks differ")
    group_splits: dict[str, set[str]] = {}
    for s in samples:
        group_splits.setdefault(s.lineage_group_id, set()).add(s.split)
    if any(len(v) != 1 for v in group_splits.values()):
        raise ValueError("lineage group crosses gallery/query split")
    if len({s.sample_id for s in samples}) != len(samples):
        raise ValueError("duplicate sample IDs")


def build_dataset() -> dict[int, list[Sample]]:
    """Generate all five planned seeds; each seed remains independently addressable."""
    return {seed: generate(seed) for seed in SEEDS}


if __name__ == "__main__":
    data = build_dataset()
    print({"source_id": SOURCE_ID, "version": VERSION,
           "seed_counts": {seed: len(items) for seed, items in data.items()},
           "total_samples": sum(map(len, data.values())),
           "interpretation": "synthetic fixtures only; no model or performance claim"})
