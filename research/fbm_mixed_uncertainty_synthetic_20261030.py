#!/usr/bin/env python3
"""Controlled mixed FBM retrieval with explicitly simulated uncertain IDs.

CPU-only synthetic experiment. Classifier scores are simulated inputs, not
measurements or predictions from a real CNN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

SEED = 20261030
SIZE = 32
TYPES = ("A", "B", "UNKNOWN")
REPRESENTATIONS = ("raw", "hard_semantic", "soft_semantic", "raw_plus_hard", "raw_plus_soft")


@dataclass(frozen=True)
class Wafer:
    asset_id: str
    split: str
    pattern: str
    truth: np.ndarray  # 0 absent, 1 A, 2 B, 3 unidentified proxy, 4 unrelated failure
    fail_mask: np.ndarray
    observed: np.ndarray
    passed: np.ndarray
    scores: np.ndarray  # per-site simulated A/B probabilities; UNKNOWN never predicted


def _wafer(seed: int, asset_id: str, split: str, pattern: str, error_rate: float,
           unknown_false_accept_rate: float, unrelated_rate: float = .2) -> Wafer:
    rng = np.random.default_rng(seed)
    # Position labels are sampled independently of site semantic labels.
    centers = ((5, 16), (26, 16), (16, 5), (16, 26))
    cy, cx = centers[("upper", "lower", "left", "right").index(pattern)]
    positions: set[tuple[int, int]] = set()
    while len(positions) < 15:
        positions.add((int(np.clip(round(rng.normal(cy, 2.7)), 0, SIZE-1)),
                       int(np.clip(round(rng.normal(cx, 2.7)), 0, SIZE-1))))
    truth = np.zeros((SIZE, SIZE), dtype=np.int8)
    for y, x in positions:
        u = rng.random()
        truth[y, x] = 4 if u < unrelated_rate else (3 if u < unrelated_rate + .25 else (1 if rng.random() < .5 else 2))
    # Some failed sites are unobserved; observed pass sites are distinct from missing.
    observed = np.ones((SIZE, SIZE), dtype=np.bool_)
    observed[rng.random((SIZE, SIZE)) < .04] = False
    failed = truth > 0
    passed = observed & ~failed
    scores = np.full((SIZE, SIZE, 2), np.nan, dtype=np.float32)
    for y, x in zip(*np.where(observed & (truth > 0))):
        known = truth[y, x] in (1, 2)
        if known:
            cls = int(truth[y, x] - 1)
            wrong = rng.random() < error_rate
            # Correct and erroneous confidence ranges overlap so accepted
            # errors can occur at the default threshold.
            confidence = float(rng.uniform(.68, .99))
            pred = (1-cls) if wrong else cls
        else:
            false_accept = rng.random() < unknown_false_accept_rate
            confidence = float(rng.uniform(.68, .99) if false_accept else rng.uniform(.50, .82))
            pred = int(rng.integers(0, 2))
        scores[y, x, pred] = confidence
        scores[y, x, 1-pred] = 1-confidence
    return Wafer(asset_id, split, pattern, truth, truth > 0, observed, passed, scores)


def build_dataset(seed: int = SEED, per_pattern: int = 8, error_rate: float = .2,
                  abstain_threshold: float = .85,
                  unknown_high_confidence_mixture_rate: float = .2) -> tuple[list[Wafer], list[Wafer]]:
    if (isinstance(per_pattern, bool) or not isinstance(per_pattern, int) or not 1 <= per_pattern <= 100
            or isinstance(seed, bool) or not isinstance(seed, int)
            or not 0 <= error_rate <= 1 or not .5 <= abstain_threshold <= 1
            or not 0 <= unknown_high_confidence_mixture_rate <= 1):
        raise ValueError("invalid dataset or classifier parameters")
    out: dict[str, list[Wafer]] = {"gallery": [], "query": []}
    for pi, pattern in enumerate(("upper", "lower", "left", "right")):
        for n in range(per_pattern):
            for split, offset in (("gallery", 0), ("query", 100000)):
                s = seed + pi*10000 + n*100 + offset
                aid = hashlib.sha256(f"{seed}|{split}|{s}".encode()).hexdigest()
                out[split].append(_wafer(s, f"{split}-{aid}", split, pattern, error_rate,
                                         unknown_high_confidence_mixture_rate))
    return out["gallery"], out["query"]


def _features(w: Wafer, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    # Return (type signature, coverage): signature is normalized only over
    # observed failures; coverage is separately compared with fixed 0.2 weight.
    hard = np.zeros(4, dtype=np.float64)  # predicted A, predicted B, threshold-rejected, score unavailable
    soft = np.zeros(4, dtype=np.float64)  # A/B proxy, unavailable; low confidence is not a hard class
    unresolved = w.observed & ~w.passed
    nfail = int(unresolved.sum())
    coverage = np.array([w.passed.sum(), nfail, (~w.observed).sum()], dtype=np.float64) / w.observed.size
    available = np.isfinite(w.scores).all(axis=2) & unresolved
    unavailable_count = int(np.count_nonzero(unresolved & ~available))
    hard[3] = unavailable_count
    soft[3] = unavailable_count
    for y, x in zip(*np.where(available)):
        a, b = map(float, w.scores[y, x])
        soft[:2] += np.array([a, b])
        if max(a, b) >= threshold:
            hard[0 if a > b else 1] += 1
        else:
            hard[2] += 1
    if nfail:
        hard /= nfail
        soft /= nfail
    return np.concatenate((hard, coverage)), np.concatenate((soft, coverage))


def _spatial_similarity(a: Wafer, b: Wafer) -> float | None:
    common = a.observed & b.observed
    if not common.any():
        return None
    afail, bfail = common & a.fail_mask, common & b.fail_mask
    union = int(np.logical_or(afail, bfail).sum())
    # Empty union carries no evidence about similarity of defect patterns.
    return float(np.logical_and(afail, bfail).sum() / union) if union else None


def _sim(a: Wafer, b: Wafer, rep: str, threshold: float) -> float | None:
    raw = _spatial_similarity(a, b)
    ah, ass = _features(a, threshold); bh, bss = _features(b, threshold)
    def cosine(x: np.ndarray, y: np.ndarray) -> float:
        x=x.ravel(); y=y.ravel(); d=np.linalg.norm(x)*np.linalg.norm(y)
        return float(np.dot(x,y)/d) if d else 0.
    def semantic(x: np.ndarray, y: np.ndarray) -> float:
        # [0:4] type/status signature, [4:7] pass/fail/missing coverage.
        sigx, sigy = x[:4], y[:4]
        type_score = cosine(sigx, sigy) if sigx.sum() and sigy.sum() else 0.0
        return .8 * type_score + .2 * cosine(x[4:], y[4:])
    semh, sems = semantic(ah,bh), semantic(ass,bss)
    if rep == "raw":
        return raw
    if rep == "hard_semantic":
        return semh
    if rep == "soft_semantic":
        return sems
    if raw is None:
        return None
    return {"raw_plus_hard":(raw+semh)/2,"raw_plus_soft":(raw+sems)/2}[rep]


def run_experiment(seed: int = SEED, per_pattern: int = 8, error_rate: float = .2,
                   abstain_threshold: float = .85,
                   unknown_high_confidence_mixture_rate: float = .2) -> dict[str, Any]:
    gallery, queries = build_dataset(seed, per_pattern, error_rate, abstain_threshold,
                                     unknown_high_confidence_mixture_rate)
    gallery_ids = [w.asset_id for w in gallery]
    query_ids = [w.asset_id for w in queries]
    id_overlap = len(set(gallery_ids) & set(query_ids))
    gallery_id_duplicates = len(gallery_ids) - len(set(gallery_ids))
    query_id_duplicates = len(query_ids) - len(set(query_ids))
    masks = [hashlib.sha256(np.packbits(w.observed & w.fail_mask).tobytes()).hexdigest()
             for w in gallery + queries]
    duplicate_mask_pairs = sum(count * (count - 1) // 2 for count in Counter(masks).values())
    rows: dict[str, list[dict[str, Any]]] = {r: [] for r in REPRESENTATIONS}
    for q in queries:
        for rep in REPRESENTATIONS:
            scored = [(g, _sim(q,g,rep,abstain_threshold)) for g in gallery]
            ranked = sorted(((g,s) for g,s in scored if s is not None), key=lambda pair: (-pair[1],pair[0].asset_id))
            if not ranked:
                continue
            qcomp = np.bincount(q.truth[q.truth > 0], minlength=5)[1:].astype(float)
            qcomp /= max(qcomp.sum(),1)
            top, top_score = ranked[0]
            spatial = _spatial_similarity(q, top)
            gcomp=np.bincount(top.truth[top.truth>0],minlength=5)[1:].astype(float); gcomp/=max(gcomp.sum(),1)
            rows[rep].append({"query_asset_id":q.asset_id,"top_asset_id":top.asset_id,
                "score":top_score,"truth_composition_l1":float(np.abs(qcomp-gcomp).sum()),
                "spatial_similarity":spatial})
    all_wafers = gallery + queries
    false_accepts = {"known_wrong": 0, "unknown_or_unrelated_as_known": 0, "accepted_known": 0,
                     "accepted_unknown_or_unrelated": 0}
    for w in all_wafers:
        for y, x in zip(*np.where(w.observed & w.fail_mask)):
            a, b = map(float, w.scores[y, x]); accepted = max(a,b) >= abstain_threshold
            if w.truth[y,x] in (1,2):
                false_accepts["accepted_known"] += int(accepted)
                false_accepts["known_wrong"] += int(accepted and ((a>b) != (w.truth[y,x] == 1)))
            else:
                false_accepts["accepted_unknown_or_unrelated"] += int(accepted)
                false_accepts["unknown_or_unrelated_as_known"] += int(accepted)
    return {"status":"synthetic_controlled_probe_complete","scope":"CPU NumPy synthetic retrieval only",
      "claims":{"real_measurement":False,"real_cnn_prediction":False,"performance_or_novelty_claim":False},
      "classifier_input":"Simulated noisy A/B scores for every observed failure. unknown_high_confidence_mixture_rate controls the mixture of higher-confidence unknown/unrelated scores; it is not an accept probability. Confidence thresholding determines simulated accepted false classifications, reported separately. Soft-mode A/B probabilities are similarity inputs only and do not assert a hard known-class assignment. No learned CNN is used.",
      "design":{"seed":seed,"size":[SIZE,SIZE],"gallery_wafers":len(gallery),"query_wafers":len(queries),"per_pattern":per_pattern,
        "error_rate":error_rate,"unknown_high_confidence_mixture_rate":unknown_high_confidence_mixture_rate,"abstain_threshold":abstain_threshold,"split":"independent wafer seeds, disjoint gallery/query IDs; per_pattern 1..100",
        "representations":list(REPRESENTATIONS),"semantic_pooling":"hard signature: A/B/threshold-rejected/score-unavailable; soft signature: unthresholded A/B proxy/score-unavailable; pass/fail/missing coverage compared separately at weight 0.2; no position retained","raw_spatial_target":"observed failures; IoU over common-observed sites only; no common coverage or empty fail union omitted as no defect-pattern evidence","soft_score_semantics":"unthresholded simulated A/B proxy, not calibrated and not a hard known-class assignment; score-unavailable is separate from low-confidence proxy and hard threshold rejection","truth_used_for_retrieval":False,"tie_handling":"deterministic opaque asset ID tie break; scores exposed"},
      "prediction_audit":false_accepts,
      "leakage_audit":{"gallery_query_asset_id_overlap":id_overlap,
                        "gallery_duplicate_asset_ids":gallery_id_duplicates,
                        "query_duplicate_asset_ids":query_id_duplicates,
                        "duplicate_observed_raw_mask_pairs":duplicate_mask_pairs},
      "results":{r:{"queries":v,"queries_with_valid_spatial_comparison":sum(x['spatial_similarity'] is not None for x in v),"mean_truth_composition_l1":float(np.mean([x['truth_composition_l1'] for x in v])) if v else None,
                     "mean_spatial_similarity":float(np.mean([x['spatial_similarity'] for x in v if x['spatial_similarity'] is not None])) if any(x['spatial_similarity'] is not None for x in v) else None} for r,v in rows.items()},
      "limitations":["All masks, positions, and A/B scores are synthetic; soft scores have no calibration claim.","truth determines synthetic fail_mask and passed masks, so independent yield effects are not tested.","Small controlled run is not evidence of real wafer retrieval performance."]}


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--seed',type=int,default=SEED)
    p.add_argument('--per-pattern',type=int,default=8); p.add_argument('--error-rate',type=float,default=.2)
    p.add_argument('--abstain-threshold',type=float,default=.85); p.add_argument('--unknown-high-confidence-mixture-rate',type=float,default=.2); a=p.parse_args()
    print(json.dumps(run_experiment(a.seed,a.per_pattern,a.error_rate,a.abstain_threshold,a.unknown_high_confidence_mixture_rate),indent=2,sort_keys=True))

if __name__ == '__main__': main()
