"""Generate and optionally analyze a wide synthetic chip-feature fixture."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import numpy as np

from config_loader import add_config_arguments, load_config
from tabular_analysis import analyze_matrix, build_platform_tabular


AS_OF = "2026-10-24"


def _inside(path: Path, root: Path) -> Path:
    resolved, resolved_root = path.resolve(), root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise ValueError("tabular demo output must remain inside configured paths.output_root") from None
    return resolved


def _feature_catalog(count: int) -> list[dict]:
    # Names/units are deliberately synthetic placeholders, not site catalogue entries.
    return [{"name": f"synthetic_item_{index + 1:03d}", "unit": f"synthetic_unit_{index // 16 + 1:02d}",
             "lower_limit": -8.0, "upper_limit": 8.0,
             "semantic_description": "synthetic demo feature; physical meaning unknown"}
            for index in range(count)]


def generate_matrix(feature_count: int = 128, chip_count: int = 6000, group_count: int = 30,
                    seed: int = 20261024):
    """Create one wide row per synthetic chip without expanding to long form."""
    if type(feature_count) is not int or not 2 <= feature_count <= 512:
        raise ValueError("feature_count must be in 2..512")
    if type(chip_count) is not int or not 100 <= chip_count <= 20_000:
        raise ValueError("chip_count must be in 100..20000")
    if type(group_count) is not int or not 10 <= group_count <= 200 or group_count > chip_count:
        raise ValueError("group_count must be in 10..min(200, chip_count)")
    rng = np.random.default_rng(seed)
    feature_catalog = _feature_catalog(feature_count)
    latent_count = min(8, feature_count)
    loadings = rng.normal(0, 0.45, size=(latent_count, feature_count))
    latent = rng.normal(0, 1, size=(chip_count, latent_count))
    matrix = latent @ loadings + rng.normal(0, 0.55, size=(chip_count, feature_count))

    per_group = np.arange(chip_count) % group_count
    # Group order is chronological. Later groups contain controlled synthetic shifts.
    group_times = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
                   for day in range(group_count)]
    groups = np.asarray([f"SYN-GRP-{index:03d}" for index in per_group])
    timestamps = np.asarray([group_times[index].isoformat(timespec="seconds") for index in per_group])
    labels = np.zeros(chip_count, dtype=np.int8)
    for row, group_index in enumerate(per_group):
        if group_index % 7 == 0:
            labels[row] = 1
            matrix[row, (group_index * 3) % feature_count] += 6.0
        if group_index >= int(group_count * 0.7) and group_index % 3 == 0:
            matrix[row, :min(4, feature_count)] += 1.5
    missing = rng.random(matrix.shape) < 0.015
    matrix[missing] = np.nan
    # Explicit duplicate records allow profile coverage of duplicate detection.
    duplicate_indexes = np.arange(17, chip_count, 997, dtype=int)
    if duplicate_indexes.size:
        matrix[duplicate_indexes] = matrix[duplicate_indexes - 1]
        groups[duplicate_indexes] = groups[duplicate_indexes - 1]
        timestamps[duplicate_indexes] = timestamps[duplicate_indexes - 1]
        labels[duplicate_indexes] = labels[duplicate_indexes - 1]
    return matrix, labels, groups, timestamps, feature_catalog


def generate(settings, *, feature_count=128, chip_count=6000, group_count=30,
             seed=None, output_dir=None, top_k=5):
    if settings.data.get("environment") not in ("demo", "test"):
        raise ValueError("synthetic tabular fixture requires demo/test environment")
    root = Path(settings.data["paths"]["output_root"]).resolve()
    target = _inside(Path(output_dir) if output_dir else root / "tabular-demo-v1", root)
    if target.exists():
        raise FileExistsError("tabular demo output exists; refusing to overwrite")
    selected_seed = int(seed if seed is not None else settings.data.get("platform", {}).get("seed", 20261024))
    X, labels, groups, timestamps, catalogue = generate_matrix(feature_count, chip_count, group_count, selected_seed)
    matrix_path = target / "synthetic_chip_features.npz"
    metadata_path = target / "synthetic_chip_features.json"
    report_path = target / "analysis.json"
    target.mkdir(parents=True)
    try:
        np.savez_compressed(matrix_path, X=X, labels=labels, groups=groups, timestamps=timestamps)
        metadata = {"synthetic": True, "fixture_as_of": AS_OF, "seed": selected_seed,
                    "feature_count": feature_count, "chip_count": chip_count, "group_count": group_count,
                    "holdout_fraction": 0.2, "wide_row_contract": "one row per synthetic chip; X columns follow features order",
                    "features": catalogue, "config_hash": settings.config_hash,
                    "source_cutoff": "synthetic fixture only; no production source cutoff"}
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = analyze_matrix(X, labels, groups, timestamps, catalogue, seed=selected_seed, top_k=top_k)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # Leave a failed directory visible rather than deleting user files recursively.
        raise
    return {"status": "SYNTHETIC_TABULAR_DEMO_READY", "synthetic": True,
            "paths": {"dataset": str(matrix_path), "metadata": str(metadata_path), "analysis": str(report_path)},
            "chip_count": chip_count, "feature_count": feature_count, "seed": selected_seed,
            "analysis_method": report["method"], "train_normal_count": report["train_normal_count"],
            "holdout_count": report["holdout_count"], "holdout_flagged_count": report["holdout_flagged_count"],
            "notice": "128 features by default are dummy synthetic channels, not actual site measurement columns."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument("--feature-count", type=int, default=128)
    parser.add_argument("--chip-count", type=int, default=6000)
    parser.add_argument("--group-count", type=int, default=30)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", help="new output directory inside configured paths.output_root")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--platform", action="store_true",
                        help="build configured wide table/model from the registered synthetic platform fixture")
    args = parser.parse_args(argv)
    if not 1 <= args.top_k <= 10:
        parser.error("--top-k must be in 1..10")
    settings = load_config(args.config, args.overlay)
    if args.platform:
        result = build_platform_tabular(settings)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = generate(settings, feature_count=args.feature_count, chip_count=args.chip_count,
                      group_count=args.group_count, seed=args.seed, output_dir=args.output_dir, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
