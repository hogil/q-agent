"""Handcrafted histogram baselines for the generated synthetic FBM roster.

This is a binary-proxy/oracle-class-map descriptor demo. It is not evidence for
position effects, generality, retrieval performance, or novelty. It does not
perform near-duplicate validation, five-group independence validation, or
encoder freeze. No training, encoder/model, or real data is used. Blind-ID
randomness and metadata isolation remain caller assertions.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

import numpy as np

from research.fbm_class_position_synthetic_generator_20261102 import (
    REGIMES, ROLES, Sample, generate,
)
from research.fbm_generated_roster_smoke_synthetic_20261102 import (
    FAMILY_COUNTS, SEED, _choose,
)
from research.fbm_separated_relevance_roster_synthetic_20261102 import (
    RosterSample, build_rosters, create_schedule_manifest,
)
from research.fbm_separated_rank_metrics_synthetic_20261102 import (
    score_separated_rank_metrics,
)

SCHEDULE_ID = "generated-descriptor-baseline-synthetic-20261102-v1"
GRID = 8
CELL = 192 // GRID
LIMITATION = (
    "Synthetic binary proxy, oracle class-map, and handcrafted descriptor demo only; "
    "not evidence for position effects, generality, retrieval performance, or novelty. "
    "Near-duplicate validation, five-group independence, and encoder freeze were not performed."
)


def _array(value: np.ndarray | bytes, *, allowed: set[int], label: str) -> np.ndarray:
    if isinstance(value, bytes):
        if len(value) != 192 * 192:
            raise ValueError(f"{label} bytes must encode a 192x192 uint8 array")
        array = np.frombuffer(value, dtype=np.uint8).reshape(192, 192)
    elif isinstance(value, np.ndarray):
        if value.shape != (192, 192) or value.dtype != np.uint8:
            raise ValueError(f"{label} must be a 192x192 uint8 array")
        array = value
    else:
        raise ValueError(f"{label} input must be an array or bytes")
    if not np.isin(array, list(allowed)).all():
        raise ValueError(f"{label} contains unsupported values")
    return array


def raw_binary_position_histogram(value: np.ndarray | bytes) -> np.ndarray:
    """Return an 8x8 spatial occupancy histogram from raw binary mask only."""
    array = _array(value, allowed={0, 1}, label="raw mask")
    return array.reshape(GRID, CELL, GRID, CELL).sum(axis=(1, 3), dtype=np.float64).ravel()


def oracle_class_position_histogram(value: np.ndarray | bytes) -> np.ndarray:
    """Return 2x8x8 class-label occupancy from an oracle ID+yield map only."""
    array = _array(value, allowed={0, 1, 2}, label="oracle map")
    if not np.any(array):
        raise ValueError("oracle map must contain at least one labeled pixel")
    maps = np.stack((array == 1, array == 2)).astype(np.uint8)
    return maps.reshape(2, GRID, CELL, GRID, CELL).sum(axis=(2, 4), dtype=np.float64).ravel()


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    left_norm, right_norm = float(np.linalg.norm(left)), float(np.linalg.norm(right))
    if not math.isfinite(left_norm) or not math.isfinite(right_norm) or left_norm == 0 or right_norm == 0:
        raise ValueError("descriptor cosine requires finite nonzero vectors")
    score = float(np.dot(left, right) / (left_norm * right_norm))
    if not math.isfinite(score):
        raise ValueError("descriptor cosine must be finite")
    return score


def _scores_for_query(
    query: Sample,
    candidate_ids: tuple[str, ...],
    by_id: dict[str, Sample],
    feature: Callable[[np.ndarray | bytes], np.ndarray],
    *,
    oracle: bool,
) -> dict[str, float]:
    query_input = query.id_maps[query.true_class] if oracle else query.raw_array
    query_feature = feature(query_input)
    scores = {}
    for candidate_id in candidate_ids:
        candidate = by_id[candidate_id]
        candidate_input = candidate.id_maps[candidate.true_class] if oracle else candidate.raw_array
        scores[candidate_id] = _cosine(query_feature, feature(candidate_input))
    return scores


def run_baseline(*, samples: list[Sample] | None = None) -> dict[str, Any]:
    cohort = samples if samples is not None else generate(SEED, family_counts=FAMILY_COUNTS)
    if len(cohort) != 66:
        raise ValueError(f"expected 66 generated samples, got {len(cohort)}")
    selected, _selection_audit = _choose(cohort)
    roster_samples = [RosterSample(
        blind_id=s.sample_id, family_id=s.family_id, split=s.role,
        true_class=s.true_class, position_stratum=s.regime,
    ) for s in selected]
    manifest = create_schedule_manifest(roster_samples, SCHEDULE_ID)
    rosters = build_rosters(roster_samples, SCHEDULE_ID, manifest)
    by_id = {s.sample_id: s for s in selected}
    samples_by_id = {s.blind_id: s for s in roster_samples}
    arms = {
        "raw_binary_position_histogram": (raw_binary_position_histogram, False),
        "oracle_class_position_histogram": (oracle_class_position_histogram, True),
    }
    per_query: dict[str, Any] = {}
    for query_id, roster in rosters.items():
        query = by_id[query_id]
        relevance = {name: set(roster[name]) for name in ("class_only", "position_only", "joint")}
        row = {"candidate_ids": list(roster["roster"]), "metrics": {}}
        for arm, (feature, oracle) in arms.items():
            scores = _scores_for_query(query, roster["roster"], by_id, feature, oracle=oracle)
            row["metrics"][arm] = score_separated_rank_metrics(
                scores=scores, relevance=relevance, schedule_id=SCHEDULE_ID,
                asserted_class_label_free_blind_ids=True,
                asserted_encoder_metadata_isolated=True,
            )
        if len(roster["roster"]) != 12 or len(relevance["class_only"]) != 6 or len(relevance["position_only"]) != 6 or len(relevance["joint"]) != 3:
            raise ValueError("unexpected balanced roster/relevance cardinality")
        per_query[query_id] = row
    if len(per_query) != 6:
        raise ValueError("expected six balanced queries")
    return {
        "status": "synthetic_handcrafted_descriptor_baseline_only",
        "limitation": LIMITATION,
        "generated_sample_count": len(cohort),
        "query_count": len(per_query),
        "same_query_candidate_comparison": True,
        "tie_break_and_id_blindness": "caller assertion; deterministic metrics tie-break hashes schedule_id|blind_id",
        "feature_inputs": "arrays/bytes only; no sample class, position, or ID metadata is passed to feature callables",
        "arms": list(arms),
        "per_query": per_query,
    }


if __name__ == "__main__":
    print(json.dumps(run_baseline(), sort_keys=True))
