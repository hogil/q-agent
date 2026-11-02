"""Post-primary class-count histogram control for synthetic FBM retrieval."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import fbm_paired_factorial_synthetic_20261030 as GENERATOR
from research import fbm_paired_retrieval_eval_synthetic_20261030 as EVALUATOR

PRIMARY_DIR = ROOT / "var/fbm-paired-primary-5seed-20261030-01"
SEEDS = (42, 1, 2, 3, 4)
EXPECTED_COUNTS = {1: 10, 2: 10}
METRICS = ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank")
LIMITS = (
    "post_primary exploratory synthetic control; not a preregistered primary result",
    "the synthetic object-ID channel is an oracle label channel",
    "identical count histograms create complete score ties; deterministic tie hashing can have bias",
    "no causal, field, production, or novelty claim is supported",
)


def count_encoder(image_array: np.ndarray, view: str) -> np.ndarray:
    """Encode only class-code pixel counts; no sample or label metadata is available."""
    a = np.asarray(image_array)
    if view == "object_id":
        if a.shape != (192, 192):
            raise ValueError("object_id expects (192,192)")
        ids = a
    elif view == "object_id_yield":
        if a.shape != (192, 192, 2):
            raise ValueError("object_id_yield expects (192,192,2)")
        ids = a[..., 0]
    elif view in ("raw", "yield"):
        return np.array([1.0, 1.0], dtype=np.float64)
    else:
        raise ValueError(f"unexpected view: {view}")
    return np.array([np.count_nonzero(ids == 1), np.count_nonzero(ids == 2)], dtype=np.float64)


def _validate_counts(samples) -> None:
    for sample in samples:
        ids = np.asarray(sample.object_id_arrays_by_policy["spatial_coupled"])
        found = {code: int(np.count_nonzero(ids == code)) for code in (1, 2)}
        if found != EXPECTED_COUNTS:
            raise ValueError(f"{sample.sample_id}: expected input-array A/B counts {EXPECTED_COUNTS}, got {found}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_sources(primary: dict) -> dict:
    frozen = primary["provenance"]["frozen_source_hashes"]
    current = {"generator": {"path": str(Path(GENERATOR.__file__).resolve()), "sha256": _sha256(Path(GENERATOR.__file__))},
               "evaluator": {"path": str(Path(EVALUATOR.__file__).resolve()), "sha256": _sha256(Path(EVALUATOR.__file__))}}
    for name, value in current.items():
        expected = frozen.get(name)
        if expected != value:
            raise RuntimeError(f"frozen {name} source mismatch; control execution refused")
    return current


def _atomic_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8", newline="\n", closefd=True) as f:
            json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n")
            f.flush()
            import os
            os.fsync(f.fileno())
        import os
        os.replace(name, path)
    except BaseException:
        import os
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def run(primary_dir: Path, output_dir: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(f"exclusive output directory already exists: {output_dir}")
    primary_path = primary_dir / "manifest.json"
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    if primary.get("status") != "requested_primary_seeds_complete" or primary.get("closed") is not True:
        raise RuntimeError("primary manifest is not closed and complete")
    frozen = _frozen_sources(primary)
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        model_rows = {int(row["seed"]): row for row in primary["results"]}
        if set(model_rows) != set(SEEDS):
            raise ValueError("primary manifest must contain exactly the five planned seeds")
        rows = []
        for seed in SEEDS:
            samples = GENERATOR.generate(seed, error_rate=0.0, reject_rate=0.0)
            _validate_counts(samples)
            result = EVALUATOR.evaluate(samples, count_encoder, label_policy="spatial_coupled",
                                        error_rate=0.0, reject_rate=0.0)
            model_metrics = model_rows[seed]["metrics"]["arms"]["object_id_yield"]
            rows.append({"seed": seed, "baseline": result["arms"],
                         "model_object_id_yield": model_metrics,
                         "model_minus_baseline": {m: model_metrics[f"mean_{m}"] - result["arms"]["object_id_yield"][f"mean_{m}"] for m in METRICS},
                         "baseline_ties": result["tie_summary_by_arm"]})
        summary = {m: {"seed_differences": [r["model_minus_baseline"][m] for r in rows],
                       "mean": statistics.mean(r["model_minus_baseline"][m] for r in rows),
                       "median": statistics.median(r["model_minus_baseline"][m] for r in rows)} for m in METRICS}
        manifest = {"status": "post_primary_exploratory_control_complete", "closed": True,
                    "created_utc": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
                    "condition": {"seeds": list(SEEDS), "label_policy": "spatial_coupled", "error_rate": 0.0, "reject_rate": 0.0},
                    "baseline": "object-ID class-code pixel-count vector [count(code 1), count(code 2)]; raw/yield are fixed [1,1]",
                    "sample_count_check": "each sample input object-ID array must contain exactly 10 code-1 and 10 code-2 pixels",
                    "metrics": list(METRICS), "paired_comparison": "model object_id_yield minus count histogram baseline, paired by master_seed",
                    "independent_unit": "master_seed", "query_rows_are_not_independent_replicates": True,
                    "source_hashes": frozen, "primary_manifest_sha256": _sha256(primary_path),
                    "seed_results": rows, "five_seed_summary": summary, "interpretation_limits": list(LIMITS)}
        _atomic_json(output_dir / "manifest.json", manifest)
        return manifest
    except BaseException:
        # Preserve the exclusive directory as a failure record location; never touch prior artifacts.
        raise


def self_check() -> dict:
    a = np.zeros((192, 192), dtype=np.uint8)
    a.flat[:10] = 1
    a.flat[10:20] = 2
    assert np.array_equal(count_encoder(a, "object_id"), [10, 10])
    combined = np.stack((a, np.zeros_like(a)), axis=-1)
    assert np.array_equal(count_encoder(combined, "object_id_yield"), [10, 10])
    assert np.array_equal(count_encoder(a, "raw"), [1, 1])
    return {"status": "self_check_pass", "inference_run": False, "output_written": False,
            "encoder_contract": "array plus view only", "metrics": list(METRICS)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--primary-dir", type=Path, default=PRIMARY_DIR)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_check:
        print(json.dumps(self_check(), indent=2))
        return 0
    if args.output_dir is None:
        parser.error("execution requires an explicit exclusive --output-dir")
    print(json.dumps(run(args.primary_dir.resolve(), args.output_dir.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
