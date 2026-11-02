#!/usr/bin/env python3
"""Explicitly gated runner for the 11 non-primary synthetic FBM conditions.

Default operation is a weight-free self-check. A complete execution requires
the frozen five-seed primary manifest and evaluates each non-primary cell once
per seed, reusing one encoder and its rendered-view embedding cache.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Callable

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for _root in (ROOT, ROOT / "research"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from research import fbm_cpu_encoder_smoke_20261030 as _BASE
from research import fbm_paired_factorial_synthetic_20261030 as FACTORIAL
from research import fbm_paired_model_runner_synthetic_20261030 as PRIMARY_RUNNER
from research import fbm_paired_retrieval_eval_synthetic_20261030 as EVALUATOR

RUN_GATE = PRIMARY_RUNNER.RUN_GATE
SEEDS = FACTORIAL.SEEDS
PRIMARY_CONDITION = {"label_policy": "spatial_coupled", "error_rate": 0.0, "reject_rate": 0.0}
CONDITIONS = tuple(dict(c) for c in PRIMARY_RUNNER.UNRUN_CONDITIONS)
PRIMARY_MANIFEST_DEFAULT = ROOT / "var/fbm-paired-primary-5seed-20261030-01/manifest.json"
PRIMARY_SOURCE_HASHES = {
    "plan": "06afc23217db6badfa1e02c82db948fe86e721179b77a71db1e3d0912a8bc8bd",
    "runner": "fea70ed8eb07ca4629512f1fe46cce3ffb2ca09f89de880f7d8bae34dbeabf4e",
    "generator": "7e0ee4c686cd5a7b456f5f5a3993b1989422b0cb4d80500bd50c54695e74fe38",
    "evaluator": "d99024ef823d4204cf8053a5898c005a4331d098f93b0af701577dbdb179fc7a",
    "encoder_base": "e18c4e3138c949b38cba7c3eca3078df71fe5217ec9605d8c5643335156c9199",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _source_paths() -> dict[str, Path]:
    return {"plan": ROOT / "docs/current/FBM_PAIRED_RETRIEVAL_SYNTHETIC_PLAN_20261030.md",
            "runner": Path(PRIMARY_RUNNER.__file__).resolve(),
            "generator": Path(FACTORIAL.__file__).resolve(),
            "evaluator": Path(EVALUATOR.__file__).resolve(),
            "encoder_base": Path(_BASE.__file__).resolve(),
            "controls_runner": Path(__file__).resolve()}


def _current_source_hashes() -> dict[str, dict[str, str]]:
    return {k: {"path": str(p.resolve()), "sha256": _sha256(p)} for k, p in _source_paths().items()}


def _verify_source_identity(frozen: dict[str, dict[str, str]], stage: str) -> None:
    current = _current_source_hashes()
    if current != frozen:
        raise RuntimeError(f"source hash changed {stage}")


def _read_primary(path: Path) -> tuple[dict[str, object], dict[int, dict[str, object]]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "requested_primary_seeds_complete" or manifest.get("closed") is not True:
        raise ValueError("primary manifest must be closed and complete")
    if manifest.get("factorial_complete") is not False or manifest.get("seeds_planned") != list(SEEDS) or manifest.get("seeds_requested") != list(SEEDS):
        raise ValueError("primary manifest seed/factorial contract mismatch")
    frozen = manifest.get("provenance", {}).get("frozen_source_hashes")
    if not isinstance(frozen, dict) or {k: frozen.get(k, {}).get("sha256") for k in PRIMARY_SOURCE_HASHES} != PRIMARY_SOURCE_HASHES:
        raise ValueError("primary frozen source hashes do not match required identity")
    current = _current_source_hashes()
    if any(current.get(k) != frozen.get(k) for k in PRIMARY_SOURCE_HASHES):
        raise ValueError("primary source identity is stale or path changed")
    rows = manifest.get("results", [])
    if len(rows) != 5 or [r.get("seed") for r in rows] != list(SEEDS):
        raise ValueError("primary manifest must contain exactly the five planned seed results in order")
    results: dict[int, dict[str, object]] = {}
    for row in rows:
        seed = int(row["seed"])
        if row.get("status") != "complete_primary_condition" or row.get("closed") is not True or row.get("condition") != PRIMARY_CONDITION:
            raise ValueError(f"primary seed {seed} is not the frozen primary condition")
        if row.get("checkpoint_hashes") != manifest.get("checkpoint_hashes"):
            raise ValueError(f"primary seed {seed} checkpoint identity mismatch")
        if row.get("frozen_source_hashes") != frozen:
            raise ValueError(f"primary seed {seed} frozen source mismatch")
        metrics = row.get("metrics", {})
        queries = metrics.get("per_query", [])
        if len(queries) != 12 or len({q.get("query_id") for q in queries}) != 12:
            raise ValueError(f"primary seed {seed} query manifest is incomplete")
        results[seed] = row
    if set(results) != set(SEEDS):
        raise ValueError("primary seeds missing or duplicated")
    return manifest, results


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    except BaseException:
        try: os.unlink(name)
        except OSError: pass
        raise


def _reserve_output(path: Path) -> Path:
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _synthetic_sample_manifest(samples: list[object], policy: str) -> list[dict[str, object]]:
    rows = []
    views = ("raw", "object_id", "yield", "object_id_yield")
    for sample in sorted(samples, key=lambda s: s.sample_id):
        byte_hashes = {}
        for view in views:
            array = EVALUATOR._view_input(sample, view, policy)
            byte_hashes[view] = hashlib.sha256(array.tobytes(order="C")).hexdigest()
        rows.append({"sample_id": sample.sample_id, "split": sample.split,
                     "lineage_group_id": sample.lineage_group_id, "wafer_class": sample.wafer_class,
                     "regime": sample.regime, "mask_sha256": sample.metadata["mask_hash"],
                     "view_array_sha256": byte_hashes,
                     "noise_coordinates_yx": [list(p) for p in sample.metadata["flipped_coordinates_yx"]],
                     "reject_coordinates_yx": [list(p) for p in sample.metadata["rejected_coordinates_yx"]]})
    return rows


def _validate_unit_commit(unit_dir: Path, key: str, condition: dict[str, object], seed: int,
                          manifest: dict[str, object]) -> bool:
    try:
        marker = json.loads((unit_dir / "commit.json").read_text(encoding="utf-8"))
        result_bytes = (unit_dir / "result.json").read_bytes()
        result = json.loads(result_bytes)
        progress = json.loads((unit_dir / "progress.json").read_text(encoding="utf-8"))
        return (marker == {"key": key, "condition": condition, "seed": seed,
                          "result_sha256": hashlib.sha256(result_bytes).hexdigest()}
                and result.get("key") == key and result.get("condition") == condition
                and result.get("seed") == seed and result.get("status") == "complete"
                and progress.get("key") == key and progress.get("condition") == condition
                and progress.get("seed") == seed and progress.get("status") == "complete"
                and progress.get("closed") is True and key in manifest.get("completed_units", []))
    except (OSError, ValueError, TypeError):
        return False


def _commit_unit(unit_dir: Path, result: dict[str, object], progress: dict[str, object],
                 manifest_path: Path, manifest: dict[str, object]) -> dict[str, object]:
    key, condition, seed = result["key"], result["condition"], result["seed"]
    _atomic_json(unit_dir / "result.json", result)
    progress.update(status="complete", closed=True, ended_utc=result["ended_utc"])
    _atomic_json(unit_dir / "progress.json", progress)
    result_bytes = (unit_dir / "result.json").read_bytes()
    marker = {"key": key, "condition": condition, "seed": seed,
              "result_sha256": hashlib.sha256(result_bytes).hexdigest()}
    _atomic_json(unit_dir / "commit.json", marker)
    updated = deepcopy(manifest)
    if key in updated["completed_units"]:
        raise RuntimeError(f"duplicate committed key {key}")
    updated["completed_units"].append(key)
    _atomic_json(manifest_path, updated)
    manifest.clear()
    manifest.update(updated)
    if not _validate_unit_commit(unit_dir, key, condition, seed, manifest):
        raise RuntimeError(f"unit commit verification failed for {key}")
    return json.loads((unit_dir / "result.json").read_text(encoding="utf-8"))


def _resource_mark() -> dict[str, float]:
    return {"wall": time.perf_counter(), "cpu": time.process_time()}


def _resource_usage(mark: dict[str, float]) -> dict[str, object]:
    usage = PRIMARY_RUNNER._resource_usage({"wall_monotonic": mark["wall"], "process_cpu": mark["cpu"]})
    usage["measurement_scope"] = "actual sequential process elapsed and CPU; peak is process-lifetime cumulative"
    return usage


def _encoder(backbone: Path, head: Path, expected_backbone: str, expected_head: str):
    # The primary implementation supplies the fixed model, preprocessing, renderer and cache contract.
    return PRIMARY_RUNNER._encoder(backbone, head, expected_backbone, expected_head)


def _primary_pair_check(primary: dict[str, object], current: dict[str, object], seed: int) -> None:
    pqs = {q["query_id"]: q for q in primary["metrics"]["per_query"]}
    cqs = {q["query_id"]: q for q in current["per_query"]}
    if pqs.keys() != cqs.keys():
        raise RuntimeError(f"query ID set differs from primary for seed {seed}")
    for qid, pq in pqs.items():
        cq = cqs[qid]
        if pq["relevant_candidate_ids"] != cq["relevant_candidate_ids"]:
            raise RuntimeError(f"relevance differs from primary for {qid}")
        for arm in EVALUATOR.ARMS:
            if set(pq["arms"][arm]["candidate_ids"]) != set(cq["arms"][arm]["candidate_ids"]):
                raise RuntimeError(f"candidate set differs for {qid}/{arm}")


def _verify_mask_pairing(seed: int, condition: dict[str, object]) -> None:
    base = FACTORIAL.generate(seed, error_rate=0.0, reject_rate=0.0)
    changed = FACTORIAL.generate(seed, error_rate=condition["error_rate"], reject_rate=condition["reject_rate"])
    baseline = {s.sample_id: (s.metadata["mask_hash"], s.lineage_group_id, s.split, s.wafer_class, s.regime)
                for s in base}
    candidate = {s.sample_id: (s.metadata["mask_hash"], s.lineage_group_id, s.split, s.wafer_class, s.regime)
                 for s in changed}
    if baseline != candidate:
        raise RuntimeError(f"raw mask or sample pairing changed for seed {seed}/{_condition_key(condition)}")


def _condition_key(condition: dict[str, object]) -> str:
    return f"{condition['label_policy']}__e{int(float(condition['error_rate'])*100):02d}__r{int(float(condition['reject_rate'])*100):02d}"


def _condition_rates(seed: int, condition: dict[str, object]) -> dict[str, object]:
    samples = FACTORIAL.generate(seed, error_rate=condition["error_rate"], reject_rate=condition["reject_rate"])
    count = sum(int(s.fail_mask.sum()) for s in samples)
    rejected = sum(int(s.reject_mask.sum()) for s in samples)
    known = count - rejected
    flipped = sum(len(s.metadata["flipped_coordinates_yx"]) for s in samples)
    labeled = [s.label_maps_by_policy[condition["label_policy"]] for s in samples]
    return {"fail_defects": count, "rejected_defects": rejected,
            "realized_reject_rate_all_defects": rejected / count,
            "flipped_known_labels": flipped,
            "realized_error_rate_all_defects": flipped / count,
            "realized_error_rate_non_rejected_denominator": flipped / known if known else None,
            "known_label_defects": known,
            "class_coverage": {"A": sum(int((m == 1).sum()) for m in labeled),
                               "B": sum(int((m == 2).sum()) for m in labeled),
                               "unknown_reject": rejected}}


def _run(args) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("--run requires Windows Job Object enforcement")
    primary_path = args.primary_manifest.resolve(strict=True)
    primary_manifest, primary_results = _read_primary(primary_path)
    if args.seed is not None:
        # Audit-only path; never eligible for full-factorial completion claim.
        seeds = (args.seed,)
    else:
        seeds = SEEDS
    frozen = _current_source_hashes()
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    _BASE._job_memory_cap()
    _BASE._disable_network()
    out = _reserve_output(args.output_dir)
    expected_units = [{"condition": c, "seed": s, "key": f"{_condition_key(c)}__seed-{s}"} for c in CONDITIONS for s in seeds]
    manifest: dict[str, object] = {
        "status": "running", "closed": False, "synthetic_only": True,
        "started_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "conditions_planned": list(CONDITIONS), "seeds_planned": list(SEEDS), "seeds_requested": list(seeds),
        "units_planned": expected_units, "completed_units": [], "failed_unit": None,
        "factorial_complete": False, "primary_manifest_path": str(primary_path),
        "primary_manifest_sha256": _sha256(primary_path), "primary_source_identity_verified": True,
        "primary_checkpoint_hashes": primary_manifest["checkpoint_hashes"], "source_hashes": frozen,
        "histogram_baseline": {"status": "unverified", "note": "existing count-only baseline was not linked or revalidated"},
        "resource_limits": {"job_memory_limit_bytes": int(2.5 * 1024**3), "torch_thread_limit": 1,
                            "cuda_visible_devices": "empty", "python_socket_connect_monkeypatch": True,
                            "network_isolation": "Python socket connect monkeypatch only; not OS isolation"},
        "termination_note": "forced process termination may leave status running and closed=false",
        "salvage_rule": "A unit counts only when commit.json matches result SHA/key/condition/seed, progress.json is complete and matching, and this overall manifest lists the key. No automatic salvage or resume; uncommitted files are retained and excluded.",
        "primary_pairing_limit": "Primary query roster, relevance, and candidate sets are cross-checked. Original primary sample bytes were not independently archived and are not directly compared.",
        "condition_runs": {},
    }
    _atomic_json(out / "manifest.json", manifest)
    try:
        bb, hd = args.backbone.resolve(strict=True), args.head.resolve(strict=True)
        expected_primary = primary_manifest.get("checkpoint_hashes", {})
        if args.expected_backbone_sha256.lower() != expected_primary.get("backbone_sha256") or \
                args.expected_head_sha256.lower() != expected_primary.get("head_sha256"):
            raise RuntimeError("expected local checkpoint hashes differ from primary manifest")
        if _sha256(bb) != args.expected_backbone_sha256.lower() or _sha256(hd) != args.expected_head_sha256.lower():
            raise RuntimeError("local checkpoint file hash does not match its explicit expected hash")
        embed, hashes = _encoder(bb, hd, args.expected_backbone_sha256, args.expected_head_sha256)
        if hashes != primary_manifest.get("checkpoint_hashes"):
            raise RuntimeError("local checkpoint/encoder spec identity differs from primary manifest")
        manifest["checkpoint_hashes"] = hashes
        _atomic_json(out / "manifest.json", manifest)
        units_seen: set[str] = set()
        for condition in CONDITIONS:
            ckey = _condition_key(condition)
            condition_results = []
            manifest["condition_runs"][ckey] = {"started_utc": _utc_now(), "ended_utc": None,
                                                "status": "running"}
            _atomic_json(out / "manifest.json", manifest)
            for seed in seeds:
                key = f"{ckey}__seed-{seed}"
                if key in units_seen:
                    raise RuntimeError(f"duplicate planned unit key {key}")
                units_seen.add(key)
                _verify_source_identity(frozen, f"before {key}")
                unit_dir = out / ckey / f"seed-{seed}"
                unit_dir.mkdir(parents=True, exist_ok=False)
                mark = _resource_mark()
                started_utc = _utc_now()
                progress = {"key": key, "status": "running", "closed": False, "condition": condition,
                            "seed": seed, "started_utc": started_utc, "ended_utc": None,
                            "checkpoint_hashes": hashes, "source_hashes": frozen}
                _atomic_json(unit_dir / "progress.json", progress)
                try:
                    _verify_mask_pairing(seed, condition)
                    samples = FACTORIAL.generate(seed, error_rate=condition["error_rate"], reject_rate=condition["reject_rate"])
                    result = EVALUATOR.evaluate(samples, embed, label_policy=condition["label_policy"],
                                                error_rate=condition["error_rate"], reject_rate=condition["reject_rate"])
                    _primary_pair_check(primary_results[seed], result, seed)
                    _verify_source_identity(frozen, f"after {key}")
                    ended_utc = _utc_now()
                    rec = {"key": key, "condition": condition, "seed": seed, "status": "complete",
                           "started_utc": started_utc, "ended_utc": ended_utc,
                           "closed": True, "metrics": result, "realized_rates_and_coverage": _condition_rates(seed, condition),
                           "resource_usage": _resource_usage(mark),
                           "primary_roster_and_regenerated_mask_consistency_verified": True,
                           "primary_sample_bytes_independently_archived": False,
                           "synthetic_sample_manifest": _synthetic_sample_manifest(samples, condition["label_policy"])}
                    progress.update(ended_utc=ended_utc)
                    rec = _commit_unit(unit_dir, rec, progress, out / "manifest.json", manifest)
                    condition_results.append(rec)
                except BaseException as exc:
                    manifest["completed_units"] = [item for item in manifest["completed_units"] if item != key]
                    manifest["condition_runs"][ckey].update(status="failed_or_interrupted", ended_utc=_utc_now())
                    progress.update(status="failed_or_interrupted", closed=True,
                                    failure_type=type(exc).__name__, failure=str(exc), resource_usage=_resource_usage(mark))
                    _atomic_json(unit_dir / "progress.json", progress)
                    manifest.update(status="failed_or_interrupted", closed=True, failed_unit=key,
                                    failure_type=type(exc).__name__, failure=str(exc), factorial_complete=False)
                    _atomic_json(out / "manifest.json", manifest)
                    raise
            if len(condition_results) == len(SEEDS) and set(seeds) == set(SEEDS):
                manifest.setdefault("condition_summaries", {})[ckey] = _summarize_condition(condition, condition_results)
            manifest["condition_runs"][ckey].update(status="complete", ended_utc=_utc_now())
            _atomic_json(out / "manifest.json", manifest)
        _verify_source_identity(frozen, "before overall completion")
        if args.seed is not None:
            manifest.update(status="audit_subset_complete", closed=True, factorial_complete=False,
                            completion_claim="requested audit seed only; not a complete factorial")
        else:
            if len(units_seen) != 55 or set(manifest["completed_units"]) != {x["key"] for x in expected_units}:
                raise RuntimeError("condition/seed matrix has missing or duplicate units")
            for item in expected_units:
                unit_dir = out / _condition_key(item["condition"]) / f"seed-{item['seed']}"
                if not _validate_unit_commit(unit_dir, item["key"], item["condition"], item["seed"], manifest):
                    raise RuntimeError(f"unit missing valid commit marker: {item['key']}")
            manifest.update(status="all_non_primary_conditions_complete", closed=True, factorial_complete=True,
                            completion_claim="11 non-primary conditions x 5 seeds complete; primary roster/candidate and regenerated-mask consistency verified")
        manifest["ended_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        _atomic_json(out / "manifest.json", manifest)
        return manifest
    except BaseException as exc:
        for condition_run in manifest.get("condition_runs", {}).values():
            if condition_run.get("status") == "running":
                condition_run.update(status="failed_or_interrupted", ended_utc=_utc_now())
        if manifest.get("status") == "running":
            manifest.update(status="failed_or_interrupted", closed=True, failure_type=type(exc).__name__,
                            failure=str(exc), factorial_complete=False)
            _atomic_json(out / "manifest.json", manifest)
        raise


def _summarize_condition(condition: dict[str, object], rows: list[dict[str, object]]) -> dict[str, object]:
    if len(rows) != 5 or {r["seed"] for r in rows} != set(SEEDS):
        raise ValueError("condition summary requires exactly five seed units")
    metrics = {}
    for arm in EVALUATOR.ARMS:
        metrics[arm] = {}
        for metric in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank"):
            values = [r["metrics"]["arms"][arm][f"mean_{metric}"] for r in rows]
            metrics[arm][metric] = {"seed_values": values, "n_seeds": 5, "mean": statistics.mean(values),
                                    "median": statistics.median(values), "population_sd": statistics.pstdev(values),
                                    "range": [min(values), max(values)]}
    return {"condition": condition, "independent_unit": "master_seed", "n_seeds": 5,
            "query_rows_are_not_independent_replicates": True, "metrics_by_arm": metrics}


def _self_check() -> dict[str, object]:
    assert len(CONDITIONS) == 11 and len({_condition_key(c) for c in CONDITIONS}) == 11
    assert all(c != PRIMARY_CONDITION for c in CONDITIONS)
    samples = FACTORIAL.generate(42, error_rate=0.2, reject_rate=0.2)
    assert all(s.label_policy == "spatial_coupled" for s in samples)
    return {"status": "controls_runner_self_check_pass", "weights_loaded": False,
            "inference_run": False, "non_primary_conditions": len(CONDITIONS),
            "planned_units": 55, "seed_count": len(SEEDS), "matrix_keys_unique": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--seed", type=int, choices=SEEDS, help="audit-only subset; never completes factorial")
    parser.add_argument("--primary-manifest", type=Path, help="explicit path to the verified, closed five-seed primary manifest")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--backbone", type=Path)
    parser.add_argument("--head", type=Path)
    parser.add_argument("--expected-backbone-sha256")
    parser.add_argument("--expected-head-sha256")
    args = parser.parse_args(argv)
    if args.self_check and not args.run:
        print(json.dumps(_self_check(), indent=2)); return 0
    if not args.run:
        parser.error("default is fail-closed; choose --self-check or explicitly gated --run")
    if os.environ.get("QAGENT_FBM_MODEL_LOAD_GATE") != RUN_GATE:
        parser.error(f"--run requires QAGENT_FBM_MODEL_LOAD_GATE={RUN_GATE}")
    if not all((args.primary_manifest, args.output_dir, args.backbone, args.head,
                args.expected_backbone_sha256, args.expected_head_sha256)):
        parser.error("--run requires explicit --primary-manifest, fresh --output-dir, local --backbone/--head, and both expected SHA-256 values")
    for name, value in (("backbone", args.expected_backbone_sha256), ("head", args.expected_head_sha256)):
        if len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            parser.error(f"--expected-{name}-sha256 must be 64 hexadecimal characters")
    print(json.dumps(_run(args), indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
