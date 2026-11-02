"""Opt-in, synthetic-only OCR + local E5 + FTS5/RRF smoke demonstration.

This is a bounded local experiment. It does not access the site's index, ACL,
or production database and does not benchmark semantic quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import socket
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(r"D:\project\q-agent-models\var\weights\multilingual-e5-small-v1")
OCR_RESULT = ROOT / "var/ocr-adapter-smoke-20261030-v2/result.json"
INCIDENT = "synthetic-ocr-e5-incident"
AS_OF = "2026-10-30"
EXPECTED_DIM = 384
_JOB_HANDLES = []


def model_manifest_sha256(folder: Path) -> str:
    """Hash every model file by relative path and content, excluding cache files."""
    digest = hashlib.sha256()
    files = sorted(p for p in folder.rglob("*") if p.is_file() and ".cache" not in p.parts)
    if not files:
        raise RuntimeError("model directory contains no files")
    for path in files:
        rel = path.relative_to(folder).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        content_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                content_hash.update(block)
        digest.update(content_hash.digest())
    return digest.hexdigest()


def require_idle_model_use(model_path: Path) -> None:
    """Refuse when another visible process appears to be using this model."""
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required to check for concurrent model processes") from exc
    needle = str(model_path.resolve()).casefold()
    for proc in psutil.process_iter(("pid", "cmdline")):
        if proc.pid == os.getpid():
            continue
        try:
            cmd = " ".join(proc.info.get("cmdline") or []).casefold()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if needle in cmd:
            raise RuntimeError(f"another process may be using the configured model (pid {proc.pid}); no process was stopped")


def require_windows_capacity(output_root: Path, job_limit_mib: int) -> None:
    if os.name != "nt":
        raise RuntimeError("the 2 GiB Job Object cap and capacity checks require Windows")
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
    status = PerformanceInfo(); status.cb = ctypes.sizeof(status)
    if not psapi.GetPerformanceInfo(ctypes.byref(status), status.cb):
        raise RuntimeError("could not read Windows commit capacity through PSAPI")
    available_commit = (status.CommitLimit - status.CommitTotal) * status.PageSize
    required_commit = job_limit_mib * 1024**2 + 4 * 1024**3
    if available_commit < required_commit:
        raise RuntimeError(f"at least {job_limit_mib / 1024 + 4:g} GiB of available Windows commit is required")
    var_path = ROOT / "var"
    if var_path.is_symlink():
        raise RuntimeError("Q-Agent var root must not be a symlink")
    var_root = var_path.resolve(strict=True)
    if not output_root.is_relative_to(var_root):
        raise RuntimeError("output root must be inside the Q-Agent var directory")
    if output_root.exists():
        raise RuntimeError("output root must not exist before the run")
    if shutil.disk_usage(var_root).free < 20 * 1024**3:
        raise RuntimeError("at least 20 GiB free disk space is required")


def confined_output_path(requested: Path) -> Path:
    var_root = (ROOT / "var").resolve(strict=True)
    lexical = Path(os.path.abspath(requested))
    if not lexical.is_relative_to(var_root):
        raise RuntimeError("output root must be lexically inside the Q-Agent var directory")
    cursor = lexical
    while cursor != var_root:
        if cursor.is_symlink():
            raise RuntimeError("output path and its existing parents must not contain symlinks")
        cursor = cursor.parent
    resolved = lexical.resolve(strict=False)
    if not resolved.is_relative_to(var_root) or resolved != lexical:
        raise RuntimeError("resolved output root escaped or differs from its Q-Agent var path")
    return lexical


def apply_job_memory_cap(job_limit_mib: int) -> None:
    """Apply a bounded per-process Job Object limit; fail closed on any error."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
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
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    info = ExtendedLimit(); info.BasicLimitInformation.LimitFlags = 0x00000100 | 0x00000200
    memory_limit = job_limit_mib * 1024**2
    info.ProcessMemoryLimit = memory_limit; info.JobMemoryLimit = memory_limit
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    _JOB_HANDLES.append(job)


def block_network() -> None:
    def denied(*_args, **_kwargs):
        raise RuntimeError("network access is disabled for this synthetic-only run")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def load_synthetic_data():
    payload = json.loads(OCR_RESULT.read_text(encoding="utf-8"))
    if payload.get("status") != "passed" or payload.get("synthetic_inputs_only") is not True:
        raise RuntimeError("OCR input is not a passed synthetic-only result")
    candidate = payload["outputs"][0]["candidate"]
    if candidate.get("source_document_id") != "synthetic-ko-document":
        raise RuntimeError("unexpected OCR source document identifier")
    # This source record is invented for this demonstration; it is not metadata
    # recovered from a real document, incident table, or site index.
    source = {"document_id": "synthetic-source-document-ko", "chunk_id": "synthetic-source-chunk-ko",
              "version": "synthetic-v1", "source_ref": "synthetic://invented/ocr-ko/page-1",
              "incident_ids": [INCIDENT], "relation": "direct", "available_at": "2026-10-29T00:00:00+00:00",
              "synthetic_fixture": True}
    candidate_for_bridge = dict(candidate)
    candidate_for_bridge["source_document_id"] = source["document_id"]
    candidate_for_bridge["source_version"] = source["version"]
    candidate_for_bridge["existing_chunk_id"] = source["chunk_id"]
    return candidate, candidate_for_bridge, source


