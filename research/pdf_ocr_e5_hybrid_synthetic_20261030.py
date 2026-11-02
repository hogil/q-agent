"""Opt-in synthetic PDF OCR provenance -> local E5 -> FTS5/RRF smoke.

This bounded experiment does not exercise company ACLs, production RAG, or
real-document coverage. Its caller-supplied hashes are byte-snapshot checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(r"D:\project\q-agent-models\var\weights\multilingual-e5-small-v1")
INCIDENT = "synthetic-pdf-e5-incident"
AS_OF = "2026-10-30"
EXPECTED_DIM = 384
_JOB_HANDLES = []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def model_manifest_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in folder.rglob("*") if p.is_file() and ".cache" not in p.parts)
    if not files:
        raise RuntimeError("model directory contains no files")
    for path in files:
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def confined_var_file(path: Path) -> Path:
    var = ROOT / "var"
    if var.is_symlink():
        raise RuntimeError("Q-Agent var root must not be a symlink")
    var = var.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    if not lexical.is_relative_to(var):
        raise RuntimeError("input and output paths must be inside Q-Agent var")
    cursor = lexical
    while cursor != var:
        if cursor.is_symlink():
            raise RuntimeError("path must not traverse symlinks")
        cursor = cursor.parent
    resolved = lexical.resolve(strict=False)
    if resolved != lexical or not resolved.is_relative_to(var):
        raise RuntimeError("path escaped the Q-Agent var directory")
    return lexical


def require_windows_capacity(output: Path, limit: int) -> None:
    if os.name != "nt":
        raise RuntimeError("Windows Job Object and capacity checks are required")
    import ctypes
    from ctypes import wintypes
    class PI(ctypes.Structure):
        _fields_ = [(n, ctypes.c_size_t) for n in ("cb", "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")] + [(n, wintypes.DWORD) for n in ("HandleCount", "ProcessCount", "ThreadCount")]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PI), wintypes.DWORD]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL
    info = PI(); info.cb = ctypes.sizeof(info)
    if not psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise RuntimeError("could not read Windows commit capacity")
    if (info.CommitLimit-info.CommitTotal)*info.PageSize < limit*1024**2 + 4*1024**3:
        raise RuntimeError("at least 7 GiB available commit is required at the minimum job cap")
    var = (ROOT / "var").resolve(strict=True)
    if output.exists():
        raise RuntimeError("output directory must not already exist")
    if shutil.disk_usage(var).free < 20*1024**3:
        raise RuntimeError("at least 20 GiB free disk is required")


def apply_job_memory_cap(limit: int) -> None:
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]; k.CreateJobObjectW.restype=wintypes.HANDLE
    k.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]; k.SetInformationJobObject.restype=wintypes.BOOL
    k.GetCurrentProcess.argtypes=[]; k.GetCurrentProcess.restype=wintypes.HANDLE
    k.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]; k.AssignProcessToJobObject.restype=wintypes.BOOL
    class Basic(ctypes.Structure):
        _fields_=[("times",ctypes.c_longlong*2),("LimitFlags",wintypes.DWORD),("MinimumWorkingSetSize",ctypes.c_size_t),("MaximumWorkingSetSize",ctypes.c_size_t),("ActiveProcessLimit",wintypes.DWORD),("Affinity",ctypes.c_size_t),("PriorityClass",wintypes.DWORD),("SchedulingClass",wintypes.DWORD)]
    class IO(ctypes.Structure): _fields_=[(n,ctypes.c_ulonglong) for n in ("ReadOperationCount","WriteOperationCount","OtherOperationCount","ReadTransferCount","WriteTransferCount","OtherTransferCount")]
    class Ext(ctypes.Structure): _fields_=[("BasicLimitInformation",Basic),("IoInfo",IO),("ProcessMemoryLimit",ctypes.c_size_t),("JobMemoryLimit",ctypes.c_size_t),("PeakProcessMemoryUsed",ctypes.c_size_t),("PeakJobMemoryUsed",ctypes.c_size_t)]
    job=k.CreateJobObjectW(None,None)
    if not job: raise OSError(ctypes.get_last_error(),"CreateJobObjectW")
    info=Ext(); info.BasicLimitInformation.LimitFlags=0x100|0x200; info.ProcessMemoryLimit=limit*1024**2; info.JobMemoryLimit=limit*1024**2
    if not k.SetInformationJobObject(job,9,ctypes.byref(info),ctypes.sizeof(info)) or not k.AssignProcessToJobObject(job,k.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(),"Job Object memory cap")
    _JOB_HANDLES.append(job)


def block_network() -> None:
    def denied(*_a, **_kw): raise RuntimeError("network disabled for this local_only synthetic run")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def prepare_candidates(payload: dict):
    if payload.get("status") != "passed" or payload.get("attempt") != "synthetic_pdf_real_rapidocr_cpu":
        raise RuntimeError("PDF OCR result must be a passed synthetic_pdf_real_rapidocr_cpu attempt")
    if payload.get("authorization") != "fake_allow_only" or payload.get("candidate_count") != 2:
        raise RuntimeError("expected fake_allow_only authorization and exactly two candidates")
    candidates = payload.get("full_candidates")
    source_info = payload.get("pdf_source")
    if not isinstance(candidates, list) or len(candidates) != 2 or not isinstance(source_info, dict):
        raise RuntimeError("two full candidates and PDF source provenance are required")
    if source_info.get("synthetic_only") is not True:
        raise RuntimeError("PDF source must be marked synthetic_only")
    source_id, version = source_info.get("source_document_id"), source_info.get("source_version")
    chunks = []
    for c in candidates:
        if c.get("status") != "candidate_unreviewed" or c.get("source_document_id") != source_id or c.get("source_version") != version:
            raise RuntimeError("candidate status or source identity/version changed")
        if c.get("existing_chunk_id") is None or c.get("page") is None or c.get("page_bbox") is None:
            raise RuntimeError("candidate original page/chunk locator provenance is incomplete")
    if len({(c["source_document_id"], c["source_version"], c["existing_chunk_id"]) for c in candidates}) != 1:
        raise RuntimeError("both OCR candidates must link to the same source chunk/version")
    source = {"document_id": source_id, "chunk_id": candidates[0]["existing_chunk_id"],
              "version": version, "source_ref": f"synthetic://pdf/{source_id}/page-{candidates[0]['page']}",
              "incident_ids": [INCIDENT], "relation": "direct", "available_at": "2026-10-29T00:00:00+00:00",
              "synthetic_fixture": True}
    if source_id != "synthetic-pdf-ko" or version != "1":
        raise RuntimeError("unexpected synthetic PDF source identity/version")
    from ocr_hybrid_synthetic_bridge_20261030 import make_ocr_chunk
    for c in candidates:
        chunks.append(make_ocr_chunk(c, source))
    if chunks[0]["chunk_id"] == chunks[1]["chunk_id"]:
        raise RuntimeError("OCR candidates did not produce distinct chunk IDs")
    distractor = {"document_id":"synthetic-distractor","chunk_id":"synthetic-distractor::chunk-1","version":"1",
        "text":"합성 웨이퍼 가장자리 스크래치 점검 기록입니다.","source_ref":"synthetic://distractor/1","locator":"fixture:1",
        "status":"active","available_at":"2026-10-29T00:00:00+00:00","incident_ids":[INCIDENT],"relation":"direct","synthetic_fixture":True}
    return candidates, source, chunks + [distractor]


def run(args) -> Path:
    for value, label in ((args.expected_pdf_sha256, "--expected-pdf-sha256"), (args.expected_model_sha256, "--expected-model-sha256")):
        if len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
            raise RuntimeError(f"{label} must be exactly 64 hexadecimal characters")
    pdf_result = confined_var_file(args.pdf_result).resolve(strict=True)
    if not pdf_result.is_file(): raise RuntimeError("PDF result must be a file")
    expected_pdf = args.expected_pdf_sha256.lower()
    actual_pdf = sha256_file(pdf_result)
    if actual_pdf != expected_pdf: raise RuntimeError("PDF result SHA-256 mismatch")
    payload = json.loads(pdf_result.read_text(encoding="utf-8"))
    candidates, source, chunks = prepare_candidates(payload)
    model_path = args.model.resolve(strict=True)
    if not model_path.is_dir(): raise RuntimeError("local E5 model directory is missing")
    model_sha = model_manifest_sha256(model_path)
    if model_sha != args.expected_model_sha256.lower(): raise RuntimeError("model manifest SHA-256 mismatch")
    output = confined_var_file(args.output_root)
    require_windows_capacity(output, args.job_limit_mib)
    os.environ.update({k:"1" for k in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS")})
    os.environ["TOKENIZERS_PARALLELISM"]="false"
    apply_job_memory_cap(args.job_limit_mib)
    if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
    if str(ROOT/"research") not in sys.path: sys.path.insert(1,str(ROOT/"research"))
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(1); torch.manual_seed(0); torch.use_deterministic_algorithms(True)
    block_network()
    tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True,trust_remote_code=False)
    model=AutoModel.from_pretrained(model_path,local_files_only=True,trust_remote_code=False).to("cpu").eval()
    def encode(texts):
        batch=tokenizer(texts,padding=True,truncation=True,max_length=256,return_tensors="pt")
        with torch.no_grad():
            hidden=model(**batch).last_hidden_state; mask=batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled=(hidden*mask).sum(1)/mask.sum(1).clamp(min=1)
            return torch.nn.functional.normalize(pooled,p=2,dim=1).cpu().tolist()
    from ocr_hybrid_synthetic_bridge_20261030 import SyntheticOCRHybridIndex, validate_for_qagent_contract
    # This token query is a lexical mechanics check on the known synthetic OCR
    # text, not evidence of semantic retrieval quality.
    query="OCR테스트입니다 합성"
    vectors=encode(["passage: "+c["text"] for c in chunks])
    qv=encode(["query: "+query])[0]
    if len(qv)!=EXPECTED_DIM or any(len(v)!=EXPECTED_DIM for v in vectors): raise RuntimeError("E5 output dimension was not 384")
    vector_map={c["chunk_id"]:v for c,v in zip(chunks,vectors)}
    authorize=lambda _scope: True
    index=SyntheticOCRHybridIndex(chunks,vector_map,authorize=authorize)
    try:
        lexical=[r[0] for r in index.db.execute("SELECT chunk_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)",(query,))]
        response=index.search(query=query,query_vector=qv,incident_ids=[INCIDENT],as_of=AS_OF,top_k=3,authorize=authorize,timezone_name="UTC",similarity_threshold=0.0)
    finally: index.close()
    validated=validate_for_qagent_contract(response,incident_ids=[INCIDENT],as_of=AS_OF,source_kind="internal_documents",timezone_name="UTC",top_k=3)
    ids=[x["chunk_id"] for x in response["items"]]
    target_ids=[c["chunk_id"] for c in chunks[:2]]
    target_items=[x for x in response["items"] if x["chunk_id"] in target_ids]
    bboxes=[json.loads(x["locator"])["page_bbox"] for x in target_items]
    if response["retrieval_method"]!="bm25_vector_hybrid" or len(target_items)!=2 or not set(target_ids).issubset(lexical) or len({json.dumps(b) for b in bboxes})!=2:
        raise RuntimeError("hybrid result must preserve both FTS hits and distinct page bbox locators in top 3")
    result={"status":"passed","attempt":"synthetic_pdf_ocr_e5_hybrid_cpu","synthetic_only":True,
        "pdf_result_path":str(pdf_result),"pdf_result_sha256":actual_pdf,"model_directory":str(model_path),"model_manifest_sha256":model_sha,
        "dimensions":len(qv),"query":query,"query_prefix":"query: ","passage_prefix":"passage: ","pooling":"attention-mask mean pooling then L2 normalization","device":"cpu",
        "source_metadata_origin":"synthetic_pdf_smoke_result","original_pdf_provenance":payload.get("pdf_source"),
        "candidate_original_hashes_and_provenance":[{k:c.get(k) for k in ("original_sha256","original_sha256_provenance","page_chunk_id_provenance","source_document_id","source_version","existing_chunk_id","page","region_id","page_bbox","page_bbox_coordinate_frame","page_rotation_degrees","visibility_status")} for c in candidates],
        "candidate_chunk_ids":target_ids,"fts5_hits":lexical,"hybrid_ranked_chunk_ids":ids,"hybrid_items":response["items"],
        "both_candidates_in_top3":True,"both_candidates_are_fts_hits":True,"distinct_page_bboxes_preserved_and_in_locators":True,
        "validated_response":validated,"authorization":"fake_allow_only","limitations":["synthetic-only; fake allow callback is not an ACL","not company ACL, production RAG, or real-document validation","coverage incomplete: vector graphics, clipped/occluded/composited visible pixels not covered","identical OCR text means candidate rank order is not meaningful or constrained"]}
    output.mkdir(parents=True,exist_ok=False)
    dest=output/"result.json"
    with dest.open("x",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2); f.write("\n")
    return dest


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--run",action="store_true")
    p.add_argument("--pdf-result",type=Path,required=True); p.add_argument("--expected-pdf-sha256",required=True)
    p.add_argument("--model",type=Path,default=DEFAULT_MODEL); p.add_argument("--expected-model-sha256",required=True)
    def limit(v):
        try: n=int(v)
        except ValueError as e: raise argparse.ArgumentTypeError("must be 2048..3072 MiB") from e
        if not 2048<=n<=3072: raise argparse.ArgumentTypeError("must be 2048..3072 MiB")
        return n
    p.add_argument("--job-limit-mib",type=limit,default=2048)
    p.add_argument("--output-root",type=Path,required=True)
    a=p.parse_args()
    if not a.run: p.print_help(); return 0
    try: result=run(a)
    except Exception as e: print(f"smoke refused/failed: {e}",file=sys.stderr); return 2
    print(result); return 0

if __name__=="__main__": raise SystemExit(main())
