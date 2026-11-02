"""Fixed-cohort paired retrieval metrics for synthetic FBM samples only.

No encoder is loaded here. Callers must explicitly inject one. Outputs describe
synthetic generator fixtures and are not evidence about real wafers or models.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
from typing import Callable, Iterable

import numpy as np

from research.fbm_paired_factorial_synthetic_20261030 import LABEL_POLICIES, Sample

RRF_K = 60
ARMS = ("raw_only", "object_id_only", "yield_only", "object_id_yield", "raw_object_id_yield_rrf")
VIEW_BY_ARM = {
    "raw_only": ("raw",),
    "object_id_only": ("object_id",),
    "yield_only": ("yield",),
    "object_id_yield": ("object_id_yield",),
}


def _validate_cohort(samples: list[Sample], error_rate: float | None, reject_rate: float | None) -> tuple[list[Sample], list[Sample], int]:
    if not samples:
        raise ValueError("samples must not be empty")
    ids = [s.sample_id for s in samples]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate sample IDs")
    seed_values = {s.master_seed for s in samples}
    if len(seed_values) != 1:
        raise ValueError("evaluate exactly one master seed at a time")
    if error_rate is not None and any(s.noise_error_rate != error_rate for s in samples):
        raise ValueError("samples do not match requested error_rate condition")
    if reject_rate is not None and any(s.reject_rate != reject_rate for s in samples):
        raise ValueError("samples do not match requested reject_rate condition")
    if len({s.noise_error_rate for s in samples}) != 1 or len({s.reject_rate for s in samples}) != 1:
        raise ValueError("samples mix error/reject conditions")
    group_splits: dict[str, set[str]] = defaultdict(set)
    hashes_by_split: dict[str, set[str]] = defaultdict(set)
    for s in samples:
        group_splits[s.lineage_group_id].add(s.split)
        mask_hash = s.metadata.get("mask_hash")
        if not isinstance(mask_hash, str) or not mask_hash:
            raise ValueError(f"{s.sample_id}: missing mask hash")
        fail = np.asarray(s.fail_mask)
        if fail.shape != (192, 192) or fail.dtype.kind not in "buif" or not np.all(np.isfinite(fail)):
            raise ValueError(f"{s.sample_id}: invalid fail mask")
        positions = tuple(sorted((int(y), int(x)) for y, x in np.argwhere(fail != 0)))
        recomputed_hash = hashlib.sha256(repr(positions).encode()).hexdigest()
        if mask_hash != recomputed_hash:
            raise ValueError(f"{s.sample_id}: metadata mask hash disagrees with fail mask")
        hashes_by_split[s.split].add(recomputed_hash)
    if any(len(splits) != 1 for splits in group_splits.values()):
        raise ValueError("lineage group crosses gallery/query split")
    if hashes_by_split["gallery"] & hashes_by_split["query"]:
        raise ValueError("duplicate mask hash across gallery/query split")
    gallery = [s for s in samples if s.split == "gallery"]
    query = [s for s in samples if s.split == "query"]
    if len(gallery) != 12 or len(query) != 12:
        raise ValueError(f"expected exactly 12 gallery and 12 query samples, got {len(gallery)}/{len(query)}")
    if {s.split for s in samples} != {"gallery", "query"}:
        raise ValueError("split must be gallery/query")
    return sorted(query, key=lambda s: s.sample_id), sorted(gallery, key=lambda s: s.sample_id), next(iter(seed_values))


def _view_input(sample: Sample, view: str, policy: str) -> np.ndarray:
    if view == "raw":
        source = sample.raw_array
    elif view == "object_id":
        if policy not in sample.object_id_arrays_by_policy:
            raise ValueError(f"{sample.sample_id}: missing object-ID policy view {policy}")
        source = sample.object_id_arrays_by_policy[policy]
    elif view == "yield":
        source = sample.yield_array
    elif view == "object_id_yield":
        if policy not in sample.object_id_arrays_by_policy:
            raise ValueError(f"{sample.sample_id}: missing object-ID policy view {policy}")
        oid = sample.object_id_arrays_by_policy[policy]
        yld = sample.yield_array
        _validate_view_array(sample, "object_id", oid)
        _validate_view_array(sample, "yield", yld)
        source = np.stack((oid, yld), axis=-1)
    else:
        raise ValueError(f"unknown view: {view}")
    _validate_view_array(sample, view, source)
    return np.array(source, copy=True)


def _validate_view_array(sample: Sample, view: str, value: object) -> None:
    array = np.asarray(value)
    if array.shape != (192, 192) and not (view == "object_id_yield" and array.shape == (192, 192, 2)):
        raise ValueError(f"{sample.sample_id}/{view}: unexpected view array shape {array.shape}")
    if array.dtype.kind not in "buif" or not np.all(np.isfinite(array)):
        raise ValueError(f"{sample.sample_id}/{view}: view array must have numeric finite values")


def _vector(encoder: Callable[[np.ndarray, str], object], sample: Sample, view: str, policy: str) -> np.ndarray:
    encoder_input = _view_input(sample, view, policy)
    value = np.asarray(encoder(encoder_input, view), dtype=np.float64)
    if value.ndim != 1 or value.size == 0 or not np.all(np.isfinite(value)):
        raise ValueError(f"{sample.sample_id}/{view}: embedding must be a finite non-empty vector")
    norm = float(np.linalg.norm(value))
    if not np.isfinite(norm) or norm == 0:
        raise ValueError(f"{sample.sample_id}/{view}: embedding norm must be finite and non-zero")
    return value / norm


def _tie_key(seed: int, sample_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"fbm-tie-v1|{seed}|{sample_id}".encode("utf-8")).hexdigest()
    return digest, sample_id


def _ranks(query: Sample, gallery: list[Sample], vectors: dict[tuple[str, str], np.ndarray], view: str,
           seed: int) -> tuple[dict[str, int], dict[str, float]]:
    q = vectors[(query.sample_id, view)]
    scored = []
    for candidate in gallery:
        if candidate.lineage_group_id == query.lineage_group_id:
            continue
        g = vectors[(candidate.sample_id, view)]
        if g.shape != q.shape:
            raise ValueError(f"embedding dimension mismatch for {query.sample_id}/{candidate.sample_id}/{view}")
        score = float(np.dot(q, g))
        if not np.isfinite(score):
            raise ValueError("non-finite similarity score")
        scored.append((candidate, score))
    if len(scored) != 12:
        raise ValueError(f"{query.sample_id}/{view}: expected 12 candidates, got {len(scored)}")
    scored.sort(key=lambda row: (-row[1], *_tie_key(seed, row[0].sample_id)))
    ranks = {candidate.sample_id: rank for rank, (candidate, _) in enumerate(scored, 1)}
    scores = {candidate.sample_id: score for candidate, score in scored}
    return ranks, scores


def _tie_groups(ranks: dict[str, int], scores: dict[str, float], gallery_by_id: dict[str, Sample]) -> list[dict[str, object]]:
    score_groups: dict[float, list[str]] = defaultdict(list)
    for sample_id, score in scores.items():
        score_groups[score].append(sample_id)
    groups = []
    for score, sample_ids in score_groups.items():
        if len(sample_ids) < 2:
            continue
        ordered_ids = sorted(sample_ids, key=ranks.__getitem__)
        class_counts = {cls: sum(gallery_by_id[sid].wafer_class == cls for sid in ordered_ids) for cls in ("A", "B")}
        groups.append({"score": score, "candidate_count": len(ordered_ids), "candidate_ids": ordered_ids,
                       "wafer_class_counts": class_counts})
    return sorted(groups, key=lambda group: group["score"], reverse=True)


def evaluate(
    samples: Iterable[Sample],
    embedding_fn: Callable[[np.ndarray, str], object],
    *,
    label_policy: str,
    error_rate: float | None = None,
    reject_rate: float | None = None,
) -> dict[str, object]:
    """Evaluate one seed/condition with `embedding_fn(image_array, view) -> vector`.

    Encoder inputs contain only copied synthetic image arrays. External side
    channels or closure state in an injected callable cannot be audited here.
    """
    cohort = list(samples)
    if label_policy not in LABEL_POLICIES:
        raise ValueError(f"unknown label_policy: {label_policy}")
    query, gallery, seed = _validate_cohort(cohort, error_rate, reject_rate)
    if not callable(embedding_fn):
        raise ValueError("an explicit embedding_fn callable is required")
    views = ("raw", "object_id", "yield", "object_id_yield")
    vectors: dict[tuple[str, str], np.ndarray] = {}
    for sample in query + gallery:
        for view in views:
            vectors[(sample.sample_id, view)] = _vector(embedding_fn, sample, view, label_policy)
    dims = {view: {vectors[(s.sample_id, view)].size for s in query + gallery} for view in views}
    if any(len(x) != 1 for x in dims.values()):
        raise ValueError("embedding dimension mismatch within view")

    per_query = []
    tie_totals = {arm: {"query_count": len(query), "queries_with_ties": 0, "tie_group_count": 0,
                       "tied_candidate_count": 0, "tied_candidate_wafer_class_counts": {"A": 0, "B": 0}}
                  for arm in ARMS}
    gallery_by_id = {s.sample_id: s for s in gallery}
    arm_totals = {arm: {"hit_at_1": 0, "hit_at_3": 0, "recall_at_1": 0.0, "recall_at_3": 0.0, "reciprocal_rank": 0.0} for arm in ARMS}
    for q in query:
        rel = {g.sample_id for g in gallery if g.lineage_group_id != q.lineage_group_id and
               (g.wafer_class, g.regime) == (q.wafer_class, q.regime)}
        if len(rel) != 2:
            raise ValueError(f"{q.sample_id}: expected exactly 2 relevant candidates, got {len(rel)}")
        ranks_by_arm = {}
        scores_by_arm = {}
        for arm, arm_views in VIEW_BY_ARM.items():
            ranks_by_arm[arm], scores_by_arm[arm] = _ranks(q, gallery, vectors, arm_views[0], seed)
        raw_ranks, raw_scores = _ranks(q, gallery, vectors, "raw", seed)
        objyield_ranks, objyield_scores = _ranks(q, gallery, vectors, "object_id_yield", seed)
        rrf_scores = {g.sample_id: 1 / (RRF_K + raw_ranks[g.sample_id]) + 1 / (RRF_K + objyield_ranks[g.sample_id]) for g in gallery}
        order = sorted(gallery, key=lambda g: (-rrf_scores[g.sample_id], *_tie_key(seed, g.sample_id)))
        ranks_by_arm["raw_object_id_yield_rrf"] = {g.sample_id: i for i, g in enumerate(order, 1)}
        scores_by_arm["raw_object_id_yield_rrf"] = rrf_scores
        metrics = {}
        query_ties = {}
        for arm, ranks in ranks_by_arm.items():
            ordered_ids = sorted(ranks, key=ranks.get)
            relevant_ranks = [ranks[sid] for sid in rel]
            first = min(relevant_ranks)
            row = {"hit_at_1": int(first <= 1), "hit_at_3": int(first <= 3),
                   "recall_at_1": sum(rank <= 1 for rank in relevant_ranks) / 2,
                   "recall_at_3": sum(rank <= 3 for rank in relevant_ranks) / 2,
                   "reciprocal_rank": 1.0 / first,
                   "candidate_count": len(ranks), "candidate_ids": ordered_ids, "ranks": dict(ranks)}
            tie_groups = _tie_groups(ranks, scores_by_arm[arm], gallery_by_id)
            query_ties[arm] = {"score_tie_definition": "exact equality of finite cosine or RRF scores before deterministic tie-key ordering",
                               "score_tie_group_count": len(tie_groups), "tied_candidate_count": sum(g["candidate_count"] for g in tie_groups),
                               "tied_candidate_wafer_class_counts": {cls: sum(g["wafer_class_counts"][cls] for g in tie_groups) for cls in ("A", "B")},
                               "score_tie_groups": tie_groups}
            tie_totals[arm]["queries_with_ties"] += bool(tie_groups)
            tie_totals[arm]["tie_group_count"] += len(tie_groups)
            tie_totals[arm]["tied_candidate_count"] += query_ties[arm]["tied_candidate_count"]
            for cls in ("A", "B"):
                tie_totals[arm]["tied_candidate_wafer_class_counts"][cls] += query_ties[arm]["tied_candidate_wafer_class_counts"][cls]
            metrics[arm] = row
            for key in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank"):
                arm_totals[arm][key] += row[key]
        per_query.append({"query_id": q.sample_id, "query_group_id": q.lineage_group_id,
                          "wafer_class": q.wafer_class, "regime": q.regime,
                          "relevant_candidate_ids": sorted(rel), "arms": metrics, "tie_summary": query_ties})
    arm_means = {arm: {"n": len(query), "mean_hit_at_1": vals["hit_at_1"] / len(query),
                       "mean_hit_at_3": vals["hit_at_3"] / len(query),
                       "mean_recall_at_1": vals["recall_at_1"] / len(query),
                       "mean_recall_at_3": vals["recall_at_3"] / len(query),
                       "mean_reciprocal_rank": vals["reciprocal_rank"] / len(query)} for arm, vals in arm_totals.items()}
    paired = {}
    for arm in ("object_id_only", "yield_only", "object_id_yield", "raw_object_id_yield_rrf"):
        paired[arm] = {metric: arm_means[arm][f"mean_{metric}"] - arm_means["raw_only"][f"mean_{metric}"]
                       for metric in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank")}
    by_class_regime = {}
    class_confusion = {}
    for arm in ARMS:
        by_class_regime[arm] = {}
        class_confusion[arm] = {"A": {"A": 0, "B": 0}, "B": {"A": 0, "B": 0}}
        for cls in ("A", "B"):
            for regime in ("center", "ring", "random"):
                rows = [row for row in per_query if row["wafer_class"] == cls and row["regime"] == regime]
                by_class_regime[arm][f"{cls}/{regime}"] = {
                    "n": len(rows),
                    "mean_hit_at_1": sum(row["arms"][arm]["hit_at_1"] for row in rows) / len(rows),
                    "mean_hit_at_3": sum(row["arms"][arm]["hit_at_3"] for row in rows) / len(rows),
                    "mean_recall_at_1": sum(row["arms"][arm]["recall_at_1"] for row in rows) / len(rows),
                    "mean_recall_at_3": sum(row["arms"][arm]["recall_at_3"] for row in rows) / len(rows),
                    "mean_reciprocal_rank": sum(row["arms"][arm]["reciprocal_rank"] for row in rows) / len(rows),
                }
        for row in per_query:
            top_id = row["arms"][arm]["candidate_ids"][0]
            predicted = next(s.wafer_class for s in gallery if s.sample_id == top_id)
            class_confusion[arm][row["wafer_class"]][predicted] += 1
    return {"status": "synthetic_paired_evaluation", "seed": seed,
            "label_policy": label_policy, "error_rate": cohort[0].noise_error_rate, "reject_rate": cohort[0].reject_rate,
            "independent_unit": "master_seed", "query_count": len(query), "gallery_count": len(gallery),
            "query_rows_are_not_independent_replicates": True, "rrf_k": RRF_K,
            "tie_break": "descending similarity/RRF score, then SHA256('fbm-tie-v1|'+str(master_seed)+'|'+sample_id) ascending, then sample_id ascending",
            "arms": arm_means, "tie_summary_by_arm": tie_totals,
            "by_class_regime": by_class_regime, "top1_class_confusion": class_confusion,
            "paired_mean_differences_vs_raw": paired, "per_query": per_query,
            "interpretation_limit": "synthetic generator fixtures only; injected embeddings are not evidence of real CNN, wafer, ACL, or yield performance. Tie hashing does not prove label independence because sample_id itself encodes class and regime. External state or side channels inside an injected callable are not audited."}
