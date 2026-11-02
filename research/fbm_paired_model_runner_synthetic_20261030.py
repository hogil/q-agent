#!/usr/bin/env python3
"""Explicitly gated, synthetic-only paired FBM retrieval runner.

Default operation is a weight-free self-check. A real model run evaluates only
the predeclared primary condition; all other factorial cells remain explicitly
unrun in the manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import statistics
import time
from typing import Callable

# Configure native pools before NumPy/BLAS and the encoder modules import.
for _thread_env_name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"):
    os.environ[_thread_env_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for _import_root in (ROOT, ROOT / "research"):
    if str(_import_root) not in sys.path:
        sys.path.insert(0, str(_import_root))

from research import fbm_cpu_encoder_smoke_20261030 as _BASE
from research import fbm_paired_factorial_synthetic_20261030 as FACTORIAL
from research import fbm_paired_retrieval_eval_synthetic_20261030 as EVALUATOR

SIZE = 192
SEEDS = FACTORIAL.SEEDS
LABEL_POLICY = "spatial_coupled"
ERROR_RATE = 0.0
REJECT_RATE = 0.0
RUN_GATE = "PARENT_AUDITED_20261030"
RENDERER_VERSION = "palette-renderer-v1"
RENDER_SPEC = "raw: grayscale fail=255/background=0; object_id: code 0 yellow,1 red,2 blue,3 black; yield: 0 black,1 white,255 midgray; object_id_yield: 2-channel conditional palette"
PREPROCESS_SPEC = _BASE.PREPROCESS
UNRUN_CONDITIONS = [
    {"label_policy": policy, "error_rate": e, "reject_rate": r}
    for policy in FACTORIAL.LABEL_POLICIES
    for e in (0.0, 0.2)
    for r in (0.0, 0.2)
    if not (policy == LABEL_POLICY and e == ERROR_RATE and r == REJECT_RATE)
]

PALETTE = {
    "object_id": {0: (255, 220, 0), 1: (255, 0, 0), 2: (0, 0, 255), 3: (0, 0, 0)},
    "yield": {0: (0, 0, 0), 1: (255, 255, 255), 255: (128, 128, 128)},
}


def _render(array: np.ndarray, view: str) -> np.ndarray:
    """Render a validated view array to RGB without reading sample metadata."""
    a = np.asarray(array)
    if view == "object_id_yield":
        if a.shape != (SIZE, SIZE, 2) or a.dtype.kind not in "bu":
            raise ValueError("object_id_yield requires uint-like (192,192,2) codes")
        oid, yld = a[..., 0], a[..., 1]
        if not np.isin(oid, (0, 1, 2, 3)).all() or not np.isin(yld, (0, 1, 255)).all():
            raise ValueError("invalid object_id_yield code")
        out = np.empty((SIZE, SIZE, 3), dtype=np.uint8)
        out[yld == 255] = (128, 128, 128)
        out[yld == 1] = (255, 255, 255)
        for code in (0, 1, 2):
            out[(yld == 0) & (oid == code)] = PALETTE["object_id"][code]
        # Yield fail at background code 3 is black as the explicit yield palette.
        out[(yld == 0) & (oid == 3)] = PALETTE["yield"][0]
        return out
    if a.shape != (SIZE, SIZE) or a.dtype.kind not in "bu":
        raise ValueError(f"{view} requires a uint-like (192,192) code array")
    if view == "raw":
        if not np.isin(a, (0, 1)).all():
            raise ValueError("raw codes must be 0/background or 1/fail")
        gray = (a.astype(np.uint8) * np.uint8(255))
        return np.repeat(gray[..., None], 3, axis=2)
    if view not in PALETTE:
        raise ValueError(f"unsupported view: {view}")
    palette = PALETTE[view]
    allowed = tuple(palette)
    if not np.isin(a, allowed).all():
        raise ValueError(f"invalid {view} code")
    out = np.empty((SIZE, SIZE, 3), dtype=np.uint8)
    for code, color in palette.items():
        out[a == code] = color
    return out


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_paths() -> dict[str, Path]:
    return {
        "plan": ROOT / "docs/current/FBM_PAIRED_RETRIEVAL_SYNTHETIC_PLAN_20261030.md",
        "runner": Path(__file__).resolve(),
        "generator": Path(FACTORIAL.__file__).resolve(),
        "evaluator": Path(EVALUATOR.__file__).resolve(),
        "encoder_base": Path(_BASE.__file__).resolve(),
    }


def _current_source_hashes() -> dict[str, dict[str, str]]:
    return {name: {"path": str(path.resolve()), "sha256": _sha256(path)}
            for name, path in _source_paths().items()}


def _verify_frozen_sources(frozen: dict[str, dict[str, str]], stage: str) -> None:
    current = _current_source_hashes()
    if current != frozen:
        changed = sorted(name for name in frozen if frozen.get(name) != current.get(name))
        raise RuntimeError(f"source hash changed {stage}: {changed}")


def _start_resource_mark() -> dict[str, float]:
    return {"wall_monotonic": time.perf_counter(), "process_cpu": time.process_time()}


def _peak_working_set_bytes() -> tuple[int | None, str | None]:
    """Return process-lifetime peak working set, not a seed-local peak."""
    if os.name != "nt":
        return None, "GetProcessMemoryInfo is Windows-only"
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t)]

        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.PeakWorkingSetSize), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _resource_usage(start: dict[str, float], *, wall_end: float | None = None,
                    cpu_end: float | None = None,
                    memory_reader: Callable[[], tuple[int | None, str | None]] = _peak_working_set_bytes
                    ) -> dict[str, object]:
    end_wall = time.perf_counter() if wall_end is None else wall_end
    end_cpu = time.process_time() if cpu_end is None else cpu_end
    try:
        peak, reason = memory_reader()
    except Exception as exc:
        peak, reason = None, f"{type(exc).__name__}: {exc}"
    return {
        "wall_elapsed_seconds": max(0.0, end_wall - start["wall_monotonic"]),
        "process_cpu_seconds": max(0.0, end_cpu - start["process_cpu"]),
        "peak_process_working_set_bytes": peak,
        "peak_process_working_set_reason": reason,
        "peak_scope": "process-lifetime cumulative peak; not an independent per-seed peak",
    }


def _encoder(backbone_path: Path, head_path: Path, expected_backbone: str,
             expected_head: str) -> tuple[Callable[[np.ndarray, str], np.ndarray], dict[str, str]]:
    backbone, head, bb_hash, head_hash, F = _BASE._load_encoder(
        backbone_path.resolve(strict=True), head_path.resolve(strict=True),
        expected_backbone, expected_head)
    import torch
    from PIL import Image
    from torchvision import transforms as T

    transform = T.Compose([
        T.Resize((384, 384), interpolation=T.InterpolationMode.BILINEAR),
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    spec = json.dumps({"model": _BASE.MODEL_ID, "backbone": bb_hash, "head": head_hash,
                       "preprocess": PREPROCESS_SPEC, "renderer": RENDERER_VERSION,
                       "render_spec": RENDER_SPEC}, sort_keys=True, separators=(",", ":"))
    def compute(rgb: np.ndarray, view: str) -> np.ndarray:
        image = Image.fromarray(rgb, mode="RGB")
        x = transform(image).unsqueeze(0)
        with torch.inference_mode():
            pooled = backbone.forward_features(x).mean(dim=(2, 3))
            vec = F.normalize(head(pooled.float()), dim=1)[0]
        if vec.numel() != _BASE.DIM or not torch.isfinite(vec).all() or abs(float(vec.norm()) - 1) > 1e-5:
            raise RuntimeError("encoder vector contract failed")
        return vec.detach().cpu().numpy().astype(np.float64, copy=True)

    embed, _ = _cached_embedding(compute, spec)
    return embed, {"backbone_sha256": bb_hash, "head_sha256": head_hash,
                   "checkpoint_sha256": hashlib.sha256((bb_hash + head_hash).encode("ascii")).hexdigest(),
                   "encoder_spec_sha256": hashlib.sha256(spec.encode()).hexdigest()}


def _cached_embedding(encoder: Callable[[np.ndarray, str], np.ndarray], spec: str):
    """Memoize an encoder by view, rendered bytes, and immutable encoder spec."""
    cache: dict[str, np.ndarray] = {}
    calls = {"count": 0}

    def invoke(array: np.ndarray, view: str) -> np.ndarray:
        rgb = _render(array, view)
        rendered = rgb.tobytes(order="C")
        key = hashlib.sha256(view.encode() + b"\0" + rendered + b"\0" + spec.encode()).hexdigest()
        if key not in cache:
            value = np.asarray(encoder(rgb, view), dtype=np.float64)
            if value.ndim != 1 or value.size == 0 or not np.isfinite(value).all():
                raise ValueError("encoder must return a finite non-empty vector")
            norm = float(np.linalg.norm(value))
            if norm == 0:
                raise ValueError("encoder vector must have non-zero norm")
            cache[key] = value / norm
            calls["count"] += 1
        return cache[key].copy()

    return invoke, calls


def _self_check() -> dict[str, object]:
    a = np.zeros((SIZE, SIZE), dtype=np.uint8)
    a[0, 0] = 1
    raw = _render(a, "raw")
    assert tuple(raw[0, 0]) == (255, 255, 255) and tuple(raw[1, 1]) == (0, 0, 0)
    oid = np.array([[0, 1], [2, 3]], dtype=np.uint8)
    rendered = _render(np.pad(oid, ((0, SIZE - 2), (0, SIZE - 2))), "object_id")
    assert tuple(rendered[0, 0]) == PALETTE["object_id"][0]
    assert tuple(rendered[0, 1]) == PALETTE["object_id"][1]
    assert tuple(rendered[1, 0]) == PALETTE["object_id"][2]
    assert tuple(rendered[1, 1]) == PALETTE["object_id"][3]
    yld = np.zeros((SIZE, SIZE), dtype=np.uint8)
    yld[0, 0], yld[0, 1], yld[0, 2] = 0, 1, 255
    yrgb = _render(yld, "yield")
    assert tuple(yrgb[0, 0]) == (0, 0, 0) and tuple(yrgb[0, 1]) == (255, 255, 255)
    assert tuple(yrgb[0, 2]) == (128, 128, 128)
    combined = np.stack((np.zeros_like(yld), yld), axis=-1)
    crgb = _render(combined, "object_id_yield")
    assert tuple(crgb[0, 0]) == PALETTE["object_id"][0]
    assert tuple(crgb[0, 1]) == (255, 255, 255)
    assert tuple(crgb[0, 2]) == (128, 128, 128)
    for bad_view, bad_array in (("raw", np.full((SIZE, SIZE), 2, np.uint8)),
                                ("yield", np.full((SIZE, SIZE), 2, np.uint8)),
                                ("object_id", np.zeros((SIZE, SIZE, 3), np.uint8))):
        try:
            _render(bad_array, bad_view)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid shape/code was accepted")
    return {"status": "synthetic_runner_self_check_pass", "weights_loaded": False,
            "inference_run": False, "seeds": list(SEEDS), "primary_condition_only": True,
            "renderer_version": RENDERER_VERSION, "unrun_factorial_conditions": len(UNRUN_CONDITIONS)}


def _run_seed(seed: int, out_dir: Path, embed: Callable[[np.ndarray, str], np.ndarray],
              encoder_hashes: dict[str, str],
              frozen_sources: dict[str, dict[str, str]]) -> dict[str, object]:
    seed_dir = out_dir / f"seed-{seed}"
    seed_dir.mkdir(exist_ok=False)
    resource_mark = _start_resource_mark()
    start = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config = {"seed": seed, "condition": {"label_policy": LABEL_POLICY,
              "error_rate": ERROR_RATE, "reject_rate": REJECT_RATE},
              "renderer": RENDERER_VERSION, "render_spec": RENDER_SPEC,
              "preprocess": PREPROCESS_SPEC}
    run_state = {"status": "running", "seed": seed, "started_utc": start,
                 "ended_utc": None, "closed": False, "condition": {"label_policy": LABEL_POLICY,
                 "error_rate": ERROR_RATE, "reject_rate": REJECT_RATE},
                 "unrun_factorial_conditions": UNRUN_CONDITIONS,
                 "unrun_planned_items": ["class_count_histogram_baseline", "all non-primary label/noise/reject conditions"],
                 "completion_claim": "primary seed condition only; factorial not complete",
                 "frozen_source_hashes": frozen_sources,
                 "plan_sha256": frozen_sources["plan"]["sha256"],
                 "runner_sha256": frozen_sources["runner"]["sha256"],
                 "generator_sha256": frozen_sources["generator"]["sha256"],
                 "evaluator_sha256": frozen_sources["evaluator"]["sha256"],
                 "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                 "checkpoint_hashes": None,
                 "encoder_source_path": frozen_sources["encoder_base"]["path"],
                 "encoder_source_sha256": frozen_sources["encoder_base"]["sha256"]}
    _atomic_json(seed_dir / "progress.json", run_state)
    try:
        _verify_frozen_sources(frozen_sources, f"before seed {seed}")
        samples = FACTORIAL.generate(seed, error_rate=ERROR_RATE, reject_rate=REJECT_RATE)
        run_state["checkpoint_hashes"] = encoder_hashes
        _atomic_json(seed_dir / "progress.json", run_state)
        result = EVALUATOR.evaluate(samples, embed, label_policy=LABEL_POLICY,
                                    error_rate=ERROR_RATE, reject_rate=REJECT_RATE)
        _verify_frozen_sources(frozen_sources, f"after seed {seed} evaluation")
        usage = _resource_usage(resource_mark)
        ended = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        manifest = {
            **run_state, "status": "complete_primary_condition", "ended_utc": ended,
            "closed": True, "synthetic_only": True, "factorial_complete": False,
            "plan_sha256": run_state["plan_sha256"], "runner_sha256": run_state["runner_sha256"],
            "generator_sha256": run_state["generator_sha256"], "evaluator_sha256": run_state["evaluator_sha256"],
            "config_sha256": run_state["config_sha256"],
            "frozen_source_hashes": frozen_sources,
            "checkpoint_hashes": encoder_hashes, "preprocess": PREPROCESS_SPEC,
            "resource_usage": usage,
            "renderer_spec": RENDER_SPEC, "palette": {k: {str(c): list(v) for c, v in p.items()} for k, p in PALETTE.items()},
            "sample_count": len(samples), "gallery_count": result["gallery_count"],
            "query_count": result["query_count"], "metrics": result,
            "resource_limits": {"job_memory_limit_bytes": int(2.5 * 1024**3),
                                "torch_thread_limit": 1, "cuda_visible_devices": "empty",
                                "python_socket_connect_monkeypatch": True,
                                "memory_limit_scope": "Windows Job Object process/job memory cap",
                                "wall_clock_limit": "not configured"},
        }
        _atomic_json(seed_dir / "result.json", manifest)
        run_state.update(status="complete_primary_condition", ended_utc=ended, closed=True,
                         resource_usage=usage)
        _atomic_json(seed_dir / "progress.json", run_state)
        return manifest
    except BaseException as exc:
        usage = _resource_usage(resource_mark)
        run_state.update(status="failed_or_interrupted", ended_utc=datetime.now(timezone.utc).replace(
            microsecond=0).isoformat().replace("+00:00", "Z"), closed=True,
            failure_type=type(exc).__name__, failure=str(exc), resource_usage=usage)
        _atomic_json(seed_dir / "progress.json", run_state)
        raise


def _run(args) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("--run requires Windows Job Object enforcement")
    frozen_sources = _current_source_hashes()
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    _BASE._job_memory_cap()
    _BASE._disable_network()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    overall = {"status": "running", "started_utc": datetime.now(timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z"), "closed": False,
        "seeds_planned": list(SEEDS), "seeds_requested": list(SEEDS if args.seed is None else (args.seed,)),
        "results": [], "factorial_complete": False, "checkpoint_hashes": None,
        "provenance": {"frozen_source_hashes": frozen_sources,
                       "encoder_source_path": frozen_sources["encoder_base"]["path"],
                       "encoder_source_sha256": frozen_sources["encoder_base"]["sha256"]},
        "termination_note": "forced process termination may leave status running and closed=false"}
    _atomic_json(out_dir / "manifest.json", overall)
    try:
        backbone = args.backbone.resolve(strict=True)
        head = args.head.resolve(strict=True)
        embed, encoder_hashes = _encoder(backbone, head,
                                         args.expected_backbone_sha256, args.expected_head_sha256)
        overall["checkpoint_hashes"] = encoder_hashes
        _atomic_json(out_dir / "manifest.json", overall)
        for seed in overall["seeds_requested"]:
            overall["results"].append(_run_seed(seed, out_dir, embed, encoder_hashes, frozen_sources))
            _atomic_json(out_dir / "manifest.json", overall)
        _verify_frozen_sources(frozen_sources, "before overall completion")
        overall.update(status="requested_primary_seeds_complete", ended_utc=datetime.now(timezone.utc).replace(
            microsecond=0).isoformat().replace("+00:00", "Z"), closed=True,
            factorial_complete=False, completion_claim="primary condition only; all planned factorial not complete")
        if tuple(overall["seeds_requested"]) == tuple(SEEDS) and len(overall["results"]) == 5:
            deltas = [float(row["metrics"]["paired_mean_differences_vs_raw"]["object_id_yield"]["hit_at_3"])
                      for row in overall["results"]]
            overall["five_seed_primary_summary"] = {
                "metric": "object_id_yield minus raw_only mean_hit_at_3",
                "independent_unit": "master_seed", "n": 5,
                "query_rows_are_not_independent_replicates": True,
                "seed_deltas": deltas, "mean": statistics.mean(deltas),
                "median": statistics.median(deltas), "population_sd": statistics.pstdev(deltas),
                "range": [min(deltas), max(deltas)],
            }
        _atomic_json(out_dir / "manifest.json", overall)
        return overall
    except BaseException as exc:
        overall.update(status="failed_or_interrupted", ended_utc=datetime.now(timezone.utc).replace(
            microsecond=0).isoformat().replace("+00:00", "Z"), closed=True,
            failure_type=type(exc).__name__, failure=str(exc))
        _atomic_json(out_dir / "manifest.json", overall)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--seed", type=int, choices=SEEDS, help="run one planned seed; omit to run all five")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--backbone", type=Path)
    parser.add_argument("--head", type=Path)
    parser.add_argument("--expected-backbone-sha256")
    parser.add_argument("--expected-head-sha256")
    args = parser.parse_args(argv)
    if args.self_check and not args.run:
        print(json.dumps(_self_check(), indent=2))
        return 0
    if not args.run:
        parser.error("default is fail-closed; choose --self-check or explicitly gated --run")
    if os.environ.get("QAGENT_FBM_MODEL_LOAD_GATE") != RUN_GATE:
        parser.error(f"--run requires QAGENT_FBM_MODEL_LOAD_GATE={RUN_GATE}")
    if not all((args.output_dir, args.backbone, args.head,
                args.expected_backbone_sha256, args.expected_head_sha256)):
        parser.error("--run requires --output-dir, local --backbone/--head, and both expected SHA-256 values")
    for label, value in (("backbone", args.expected_backbone_sha256), ("head", args.expected_head_sha256)):
        if len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            parser.error(f"--expected-{label}-sha256 must be 64 hexadecimal characters")
    print(json.dumps(_run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
