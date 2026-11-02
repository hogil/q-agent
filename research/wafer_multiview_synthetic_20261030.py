"""Synthetic chip diagnostic and wafer-pattern composition proof-of-concept.

Both analyses use a deliberately artificial generator, not fab data. The chip
task is a noisy-oracle diagnostic. The wafer task predicts an independent
upstream pattern condition from spatially aggregated views; results only check
recovery of effects injected here.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


SEED = 20261030
N_LOTS = 24
WAFERS_PER_LOT = 2
CHIPS_PER_WAFER = 48
N_CLASSES = 4
N_MEASURES = 4
ARMS = {
    "raw": ("raw",),
    "object_yield": ("object_yield",),
    "measure": ("measure",),
    "raw_object_yield": ("raw", "object_yield"),
    "raw_measure": ("raw", "measure"),
    "object_yield_measure": ("object_yield", "measure"),
    "all": ("raw", "object_yield", "measure"),
}


@dataclass
class Dataset:
    lot: np.ndarray
    wafer: np.ndarray
    x: np.ndarray
    y: np.ndarray
    radius: np.ndarray
    labels: np.ndarray
    observed: np.ndarray
    valid: np.ndarray
    raw: np.ndarray
    object_yield: np.ndarray
    measure: np.ndarray
    measure_available: np.ndarray
    post_cutoff_sentinel: np.ndarray
    join_error_sentinel: np.ndarray
    spatial_pattern: np.ndarray
    wafer_pattern: np.ndarray


def make_data(seed: int = SEED) -> Dataset:
    """Create fixed-layout lots, paired classes in a ring, and controlled faults."""
    rng = np.random.default_rng(seed)
    lots = np.repeat(np.arange(N_LOTS), WAFERS_PER_LOT)
    wafer_ids = np.repeat(np.arange(len(lots)), CHIPS_PER_WAFER)
    lot_ids = np.repeat(lots, CHIPS_PER_WAFER)
    n = len(wafer_ids)
    theta_base = np.arange(CHIPS_PER_WAFER) * (2 * np.pi / CHIPS_PER_WAFER)
    theta = np.tile(theta_base, len(lots)) + rng.normal(0, 0.035, n)
    radius = np.sqrt(rng.uniform(0.015, 0.985, n))
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)

    wafer_pattern = np.zeros(len(lots), dtype=int)
    # Every Lot gets two adjacent pattern classes; swap wafer order randomly.
    # This balances each split while preventing a one-to-one Lot/class mapping.
    for lot_id in range(N_LOTS):
        rows = np.flatnonzero(lots == lot_id)
        wafer_pattern[rows] = rng.permutation([lot_id % 4, (lot_id + 1) % 4])
    scenario = np.repeat(wafer_pattern, CHIPS_PER_WAFER)
    # Ring wafers share the same total-fail spatial distribution, but differ in
    # whether A or B dominates the ring. Control and neutral wafers have no ring
    # enrichment. This is an injected condition, not a real process mechanism.
    ring = (radius >= 0.48) & (radius <= 0.70)
    probabilities = np.full((n, N_CLASSES), 0.11)
    probabilities[:, 0] += 0.10
    probabilities[:, 1] += 0.10
    overlap = scenario == 0
    probabilities[overlap & ring, 0] += 0.22
    probabilities[(scenario == 1) & ring, 0] += 0.34
    probabilities[(scenario == 2) & ring, 1] += 0.34
    center = (scenario == 3) & (radius < 0.38)
    probabilities[center, 2] += 0.12
    # scenario 2 is spatially neutral. Labels are multi-hot and independent.
    labels = rng.random((n, N_CLASSES)) < probabilities
    spatial_pattern = np.where(scenario == 0, 1, np.where(scenario == 3, 2, 0))

    observed = rng.random(n) >= 0.045
    valid = observed & (rng.random(n) >= 0.025)
    # Raw FBM: 8 fail-bit channels, noisy but class-specific; masks remain separate.
    class_templates = np.array([
        [1, 1, 0, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 0, 0, 0, 0],
        [0, 0, 0, 0, 1, 1, 0, 0],
        [0, 0, 0, 0, 0, 0, 1, 1],
    ], dtype=float)
    raw = np.zeros((n, 8), dtype=float)
    for cls in range(N_CLASSES):
        raw += labels[:, cls, None] * class_templates[cls]
    raw = np.clip(raw + rng.normal(0, 0.32, raw.shape), 0, None)
    raw[~valid] = 0.0

    # Synthetic noisy oracle: object IDs are generated from latent labels through
    # a fixed confusion matrix, not produced by a trained upstream detector.
    confusion = np.array([
        [0.84, 0.08, 0.04, 0.04],
        [0.08, 0.84, 0.04, 0.04],
        [0.05, 0.05, 0.84, 0.06],
        [0.05, 0.05, 0.06, 0.84],
    ])
    obj = np.zeros_like(labels, dtype=float)
    for cls in range(N_CLASSES):
        present = labels[:, cls] & valid
        for i in np.flatnonzero(present):
            obj[i] += rng.multinomial(1, confusion[cls])
    # Yield is separate: 1=pass, 0=fail; invalid/missing use explicit status channel.
    yield_value = ((labels.sum(axis=1) == 0) & valid).astype(float)[:, None]
    status = np.column_stack([observed, valid]).astype(float)
    object_yield = np.column_stack([obj, yield_value, status])

    # Pre-cutoff measure has class-dependent, deliberately varied signal strength.
    strengths = np.array([2.4, 1.7, 0.0, 2.8])
    measure = rng.normal(0, 1, (n, N_MEASURES))
    for cls in range(N_CLASSES):
        measure[:, cls] += strengths[cls] * labels[:, cls]
    measure += rng.normal(0, 0.25, (len(lots), N_MEASURES))[lot_ids]
    measure_available = rng.random(n) >= 0.12
    measure[~measure_available] = 0.0
    # Sentinels are stored outside all eligible feature matrices by construction.
    post_cutoff = rng.normal(0, 1, n)
    join_error = rng.normal(0, 1, n)
    return Dataset(lot_ids, wafer_ids, x, y, radius, labels, observed, valid,
                   raw, object_yield, measure, measure_available, post_cutoff,
                   join_error, spatial_pattern, wafer_pattern)


def split_lots(data: Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fixed group split, with entire Lots assigned before model fitting."""
    lot_ids = np.unique(data.lot)
    train_lots, val_lots, test_lots = lot_ids[:14], lot_ids[14:19], lot_ids[19:]
    split = tuple(np.flatnonzero(np.isin(data.lot, groups))
                  for groups in (train_lots, val_lots, test_lots))
    assert not (set(train_lots) & set(val_lots) or set(train_lots) & set(test_lots)
                or set(val_lots) & set(test_lots))
    return split  # type: ignore[return-value]


