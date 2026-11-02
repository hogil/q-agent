#!/usr/bin/env python3
"""Tiny controlled synthetic retrieval probe: defect pattern vs defect type.

This is not an FBM image model and does not claim production performance. The
object-ID/yield channel is an oracle synthetic annotation. ID comparison pools
semantic one-hot counts and yield rate, deliberately discarding wafer position.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

SEED = 20261030
SIZE = 32
DEFECTS = 12
PATTERNS = ("upper", "lower", "left", "right")
TYPES = ("A", "B", "UNKNOWN")
ID_VALUES = {"A": 0, "B": 1, "UNKNOWN": 2}
REPRESENTATIONS = ("raw_only", "oracle_id_yield_only", "raw_plus_id_late_fusion")


@dataclass(frozen=True)
class Wafer:
    asset_id: str
    split: str
    pattern: str
    defect_type: str
    defect_mask: np.ndarray
    chip_id_map: np.ndarray  # -1 means no defect; 0/1/2 are semantic A/B/UNKNOWN IDs.
    yield_mask: np.ndarray  # Independent array; True marks a failed chip.


def _make_wafer(asset_id: str, split: str, pattern: str, defect_type: str,
                seed: int) -> Wafer:
    rng = np.random.default_rng(seed)
    centers = {"upper": (8, 16), "lower": (23, 16),
               "left": (16, 8), "right": (16, 23)}
    cy, cx = centers[pattern]
    # Every type uses the same position generator for a given seed. Type never
    # controls location; the four broad pattern zones are only synthetic labels.
    points: set[tuple[int, int]] = set()
    while len(points) < DEFECTS:
        y = int(np.clip(round(rng.normal(cy, 2.0)), 0, SIZE - 1))
        x = int(np.clip(round(rng.normal(cx, 2.0)), 0, SIZE - 1))
        points.add((y, x))
    defect = np.zeros((SIZE, SIZE), dtype=np.bool_)
    for y, x in points:
        defect[y, x] = True
    ids = np.full((SIZE, SIZE), -1, dtype=np.int8)
    ids[defect] = ID_VALUES[defect_type]
    # Keep yield outcome as a separate explicit mask. This controlled probe
    # treats every annotated defect as a failed chip, including UNKNOWN IDs.
    yield_mask = defect.copy()
    return Wafer(asset_id, split, pattern, defect_type, defect, ids, yield_mask)


def build_dataset(seed: int = SEED, per_cell: int = 3) -> tuple[list[Wafer], list[Wafer]]:
    """Cross pattern/type labels; gallery and query get disjoint wafer seeds."""
    if per_cell < 1:
        raise ValueError("per_cell must be positive")
    gallery: list[Wafer] = []
    query: list[Wafer] = []
    for pi, pattern in enumerate(PATTERNS):
        for rep in range(per_cell):
            for split, target in (("gallery", gallery), ("query", query)):
                # Choose which independent location seed goes with each type by
                # a permutation generated without reading the type label.
                # This prevents a type-conditioned seed rule while avoiding
                # deliberately duplicated raw masks across different wafers.
                base = seed + pi * 100_000 + rep * 1_000 + (0 if split == "gallery" else 50_000)
                seeds = np.random.default_rng(base).permutation(
                    np.arange(base + 1, base + len(TYPES) + 1))
                for ti, defect_type in enumerate(TYPES):
                    wafer_seed = int(seeds[ti])
                    # Opaque, reproducible search metadata ID; semantic labels
                    # remain separate evaluation fields and are not features.
                    opaque = hashlib.sha256(f"{seed}|{split}|{wafer_seed}".encode("ascii")).hexdigest()
                    asset_id = f"{split}-{opaque}"
                    target.append(_make_wafer(asset_id, split, pattern, defect_type, wafer_seed))
    return gallery, query


def _raw_similarity(a: Wafer, b: Wafer) -> float:
    union = int(np.logical_or(a.defect_mask, b.defect_mask).sum())
    return float(np.logical_and(a.defect_mask, b.defect_mask).sum() / union) if union else 1.0


def _id_yield_features(w: Wafer) -> np.ndarray:
    # Semantic one-hot categories, pooled over positions. Never compare the
    # arbitrary numeric ID codes by magnitude or use chip coordinates here.
    one_hot_counts = np.array([np.count_nonzero(w.chip_id_map == ID_VALUES[k])
                               for k in TYPES], dtype=np.float64)
    one_hot_counts /= max(float(one_hot_counts.sum()), 1.0)
    yield_rate = np.array([float(w.yield_mask.mean())], dtype=np.float64)
    return np.concatenate((one_hot_counts, yield_rate))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _score(rep: str, q: Wafer, g: Wafer) -> float:
    raw = _raw_similarity(q, g)
    semantic = _cosine(_id_yield_features(q), _id_yield_features(g))
    if rep == "raw_only":
        return raw
    if rep == "oracle_id_yield_only":
        return semantic
    if rep == "raw_plus_id_late_fusion":
        return (raw + semantic) / 2.0
    raise ValueError(f"unknown representation: {rep}")


def _metrics(rows: list[dict[str, Any]], target: str) -> dict[str, Any]:
    correct1 = sum(bool(r["ranking"]) and r["ranking"][0][target] == r[f"query_{target}"] for r in rows)
    correct3 = sum(any(x[target] == r[f"query_{target}"] for x in r["ranking"][:3]) for r in rows)
    n = len(rows)
    expected1 = sum(r[f"expected_top1_{target}_hit"] for r in rows)
    expected3 = sum(r[f"expected_top3_{target}_hit"] for r in rows)
    return {"queries": n, "top1_correct": correct1, "top1_accuracy": correct1 / n if n else None,
            "top3_correct": correct3, "top3_accuracy": correct3 / n if n else None,
            "expected_top1_hit_rate": expected1 / n if n else None,
            "expected_top3_hit_rate": expected3 / n if n else None}


def _expected_hit_at_k(ranking: list[dict[str, Any]], target: str,
                       expected_label: str, k: int) -> float:
    """Expected hit if exact-score boundary ties are uniformly permuted.

    Group boundaries use exact Python float equality. Asset IDs and labels do
    not participate in ordering or the hypergeometric hit probability.
    """
    if k < 1:
        raise ValueError("k must be positive")
    ordered = sorted(ranking, key=lambda item: item["score"], reverse=True)
    selected = 0
    start = 0
    while start < len(ordered) and selected < k:
        score = ordered[start]["score"]
        end = start + 1
        while end < len(ordered) and ordered[end]["score"] == score:
            end += 1
        group = ordered[start:end]
        n_tied = len(group)
        positives = sum(item[target] == expected_label for item in group)
        remaining = k - selected
        if n_tied <= remaining:
            if positives:
                return 1.0
            selected += n_tied
            start = end
            continue
        # Boundary tie: sample `remaining` slots uniformly without replacement.
        no_hit = math.comb(n_tied - positives, remaining) / math.comb(n_tied, remaining)
        return 1.0 - no_hit
    return 0.0


def run_experiment(seed: int = SEED, per_cell: int = 3) -> dict[str, Any]:
    gallery, queries = build_dataset(seed, per_cell)
    if {w.asset_id for w in gallery} & {w.asset_id for w in queries}:
        raise RuntimeError("gallery/query wafer identity leakage")
    all_wafers = gallery + queries
    hashes = {w.asset_id: hashlib.sha256(np.packbits(w.defect_mask).tobytes()).hexdigest()
              for w in all_wafers}
    duplicate_raw_pairs = sum(hashes[a.asset_id] == hashes[b.asset_id]
                              for i, a in enumerate(all_wafers) for b in all_wafers[i + 1:])
    if duplicate_raw_pairs:
        raise RuntimeError("duplicate raw defect masks across distinct wafers")

    results: dict[str, Any] = {}
    for rep in REPRESENTATIONS:
        rows = []
        for q in queries:
            ranked = sorted(gallery, key=lambda g: (-_score(rep, q, g), g.asset_id))
            ranking = [{"asset_id": g.asset_id, "pattern": g.pattern,
                        "defect_type": g.defect_type,
                        "score": _score(rep, q, g)} for g in ranked]
            rows.append({"query_asset_id": q.asset_id, "query_pattern": q.pattern,
                         "query_defect_type": q.defect_type,
                         "expected_top1_pattern_hit": _expected_hit_at_k(ranking, "pattern", q.pattern, 1),
                         "expected_top3_pattern_hit": _expected_hit_at_k(ranking, "pattern", q.pattern, 3),
                         "expected_top1_defect_type_hit": _expected_hit_at_k(ranking, "defect_type", q.defect_type, 1),
                         "expected_top3_defect_type_hit": _expected_hit_at_k(ranking, "defect_type", q.defect_type, 3),
                         "ranking": ranking})
        results[rep] = {"queries": rows,
                        "pattern_metrics": _metrics(rows, "pattern"),
                        "defect_type_metrics": _metrics(rows, "defect_type")}

    # Confirm the spatial generator has no explicit type-conditioned seed and
    # report per-type mean row/column; these are diagnostics, not a significance test.
    type_positions = {}
    for defect_type in TYPES:
        coords = np.concatenate([np.argwhere(w.defect_mask) for w in all_wafers if w.defect_type == defect_type])
        type_positions[defect_type] = {"mean_row": float(coords[:, 0].mean()),
                                       "mean_col": float(coords[:, 1].mean()),
                                       "defect_sites": int(len(coords))}
    return {
        "status": "synthetic_controlled_probe_complete",
        "scope": "tiny CPU/Numpy synthetic retrieval; no image model or production data",
        "claims": {"real_wafer_performance": False, "cnn_prediction": False,
                   "technology_superiority": False},
        "oracle_annotation": "oracle synthetic chip IDs A/B/UNKNOWN and yield masks are ground-truth annotations, not model predictions; type retrieval is an oracle upper-bound/wiring sanity check, not performance evidence",
        "design": {"seed": seed, "size": [SIZE, SIZE], "patterns": list(PATTERNS),
                   "defect_types": list(TYPES), "per_pattern_type_split": per_cell,
                   "gallery_wafers": len(gallery), "query_wafers": len(queries),
                   "representations": list(REPRESENTATIONS),
                   "defect_type_controls_position": False,
                   "id_similarity": "semantic one-hot count histogram plus yield rate; chip coordinates pooled out",
                   "search_input_metadata": "full opaque asset IDs are carried for exclusion and deterministic tie-break only; IDs are not classifier features",
                   "tie_metrics": "original fixed-ID-order accuracy retained; expected top-k hit assumes uniform random selection at exact-float-score boundary ties, independent of ID/label order",
                   "unknown_id": "UNKNOWN is a proxy category for unidentified defects, not oracle knowledge of a specific unknown defect class",
                   "yield_mask_limitation": "yield_mask is a separate copy of defect_mask in this probe; its independent contribution is not evaluated"},
        "leakage_audit": {"gallery_query_asset_id_overlap": 0,
                          "duplicate_raw_mask_pairs_across_distinct_wafers": duplicate_raw_pairs,
                          "type_spatial_diagnostics": type_positions},
        "results": results,
        "limitations": ["Position bands are intentionally simple synthetic pattern labels.",
                        "Oracle ID/yield features expose synthetic labels and are not inferred by an FBM model; type retrieval is an upper-bound/wiring sanity check only.",
                        "UNKNOWN denotes an unidentified-category proxy, not a specific unknown defect class; yield and defect masks are equal, so yield adds no independent evidence.",
                        "The small fixed-seed probe is a functionality/control experiment, not statistical evidence."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--per-cell", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.seed, args.per_cell), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
