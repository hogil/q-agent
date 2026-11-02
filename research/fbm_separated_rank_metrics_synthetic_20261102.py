"""Synthetic score-only ranking metrics for the preregistered FBM roster.

Blind-ID hashing and encoder metadata isolation are caller assertions; this
module cannot establish either property. It does not infer family or seed.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence, Set
from typing import Any


RELEVANCE_NAMES = ("class_only", "position_only", "joint")


def _expected_hit_at_k(scores: Mapping[str, float], relevant: Set[str], k: int) -> float:
    """Hit probability under uniform random ordering within a boundary tie."""
    ranked_scores = sorted(scores.values(), reverse=True)
    threshold = ranked_scores[k - 1]
    above = {key for key, score in scores.items() if score > threshold}
    tied = {key for key, score in scores.items() if score == threshold}
    slots = k - len(above)
    rel_tied = len(tied & relevant)
    if above & relevant:
        return 1.0
    if rel_tied == 0:
        return 0.0
    # Probability that a uniform size-slots subset of the tied group includes
    # at least one relevant item: 1 - choose(nonrelevant, slots)/choose(total, slots).
    nonrel = len(tied) - rel_tied
    if slots > nonrel:
        return 1.0
    miss = 1.0
    for i in range(slots):
        miss *= (nonrel - i) / (len(tied) - i)
    return 1.0 - miss


def score_separated_rank_metrics(
    *,
    scores: Mapping[str, float],
    relevance: Mapping[str, Set[str]],
    schedule_id: str,
    asserted_class_label_free_blind_ids: bool,
    asserted_encoder_metadata_isolated: bool,
) -> dict[str, Any]:
    """Compute ranking metrics for the same 12 candidates under 3 relevance sets.

    Candidates are ordered by descending finite score, then SHA256 of
    ``schedule_id|blind_id``. Both assertions are caller supplied and are not
    independently verified here.
    """
    if asserted_class_label_free_blind_ids is not True:
        raise ValueError("caller must assert candidate IDs are class-label-free")
    if asserted_encoder_metadata_isolated is not True:
        raise ValueError("caller must assert encoder metadata isolation")
    if not isinstance(schedule_id, str) or not schedule_id:
        raise ValueError("schedule_id must be a non-empty string")
    if not isinstance(scores, Mapping) or len(scores) != 12:
        raise ValueError("scores must contain exactly 12 candidate IDs")
    ids = list(scores)
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != 12:
        raise ValueError("candidate IDs must be 12 unique non-empty strings")
    for score in scores.values():
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("all scores must be finite numbers")
    if set(relevance) != set(RELEVANCE_NAMES):
        raise ValueError("relevance must define class_only, position_only, and joint")
    required_counts = {"class_only": 6, "position_only": 6, "joint": 3}
    normalized: dict[str, set[str]] = {}
    for name, expected in required_counts.items():
        members = relevance[name]
        if isinstance(members, (str, bytes)) or not isinstance(members, Set):
            raise ValueError(f"{name} relevance must be a set of candidate IDs")
        if len(members) != expected or not members <= set(ids):
            raise ValueError(f"{name} relevance must contain {expected} distinct candidate IDs")
        normalized[name] = set(members)
    if normalized["joint"] != normalized["class_only"] & normalized["position_only"]:
        raise ValueError("joint relevance must equal class_only intersect position_only")

    def tie_key(candidate_id: str) -> str:
        return hashlib.sha256(f"{schedule_id}|{candidate_id}".encode("utf-8")).hexdigest()

    ranked = sorted(ids, key=lambda x: (-scores[x], tie_key(x)))
    groups: dict[str, list[str]] = {}
    for candidate_id in ids:
        groups.setdefault(str(scores[candidate_id]), []).append(candidate_id)
    tie_groups = [sorted(group) for group in groups.values() if len(group) > 1]
    result: dict[str, Any] = {
        "ranking": ranked,
        "tie_groups": tie_groups,
        "tie_break": "sha256(schedule_id|blind_id); deterministic ordering; class-blindness is caller assertion",
        "assertions": {
            "class_label_free_blind_ids": True,
            "encoder_metadata_isolated": True,
            "verified_by_function": False,
        },
        "metrics": {},
    }
    for name, relevant in normalized.items():
        top = ranked[:3]
        hit = float(bool(set(top) & relevant))
        recall = len(set(top) & relevant) / len(relevant)
        reciprocal_rank = next((1.0 / (i + 1) for i, x in enumerate(ranked) if x in relevant), 0.0)
        dcg = sum((1.0 / math.log2(i + 2)) for i, x in enumerate(top) if x in relevant)
        ideal_n = min(3, len(relevant))
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_n))
        result["metrics"][name] = {
            "hit_at_3": hit,
            "expected_hit_at_3_uniform_boundary_tie": _expected_hit_at_k(scores, relevant, 3),
            "recall_at_3": recall,
            "mrr": reciprocal_rank,
            "ndcg_at_3": dcg / idcg,
        }
    return result