def feature_matrix(data: Dataset, arm: str, position: bool) -> np.ndarray:
    pieces = [getattr(data, name) for name in ARMS[arm]]
    if position:
        pieces.append(np.column_stack([data.x, data.y, data.radius]))
    return np.column_stack(pieces)


def wafer_table(data: Dataset) -> tuple[list[int], np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray]:
    """Aggregate valid chip views into fixed radial-bin summaries by wafer."""
    bins = np.digitize(data.radius, [0.38, 0.48, 0.70, 0.84])
    view_arrays = {"raw": data.raw, "object_yield": data.object_yield, "measure": data.measure}
    eligible = data.valid & data.measure_available
    ids = []
    targets = []
    summaries = {name: [] for name in view_arrays}
    pooled = {name: [] for name in view_arrays}
    positions = []
    for wafer in np.unique(data.wafer):
        rows = np.flatnonzero((data.wafer == wafer) & eligible)
        if len(rows) == 0:
            continue
        ids.append(int(wafer))
        targets.append(int(data.wafer_pattern[wafer]))
        # Each view contributes per-bin channel means and bin coverage; no label
        # or scenario metadata enters these features.
        for name, values in view_arrays.items():
            pooled[name].append(np.concatenate([values[rows].mean(axis=0),
                                                np.array([len(rows) / CHIPS_PER_WAFER])]))
            chunks = []
            for b in range(5):
                rb = rows[bins[rows] == b]
                chunks.append(values[rb].mean(axis=0) if len(rb) else np.zeros(values.shape[1]))
                chunks.append(np.array([len(rb) / CHIPS_PER_WAFER]))
            summaries[name].append(np.concatenate(chunks))
        # Geometry-only per-bin occupancy. Never read outcome labels here.
        positions.append(np.array([np.mean(bins[rows] == b) for b in range(5)]))
    return (ids, np.asarray(targets), {k: np.asarray(v) for k, v in summaries.items()},
            {k: np.asarray(v) for k, v in pooled.items()}, np.asarray(positions))


