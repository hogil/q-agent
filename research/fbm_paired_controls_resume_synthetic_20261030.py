#!/usr/bin/env python3
"""Explicitly gated resume runner for the synthetic paired FBM controls."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import fbm_paired_controls_runner_synthetic_20261030 as OLD
from research import fbm_paired_model_runner_synthetic_20261030 as PRIMARY
from research import fbm_paired_factorial_synthetic_20261030 as FACTORIAL
from research import fbm_paired_retrieval_eval_synthetic_20261030 as EVALUATOR

RUN_GATE = PRIMARY.RUN_GATE
SEEDS = FACTORIAL.SEEDS
CONDITIONS = tuple(dict(c) for c in PRIMARY.UNRUN_CONDITIONS)
PRIMARY_CONDITION = OLD.PRIMARY_CONDITION


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expected_keys() -> dict[str, tuple[dict[str, object], int]]:
    return {f"{OLD._condition_key(c)}__seed-{s}": (c, s) for c in CONDITIONS for s in SEEDS}


def _audit_prior(path: Path, primary_path: Path, primary_manifest: dict[str, object], primary_rows: dict[int, dict[str, object]]) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = _expected_keys()
    roster = manifest.get("units_planned")
    if not isinstance(roster, list) or len(roster) != 55:
        raise ValueError("prior control roster must contain 55 units")
    roster_keys = [x.get("key") for x in roster]
    if len(set(roster_keys)) != 55 or set(roster_keys) != set(expected):
        raise ValueError("prior control roster has duplicate, missing, or unexpected keys")
    for row in roster:
        key = row["key"]
        condition, seed = expected[key]
        if row.get("condition") != condition or row.get("seed") != seed:
            raise ValueError(f"prior roster key mismatch: {key}")
    if manifest.get("checkpoint_hashes") != primary_manifest.get("checkpoint_hashes"):
        raise ValueError("prior checkpoint identity differs from frozen primary")
    if manifest.get("primary_checkpoint_hashes") != primary_manifest.get("checkpoint_hashes"):
        raise ValueError("prior primary checkpoint identity differs from current primary")
    if manifest.get("primary_manifest_sha256") != _sha(primary_path):
        raise ValueError("prior primary manifest hash differs from supplied primary cohort")
    source = manifest.get("source_hashes")
    if not isinstance(source, dict) or source.get("controls_runner", {}).get("sha256") != OLD._sha256(Path(OLD.__file__).resolve()):
        raise ValueError("prior controls source identity is stale")
    primary_frozen = primary_manifest["provenance"]["frozen_source_hashes"]
    for name in ("plan", "runner", "generator", "evaluator", "encoder_base"):
        if source.get(name) != primary_frozen.get(name) or source.get(name) != OLD._current_source_hashes().get(name):
            raise ValueError(f"prior source identity differs from frozen/current source: {name}")
    imported: list[dict[str, object]] = []
    snapshots: dict[str, str] = {}
    completed = manifest.get("completed_units", [])
    if len(set(completed)) != len(completed) or not set(completed) <= set(expected):
        raise ValueError("prior completed unit list is invalid")
    required_reuse = {"spatial_coupled__e00__r20__seed-" + str(s) for s in SEEDS}
    if set(completed) != required_reuse:
        raise ValueError("prior must contain exactly the five expected reusable committed units")
    for key in completed:
        condition, seed = expected[key]
        unit = path.parent / OLD._condition_key(condition) / f"seed-{seed}"
        if not OLD._validate_unit_commit(unit, key, condition, seed, manifest):
            raise ValueError(f"prior unit commit invalid: {key}")
        for filename in ("commit.json", "result.json", "progress.json"):
            snapshots[str(unit / filename)] = _sha(unit / filename)
        progress = json.loads((unit / "progress.json").read_text(encoding="utf-8"))
        marker = json.loads((unit / "commit.json").read_text(encoding="utf-8"))
        result = json.loads((unit / "result.json").read_text(encoding="utf-8"))
        if marker != {"key": key, "condition": condition, "seed": seed,
                      "result_sha256": hashlib.sha256((unit / "result.json").read_bytes()).hexdigest()}:
            raise ValueError(f"prior marker mismatch: {key}")
        if progress.get("source_hashes") != source or progress.get("checkpoint_hashes") != manifest.get("checkpoint_hashes"):
            raise ValueError(f"prior unit provenance mismatch: {key}")
        if progress.get("status") != "complete" or progress.get("closed") is not True or progress.get("key") != key or progress.get("condition") != condition or progress.get("seed") != seed:
            raise ValueError(f"prior unit progress mismatch: {key}")
        result["result_checkpoint_provenance_indirect_via_progress_manifest"] = True
        if seed not in primary_rows:
            raise ValueError(f"primary seed missing for imported unit: {key}")
        imported.append(result)
    if path.read_bytes() != manifest_bytes:
        raise RuntimeError("prior manifest changed during audit")
    manifest["_audit_file_sha256"] = snapshots
    return manifest, imported


def _self_check() -> dict[str, object]:
    return {"status": "resume_self_check_pass", "weights_loaded": False, "inference_run": False,
            "planned_units": 55, "unique_keys": len(_expected_keys()) == 55}


def _run(args) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("--run requires Windows Job Object enforcement")
    prior_path = args.prior_manifest.resolve(strict=True)
    primary_path = args.primary_manifest.resolve(strict=True)
    primary_manifest, primary_rows = OLD._read_primary(primary_path)
    prior_bytes_hash = _sha(prior_path)
    prior, reused = _audit_prior(prior_path, primary_path, primary_manifest, primary_rows)
    audit_file_sha256 = prior.pop("_audit_file_sha256")
    frozen_sources = OLD._current_source_hashes()
    frozen_sources["resume_runner"] = {"path": str(Path(__file__).resolve()), "sha256": _sha(Path(__file__).resolve())}
    frozen_sources["prior_manifest"] = {"path": str(prior_path), "sha256": prior_bytes_hash}
    frozen_sources["primary_manifest"] = {"path": str(primary_path), "sha256": _sha(primary_path)}
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    OLD._BASE._job_memory_cap()
    OLD._BASE._disable_network()
    out = OLD._reserve_output(args.output_dir)
    expected = _expected_keys()
    reuse_by_key = {r["key"]: r for r in reused}
    manifest: dict[str, object] = {
        "status": "running", "closed": False, "synthetic_only": True,
        "started_utc": _timestamp(), "conditions_planned": list(CONDITIONS), "seeds_planned": list(SEEDS),
        "units_planned": [{"key": k, "condition": c, "seed": s} for k, (c, s) in expected.items()],
        "completed_units": [], "factorial_complete": False, "source_hashes": frozen_sources,
        "prior_manifest_path": str(prior_path), "prior_manifest_sha256": prior_bytes_hash,
        "prior_status_at_audit": prior.get("status"), "prior_closed_at_audit": prior.get("closed"),
        "prior_interrupted_process_stopped_by_caller": True,
        "prior_process_stop_limit": "Caller assertion only; process state is not independently verifiable by this runner.",
        "primary_manifest_path": str(primary_path), "primary_manifest_sha256": _sha(primary_path),
        "checkpoint_hashes": primary_manifest["checkpoint_hashes"], "primary_checkpoint_hashes": primary_manifest["checkpoint_hashes"],
        "histogram_baseline": deepcopy(prior.get("histogram_baseline", {"status": "unverified"})),
        "reproducibility_limit": "The six prior source/plan files have hashes but no Git commit identity; old primary sample bytes were not retained.",
        "reused_units": [{"key": k, "prior_result_path": str(prior_path.parent / OLD._condition_key(expected[k][0]) / f"seed-{expected[k][1]}" / "result.json"), "prior_result_sha256": _sha(prior_path.parent / OLD._condition_key(expected[k][0]) / f"seed-{expected[k][1]}" / "result.json")} for k in sorted(reuse_by_key)], "termination_note": "Forced termination leaves this fresh output partial; no automatic resume.",
        "condition_runs": {}, "condition_summaries": {},
    }
    def _verify_inputs(stage: str) -> None:
        old_sources = OLD._current_source_hashes()
        resume_source = frozen_sources["resume_runner"]
        if (_sha(prior_path) != prior_bytes_hash or _sha(primary_path) != frozen_sources["primary_manifest"]["sha256"]
                or any(frozen_sources.get(k) != v for k, v in old_sources.items())
                or _sha(Path(resume_source["path"])) != resume_source["sha256"]
                or any(_sha(Path(p)) != digest for p, digest in audit_file_sha256.items())):
            raise RuntimeError(f"prior, primary, source, or imported-unit drift {stage}")
    OLD._atomic_json(out / "manifest.json", manifest)
    try:
        bb, hd = args.backbone.resolve(strict=True), args.head.resolve(strict=True)
        if args.expected_backbone_sha256.lower() != primary_manifest["checkpoint_hashes"]["backbone_sha256"] or args.expected_head_sha256.lower() != primary_manifest["checkpoint_hashes"]["head_sha256"]:
            raise RuntimeError("explicit checkpoint hashes differ from primary manifest")
        embed, hashes = OLD._encoder(bb, hd, args.expected_backbone_sha256, args.expected_head_sha256)
        if hashes != primary_manifest["checkpoint_hashes"]:
            raise RuntimeError("encoder checkpoint identity differs from primary")
        missing = set(expected) - set(reuse_by_key)
        for condition in CONDITIONS:
            ckey = OLD._condition_key(condition)
            manifest["condition_runs"][ckey] = {"status": "running", "started_utc": _timestamp()}
            OLD._atomic_json(out / "manifest.json", manifest)
            condition_rows = []
            for seed in SEEDS:
                key = f"{ckey}__seed-{seed}"
                _verify_inputs(f"before {key}")
                if key in reuse_by_key:
                    original = reuse_by_key[key]
                    row = deepcopy(original)
                    row["provenance"] = {"unit_source": "prior_committed_result", "prior_manifest_sha256": prior_bytes_hash}
                    manifest["completed_units"].append(key)
                    condition_rows.append(row)
                    _verify_inputs(f"after reused {key}")
                    continue
                if key not in missing:
                    raise RuntimeError(f"unit neither imported nor pending: {key}")
                unit_dir = out / ckey / f"seed-{seed}"
                unit_dir.mkdir(parents=True, exist_ok=False)
                mark = OLD._resource_mark(); started = _timestamp()
                progress = {"key": key, "condition": condition, "seed": seed, "status": "running", "closed": False,
                            "started_utc": started, "source_hashes": frozen_sources, "checkpoint_hashes": hashes}
                OLD._atomic_json(unit_dir / "progress.json", progress)
                try:
                    OLD._verify_mask_pairing(seed, condition)
                    samples = FACTORIAL.generate(seed, error_rate=condition["error_rate"], reject_rate=condition["reject_rate"])
                    metrics = EVALUATOR.evaluate(samples, embed, label_policy=condition["label_policy"], error_rate=condition["error_rate"], reject_rate=condition["reject_rate"])
                    OLD._primary_pair_check(primary_rows[seed], metrics, seed)
                    row = {"key": key, "condition": condition, "seed": seed, "status": "complete", "closed": True,
                           "started_utc": started, "ended_utc": _timestamp(), "metrics": metrics,
                           "realized_rates_and_coverage": OLD._condition_rates(seed, condition), "resource_usage": OLD._resource_usage(mark),
                           "primary_roster_and_regenerated_mask_consistency_verified": True,
                           "primary_sample_bytes_independently_archived": False,
                           "synthetic_sample_manifest": OLD._synthetic_sample_manifest(samples, condition["label_policy"]),
                           "source_hashes": frozen_sources, "checkpoint_hashes": hashes}
                    row = OLD._commit_unit(unit_dir, row, progress, out / "manifest.json", manifest)
                    condition_rows.append(row)
                    _verify_inputs(f"after {key}")
                except BaseException as exc:
                    progress.update(status="failed_or_interrupted", closed=True, failure_type=type(exc).__name__, failure=str(exc))
                    OLD._atomic_json(unit_dir / "progress.json", progress)
                    manifest.update(status="failed_or_interrupted", closed=True, failed_unit=key, factorial_complete=False)
                    OLD._atomic_json(out / "manifest.json", manifest)
                    raise
            if len(condition_rows) == len(SEEDS):
                manifest["condition_summaries"][ckey] = OLD._summarize_condition(condition, condition_rows)
                manifest["condition_summaries"][ckey]["unit_provenance"] = ["prior_reused" if r["key"] in reuse_by_key else "newly_evaluated" for r in condition_rows]
            manifest["condition_runs"][ckey].update(status="complete", ended_utc=_timestamp())
            OLD._atomic_json(out / "manifest.json", manifest)
        _verify_inputs("before overall completion")
        expected_reuse = {"spatial_coupled__e00__r20__seed-" + str(s) for s in SEEDS}
        if set(reuse_by_key) != expected_reuse or len(manifest["completed_units"]) != 55 or set(manifest["completed_units"]) != set(expected):
            raise RuntimeError("overall completion guard: expected exactly five reused and 50 newly committed unique units")
        for key, (condition, seed) in expected.items():
            if key in reuse_by_key:
                continue
            unit = out / OLD._condition_key(condition) / f"seed-{seed}"
            if not OLD._validate_unit_commit(unit, key, condition, seed, manifest):
                raise RuntimeError(f"invalid new unit commit: {key}")
        manifest.update(status="all_non_primary_conditions_complete", closed=True, factorial_complete=True,
                        ended_utc=_timestamp(), completion_claim="11 conditions x 5 seeds: 5 prior committed units reused and 50 newly committed units")
        OLD._atomic_json(out / "manifest.json", manifest)
        return manifest
    except BaseException as exc:
        if manifest.get("status") == "running":
            manifest.update(status="failed_or_interrupted", closed=True, failure_type=type(exc).__name__, failure=str(exc), factorial_complete=False)
            OLD._atomic_json(out / "manifest.json", manifest)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true"); parser.add_argument("--run", action="store_true")
    parser.add_argument("--prior-manifest", type=Path); parser.add_argument("--primary-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path); parser.add_argument("--backbone", type=Path); parser.add_argument("--head", type=Path)
    parser.add_argument("--expected-backbone-sha256"); parser.add_argument("--expected-head-sha256")
    args = parser.parse_args(argv)
    if args.self_check and not args.run:
        print(json.dumps(_self_check(), indent=2)); return 0
    if not args.run or os.environ.get("QAGENT_FBM_MODEL_LOAD_GATE") != RUN_GATE:
        parser.error(f"--run and QAGENT_FBM_MODEL_LOAD_GATE={RUN_GATE} are required")
    if not all((args.prior_manifest, args.primary_manifest, args.output_dir, args.backbone, args.head, args.expected_backbone_sha256, args.expected_head_sha256)):
        parser.error("--run requires both manifests, fresh --output-dir, checkpoints, and explicit hashes")
    for value in (args.expected_backbone_sha256, args.expected_head_sha256):
        if len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value): parser.error("expected hashes must be 64 hexadecimal characters")
    print(json.dumps(_run(args), indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
