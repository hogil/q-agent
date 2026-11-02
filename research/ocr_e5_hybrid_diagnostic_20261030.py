"""Opt-in staged diagnostic for the synthetic OCR to local E5 hybrid path.

Importing this module or asking for help performs no model work. Only --run
starts a bounded child process. The experiment is synthetic and diagnostic;
its outcome is not evidence of production retrieval quality.
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
OCR_RESULT = ROOT / "var/ocr-adapter-smoke-20261030-v2/result.json"
OCR_LOG = ROOT / "var/ocr-adapter-smoke-20261030-v2/stdout.log"
EXPECTED_OCR_TEXT = "합성OCR테스트입니다"
EXPECTED_IMAGE_SHA256 = "eaed2b1466b95f6e8ac1830e103309d610a83010ba53626171a3f428d21b6926"
INCIDENT = "synthetic-ocr-e5-incident"
AS_OF = "2026-10-30"
EXPECTED_DIM = 384
CAP_BYTES = 2 * 1024**3
_JOB_HANDLES = []


def marker(name: str, **details) -> None:
    print(json.dumps({"stage": name, **details}, ensure_ascii=False), flush=True)


def model_manifest_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in folder.rglob("*") if p.is_file() and ".cache" not in p.parts)
    if not files:
        raise RuntimeError("model directory contains no files")
    for path in files:
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        content_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                content_hash.update(block)
        digest.update(content_hash.digest())
    return digest.hexdigest()


def apply_capacity_guard(output_root: Path) -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows PSAPI and Job Object checks are required")
    import ctypes
    from ctypes import wintypes

    class PerformanceInfo(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t),
                    ("CommitLimit", ctypes.c_size_t), ("CommitPeak", ctypes.c_size_t),
                    ("PhysicalTotal", ctypes.c_size_t), ("PhysicalAvailable", ctypes.c_size_t),
                    ("SystemCache", ctypes.c_size_t), ("KernelTotal", ctypes.c_size_t),
                    ("KernelPaged", ctypes.c_size_t), ("KernelNonpaged", ctypes.c_size_t),
                    ("PageSize", ctypes.c_size_t), ("HandleCount", wintypes.DWORD),
                    ("ProcessCount", wintypes.DWORD), ("ThreadCount", wintypes.DWORD)]

    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PerformanceInfo), wintypes.DWORD]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL
    pi = PerformanceInfo(); pi.cb = ctypes.sizeof(pi)
    if not psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
        raise OSError(ctypes.get_last_error(), "GetPerformanceInfo failed")
    available_commit = (pi.CommitLimit - pi.CommitTotal) * pi.PageSize
    var_root = (ROOT / "var").resolve(strict=True)
    if (ROOT / "var").is_symlink() or not output_root.resolve(strict=False).is_relative_to(var_root):
        raise RuntimeError("output root must be inside the non-symlink Q-Agent var directory")
    if not output_root.is_dir() or {p.name for p in output_root.iterdir()} != {"stdout.bin", "stderr.bin"}:
        raise RuntimeError("output root must be the fresh wrapper-owned directory with only its exclusive log files")
    free_disk = shutil.disk_usage(Path("D:\\")).free
    details = {"available_commit_bytes": available_commit, "required_commit_bytes": 4 * 1024**3,
               "d_free_bytes": free_disk, "required_d_free_bytes": 20 * 1024**3}
    if available_commit < details["required_commit_bytes"] or free_disk < details["required_d_free_bytes"]:
        raise RuntimeError(f"capacity guard failed: {details}")
    return details


def apply_job_cap() -> dict:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    info = ExtendedLimit(); info.BasicLimitInformation.LimitFlags = 0x100 | 0x200
    info.ProcessMemoryLimit = CAP_BYTES; info.JobMemoryLimit = CAP_BYTES
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    _JOB_HANDLES.append(job)
    return {"process_cap_bytes": CAP_BYTES, "job_cap_bytes": CAP_BYTES,
            "limit_flags": info.BasicLimitInformation.LimitFlags, "job_handle": int(job)}


def block_network() -> None:
    def denied(*_args, **_kwargs):
        raise RuntimeError("socket network access is disabled")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def load_synthetic_data():
    payload = json.loads(OCR_RESULT.read_text(encoding="utf-8"))
    log_lines = OCR_LOG.read_text(encoding="utf-8").splitlines()
    log_summary = json.loads(log_lines[-1]) if log_lines else {}
    if (payload.get("status") != "passed" or payload.get("synthetic_inputs_only") is not True
            or payload.get("fake_authorization_only") is not True or payload.get("no_live_rag_write") is not True
            or not log_lines or log_lines[0].strip() != "structured result in result.json"
            or log_summary.get("status") != "passed" or log_summary.get("failed_assertions") != []):
        raise RuntimeError("OCR result is not marked passed and synthetic-only")
    rows = payload.get("outputs")
    korean_rows = [r for r in rows if isinstance(r, dict) and r.get("language") == "ko"] if isinstance(rows, list) else []
    if len(korean_rows) != 1:
        raise RuntimeError("OCR fixture does not have exactly one Korean synthetic output")
    row = korean_rows[0]
    candidate = row.get("candidate")
    observed = "".join(x.get("text", "") for x in candidate.get("ordered_text_confidence", []))
    if (candidate.get("source_document_id") != "synthetic-ko-document" or observed != EXPECTED_OCR_TEXT
            or row.get("observed_text") != EXPECTED_OCR_TEXT or row.get("expected_text") != "합성 OCR 테스트입니다"
            or candidate.get("image_sha256") != EXPECTED_IMAGE_SHA256 or row.get("image_sha256") != EXPECTED_IMAGE_SHA256
            or candidate.get("original_sha256_provenance") != "caller_asserted_unverified"):
        raise RuntimeError("OCR fixture source, recognized text, or image hash did not match its synthetic contract")
    source = {"document_id": "synthetic-source-document-ko", "chunk_id": "synthetic-source-chunk-ko",
              "version": "synthetic-v1", "source_ref": "synthetic://invented/ocr-ko/page-1",
              "incident_ids": [INCIDENT], "available_at": "2026-10-29T00:00:00+00:00", "synthetic_fixture": True}
    bridged = dict(candidate, source_document_id=source["document_id"], source_version=source["version"],
                   existing_chunk_id=source["chunk_id"])
    return bridged, source


def child(args) -> int:
    try:
        marker("preflight_start")
        model_path = args.model.resolve(strict=True)
        if not model_path.is_dir(): raise RuntimeError("model path is not a directory")
        if not args.expected_model_sha256: raise RuntimeError("caller expected model SHA-256 is required")
        if not args.model_provenance: raise RuntimeError("caller-asserted model provenance is required")
        actual_sha = model_manifest_sha256(model_path)
        if actual_sha.casefold() != args.expected_model_sha256.casefold():
            raise RuntimeError("model manifest SHA-256 mismatch")
        marker("preflight_complete", model_manifest_sha256=actual_sha,
               model_provenance=args.model_provenance, provenance_is_caller_asserted=True)
        marker("psapi_guard_before")
        capacity = apply_capacity_guard(args.output_root)
        marker("psapi_guard_after", **capacity)
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ[name] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        marker("job_cap_before")
        cap = apply_job_cap()
        marker("job_cap_after", **cap)
        marker("torch_import_before")
        import torch
        marker("torch_import_after", version=torch.__version__)
        marker("transformers_import_before")
        from transformers import AutoModel, AutoTokenizer
        marker("transformers_import_after")
        sys.path.insert(0, str(ROOT / "research"))
        from ocr_hybrid_synthetic_bridge_20261030 import SyntheticOCRHybridIndex, make_ocr_chunk, validate_for_qagent_contract
        torch.set_num_threads(1); torch.manual_seed(0); torch.use_deterministic_algorithms(True)
        block_network()
        marker("tokenizer_construction_before")
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
        marker("tokenizer_construction_after")
        marker("model_construction_weights_before")
        model = AutoModel.from_pretrained(model_path, local_files_only=True, trust_remote_code=False).to("cpu").eval()
        marker("model_construction_weights_after")
        marker("model_manifest_after_load_before")
        post_load_sha = model_manifest_sha256(model_path)
        marker("model_manifest_after_load_after", model_manifest_sha256=post_load_sha,
               changed_during_load=post_load_sha.casefold() != actual_sha.casefold())
        if post_load_sha.casefold() != actual_sha.casefold():
            raise RuntimeError("model manifest changed during load; provenance and TOCTOU are not independently authenticated")

        def encode(texts):
            batch = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
            with torch.no_grad():
                hidden = model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().tolist()
        bridged, source = load_synthetic_data()
        ocr_chunk = make_ocr_chunk(bridged, source)
        chunks = [ocr_chunk,
                  {"document_id":"synthetic-distractor-1","chunk_id":"synthetic-distractor-1::chunk-1","version":"1","text":"합성 웨이퍼 가장자리 스크래치 점검 기록입니다.","source_ref":"synthetic://distractor/1","locator":"fixture:1","status":"active","available_at":"2026-10-29T00:00:00+00:00","incident_ids":[INCIDENT],"synthetic_fixture":True},
                  {"document_id":"synthetic-distractor-2","chunk_id":"synthetic-distractor-2::chunk-1","version":"1","text":"합성 노광 장비 압력 점검 기록입니다.","source_ref":"synthetic://distractor/2","locator":"fixture:2","status":"active","available_at":"2026-10-29T00:00:00+00:00","incident_ids":[INCIDENT],"synthetic_fixture":True}]
        query = "OCR테스트입니다 합성"
        marker("encode_before", item_count=len(chunks) + 1)
        vectors = encode(["passage: " + c["text"] for c in chunks]); query_vector = encode(["query: " + query])[0]
        marker("encode_after", dimensions=len(query_vector))
        vector_map = {c["chunk_id"]: v for c, v in zip(chunks, vectors)}
        authorize = lambda _scope: True
        marker("index_before")
        index = SyntheticOCRHybridIndex(chunks, vector_map, authorize=authorize)
        marker("index_after", chunk_count=len(chunks))
        try:
            marker("search_before")
            lexical_ids = [r[0] for r in index.db.execute("SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)", (query,))]
            response = index.search(query=query, query_vector=query_vector, incident_ids=[INCIDENT], as_of=AS_OF,
                top_k=3, authorize=authorize, timezone_name="UTC", similarity_threshold=0.0)
            marker("search_after", lexical_hit=ocr_chunk["chunk_id"] in lexical_ids,
                   hybrid_target_rank=next((i + 1 for i, it in enumerate(response["items"]) if it["chunk_id"] == ocr_chunk["chunk_id"]), None))
        finally:
            index.close()
        marker("response_validation_before")
        validated = validate_for_qagent_contract(response, incident_ids=[INCIDENT], as_of=AS_OF,
            source_kind="internal_documents", timezone_name="UTC", top_k=3)
        marker("response_validation_after")
        result = {"status":"diagnostic_completed", "synthetic_only":True,
                  "implementation":"separate_diagnostic_reimplementation_not_original_smoke_invocation",
                  "shared_stages":["synthetic OCR candidate-to-chunk contract", "local E5 tokenizer/model encode", "in-memory FTS5 plus vector RRF search", "response contract validation"],
                  "original_smoke_failure_stage":"unknown; this run does not establish the earlier failure stage",
                  "model_manifest_sha256":actual_sha,"model_provenance":args.model_provenance,
                  "post_load_model_manifest_sha256":post_load_sha,
                  "model_provenance_limit":"caller asserted; source authenticity and model file TOCTOU are not fully proven",
                  "model_directory":str(model_path),"dimensions":len(query_vector),"expected_dimensions":EXPECTED_DIM,
                  "ocr_candidate_chunk_id":ocr_chunk["chunk_id"],"query":query,
                  "ocr_fixture_contract_verified":True,"source_metadata_origin":"invented_synthetic_fixture",
                  "validated_response":validated,"diagnostic_only":True}
        marker("output_before")
        with (args.output_root / "result.json").open("x", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2); f.write("\n")
        marker("output_after", result_path=str(args.output_root / "result.json"))
        return 0
    except BaseException as exc:
        marker("child_error", error_type=type(exc).__name__, error=str(exc))
        return 1


def peak_usage(pid: int) -> dict:
    if os.name != "nt": return {"error": "Windows only"}
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True); psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]; kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle: return {"error": "OpenProcess", "winerror": ctypes.get_last_error()}
    try:
        c = Counters(); c.cb = ctypes.sizeof(c)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
            return {"error": "GetProcessMemoryInfo", "winerror": ctypes.get_last_error()}
        return {"private_bytes": c.PrivateUsage, "working_set_bytes": c.WorkingSetSize,
                "peak_private_bytes": c.PeakPagefileUsage, "peak_working_set_bytes": c.PeakWorkingSetSize}
    finally:
        kernel.CloseHandle(handle)


def parent(args) -> int:
    if os.name != "nt": raise RuntimeError("diagnostic harness requires Windows")
    var_root = (ROOT / "var").resolve(strict=True)
    if (ROOT / "var").is_symlink(): raise RuntimeError("Q-Agent var root must not be a symlink")
    output = Path(os.path.abspath(args.output_root))
    if not output.is_relative_to(var_root): raise RuntimeError("output root must be inside Q-Agent var")
    cursor = output
    while cursor != var_root:
        if cursor.is_symlink(): raise RuntimeError("output path parents must not contain symlinks")
        cursor = cursor.parent
    if output.exists(): raise RuntimeError("output root already exists; refusing overwrite")
    cmd = [sys.executable, str(Path(__file__).resolve()), "--run", "--_child", "--model", str(args.model),
           "--expected-model-sha256", args.expected_model_sha256 or "", "--model-provenance", args.model_provenance or "",
           "--output-root", str(output)]
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    output.mkdir(parents=True, exist_ok=False)
    stdout_path, stderr_path = output / "stdout.bin", output / "stderr.bin"
    samples = []
    start = time.monotonic(); timed_out = False
    with stdout_path.open("xb") as stdout_stream, stderr_path.open("xb") as stderr_stream:
        proc = subprocess.Popen(cmd, stdout=stdout_stream, stderr=stderr_stream, env=env)
        while proc.poll() is None:
            samples.append({"elapsed_seconds": round(time.monotonic() - start, 3), **peak_usage(proc.pid)})
            if time.monotonic() - start >= args.timeout_seconds:
                timed_out = True
                proc.kill()  # Only the child started by this wrapper.
                break
            time.sleep(0.25)
        proc.wait()
    raw_rc = proc.returncode & 0xFFFFFFFF
    summary = {"implementation":"separate_diagnostic_reimplementation_not_original_smoke_invocation",
               "shared_stages":["synthetic OCR candidate-to-chunk contract", "local E5 tokenizer/model encode", "in-memory FTS5 plus vector RRF search", "response contract validation"],
               "original_smoke_failure_stage":"unknown; this run does not establish the earlier failure stage",
               "child_pid": proc.pid, "raw_return_code_unsigned": raw_rc, "timed_out": timed_out,
               "timeout_seconds": args.timeout_seconds, "peak_samples": samples,
               "peak_private_bytes_observed": max((x.get("peak_private_bytes", 0) for x in samples), default=0),
               "peak_working_set_bytes_observed": max((x.get("peak_working_set_bytes", 0) for x in samples), default=0),
               "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}
    with (output / "wrapper-summary.json").open("x", encoding="utf-8") as f:
        json.dump(summary, f, indent=2); f.write("\n")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if raw_rc == 0 and not timed_out else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="launch bounded diagnostic child")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--expected-model-sha256", help="caller-provided aggregate manifest SHA-256")
    parser.add_argument("--model-provenance", help="caller-asserted provenance statement; not independently authenticated")
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/output" / f"ocr-e5-hybrid-diagnostic-20261030-{uuid.uuid4().hex}")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.run:
        parser.print_help(); return 0
    if args.timeout_seconds < 1 or args.timeout_seconds > 1800:
        parser.error("--timeout-seconds must be 1..1800")
    try:
        return child(args) if args._child else parent(args)
    except Exception as exc:
        print(f"diagnostic wrapper failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