def run(args) -> Path:
    model_path = args.model.resolve()
    if not model_path.is_dir():
        raise RuntimeError("local model directory does not exist")
    if not args.expected_model_sha256:
        raise RuntimeError("--expected-model-sha256 is required for caller-controlled local byte-snapshot comparison")
    actual_sha = model_manifest_sha256(model_path)
    if actual_sha.casefold() != args.expected_model_sha256.casefold():
        raise RuntimeError("local model manifest SHA-256 did not match the caller's expected value")
    output = confined_output_path(args.output_root)
    require_windows_capacity(output, args.job_limit_mib)
    require_idle_model_use(model_path)

    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    apply_job_memory_cap(args.job_limit_mib)
    import torch
    from transformers import AutoModel, AutoTokenizer
    # This script is invoked by file path, so Python otherwise puts only
    # research/ on sys.path. Add the verified project root for app imports.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "research"))
    from ocr_hybrid_synthetic_bridge_20261030 import SyntheticOCRHybridIndex, make_ocr_chunk, validate_for_qagent_contract

    torch.set_num_threads(1)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    block_network()
    print("[marker] model load start", file=sys.stderr, flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(model_path, local_files_only=True, trust_remote_code=False).to("cpu").eval()
    print("[marker] model load complete", file=sys.stderr, flush=True)

    def encode(texts):
        batch = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        with torch.no_grad():
            hidden = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().tolist()

    original_candidate, candidate_for_bridge, source = load_synthetic_data()
    ocr_chunk = make_ocr_chunk(candidate_for_bridge, source)
    chunks = [ocr_chunk,
              {"document_id": "synthetic-distractor-1", "chunk_id": "synthetic-distractor-1::chunk-1", "version": "1", "text": "합성 웨이퍼 가장자리 스크래치 점검 기록입니다.", "source_ref": "synthetic://distractor/1", "locator": "fixture:1", "status": "active", "available_at": "2026-10-29T00:00:00+00:00", "incident_ids": [INCIDENT], "relation": "direct", "synthetic_fixture": True},
              {"document_id": "synthetic-distractor-2", "chunk_id": "synthetic-distractor-2::chunk-1", "version": "1", "text": "합성 노광 장비 압력 점검 기록입니다.", "source_ref": "synthetic://distractor/2", "locator": "fixture:2", "status": "active", "available_at": "2026-10-29T00:00:00+00:00", "incident_ids": [INCIDENT], "relation": "direct", "synthetic_fixture": True}]
    query = "OCR테스트입니다 합성"
    observation_queries = ["인공 문자 인식 검사", "이미지에서 읽어낸 문구와 관련된 자료를 검색해줘"]
    vectors = encode(["passage: " + c["text"] for c in chunks])
    query_vectors = encode(["query: " + text for text in [query, *observation_queries]])
    query_vector = query_vectors[0]
    if len(query_vector) != EXPECTED_DIM or any(len(vector) != EXPECTED_DIM for vector in vectors):
        raise RuntimeError("E5 embedding dimension was not 384")
    print("[marker] embeddings complete", file=sys.stderr, flush=True)
    vector_map = {c["chunk_id"]: v for c, v in zip(chunks, vectors)}
    authorize = lambda _scope: True  # synthetic demonstration only; no ACL semantics
    index = SyntheticOCRHybridIndex(chunks, vector_map, authorize=authorize)
    try:
        print("[marker] RRF search start", file=sys.stderr, flush=True)
        lexical_ids = [row[0] for row in index.db.execute(
            "SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)", (query,))]
        vector_scores = {cid: sum(a * b for a, b in zip(query_vector, vector)) for cid, vector in vector_map.items()}
        response = index.search(query=query, query_vector=query_vector, incident_ids=[INCIDENT], as_of=AS_OF,
                                top_k=3, authorize=authorize, timezone_name="UTC", similarity_threshold=0.0)
        observed_retrieval = []
        for observed_query, observed_vector in zip(observation_queries, query_vectors[1:]):
            # Capture actual FTS5/BM25 hits for this phrasing. No expected hit
            # or preferred retrieval order is imposed on the observation.
            observed_lexical_rows = list(index.db.execute(
                "SELECT chunk_id, bm25(docs) AS score FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)",
                (observed_query,)))
            observed_lexical_ids = [row[0] for row in observed_lexical_rows]
            observed_vector_scores = {
                cid: sum(a * b for a, b in zip(observed_vector, vector))
                for cid, vector in vector_map.items()
            }
            observed_vector_ranked = sorted(
                observed_vector_scores, key=lambda cid: (-observed_vector_scores[cid], cid))
            observed_response = index.search(
                query=observed_query, query_vector=observed_vector, incident_ids=[INCIDENT], as_of=AS_OF,
                top_k=len(chunks), authorize=authorize, timezone_name="UTC", similarity_threshold=0.0)
            observed_hybrid_items = observed_response["items"]
            observed_hybrid_ranked = [item["chunk_id"] for item in observed_hybrid_items]
            target_id = ocr_chunk["chunk_id"]
            observed_retrieval.append({
                "query": observed_query,
                "ocr_target_chunk_id": target_id,
                "fts5_target_hit": target_id in observed_lexical_ids,
                "fts5_target_rank": observed_lexical_ids.index(target_id) + 1 if target_id in observed_lexical_ids else None,
                "fts5_hits": [{"chunk_id": row[0], "bm25_score": row[1], "rank": rank}
                               for rank, row in enumerate(observed_lexical_rows, 1)],
                "vector_target_rank": observed_vector_ranked.index(target_id) + 1,
                "vector_cosine_scores": observed_vector_scores,
                "hybrid_target_rank": observed_hybrid_ranked.index(target_id) + 1 if target_id in observed_hybrid_ranked else None,
                "hybrid_rrf_scores": {item["chunk_id"]: item.get("score") for item in observed_hybrid_items},
                "hybrid_items": observed_hybrid_items,
            })
    finally:
        index.close()
    validated = validate_for_qagent_contract(response, incident_ids=[INCIDENT], as_of=AS_OF,
                                               source_kind="internal_documents", timezone_name="UTC", top_k=3)
    print("[marker] RRF search complete", file=sys.stderr, flush=True)
    ranked_ids = [item["chunk_id"] for item in response["items"]]
    target_rank = ranked_ids.index(ocr_chunk["chunk_id"]) + 1 if ocr_chunk["chunk_id"] in ranked_ids else None
    lexical_hit = ocr_chunk["chunk_id"] in lexical_ids
    vector_ranked = sorted(vector_scores, key=lambda cid: (-vector_scores[cid], cid))
    vector_rank = vector_ranked.index(ocr_chunk["chunk_id"]) + 1
    if not lexical_hit or target_rank != 1 or response.get("retrieval_method") != "bm25_vector_hybrid":
        raise RuntimeError("OCR candidate must be an FTS5 hit and rank first after hybrid fusion")
    result = {"status": "passed", "synthetic_only": True, "model_manifest_sha256": actual_sha,
              "model_directory": str(model_path), "dimensions": len(query_vector), "expected_dimensions": EXPECTED_DIM,
              "ocr_candidate_chunk_id": ocr_chunk["chunk_id"], "query": query,
              "original_ocr_candidate": original_candidate,
              "source_metadata_origin": "invented_synthetic_fixture",
              "lexical_hit": lexical_hit, "lexical_rank": lexical_ids.index(ocr_chunk["chunk_id"]) + 1,
              "e5_cosine_scores": vector_scores, "e5_rank": vector_rank,
              "observation_queries": observed_retrieval,
              "hybrid_target_rank": target_rank, "evidence_contract_valid": True,
              "validated_response": validated,
              "limits": ["synthetic OCR fixture only", "fake allow callback is not an ACL", "in-memory FTS5/RRF is not the site index", "few documents and query/OCR tokenization differences make these phrase-sensitive observations, not semantic-only quality evidence", "observation queries are not a semantic benchmark"]}
    output = confined_output_path(output)
    output.mkdir(parents=True, exist_ok=False)
    result_path = output / "result.json"
    try:
        print("[marker] result save start", file=sys.stderr, flush=True)
        with result_path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print("[marker] result save complete", file=sys.stderr, flush=True)
    except Exception:
        # Keep any unexpected pre-existing result untouched; remove only the
        # empty directory created by this run when it is still empty.
        try:
            output.rmdir()
        except OSError:
            pass
        raise
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="perform the bounded synthetic-only model run")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--expected-model-sha256", help="caller-provided aggregate model SHA-256 for byte-snapshot comparison (not source authentication)")
    def job_limit_mib(value: str) -> int:
        try:
            limit = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer from 2048 through 3072 MiB") from exc
        if not 2048 <= limit <= 3072:
            raise argparse.ArgumentTypeError("must be from 2048 through 3072 MiB")
        return limit
    parser.add_argument("--job-limit-mib", type=job_limit_mib, default=2048,
                        metavar="2048..3072", help="per-process and Job Object memory cap in MiB (default: 2048; max: 3072)")
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/output/ocr-e5-hybrid-smoke-20261030")
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    try:
        result = run(args)
    except Exception as exc:
        print(f"smoke refused/failed: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
