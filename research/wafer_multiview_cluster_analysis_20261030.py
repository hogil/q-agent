"""Exploratory lot-cluster bootstrap for the controlled synthetic wafer study.

No raw fab records or actual site data are available. This script summarizes
only the saved synthetic generator outputs; it does not establish field performance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "var" / "research" / "wafer-controlled-20261030-v1"
LOW_FILE = "mixed_error_008_missing_005_012.json"
HIGH_FILE = "mixed_error_075_missing_005_012.json"
MANIFEST_FILE = "manifest.json"
GENERATOR_PATH = ROOT / "research" / "wafer_multiview_controlled_20261030.py"
WAFERS_PER_LOT = 2  # Generator definition: N_LOTS=48, WAFERS_PER_LOT=2.
BOOTSTRAP_REPETITIONS = 5000
BOOTSTRAP_SEED = 20261030


def load_condition(path: Path, expected_error: float) -> dict[int, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = {}
    for result in payload["seed_results"]:
        if result["scenario"] != "mixed" or result["parameters"]["object_error"] != expected_error:
            raise ValueError(f"unexpected condition in {path}")
        seed = int(result["seed"])
        if seed in records:
            raise ValueError(f"duplicate seed {seed} in {path}")
        records[seed] = result
    return records


def exact_count(value, label: str) -> int:
    number = float(value)
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"invalid non-integer/non-finite/negative count for {label}: {value}")
    return int(number)


def verify_generator_manifest(input_dir: Path) -> str:
    manifest = json.loads((input_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    declared = Path(manifest["script"]).resolve()
    expected = GENERATOR_PATH.resolve()
    if declared != expected:
        raise ValueError("FAIL CLOSED: manifest generator path differs from expected source")
    actual_hash = hashlib.sha256(declared.read_bytes()).hexdigest().upper()
    if actual_hash != str(manifest["script_sha256"]).upper():
        raise ValueError("FAIL CLOSED: generator SHA256 does not match manifest")
    return actual_hash


def wafer_class_rows(result: dict) -> dict[tuple, dict]:
    by_kind = result["spatial_null_and_mixed"]["wafer_class_spatial_rates"]["by_spatial_kind"]
    test_lots = {exact_count(x, "test lot id") for x in result["split_lots"]["test"]}
    if len(test_lots) != len(result["split_lots"]["test"]):
        raise ValueError("FAIL CLOSED: duplicate test lot id")
    rows = {}
    for spatial_kind, group in by_kind.items():
        for wafer in group["per_wafer"]:
            wid = int(wafer["wafer_id"])
            if wafer["spatial_kind"] != spatial_kind:
                raise ValueError("spatial_kind disagrees with its grouping")
            lot_id = wid // WAFERS_PER_LOT
            if lot_id not in test_lots:
                raise ValueError(f"FAIL CLOSED: wafer {wid} does not map to a test lot")
            for item in wafer["classes"]:
                cls = int(item["class_id"])
                regions = item["regions"]
                ring, outside = regions["ring"], regions["outside_ring"]
                # Eligibility has to be the same chip set in both conditions;
                # the stored counts are the available evidence for that check.
                denoms = (exact_count(ring["eligible_chips"], "ring eligible_chips"),
                          exact_count(outside["eligible_chips"], "outside eligible_chips"))
                truth = item["truth_ring_minus_outside"]
                error = item["absolute_error_object_vs_truth"]
                raw_counts = (exact_count(ring["truth_defect_events"], "ring truth events"),
                              exact_count(outside["truth_defect_events"], "outside truth events"),
                              float(ring["object_id_occurrences"]),
                              float(outside["object_id_occurrences"]))
                key = (lot_id, wid, cls, spatial_kind)
                if key in rows:
                    raise ValueError(f"FAIL CLOSED: duplicate wafer-class-spatial key {key}")
                rows[key] = {"lot_id": lot_id, "wafer_id": wid,
                             "class_id": cls, "spatial_kind": spatial_kind,
                             "denominators": denoms, "truth_delta": truth,
                             "mae": error, "raw_counts": raw_counts,
                             "truth_events": raw_counts[:2]}
    return rows


def finite_or_none(value):
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite metric")
    return value


def validate_and_pair(low: dict, high: dict) -> dict:
    if low["split_lots"]["test"] != high["split_lots"]["test"]:
        raise ValueError("FAIL CLOSED: low/high test lot splits differ")
    low_rows, high_rows = wafer_class_rows(low), wafer_class_rows(high)
    if low_rows.keys() != high_rows.keys():
        raise ValueError("FAIL CLOSED: low/high wafer-class-spatial keys differ")
    pairs = {}
    for key in low_rows:
        a, b = low_rows[key], high_rows[key]
        if a["denominators"] != b["denominators"]:
            raise ValueError(f"FAIL CLOSED: common eligibility differs at {key}")
        if a["truth_events"] != b["truth_events"] or a["truth_delta"] != b["truth_delta"]:
            raise ValueError(f"FAIL CLOSED: paired truth differs at {key}")
        if any(n < 0 for n in a["denominators"]):
            raise ValueError(f"negative denominator at {key}")
        # Zero denominators should make derived deltas and MAE missing.
        eligible = all(n > 0 for n in a["denominators"])
        for row in (a, b):
            truth, mae = finite_or_none(row["truth_delta"]), finite_or_none(row["mae"])
            raw = row["raw_counts"]
            if any(not math.isfinite(float(x)) or x < 0 for x in raw):
                raise ValueError(f"invalid event count at {key}")
            if eligible and (truth is None or mae is None):
                raise ValueError(f"missing metric despite nonzero denominators at {key}")
            if not eligible and (truth is not None or mae is not None):
                raise ValueError(f"metric present despite zero denominator at {key}")
            if mae is not None and mae < 0:
                raise ValueError(f"negative MAE at {key}")
            if eligible:
                n_ring, n_out = row["denominators"]
                truth_from_counts = raw[0] / n_ring - raw[1] / n_out
                object_from_counts = raw[2] / n_ring - raw[3] / n_out
                if not math.isclose(truth, truth_from_counts, rel_tol=1e-9, abs_tol=1e-12):
                    raise ValueError(f"truth delta/count inconsistency at {key}")
                if not math.isclose(mae, abs(object_from_counts - truth_from_counts),
                                    rel_tol=1e-9, abs_tol=1e-12):
                    raise ValueError(f"MAE/count inconsistency at {key}")
            row["truth_delta"], row["mae"] = truth, mae
        if eligible:
            pairs[key] = {**a, "low_mae": a["mae"], "high_mae": b["mae"],
                          "difference_high_minus_low": b["mae"] - a["mae"]}
    return pairs


def lot_bootstrap_ci(rows: list[dict], repetitions=BOOTSTRAP_REPETITIONS,
                     seed=BOOTSTRAP_SEED) -> dict:
    # Estimand: mean paired wafer-class MAE difference, with equal lot weight;
    # within-lot rows are retained together and averaged before lot aggregation.
    per_lot = defaultdict(list)
    for row in rows:
        per_lot[row["lot_id"]].append(row["difference_high_minus_low"])
    lot_values = [sum(v) / len(v) for _, v in sorted(per_lot.items())]
    if not lot_values:
        return {"paired_eligible": False, "n_lots": 0, "n_wafers": 0,
                "mean_difference": None, "ci_status": "no_paired_rows",
                "percentile_ci95": None,
                "repetitions": repetitions, "seed": seed}
    mean_difference = sum(lot_values) / len(lot_values)
    if len(lot_values) < 2:
        return {"paired_eligible": True, "n_lots": len(lot_values),
                "n_wafers": len({r["wafer_id"] for r in rows}),
                "mean_difference": mean_difference,
                "ci_status": "insufficient_lots", "percentile_ci95": None,
                "repetitions": repetitions, "seed": seed}
    rng = random.Random(seed)
    n = len(lot_values)
    draws = sorted(sum(lot_values[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(repetitions))
    return {"paired_eligible": True, "n_lots": n,
            "n_wafers": len({r["wafer_id"] for r in rows}),
            "mean_difference": mean_difference, "ci_status": "available",
            "percentile_ci95": [draws[int(.025 * repetitions)],
                                 draws[min(repetitions - 1, int(.975 * repetitions))]],
            "repetitions": repetitions, "seed": seed}


def analyze(input_dir: Path, repetitions=BOOTSTRAP_REPETITIONS,
            bootstrap_seed=BOOTSTRAP_SEED) -> dict:
    generator_sha256 = verify_generator_manifest(input_dir)
    low_path, high_path = input_dir / LOW_FILE, input_dir / HIGH_FILE
    input_hashes = {LOW_FILE: hashlib.sha256(low_path.read_bytes()).hexdigest(),
                    HIGH_FILE: hashlib.sha256(high_path.read_bytes()).hexdigest()}
    low = load_condition(low_path, .08)
    high = load_condition(high_path, .75)
    if low.keys() != high.keys():
        raise ValueError("FAIL CLOSED: seed sets differ between conditions")
    per_seed = {}
    for study_seed in sorted(low):
        paired = validate_and_pair(low[study_seed], high[study_seed])
        strata = defaultdict(list)
        for row in paired.values():
            strata[(row["spatial_kind"], row["class_id"])].append(row)
        per_seed[str(study_seed)] = {}
        for (kind, cls), rows in sorted(strata.items()):
            stat = lot_bootstrap_ci(rows, repetitions, bootstrap_seed + study_seed)
            stat["transform"] = "MAE=abs(object ring-minus-outside - truth ring-minus-outside); high_error minus low_error"
            per_seed[str(study_seed)][f"{kind}|class={cls}"] = stat
    return {"status": "exploratory synthetic output only; no raw fab/site data",
            "common_eligibility": "same keys and region-level eligible-chip counts checked; chip IDs are absent, so identity of eligible chip sets is unverified",
            "generator_sha256_verified_against_manifest": generator_sha256,
            "test_lot_validation": "low/high test lot arrays equal; every summarized wafer_id // 2 belongs to that seed's test lot set",
            "lot_mapping": "lot_id = wafer_id // 2 (generator WAFERS_PER_LOT=2)",
            "bootstrap_unit": "lot, equal weight per lot; paired differences within lot",
            "input_sha256": input_hashes,
            "input_integrity_limit": "Hashes identify the bytes read during this run; without trusted signed checksums or an immutable source, they do not prove source authenticity or pre-run integrity.",
            "seeds_are_independent_fab_worlds": False,
            "bootstrap_repetitions": repetitions, "bootstrap_seed_base": bootstrap_seed,
            "per_seed": per_seed}


def self_check() -> dict:
    rows = [
        {"lot_id": 0, "wafer_id": 0, "difference_high_minus_low": 2.0},
        {"lot_id": 0, "wafer_id": 1, "difference_high_minus_low": 4.0},
        {"lot_id": 1, "wafer_id": 2, "difference_high_minus_low": 8.0},
    ]
    got = lot_bootstrap_ci(rows, repetitions=200, seed=11)
    assert got["n_lots"] == 2 and got["n_wafers"] == 3
    assert got["mean_difference"] == 5.5  # equal lot weighting: (3 + 8)/2
    assert len(got["percentile_ci95"]) == 2
    single_lot = lot_bootstrap_ci(rows[:2], repetitions=200, seed=11)
    assert single_lot["mean_difference"] == 3.0
    assert single_lot["ci_status"] == "insufficient_lots" and single_lot["percentile_ci95"] is None

    def fixture(truth_events=(2, 1), object_events=(2, 1), duplicate=False):
        ring_n, outside_n = 4, 4
        truth_delta = truth_events[0] / ring_n - truth_events[1] / outside_n
        object_delta = object_events[0] / ring_n - object_events[1] / outside_n
        row = {"wafer_id": 0, "spatial_kind": "A_ring", "classes": []}
        item = {"class_id": 0,
                "regions": {"ring": {"eligible_chips": ring_n, "truth_defect_events": truth_events[0], "object_id_occurrences": object_events[0]},
                            "outside_ring": {"eligible_chips": outside_n, "truth_defect_events": truth_events[1], "object_id_occurrences": object_events[1]}},
                "truth_ring_minus_outside": truth_delta,
                "absolute_error_object_vs_truth": abs(object_delta - truth_delta)}
        row["classes"] = [item, dict(item)] if duplicate else [item]
        return {"split_lots": {"test": [0]}, "spatial_null_and_mixed": {"wafer_class_spatial_rates": {"by_spatial_kind": {"A_ring": {"per_wafer": [row]}}}}}

    def rejected(call, label):
        try:
            call()
        except ValueError:
            return True
        raise AssertionError(f"{label} should fail closed")

    assert rejected(lambda: wafer_class_rows(fixture(duplicate=True)), "duplicate key")
    assert rejected(lambda: validate_and_pair(fixture((2, 1)), fixture((3, 1))), "truth mismatch")
    split_mismatch = fixture()
    split_mismatch["split_lots"]["test"] = [1]
    assert rejected(lambda: validate_and_pair(fixture(), split_mismatch), "test split mismatch")
    assert rejected(lambda: exact_count(1.5, "test"), "fractional count")
    return {"lot_weighting": True, "percentile_ci": True,
            "single_lot_ci_suppressed": True, "duplicate_key_rejected": True,
            "truth_mismatch_rejected": True, "test_split_mismatch_rejected": True,
            "fractional_count_rejected": True,
            "lot_mapping": "wafer_id // 2", "real_data_used": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--repetitions", type=int, default=BOOTSTRAP_REPETITIONS)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.repetitions < 100:
        parser.error("--repetitions must be at least 100")
    result = self_check() if args.self_check else analyze(args.input_dir, args.repetitions, args.seed)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
