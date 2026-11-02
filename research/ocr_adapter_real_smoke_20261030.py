"""One-shot actual RapidOCR injection smoke; synthetic images only."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import gc
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from datetime import datetime, timezone


ROOT = Path(r"D:\project\q-agent\var\ocr-runtime-20261030")
OUT = Path(r"D:\project\q-agent\var\ocr-adapter-smoke-20261030-v2")
ADAPTER = Path(r"D:\project\q-agent\research\document_image_ocr_adapter_20261030.py")


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class EXT_LIMIT(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def install_job_cap():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
    info = EXT_LIMIT()
    info.BasicLimitInformation.LimitFlags = 0x100
    info.ProcessMemoryLimit = 1536 * 1024 * 1024
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
    return kernel, handle


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def peak_memory(kernel):
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    info = PMC()
    info.cb = ctypes.sizeof(info)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
        return None
    return {"peak_working_set_mib": round(info.PeakWorkingSetSize / 1048576, 1),
            "peak_private_mib": round(info.PeakPagefileUsage / 1048576, 1)}


def main():
    if OUT.exists():
        raise RuntimeError("output directory already exists; refusing overwrite")
    OUT.mkdir(parents=True)
    kernel, job_handle = install_job_cap()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ[name] = "1"
    def blocked(*_args, **_kwargs):
        raise RuntimeError("network disabled by socket.connect/connect_ex guard")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked

    sys.path.insert(0, str(ADAPTER.parent))
    from document_image_ocr_adapter_20261030 import OCRModelConfig, extract_ocr_candidate
    from PIL import Image
    from rapidocr import RapidOCR

    manifest = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(maxsplit=1)
        manifest[rel.strip()] = digest
    outputs = []
    assertions = []
    for lang, rec, image_name, expected in (
        ("ko", "korean", "synthetic-ko.png", "합성 OCR 테스트입니다"),
        ("en", "en", "synthetic-en.png", "SYNTHETIC OCR TEST 2026"),
    ):
        det = ROOT / "models" / "ch_PP-OCRv5_det_mobile.onnx"
        rec_path = ROOT / "models" / f"{rec}_PP-OCRv5_rec_mobile.onnx"
        image = ROOT / image_name
        for p in (det, rec_path, image, ROOT / f"rapidocr-{lang}.yaml"):
            if not p.is_file() or not p.resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError("input/config/model path failed runtime-root check")
        det_hash, rec_hash = sha(det), sha(rec_path)
        expected_det = manifest["models/ch_PP-OCRv5_det_mobile.onnx"]
        expected_rec = manifest[f"models/{rec_path.name}"]
        if det_hash != expected_det or rec_hash != expected_rec:
            raise RuntimeError("local model hash does not match read-only SHA256SUMS")
        image_hash = sha(image)
        with Image.open(image) as im:
            width, height = im.size
        config_path = ROOT / f"rapidocr-{lang}.yaml"
        engine = RapidOCR(config_path=str(config_path))
        metadata = {
            "source_document_id": f"synthetic-{lang}-document", "source_version": "1",
            "original_sha256": hashlib.sha256(f"synthetic caller asserted document {lang}".encode()).hexdigest(),
            "page": 1, "region_id": f"synthetic-{lang}-region-1", "region_coords": [0, 0, width, height],
            "coordinate_frame": "image_pixels", "chunk_id": f"synthetic-existing-chunk-{lang}",
            "available_at": datetime(2026, 10, 29, tzinfo=timezone.utc),
        }
        called = []
        def fake_authorize(meta):
            called.append(meta["source_document_id"])
            return True
        candidate = extract_ocr_candidate(
            image_path=image, source_root=ROOT, metadata=metadata,
            model=OCRModelConfig("RapidOCR-3.10.0-PP-OCRv5", det, det_hash, rec_path, rec_hash),
            model_root=ROOT / "models", authorize_source=fake_authorize,
            as_of=datetime(2026, 10, 30, tzinfo=timezone.utc), engine=engine,
        )
        # RapidOCR creates ONNX sessions lazily during its first inference.
        providers = {
            "detection": engine.text_det.session.session.get_providers(),
            "recognition": engine.text_rec.session.session.get_providers(),
        }
        cpu_only = providers == {"detection": ["CPUExecutionProvider"], "recognition": ["CPUExecutionProvider"]}
        observed = "".join(row["text"] for row in candidate["ordered_text_confidence"])
        normalized = "".join(observed.split()).upper()
        want = "".join(expected.split()).upper()
        checks = {
            "expected_text_present_after_whitespace_normalization": want in normalized,
            "provider_cpu_only": cpu_only,
            "model_hashes_match_manifest": True,
            "image_sha256_matches_independent_hash": candidate["image_sha256"] == image_hash,
            "caller_asserted_document_hash_labelled": candidate["original_sha256_provenance"] == "caller_asserted_unverified",
            "page_region_coordinates_and_chunk_linked": candidate["page"] == 1 and candidate["region_id"] == metadata["region_id"] and candidate["region_coords"] == metadata["region_coords"] and candidate["existing_chunk_id"] == metadata["chunk_id"],
            "fake_authorizer_called": called == [metadata["source_document_id"]],
            "as_of_cutoff_applied": candidate["as_of"] == "2026-10-30T00:00:00+00:00" and candidate["available_at"] == "2026-10-29T00:00:00+00:00",
            "candidate_unreviewed": candidate["status"] == "candidate_unreviewed",
        }
        outputs.append({"language": lang, "expected_text": expected, "observed_text": observed,
                        "model_sha256": {"detection": det_hash, "recognition": rec_hash},
                        "image_sha256": image_hash, "config_sha256": sha(config_path),
                        "providers": providers, "authorization": "fake_allow_only",
                        "candidate": candidate, "checks": checks})
        assertions.extend(f"{lang}.{key}" for key, ok in checks.items() if not ok)
        del engine
        gc.collect()
    report = {"status": "passed" if not assertions else "failed", "attempt": "v2_after_lazy_load_fix", "runtime": str(ROOT),
              "adapter": str(ADAPTER), "synthetic_inputs_only": True,
              "network_blocking": ["socket.connect", "socket.connect_ex"],
              "network_isolation_limitation": "Python socket method guards do not prove OS-wide isolation or block all native/network techniques.",
              "job_object_memory_cap_mib": 1536, "thread_environment_cap": 1,
              "fake_authorization_only": True, "no_live_rag_write": True,
              "outputs": outputs, "failed_assertions": assertions, "peak_memory": peak_memory(kernel)}
    (OUT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "stdout.log").write_text("structured result in result.json\n" + json.dumps({"status": report["status"], "peak_memory": report["peak_memory"], "failed_assertions": assertions}, ensure_ascii=False) + "\n", encoding="utf-8")
    # Preserve the Job Object handle until all outputs are safely closed.
    _ = job_handle
    if assertions:
        raise AssertionError(", ".join(assertions))


if __name__ == "__main__":
    main()