def wafer_eval(data: Dataset, seed: int) -> dict:
    """Compare wafer-level pattern composition from common-coverage summaries."""
    wafer_ids, target, summaries, pooled, positions = wafer_table(data)
    wafer_ids = np.asarray(wafer_ids)
    # The dataset has two consecutive wafer IDs per Lot; group split follows the
    # same 14/5/5 Lot manifest as the chip task.
    lot = wafer_ids // WAFERS_PER_LOT
    train = np.flatnonzero(lot < 14)
    val = np.flatnonzero((lot >= 14) & (lot < 19))
    test = np.flatnonzero(lot >= 19)
    assert not (set(lot[train]) & set(lot[val]) or set(lot[train]) & set(lot[test])
                or set(lot[val]) & set(lot[test]))
    results = {}
    wafer_arms = {"position_only": (), **ARMS}
    for arm, names in wafer_arms.items():
        X = np.column_stack([pooled[name] for name in names]) if names else np.zeros((len(target), 0))
        for position in ((True,) if arm == "position_only" else (False, True)):
            xx = X
            # Position-present has per-bin occupancy appended, computed from
            # geometry only. Keep the same model and train/test wafer groups.
            if position:
                spatial_views = np.column_stack([summaries[name] for name in names]) if names else np.zeros((len(target), 0))
                xx = np.column_stack([X, spatial_views, positions]) if X.shape[1] else positions
            model = make_pipeline(StandardScaler(), LogisticRegression(
                C=0.35, max_iter=400, random_state=seed))
            model.fit(xx[train], target[train])
            pred = model.predict(xx[test])
            key = f"{arm}|position={'yes' if position else 'no'}"
            results[key] = {
                "macro_f1": float(f1_score(target[test], pred, average="macro", zero_division=0)),
                "n_test_wafers": int(len(test)),
                "per_pattern_recall": [float(np.mean(pred[target[test] == c] == c))
                    if np.any(target[test] == c) else None for c in range(4)],
            }
    scenarios = {}
    for cls, name in enumerate(("neutral", "A_ring", "B_ring", "control")):
        mask = target[test] == cls
        scenarios[name] = {"n_wafers": int(mask.sum()),
                           "per_wafer_mean_class_rates": np.mean([
                               data.labels[data.wafer == w].mean(axis=0)
                               for w in wafer_ids[test][mask]], axis=0).round(4).tolist()
                           if np.any(mask) else None}
    # Same geometry bins and common eligibility for all input arms.
    eligible = data.valid & data.measure_available
    eligible_by_wafer = np.array([np.count_nonzero(eligible & (data.wafer == w))
                                  for w in wafer_ids])
    return {"n_train_validation_test_wafers": [len(train), len(val), len(test)],
            "coverage_common_eligible_by_wafer": True,
            "coverage_chip_count_per_included_wafer": {
                "min": int(eligible_by_wafer.min()), "mean": float(eligible_by_wafer.mean()),
                "max": int(eligible_by_wafer.max()), "eligible_fraction_mean": float((eligible_by_wafer / CHIPS_PER_WAFER).mean())},
            "target_population": "All generated wafers; independent upstream-condition label assigned once per wafer. Feature summaries use valid-map AND pre-cutoff-Measure-available chips only.",
            "split_lots": {"train": list(range(14)), "validation": list(range(14, 19)),
                           "test": list(range(19, 24))},
            "test_scenarios": scenarios, "arms": results,
            "unit_of_evaluation": "wafer; no chip-level pseudo-replication",
            "position_factor": "off=whole-wafer channel means+coverage; on=the same pooled summary plus radial-bin channel means+coverage and bin occupancy",
            "dimension_limitation": "Position-on has more coefficients/features than position-off under the same single logistic model; equal parameter-count ablation is not implemented."}


def run(seed: int = SEED) -> dict:
    data = make_data(seed)
    train, val, test = split_lots(data)
    # Common eligibility ensures every arm and position condition sees identical rows.
    eligible = data.valid & data.measure_available
    train, val, test = [idx[eligible[idx]] for idx in (train, val, test)]
    y_train, y_val, y_test = data.labels[train], data.labels[val], data.labels[test]
    results = {}
    for arm in ARMS:
        for position in (False, True):
            X = feature_matrix(data, arm, position)
            predictions = np.zeros_like(y_test, dtype=int)
            for cls in range(N_CLASSES):
                model = make_pipeline(StandardScaler(), LogisticRegression(
                    C=0.35, max_iter=250, random_state=seed))
                model.fit(X[train], y_train[:, cls])
                # Fixed 0.5 threshold; validation is recorded, not used to tune.
                predictions[:, cls] = model.predict_proba(X[test])[:, 1] >= 0.5
            key = f"{arm}|position={'yes' if position else 'no'}"
            results[key] = {
                "macro_f1": float(f1_score(y_test, predictions, average="macro", zero_division=0)),
                "per_class_f1": f1_score(y_test, predictions, average=None, zero_division=0).round(4).tolist(),
                "n_test": int(len(test)),
                "n_validation": int(len(val)),
            }
    # Spatial-pattern diagnostic uses held-out labels, independent of model outputs.
    radial = data.radius[test]
    ring = (radial >= 0.48) & (radial <= 0.70)
    pattern = data.spatial_pattern[test]
    spatial = {}
    for name, mask in (("overlap_ring", pattern == 1), ("center", pattern == 2),
                       ("neutral", pattern == 0)):
        if np.any(mask):
            spatial[name] = {
                "class_rates_ring": data.labels[test][mask & ring].mean(axis=0).round(4).tolist()
                    if np.any(mask & ring) else None,
                "class_rates_elsewhere": data.labels[test][mask & ~ring].mean(axis=0).round(4).tolist()
                    if np.any(mask & ~ring) else None,
                "n": int(mask.sum()),
            }
    return {
        "seed": seed,
        "generator": "synthetic-v2",
        "split_lots": {"train": 14, "validation": 5, "test": 5},
        "eligible_counts": {"train": len(train), "validation": len(val), "test": len(test)},
        "coverage": {
            "valid_map_fraction": float(data.valid.mean()),
            "measure_available_fraction": float(data.measure_available.mean()),
            "common_eligible_fraction": float((data.valid & data.measure_available).mean()),
            "excluded_invalid_or_missing_measure": int((~(data.valid & data.measure_available)).sum()),
        },
        "coverage_limitation": "Common eligible subset excludes invalid-map or missing-Measure chips; this is not a missingness robustness comparison.",
        "arms": results,
        "chip_noisy_oracle_diagnostic": spatial,
        "wafer_pattern_composition": wafer_eval(data, seed),
        "checks": self_check(data, train, val, test),
        "leakage_limitation": "Synthetic sentinels are held outside feature arrays; this only checks code wiring, not real join/cutoff guards.",
        "interpretation": "Synthetic generator recovery only; object IDs are noisy-oracle labels. No fab-performance, data-contract, or novelty claim.",
    }


