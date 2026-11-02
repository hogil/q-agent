"""One-shot real RapidOCR CPU smoke for a synthetic DOCX fixture only."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import sys
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "var" / "ocr-runtime-20261030"
OUT_BASE = PROJECT_ROOT / "var"
EXPECTED = "합성 OCR 테스트입니다"
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


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
    info.ProcessMemoryLimit = info.JobMemoryLimit = 1536 * 1024 * 1024
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
    return kernel, handle


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def checked_existing_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RuntimeError(f"expected existing directory: {path}")
    current = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            raise RuntimeError(f"directory path traverses symlink/reparse point: {path}")
    return resolved


def module_origin_in(module_name: str, allowed_root: Path) -> str:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        raise RuntimeError(f"module spec not found before import: {module_name}")
    origins = ([spec.origin] if spec.origin and spec.origin not in ("built-in", "frozen") else []) + list(spec.submodule_search_locations or ())
    if not origins or any(not Path(origin).resolve().is_relative_to(allowed_root) for origin in origins):
        raise RuntimeError(f"module spec for {module_name} is outside trusted venv {allowed_root}: {origins}")
    return str(Path(origins[0]).resolve())


def available_output() -> Path:
    checked_existing_directory(PROJECT_ROOT)
    checked_existing_directory(OUT_BASE)
    for i in range(1, 10000):
        candidate = OUT_BASE / f"docx-ocr-real-smoke-20261030-{i:04d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("no unused output directory name")


def make_docx(path: Path, png: bytes) -> None:
    entries = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''',
        "word/_rels/document.xml.rels": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdImage" Type="{IMAGE_REL_TYPE}" Target="media/image1.png"/></Relationships>''',
    }
    drawing = lambda docpr: f'''<w:p><w:r><w:drawing><wp:inline><wp:extent cx="3000000" cy="1500000"/><wp:docPr id="{docpr}" name="Synthetic image {docpr}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="{docpr}" name="Synthetic image {docpr}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3000000" cy="1500000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''
    entries["word/document.xml"] = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>''' + drawing(1) + drawing(2) + '''<w:sectPr/></w:body></w:document>'''
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data.encode("utf-8"))
        archive.writestr("word/media/image1.png", png)


def main():
    parser = argparse.ArgumentParser(description="Run one isolated RapidOCR CPU smoke on a synthetic two-placement DOCX fixture.")
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--expected-image-sha256", required=True)
    args = parser.parse_args()
    expected_config_sha = canonical_sha256(args.expected_config_sha256, "--expected-config-sha256")
    expected_image_sha = canonical_sha256(args.expected_image_sha256, "--expected-image-sha256")
    if os.name != "nt":
        raise RuntimeError("Windows Job Object is required")
    if shutil.disk_usage("D:\\").free < 20 * 1024**3:
        raise RuntimeError("D: free space is below 20 GiB")
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
    mem = MEMORYSTATUSEX(); mem.dwLength = ctypes.sizeof(mem)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(mem)) or mem.ullAvailPageFile < 4 * 1024**3:
        raise RuntimeError("Windows commit headroom below 4 GiB or query failed")
    job_kernel, job_handle = install_job_cap()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ[name] = "1"
    def blocked(*_args, **_kwargs):
        raise RuntimeError("network disabled by socket connect/connect_ex guard")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    research = (PROJECT_ROOT / "research").resolve(strict=True)
    if not research.is_dir() or not research.is_relative_to(PROJECT_ROOT):
        raise RuntimeError("research package is not contained in script-derived project root")
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    venv = (ROOT / "venv").resolve(strict=True)
    expected_python = (venv / "Scripts" / "python.exe").resolve(strict=True)
    if Path(sys.executable).resolve(strict=True) != expected_python:
        raise RuntimeError(f"runner must use configured venv interpreter: {expected_python}")
    out = available_output()
    preimport = {name: module_origin_in(name, venv) for name in ("numpy", "onnxruntime", "PIL", "rapidocr")}
    import numpy, onnxruntime
    from PIL import Image
    from rapidocr import RapidOCR
    module_paths = {name: str(Path(sys.modules[name].__file__).resolve()) for name in ("numpy", "onnxruntime", "PIL", "rapidocr")}
    if any(not Path(p).is_relative_to(venv) for p in module_paths.values()):
        raise RuntimeError("runtime module imported outside configured venv")
    manifest = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(maxsplit=1); manifest[rel.strip()] = canonical_sha256(digest, f"manifest hash for {rel.strip()}")
    model_root = checked_directory(ROOT, ROOT / "models")
    det = checked(ROOT, model_root / "ch_PP-OCRv5_det_mobile.onnx")
    rec = checked(ROOT, model_root / "korean_PP-OCRv5_rec_mobile.onnx")
    image = checked(ROOT, ROOT / "synthetic-ko.png")
    config = checked(ROOT, ROOT / "rapidocr-ko.yaml")
    hashes = {"detection": sha(det), "recognition": sha(rec), "image": sha(image), "config": sha(config)}
    if hashes["detection"] != manifest["models/ch_PP-OCRv5_det_mobile.onnx"] or hashes["recognition"] != manifest["models/korean_PP-OCRv5_rec_mobile.onnx"]:
        raise RuntimeError("local model SHA mismatch against trusted SHA256SUMS manifest")
    if hashes["config"] != expected_config_sha or hashes["image"] != expected_image_sha:
        raise RuntimeError("synthetic config/image SHA mismatch against caller-supplied expected SHA256")
    import yaml
    if not Path(module_origin_in("yaml", venv)).resolve().is_relative_to(venv):
        raise RuntimeError("PyYAML module is outside configured venv")
    with config.open("r", encoding="utf-8") as stream:
        parsed_config = yaml.safe_load(stream)
    if not isinstance(parsed_config, dict):
        raise RuntimeError("pinned OCR YAML must parse to a mapping")
    for section, model_path in (("Det", det), ("Rec", rec)):
        cfg = parsed_config.get(section)
        if not isinstance(cfg, dict) or cfg.get("engine_type") != "onnxruntime":
            raise RuntimeError(f"{section} must select exactly the verified ONNX Runtime engine")
        configured = Path(cfg.get("model_path", "")).resolve(strict=True)
        if configured != model_path.resolve(strict=True):
            raise RuntimeError(f"{section}.model_path does not resolve to the exact manifest-verified checkpoint")
    engine_cfg = parsed_config.get("EngineConfig")
    if not isinstance(engine_cfg, dict) or not isinstance(engine_cfg.get("onnxruntime"), dict) or engine_cfg["onnxruntime"].get("use_cuda") is not False:
        raise RuntimeError("EngineConfig.onnxruntime.use_cuda must be exactly false")
    if not isinstance(parsed_config.get("Global"), dict):
        raise RuntimeError("pinned OCR YAML is missing Global configuration")
    engine = RapidOCR(config_path=str(config))
    from research.document_image_ocr_adapter_20261030 import OCRModelConfig
    from research.docx_inline_image_ocr_research_20261030 import extract_docx_inline_image_ocr_candidates
    source = out / "synthetic-two-placement.docx"
    if source.exists():
        raise RuntimeError(f"refusing to overwrite existing fixture: {source}")
    make_docx(source, image.read_bytes())
    snapshot_hash = sha(source)
    metadata = {"source_document_id": "synthetic-docx-ko", "source_version": "1",
                "anchor_chunk_ids": {"word/document.xml#drawing-1": "synthetic-existing-anchor-chunk-1"},
                "available_at": datetime(2026, 10, 29, tzinfo=timezone.utc)}
    authorized = []
    def fake_authorize(meta):
        authorized.append((meta["source_document_id"], meta.get("anchor_id")))
        return True
    result = extract_docx_inline_image_ocr_candidates(
        docx_path=source, source_root=out, metadata=metadata,
        as_of=datetime(2026, 10, 30, tzinfo=timezone.utc), authorize_source=fake_authorize,
        model=OCRModelConfig("RapidOCR-3.10.0-PP-OCRv5", det, hashes["detection"], rec, hashes["recognition"]),
        model_root=model_root, engine=engine)
    providers = {"detection": engine.text_det.session.session.get_providers(),
                 "recognition": engine.text_rec.session.session.get_providers()}
    candidates = result["candidates"]
    expected_anchor_ids = ["word/document.xml#drawing-1", "word/document.xml#drawing-2"]
    normalized_expected = "".join(EXPECTED.split())
    with ZipFile(source) as archive:
        embedded = archive.read("word/media/image1.png")
        document_xml = archive.read("word/document.xml")
    checks = {
        "docx_snapshot_sha256_independently_matches_result": result["original_sha256"] == snapshot_hash == sha(source),
        "minimal_ooxml_fixture_has_two_inline_image_placements": document_xml.count(b"<a:blip") == 2 and embedded == image.read_bytes(),
        "two_candidates_have_unknown_page_and_main_document_anchors": len(candidates) == 2 and all(
            c["page"] is None and c["page_status"] == "unknown_requires_layout_rendering" and
            c["anchor_part"] == "word/document.xml" and c["status"] == "candidate_unreviewed" for c in candidates),
        "anchor_identity_ordinal_order_unique_and_source_identity_match":
            [c["anchor_id"] for c in candidates] == expected_anchor_ids and
            [c["anchor_ordinal"] for c in candidates] == [1, 2] and len({c["anchor_id"] for c in candidates}) == 2 and
            all(c["source_document_id"] == "synthetic-docx-ko" and c["source_version"] == "1" for c in candidates) and
            result["source_document_id"] == "synthetic-docx-ko" and result["source_version"] == "1",
        "anchor_one_fake_chunk_mapping_and_anchor_two_unlinked": len(candidates) == 2 and
            candidates[0]["existing_chunk_id"] == "synthetic-existing-anchor-chunk-1" and candidates[0]["chunk_link_status"] == "caller_asserted_unverified" and
            candidates[1]["existing_chunk_id"] is None and candidates[1]["chunk_link_status"] == "unlinked",
        "both_image_hashes_equal_original_png_bytes": len(candidates) == 2 and all(c["image_sha256"] == hashes["image"] for c in candidates),
        "expected_korean_text_in_each_candidate_after_whitespace_normalization": len(candidates) == 2 and all(
            normalized_expected in "".join("".join(row["text"] for row in c["ordered_text_confidence"]).split()) for c in candidates),
        "provider_cpu_only_after_lazy_inference": providers == {"detection": ["CPUExecutionProvider"], "recognition": ["CPUExecutionProvider"]},
        "fake_authorization_invoked_for_source_and_each_anchor": len(authorized) >= 3,
        "coverage_incomplete_and_embedded_main_document_only": result["coverage_status"] == "incomplete_not_verified" and "coverage incomplete: only DrawingML a:blip r:embed in document.xml is inspected" in result["limitations"],
        "model_hashes_match_read_only_manifest": True,
        "python_runtime_modules_within_venv": True,
    }
    report = {"status": "passed" if all(checks.values()) else "failed", "attempt": "synthetic_docx_real_rapidocr_cpu",
              "docx_path": str(source), "docx_sha256": snapshot_hash, "independent_docx_sha256": sha(source),
              "runtime_root": str(ROOT), "adapter": str(PROJECT_ROOT / "research" / "docx_inline_image_ocr_research_20261030.py"),
              "output_directory": str(out), "module_paths": module_paths, "preimport_module_origins": preimport,
              "sha256": hashes, "providers_after_inference": providers, "authorization": "fake_allow_only",
              "candidate_count": len(candidates), "checks": checks, "source": {"source_document_id": result["source_document_id"],
              "source_version": result["source_version"], "original_sha256": result["original_sha256"],
              "original_sha256_provenance": result["original_sha256_provenance"], "synthetic_only": True},
              "coverage_status": result["coverage_status"], "limitations": result["limitations"],
              "full_candidates": candidates, "execution_limitations": [
                  "synthetic fixture and fake authorization only; real ACL was not tested",
                  "page layout cannot be verified without document rendering",
                  "index/chunk mapping is caller asserted and not verified against an index",
                  "RapidOCR engine identity is not cryptographically bound to the configured model hashes",
                  "verified config SHA pins parsed config and resolves duplicate/ambiguous config selection; it does not prove which model bytes the engine actually loaded",
                  "native dependency provenance and real deployment bindings were not verified",
                  "coverage is incomplete and restricted to embedded raster images in word/document.xml",
                  "failures before exclusive output allocation leave no local report; the invoking run log must capture early failures"],
              "network_guard": "socket connect/connect_ex only; not an OS firewall or OS-wide isolation",
              "job_object_process_and_aggregate_cap_mib": 1536, "thread_environment_cap": 1,
              "commit_headroom_bytes_before_run": mem.ullAvailPageFile, "disk_free_bytes_before_run": shutil.disk_usage("D:\\").free}
    report_path = out / "result.json"
    if report_path.exists():
        raise RuntimeError(f"refusing to overwrite existing report: {report_path}")
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _ = job_kernel, job_handle, numpy, onnxruntime
    if not all(checks.values()):
        raise AssertionError(", ".join(k for k, ok in checks.items() if not ok))


if __name__ == "__main__":
    main()
