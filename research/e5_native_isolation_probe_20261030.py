"""Opt-in, process-isolated probes for a local E5 model load incident.

Import and --help are inert. --run is intentionally an explicit operator action;
it performs only staged tokenizer/config, safetensors, empty-config, or combined
empty-model plus bounded-tensor probes.
No result from this diagnostic establishes the cause of a prior native crash or
the semantic quality of an embedding model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(r"D:\project\q-agent-models\var\weights\multilingual-e5-small-v1")
MIN_JOB_LIMIT_MIB = 2048
MAX_JOB_LIMIT_MIB = 3072
DEFAULT_TENSOR_READ_MAX = 128 * 1024**2
MAX_TENSOR_READ_MAX = 512 * 1024**2
PROBE_TIMEOUT_SECONDS = 180
_JOB_HANDLES = []
SAFETENSORS_TO_TORCH_DTYPE = {
    "F64": "torch.float64", "I64": "torch.int64", "U64": "torch.uint64",
    "F32": "torch.float32", "I32": "torch.int32", "U32": "torch.uint32",
    "F16": "torch.float16", "BF16": "torch.bfloat16", "I16": "torch.int16",
    "U16": "torch.uint16", "I8": "torch.int8", "U8": "torch.uint8", "BOOL": "torch.bool",
}


def mark(stage: str, **data) -> None:
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def snapshot(folder: Path) -> dict:
    files = sorted(p for p in folder.rglob("*") if p.is_file() and ".cache" not in p.parts)
    if not files:
        raise RuntimeError("model directory contains no files")
    digest = hashlib.sha256()
    for p in files:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        rel = p.relative_to(folder).as_posix()
        digest.update(rel.encode() + b"\0" + bytes.fromhex(h.hexdigest()))
    return {"path": str(folder), "manifest_sha256": digest.hexdigest()}


def capacity_guard(job_limit_bytes: int) -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows PSAPI capacity check is required")
    import ctypes
    from ctypes import wintypes
    class PI(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in ("CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")] + [(n, wintypes.DWORD) for n in ("HandleCount", "ProcessCount", "ThreadCount")]
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.GetPerformanceInfo.argtypes = [ctypes.POINTER(PI), wintypes.DWORD]
    api.GetPerformanceInfo.restype = wintypes.BOOL
    pi = PI(); pi.cb = ctypes.sizeof(pi)
    if not api.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
        raise OSError(ctypes.get_last_error(), "GetPerformanceInfo failed")
    commit = (pi.CommitLimit - pi.CommitTotal) * pi.PageSize
    disk = shutil.disk_usage(Path("D:\\")).free
    result = {"available_commit_bytes": commit, "required_commit_bytes": job_limit_bytes + 4 * 1024**3,
              "d_free_bytes": disk, "required_d_free_bytes": 20 * 1024**3}
    if commit < result["required_commit_bytes"] or disk < result["required_d_free_bytes"]:
        raise RuntimeError(f"capacity pre-check failed: {result}")
    return result


def job_cap(job_limit_bytes: int) -> None:
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]; k.CreateJobObjectW.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = wintypes.HANDLE
    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
    class Io(ctypes.Structure): _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class Ext(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    h = k.CreateJobObjectW(None, None)
    if not h: raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    x = Ext(); x.BasicLimitInformation.LimitFlags = 0x100 | 0x200; x.ProcessMemoryLimit = job_limit_bytes; x.JobMemoryLimit = job_limit_bytes
    if not k.SetInformationJobObject(h, 9, ctypes.byref(x), ctypes.sizeof(x)) or not k.AssignProcessToJobObject(h, k.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "job memory cap setup failed")
    _JOB_HANDLES.append(h)


def deny_network() -> None:
    def denied(*_a, **_kw): raise RuntimeError("network socket connection denied")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def child(args) -> int:
    try:
        if not MIN_JOB_LIMIT_MIB <= args.job_limit_mib <= MAX_JOB_LIMIT_MIB:
            raise RuntimeError("child job limit outside allowed range")
        job_limit_bytes = args.job_limit_mib * 1024**2
        mark("preflight_before", requested_job_limit_mib=args.job_limit_mib)
        model = args.model.resolve(strict=True)
        if not model.is_dir(): raise RuntimeError("model path is not a directory")
        if not args.expected_sha256:
            raise RuntimeError("caller-supplied expected model manifest SHA-256 is required")
        before = snapshot(model)
        if args.expected_sha256 and args.expected_sha256.casefold() != before["manifest_sha256"].casefold():
            raise RuntimeError("caller expected model manifest SHA-256 mismatch")
        mark("preflight_after", snapshot=before, expected_hash_supplied=bool(args.expected_sha256))
        mark("capacity_before"); capinfo = capacity_guard(job_limit_bytes); mark("capacity_after", **capinfo)
        mark("job_cap_before", requested_bytes=job_limit_bytes); job_cap(job_limit_bytes); mark("job_cap_after", bytes=job_limit_bytes, mib=args.job_limit_mib)
        for n in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"): os.environ[n] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        deny_network()
        p = args.probe
        if p in ("tokenizer", "config"):
            mark(p + "_import_before")
            if p == "tokenizer":
                from transformers import AutoTokenizer
                mark("tokenizer_load_before"); AutoTokenizer.from_pretrained(model, local_files_only=True, trust_remote_code=False); mark("tokenizer_load_after")
            else:
                from transformers import AutoConfig
                mark("config_load_before"); config = AutoConfig.from_pretrained(model, local_files_only=True, trust_remote_code=False); mark("config_load_after", model_type=getattr(config, "model_type", None))
        elif p.startswith("safetensors"):
            mark("safetensors_import_before")
            from safetensors import safe_open
            from safetensors.torch import load_file
            candidates = sorted(model.glob("*.safetensors"))
            if not candidates: raise RuntimeError("no top-level safetensors file; probe skipped")
            path = candidates[0]
            mark("safe_open_before", file=path.name)
            with safe_open(str(path), framework="pt", device="cpu") as f:
                keys = list(f.keys()); mark("safe_open_after", tensor_count=len(keys))
                if p != "safetensors_meta":
                    # Select by metadata without materializing tensors.
                    infos = [(f.get_slice(k).get_shape(), k, f.get_slice(k).get_dtype()) for k in keys]
                    widths = {"F64":8,"I64":8,"U64":8,"F32":4,"I32":4,"U32":4,"F16":2,"BF16":2,"I16":2,"U16":2,"I8":1,"U8":1,"BOOL":1}
                    sizes = [( __import__("math").prod(shape) * widths[dtype], key) if dtype in widths else (args.tensor_read_max + 1, key) for shape,key,dtype in infos]
                    chosen = min(sizes) if p == "safetensors_small" else max(sizes)
                    if chosen[0] > args.tensor_read_max:
                        mark("tensor_read_skipped", key=chosen[1], estimated_bytes=chosen[0], max_bytes=args.tensor_read_max,
                             reason="selected tensor exceeds bounded read size")
                        return 0
                    mark("tensor_read_before", key=chosen[1], estimated_bytes=chosen[0])
                    tensor = f.get_tensor(chosen[1]); mark("tensor_read_after", shape=list(tensor.shape), dtype=str(tensor.dtype), numel=tensor.numel())
        elif p == "empty_model":
            mark("torch_import_before"); import torch
            torch.set_num_threads(1)
            from transformers import AutoConfig, AutoModel
            mark("empty_model_config_before"); cfg = AutoConfig.from_pretrained(model, local_files_only=True, trust_remote_code=False); mark("empty_model_config_after")
            mark("empty_model_construct_before"); m = AutoModel.from_config(cfg, trust_remote_code=False); mark("empty_model_construct_after", parameter_count=sum(x.numel() for x in m.parameters()))
        elif p == "combined_probe":
            mark("torch_import_before"); import torch
            torch.set_num_threads(1)
            from transformers import AutoConfig, AutoModel
            mark("combined_config_before"); cfg = AutoConfig.from_pretrained(model, local_files_only=True, trust_remote_code=False); mark("combined_config_after", model_type=getattr(cfg, "model_type", None))
            mark("combined_model_construct_before"); m = AutoModel.from_config(cfg, trust_remote_code=False)
            parameter_count = sum(x.numel() for x in m.parameters())
            mark("combined_model_construct_after", parameter_count=parameter_count)
            candidates = sorted(model.glob("*.safetensors"))
            if not candidates: raise RuntimeError("no top-level safetensors file; combined probe skipped")
            from safetensors import safe_open
            path = candidates[0]
            key = "embeddings.word_embeddings.weight"
            with safe_open(str(path), framework="pt", device="cpu") as f:
                keys = list(f.keys())
                if key not in keys: raise RuntimeError(f"required tensor missing from {path.name}: {key}")
                tensor_slice = f.get_slice(key)
                shape = tensor_slice.get_shape()
                dtype = tensor_slice.get_dtype()
                widths = {"F64":8,"I64":8,"U64":8,"F32":4,"I32":4,"U32":4,"F16":2,"BF16":2,"I16":2,"U16":2,"I8":1,"U8":1,"BOOL":1}
                if dtype not in widths: raise RuntimeError(f"unknown tensor dtype: {dtype}")
                if any(not isinstance(dim, int) or dim < 0 for dim in shape): raise RuntimeError(f"invalid tensor shape: {shape}")
                limit = min(args.tensor_read_max, MAX_TENSOR_READ_MAX)
                numel = 1
                for dim in shape:
                    if dim and numel > limit // dim: raise RuntimeError("tensor element count exceeds bounded size")
                    numel *= dim
                width = widths[dtype]
                if numel > limit // width: raise RuntimeError("tensor byte count exceeds bounded size")
                estimated_bytes = numel * width
                mark("combined_tensor_metadata", file=path.name, key=key, shape=shape, dtype=dtype,
                     estimated_bytes=estimated_bytes, max_bytes=args.tensor_read_max)
                if estimated_bytes != 384056832:
                    raise RuntimeError(f"word embedding size mismatch: expected 384056832, got {estimated_bytes}")
                if estimated_bytes > args.tensor_read_max:
                    mark("tensor_read_skipped", key=key, estimated_bytes=estimated_bytes, max_bytes=args.tensor_read_max,
                         reason="word embedding exceeds bounded read size")
                    return 0
                mark("combined_tensor_read_before", file=path.name, key=key, shape=shape, dtype=dtype,
                     estimated_bytes=estimated_bytes)
                tensor = f.get_tensor(key)
                actual_shape = list(tensor.shape)
                actual_dtype = str(tensor.dtype)
                actual_bytes = tensor.numel() * tensor.element_size()
                mark("combined_tensor_materialized_metadata", file=path.name, key=key, shape=actual_shape,
                     dtype=actual_dtype, numel=tensor.numel(), element_size=tensor.element_size(),
                     actual_bytes=actual_bytes, expected_shape=shape, safetensors_dtype=dtype,
                     expected_bytes=estimated_bytes)
                expected_torch_dtype = SAFETENSORS_TO_TORCH_DTYPE.get(dtype)
                if actual_shape != shape or actual_dtype != expected_torch_dtype or actual_bytes != estimated_bytes:
                    raise RuntimeError("materialized tensor metadata differs from safetensors slice metadata")
                mark("combined_tensor_read_after", file=path.name, key=key, shape=actual_shape,
                     dtype=str(tensor.dtype), numel=tensor.numel(), estimated_bytes=estimated_bytes, parameter_count=parameter_count,
                     empty_model_parameter_count=sum(x.numel() for x in m.parameters()),
                     model_object_retained=True, tensor_object_retained=True)
        else: raise RuntimeError("unknown probe")
        after = snapshot(model)
        mark("post_snapshot", manifest_sha256=after["manifest_sha256"], unchanged=after["manifest_sha256"] == before["manifest_sha256"])
        if after["manifest_sha256"] != before["manifest_sha256"]: raise RuntimeError("model contents changed during probe")
        mark("probe_complete", probe=p, interpretation="No crash cause or semantic quality conclusion")
        return 0
    except ModuleNotFoundError as e:
        mark("probe_skipped", reason="required library unavailable", module=e.name)
        return 0
    except BaseException as e:
        mark("probe_error", error_type=type(e).__name__, error=str(e))
        return 2


def run(args) -> int:
    if os.name != "nt": raise RuntimeError("--run requires Windows")
    if not args.expected_sha256: raise RuntimeError("--expected-sha256 is required; use the independently recorded model manifest hash")
    requested = args.output_root.absolute()
    probe_path = requested
    while probe_path != probe_path.parent:
        if probe_path.exists() and (probe_path.is_symlink() or getattr(probe_path.stat(), "st_file_attributes", 0) & 0x400):
            raise RuntimeError("output path contains a symlink or reparse point")
        probe_path = probe_path.parent
    out = requested.resolve()
    var = (ROOT / "var").resolve(strict=True)
    if (ROOT / "var").is_symlink() or not out.is_relative_to(var): raise RuntimeError("output must be beneath non-symlink var")
    out.mkdir(parents=True, exist_ok=False)
    results = []
    probes = ["combined_probe"] if args.combined_only else ["tokenizer", "config", "safetensors_meta", "safetensors_small", "safetensors_large", "empty_model"]
    if args.combined_probe and not args.combined_only: probes.append("combined_probe")
    for probe in probes:
        started = time.monotonic(); cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "--probe", probe, "--model", str(args.model), "--tensor-read-max", str(args.tensor_read_max), "--job-limit-mib", str(args.job_limit_mib)]
        if args.expected_sha256: cmd += ["--expected-sha256", args.expected_sha256]
        stdout_path, stderr_path = out / f"{probe}.stdout.log", out / f"{probe}.stderr.log"
        with stdout_path.open("x", encoding="utf-8") as stdout_file, stderr_path.open("x", encoding="utf-8") as stderr_file:
            proc = subprocess.Popen(cmd, stdout=stdout_file, stderr=stderr_file, text=True)
        peak_private = peak_working = 0
        samples = 0
        sampling_error = None
        timed_out = False
        # Sample this child only; never enumerate or stop unrelated processes.
        try:
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                            ("PrivateUsage", ctypes.c_size_t)]
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            while proc.poll() is None:
                if time.monotonic() - started > PROBE_TIMEOUT_SECONDS:
                    timed_out = True
                    proc.kill()
                    break
                c = Counters(); c.cb = ctypes.sizeof(c)
                if psapi.GetProcessMemoryInfo(int(proc._handle), ctypes.byref(c), c.cb):
                    peak_private = max(peak_private, c.PrivateUsage)
                    peak_working = max(peak_working, c.WorkingSetSize)
                    samples += 1
                else:
                    sampling_error = f"GetProcessMemoryInfo failed: {ctypes.get_last_error()}"
                    break
                time.sleep(0.1)
        except Exception as e:
            sampling_error = f"{type(e).__name__}: {e}"
        if timed_out: proc.kill()
        proc.wait(timeout=10)
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        rows = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
        completed = any(r.get("stage") == "probe_complete" for r in rows)
        skipped = any(r.get("stage") in ("probe_skipped", "tensor_read_skipped") for r in rows)
        sample_state = "available" if samples else "unavailable"
        success = proc.returncode == 0 and not timed_out and (completed or skipped)
        results.append({"probe": probe, "requested_job_limit_mib": args.job_limit_mib, "actual_job_limit_bytes": args.job_limit_mib * 1024**2, "return_code": proc.returncode, "native_unsigned_status": proc.returncode & 0xFFFFFFFF,
                        "elapsed_seconds": round(time.monotonic()-started, 3),
                        "memory_sample_status": sample_state, "memory_sample_count": samples,
                        "peak_private_bytes_sampled": peak_private if samples else None,
                        "peak_working_set_bytes_sampled": peak_working if samples else None,
                        "memory_sampling_error": sampling_error,
                        "timed_out": timed_out, "completed": completed, "skipped": skipped,
                        "status": "passed" if success else "failed_or_incomplete", "stage_markers": rows, "stderr": stderr[-4000:]})
    all_ok = all(r["status"] == "passed" for r in results)
    any_skipped = any(r["skipped"] for r in results)
    report = {"status": "partial_failure" if not all_ok else ("completed_with_skips" if any_skipped else "diagnostic_complete_success"),
              "requested_job_limit_mib": args.job_limit_mib,
              "actual_job_limit_bytes": args.job_limit_mib * 1024**2,
              "experiment_mode": "combined_only" if args.combined_only else "standard",
              "crash_cause_assumed": False, "semantic_quality_claimed": False,
              "full_weight_load_performed": False, "probe_results": results,
              "note": "Tensor probes read one selected tensor each; empty_model initializes random parameters from config. combined_probe retains an empty config model while reading one bounded pretrained tensor; this does not prove why any prior full load succeeded or failed."}
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--expected-sha256", default="")
    ap.add_argument("--tensor-read-max", type=int, default=DEFAULT_TENSOR_READ_MAX,
                    help="maximum tensor bytes to read (default 134217728; allowed 134217728-536870912)")
    ap.add_argument("--output-root", type=Path, default=ROOT / "var/output" / f"e5-native-isolation-20261030-{uuid.uuid4().hex}")
    ap.add_argument("--run", action="store_true", help="explicitly run bounded isolated probes")
    ap.add_argument("--combined-probe", action="store_true", help="also run an isolated empty-model plus one bounded word-embedding read probe")
    ap.add_argument("--combined-only", action="store_true", help="run only the combined empty-model plus bounded tensor probe")
    ap.add_argument("--job-limit-mib", type=int, default=2048, help="Windows job memory limit in MiB (default 2048; allowed 2048-3072)")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--probe", choices=("tokenizer","config","safetensors_meta","safetensors_small","safetensors_large","empty_model","combined_probe"), default="tokenizer", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if not DEFAULT_TENSOR_READ_MAX <= args.tensor_read_max <= MAX_TENSOR_READ_MAX:
        ap.error(f"--tensor-read-max must be between {DEFAULT_TENSOR_READ_MAX} and {MAX_TENSOR_READ_MAX} bytes")
    if not MIN_JOB_LIMIT_MIB <= args.job_limit_mib <= MAX_JOB_LIMIT_MIB:
        ap.error(f"--job-limit-mib must be an integer between {MIN_JOB_LIMIT_MIB} and {MAX_JOB_LIMIT_MIB}")
    if args.child: return child(args)
    if not args.run:
        print("Preparation only. No model work performed; pass --run only after audit.")
        return 0
    return run(args)


if __name__ == "__main__": raise SystemExit(main())