def self_check(data: Dataset, train: np.ndarray, val: np.ndarray, test: np.ndarray) -> dict:
    # Split disjointness and intended exclusion of invalid/missing Measure rows.
    assert not (set(data.lot[train]) & set(data.lot[val]))
    assert not (set(data.lot[train]) & set(data.lot[test]))
    assert not (set(data.lot[val]) & set(data.lot[test]))
    assert np.all(data.valid[np.concatenate([train, val, test])])
    assert np.all(data.measure_available[np.concatenate([train, val, test])])
    # Canary mutations cannot affect the feature matrix (prevents sentinel leakage).
    base = feature_matrix(data, "all", True)
    changed = Dataset(**{**data.__dict__,
                         "post_cutoff_sentinel": data.post_cutoff_sentinel + 1000,
                         "join_error_sentinel": data.join_error_sentinel - 1000})
    assert np.array_equal(base, feature_matrix(changed, "all", True))
    # Overlapping class labels exist, including cells with both A and B.
    assert np.any(data.labels[:, 0] & data.labels[:, 1] & (data.spatial_pattern == 1))
    # Status fields distinguish missing and invalid from pass/fail values.
    assert data.object_yield.shape[1] == N_CLASSES + 3
    # Each pattern condition is represented in each locked Lot split, while
    # wafer labels remain a separate array from all model input arrays.
    wafer_lots = np.arange(len(data.wafer_pattern)) // WAFERS_PER_LOT
    for lo, hi in ((0, 14), (14, 19), (19, 24)):
        assert set(data.wafer_pattern[(wafer_lots >= lo) & (wafer_lots < hi)]) == {0, 1, 2, 3}
    altered_truth = Dataset(**{**data.__dict__,
                               "labels": np.logical_not(data.labels),
                               "spatial_pattern": np.roll(data.spatial_pattern, 1),
                               "wafer_pattern": np.roll(data.wafer_pattern, 1)})
    ids_base, target_base, summaries_base, pooled_base, position_base = wafer_table(data)
    ids_alt, target_alt, summaries_alt, pooled_alt, position_alt = wafer_table(altered_truth)
    assert ids_base == ids_alt
    assert np.array_equal(position_base, position_alt)
    assert summaries_base.keys() == summaries_alt.keys()
    assert pooled_base.keys() == pooled_alt.keys()
    assert all(np.array_equal(summaries_base[k], summaries_alt[k]) for k in summaries_base)
    assert all(np.array_equal(pooled_base[k], pooled_alt[k]) for k in pooled_base)
    # Labels are the target, so the target table should change under this mutation.
    assert not np.array_equal(target_base, target_alt)
    for arm in ARMS:
        assert np.array_equal(feature_matrix(data, arm, True),
                              feature_matrix(altered_truth, arm, True))
    return {"lot_group_split": True, "common_eligibility": True,
            "sentinels_excluded_from_feature_arrays": True,
            "overlap_and_status_controls": True,
            "wafer_pattern_labels_separate_and_split_balanced": True,
            "all_wafer_input_summaries_independent_of_truth_labels": True,
            "position_and_chip_features_independent_of_truth_labels": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    print(json.dumps(run(args.seed), indent=2))


if __name__ == "__main__":
    main()
