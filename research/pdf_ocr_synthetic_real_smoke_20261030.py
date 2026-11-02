"""One-shot real RapidOCR CPU smoke for synthetic PDF image placements only."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import argparse
from io import BytesIO
import importlib.util
import stat
import shutil
import socket
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "var" / "ocr-runtime-20261030"
OUT_BASE = PROJECT_ROOT / "var"
ADAPTER = PROJECT_ROOT / "research" / "pdf_image_ocr_research_20261030.py"
EXPECTED = "합성 OCR 테스트입니다"


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
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
    info = EXT_LIMIT()
    info.BasicLimitInformation.LimitFlags = 0x100 | 0x200
    info.ProcessMemoryLimit = 1536 * 1024 * 1024
    info.JobMemoryLimit = 1536 * 1024 * 1024
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
    return kernel, handle


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise RuntimeError(f"{label} must be exactly 64 hexadecimal characters")
    return value.lower()


def checked(root: Path, path: Path) -> Path:
    resolved_root, resolved = root.resolve(strict=True), path.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise RuntimeError(f"path outside trusted runtime root: {path}")
    return resolved


def checked_directory(root: Path, path: Path) -> Path:
    resolved_root, resolved = root.resolve(strict=True), path.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or not resolved.is_dir():
        raise RuntimeError(f"directory outside trusted runtime root: {path}")
    current = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            raise RuntimeError(f"directory path traverses symlink/reparse point: {path}")
    return resolved


def checked_trusted_system_site(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeError("--allow-trusted-system-site must be an absolute path without parent traversal")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            raise RuntimeError("--allow-trusted-system-site traverses a symlink/reparse point")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RuntimeError("--allow-trusted-system-site must name an existing directory")
    return resolved


def module_origin_in(module_name: str, allowed_root: Path) -> str:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        raise RuntimeError(f"module spec not found before import: {module_name}")
    locations = list(spec.submodule_search_locations or ())
    origins = ([spec.origin] if spec.origin and spec.origin not in ("built-in", "frozen") else []) + locations
    if not origins or any(not Path(origin).resolve().is_relative_to(allowed_root) for origin in origins):
        raise RuntimeError(f"module spec for {module_name} is outside trusted root {allowed_root}: {origins}")
    return str(Path(origins[0]).resolve())


def available_output() -> Path:
    for i in range(1, 10000):
        candidate = OUT_BASE / f"pdf-ocr-real-smoke-20261030-{i:04d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("no unused output directory name")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-trusted-system-site", required=True,
                        help="explicit trusted system site-packages directory used only as a fallback import path")
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--expected-image-sha256", required=True)
    args = parser.parse_args()
    system_site = checked_trusted_system_site(args.allow_trusted_system_site)
    research_package = (PROJECT_ROOT / "research").resolve(strict=True)
    if not research_package.is_dir() or not research_package.is_relative_to(PROJECT_ROOT):
        raise RuntimeError("research package is not contained in script-derived project root")
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if os.name != "nt":
        raise RuntimeError("Windows Job Object is required")
    if shutil.disk_usage("D:\\").free < 20 * 1024**3:
        raise RuntimeError("D: free space is below 20 GiB")
    # GlobalMemoryStatusEx reports system commit headroom; fail closed below 4 GiB.
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(mem)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(mem)) or mem.ullAvailPageFile < 4 * 1024**3:
        raise RuntimeError("Windows commit headroom below 4 GiB or query failed")
    job_kernel, job_handle = install_job_cap()

    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ[name] = "1"
    def blocked(*_args, **_kwargs):
        raise RuntimeError("network disabled by socket connect/connect_ex guard")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked

    out = available_output()
    sys.path.append(str(system_site))
    venv = (ROOT / "venv").resolve(strict=True)
    preimport_paths = {"fitz": module_origin_in("fitz", system_site),
                       "pymupdf": module_origin_in("pymupdf", system_site),
                       "numpy": module_origin_in("numpy", venv),
                       "onnxruntime": module_origin_in("onnxruntime", venv),
                       "PIL": module_origin_in("PIL", venv),
                       "rapidocr": module_origin_in("rapidocr", venv)}
    import fitz
    import pymupdf
    import numpy
    import onnxruntime
    from PIL import Image
    from rapidocr import RapidOCR

    module_paths = {name: str(sys.modules[name].__file__) for name in ("fitz", "numpy", "onnxruntime", "PIL", "rapidocr")}
    module_paths["pymupdf"] = str(Path(pymupdf.__file__).resolve())
    if not Path(module_paths["pymupdf"]).is_relative_to(system_site):
        raise RuntimeError(f"pymupdf imported outside trusted system directory: {module_paths['pymupdf']}")
    for name in ("numpy", "onnxruntime", "PIL", "rapidocr"):
        if not Path(module_paths[name]).resolve().is_relative_to(venv):
            raise RuntimeError(f"{name} did not import from runtime venv: {module_paths[name]}")
    if not Path(module_paths["fitz"]).resolve().is_relative_to(system_site):
        raise RuntimeError(f"fitz did not import from trusted system directory: {module_paths['fitz']}")

    manifest = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(maxsplit=1)
        manifest[rel.strip()] = canonical_sha256(digest, f"manifest hash for {rel.strip()}")
    model_root = checked_directory(ROOT, ROOT / "models")
    det = checked(ROOT, model_root / "ch_PP-OCRv5_det_mobile.onnx")
    rec = checked(ROOT, model_root / "korean_PP-OCRv5_rec_mobile.onnx")
    image = checked(ROOT, ROOT / "synthetic-ko.png")
    config = checked(ROOT, ROOT / "rapidocr-ko.yaml")
    hashes = {"detection": sha(det), "recognition": sha(rec), "image": sha(image), "config": sha(config)}
    if hashes["detection"] != manifest["models/ch_PP-OCRv5_det_mobile.onnx"] or hashes["recognition"] != manifest["models/korean_PP-OCRv5_rec_mobile.onnx"]:
        raise RuntimeError("local model SHA mismatch against trusted SHA256SUMS manifest")
    expected_config_sha = canonical_sha256(args.expected_config_sha256, "--expected-config-sha256")
    expected_image_sha = canonical_sha256(args.expected_image_sha256, "--expected-image-sha256")
    if hashes["config"] != expected_config_sha or hashes["image"] != expected_image_sha:
        raise RuntimeError("synthetic config/image SHA mismatch against caller-supplied expected SHA256")
    # The YAML is constrained by verified hash and explicitly requires CPU inference.
    config_text = config.read_text(encoding="utf-8")
    if "use_cuda: false" not in config_text.lower() or "engine_type: onnxruntime" not in config_text.lower():
        raise RuntimeError("verified OCR config does not explicitly select ONNX Runtime CPU mode")
    with Image.open(image) as im:
        image_size = im.size
    pdf_path = out / "synthetic-two-placement.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(36, 60, 576, 330), filename=str(image))
    page.insert_image(fitz.Rect(36, 420, 576, 690), filename=str(image))
    doc.save(pdf_path)
    doc.close()
    pdf_hash = sha(pdf_path)
    engine = RapidOCR(config_path=str(config))
    from research.document_image_ocr_adapter_20261030 import OCRModelConfig
    from research.pdf_image_ocr_research_20261030 import extract_pdf_image_ocr_candidates
    metadata = {"source_document_id": "synthetic-pdf-ko", "source_version": "1",
                "page_chunk_ids": {1: "synthetic-existing-page-chunk-1"},
                "available_at": datetime(2026, 10, 29, tzinfo=timezone.utc)}
    authorized = []
    def fake_authorize(meta):
        authorized.append(meta["source_document_id"])
        return True
    result = extract_pdf_image_ocr_candidates(
        pdf_path=pdf_path, source_root=out, metadata=metadata, authorize_source=fake_authorize,
        as_of=datetime(2026, 10, 30, tzinfo=timezone.utc), output_root=out,
        model=OCRModelConfig("RapidOCR-3.10.0-PP-OCRv5", det, hashes["detection"], rec, hashes["recognition"]),
        model_root=model_root, engine=engine)
    providers = {"detection": engine.text_det.session.session.get_providers(),
                 "recognition": engine.text_rec.session.session.get_providers()}
    candidates = result["candidates"]
    normalized_expected = "".join(EXPECTED.split())
    extracted_images = {}
    with fitz.open(pdf_path) as fixture_doc, Image.open(image) as source_image:
        source_pixels = source_image.convert("RGB")
        for candidate in candidates:
            xref = int(candidate["region_id"].rsplit("-xref-", 1)[1])
            extracted = fixture_doc.extract_image(xref)["image"]
            with Image.open(BytesIO(extracted)) as extracted_image:
                pixel_equal = extracted_image.convert("RGB").size == source_pixels.size and extracted_image.convert("RGB").tobytes() == source_pixels.tobytes()
            extracted_images[candidate["region_id"]] = {
                "sha256": hashlib.sha256(extracted).hexdigest(), "pixels_equal_source": pixel_equal}
    checks = {
        "pdf_sha256_independently_matches_result": result["original_sha256"] == pdf_hash,
        "single_page_has_two_candidates": len(candidates) == 2 and all(c["page"] == 1 for c in candidates),
        "each_candidate_unreviewed_with_page_bbox_px_and_chunk": all(
            c["status"] == "candidate_unreviewed" and c["page"] == 1 and
            c["region_coords"] == [0, 0, image_size[0], image_size[1]] and
            c["coordinate_frame"] == "image_pixels" and
            c["image_sha256"] == extracted_images[c["region_id"]]["sha256"] and
            extracted_images[c["region_id"]]["pixels_equal_source"] and
            c["page_chunk_id_provenance"] == "caller_asserted_mapping_unverified_against_index" and
            c["existing_chunk_id"] == "synthetic-existing-page-chunk-1" and len(c.get("page_bbox", [])) == 4
            for c in candidates),
        "same_page_placements_have_distinct_page_bboxes": len(candidates) == 2 and candidates[0]["page_bbox"] != candidates[1]["page_bbox"],
        "expected_korean_text_after_whitespace_normalization": all(
            normalized_expected in "".join("".join(row["text"] for row in c["ordered_text_confidence"]).split())
            for c in candidates),
        "provider_cpu_only_after_lazy_inference": providers == {"detection": ["CPUExecutionProvider"], "recognition": ["CPUExecutionProvider"]},
        "fake_authorization_invoked_for_two_candidates": len(authorized) >= 3,
        "model_hashes_match_read_only_manifest": True,
        "python_runtime_modules_within_venv_except_fitz_pymupdf": True,
    }
    report = {"status": "passed" if all(checks.values()) else "failed", "attempt": "synthetic_pdf_real_rapidocr_cpu",
              "pdf_path": str(pdf_path), "pdf_sha256": pdf_hash, "independent_pdf_sha256": sha(pdf_path),
              "runtime_root": str(ROOT), "adapter": str(ADAPTER), "output_directory": str(out),
              "module_paths": module_paths, "preimport_module_origins": preimport_paths, "sha256": hashes, "providers_after_inference": providers,
              "authorization": "fake_allow_only", "candidate_count": len(candidates), "checks": checks,
              "pdf_source": {"source_document_id": result["source_document_id"],
                  "source_version": result["source_version"],
                  "original_sha256": result["original_sha256"],
                  "original_sha256_provenance": result["original_sha256_provenance"],
                  "page_chunk_mapping_provenance": result["page_chunk_mapping_provenance"],
                  "synthetic_only": True},
              "coverage_status": result["coverage_status"],
              "limitations": result["limitations"] + [
                  "synthetic fixture only; fake authorization callback does not represent company ACL"],
              "full_candidates": candidates,
              "candidate_summary": [{**{k: c.get(k) for k in ("status", "page", "region_id", "region_coords", "coordinate_frame", "image_sha256", "original_sha256", "existing_chunk_id", "page_chunk_id_provenance", "page_bbox", "ordered_text_confidence")}, "independently_extracted_image": extracted_images[c["region_id"]]} for c in candidates],
              "execution_limitations": ["fake authorization is not cryptographically bound to engine or source ACL",
                  "config/model hashes record local inputs but do not bind engine identity cryptographically",
                  "CPU is selected by verified config before load; post-inference provider inspection is corroborating evidence only",
                  "sys.path and native dependency resolution remain process/OS trust boundaries; Python spec checks do not validate native dependency provenance",
                  "vector graphics and clipped, occluded, or composited visible pixels are not OCR-complete",
                  "company ACL, site RAG, and real document permissions were not tested"],
              "network_guard": "socket connect/connect_ex only; not an OS firewall or OS-wide isolation",
              "job_object_process_and_aggregate_cap_mib": 1536, "thread_environment_cap": 1,
              "commit_headroom_bytes_before_run": mem.ullAvailPageFile, "disk_free_bytes_before_run": shutil.disk_usage("D:\\").free}
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _ = job_kernel, job_handle
    if not all(checks.values()):
        raise AssertionError(", ".join(k for k, ok in checks.items() if not ok))


if __name__ == "__main__":
    main()
