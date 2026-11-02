"""One-shot synthetic PDF full-page render and RapidOCR CPU smoke."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "var" / "ocr-runtime-20261030"
OUT_BASE = PROJECT_ROOT / "var"
PREP = PROJECT_ROOT / "research" / "pdf_ocr_synthetic_real_smoke_20261030.py"
VECTOR_EXPECTED = "VECTORTEXTTEST2026"
IMAGE_EXPECTED = "SYNTHETICOCRTEST2026"


def reserve_failure_output() -> Path:
    for i in range(1, 10000):
        candidate = OUT_BASE / f"pdf-render-ocr-smoke-failed-20261030-{i:04d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("no unused failure output directory name")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-trusted-system-site", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--expected-image-sha256", required=True)
    args = parser.parse_args()
    prep = None
    out = None
    report = {"status": "failed", "attempt": "synthetic_pdf_rendered_page_real_rapidocr_cpu",
              "synthetic_only": True, "annotations": False, "checks": {}, "full_candidates": [],
              "limitations": ["coverage incomplete; only rendered visible page pixels are considered",
                  "annotations disabled; embedded OCR text is not merged into results",
                  "pixel-to-page coordinate transform is reported but exact accuracy is unvalidated",
                  "real ACL/index authorization and engine hash binding are not tested",
                  "native provider and dependency provenance cannot be fully established by Python module checks"],
              "execution_error": None}
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from research import pdf_ocr_synthetic_real_smoke_20261030 as prep
        system_site = prep.checked_trusted_system_site(args.allow_trusted_system_site)
        report["trusted_system_site"] = str(system_site)
        if os.name != "nt":
            raise RuntimeError("Windows Job Object is required")
        if shutil.disk_usage("D:\\").free < 20 * 1024**3:
            raise RuntimeError("D: free space is below 20 GiB")

        import ctypes
        from ctypes import wintypes
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
        job_kernel, job_handle = prep.install_job_cap()
        report["job_object_process_and_aggregate_cap_mib"] = 1536
        report["commit_headroom_bytes_before_run"] = mem.ullAvailPageFile
        report["disk_free_bytes_before_run"] = shutil.disk_usage("D:\\").free
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
            os.environ[name] = "1"
        def blocked(*_args, **_kwargs):
            raise RuntimeError("network disabled by socket connect/connect_ex guard")
        socket.socket.connect = blocked
        socket.socket.connect_ex = blocked

        out = prep.available_output()
        report["output_directory"] = str(out)
        sys.path.append(str(system_site))
        venv = (ROOT / "venv").resolve(strict=True)
        origins = {"fitz": prep.module_origin_in("fitz", system_site),
                   "pymupdf": prep.module_origin_in("pymupdf", system_site)}
        for name in ("rapidocr", "numpy", "onnxruntime", "PIL"):
            origins[name] = prep.module_origin_in(name, venv)
        report["preimport_module_origins"] = origins
        import fitz
        import pymupdf
        import numpy
        import onnxruntime
        from PIL import Image
        from rapidocr import RapidOCR
        import_paths = {name: str(Path(sys.modules[name].__file__).resolve())
                        for name in ("fitz", "numpy", "onnxruntime", "PIL", "rapidocr")}
        import_paths["pymupdf"] = str(Path(pymupdf.__file__).resolve())
        allowed = {"fitz": system_site, "pymupdf": system_site,
                   "numpy": venv, "onnxruntime": venv, "PIL": venv, "rapidocr": venv}
        if not all(Path(import_paths[k]).is_relative_to(v) for k, v in allowed.items()):
            raise RuntimeError(f"imported module origin outside allowed roots: {import_paths}")
        report["module_paths"] = import_paths

        manifest = {}
        for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
            digest, rel = line.split(maxsplit=1)
            manifest[rel.strip()] = prep.canonical_sha256(digest, f"manifest hash for {rel.strip()}")
        model_root = prep.checked_directory(ROOT, ROOT / "models")
        det = prep.checked(ROOT, model_root / "ch_PP-OCRv5_det_mobile.onnx")
        rec = prep.checked(ROOT, model_root / "en_PP-OCRv5_rec_mobile.onnx")
        dictionary = prep.checked(ROOT, model_root / "ppocrv5_en_dict.txt")
        image = prep.checked(ROOT, ROOT / "synthetic-en.png")
        config = prep.checked(ROOT, ROOT / "rapidocr-en.yaml")
        hashes = {"detection": prep.sha(det), "recognition": prep.sha(rec),
                  "dictionary": prep.sha(dictionary), "image": prep.sha(image), "config": prep.sha(config)}
        expected_config = prep.canonical_sha256(args.expected_config_sha256, "--expected-config-sha256")
        expected_image = prep.canonical_sha256(args.expected_image_sha256, "--expected-image-sha256")
        if hashes["detection"] != manifest["models/ch_PP-OCRv5_det_mobile.onnx"] or hashes["recognition"] != manifest["models/en_PP-OCRv5_rec_mobile.onnx"] or hashes["dictionary"] != manifest["models/ppocrv5_en_dict.txt"]:
            raise RuntimeError("English model/dictionary SHA mismatch against local manifest")
        if hashes["config"] != expected_config or hashes["image"] != expected_image:
            raise RuntimeError("config/image SHA mismatch against caller-supplied expected SHA256")
        config_text = config.read_text(encoding="utf-8").lower()
        if "use_cuda: false" not in config_text or "engine_type: onnxruntime" not in config_text:
            raise RuntimeError("verified config does not explicitly select ONNX Runtime CPU mode")
        with Image.open(image) as im:
            source_size = im.size

        pdf_path = out / "synthetic-rendered-page.pdf"
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(42, 62, 570, 326), filename=str(image))
        page.insert_text((54, 400), "VECTOR TEXT TEST 2026", fontsize=24, fontname="helv")
        vector_text = page.get_text()
        doc.save(pdf_path); doc.close()
        if "VECTOR TEXT TEST 2026" not in vector_text:
            raise RuntimeError("PyMuPDF text extraction did not confirm vector text content")
        pdf_hash = prep.sha(pdf_path)
        engine = RapidOCR(config_path=str(config))
        from research.document_image_ocr_adapter_20261030 import OCRModelConfig
        from research.pdf_page_render_ocr_20261030 import extract_pdf_rendered_page_ocr_candidates
        metadata = {"source_document_id": "synthetic-rendered-page-en", "source_version": "1",
                    "page_chunk_ids": {1: "synthetic-existing-page-chunk-1"},
                    "available_at": datetime(2026, 10, 29, tzinfo=timezone.utc)}
        authorized = []
        def fake_authorize(meta):
            authorized.append(meta.get("source_document_id")); return True
        result = extract_pdf_rendered_page_ocr_candidates(pdf_path=pdf_path, source_root=out,
            metadata=metadata, authorize_source=fake_authorize,
            as_of=datetime(2026, 10, 30, tzinfo=timezone.utc), output_root=out,
            model=OCRModelConfig("RapidOCR-3.10.0-PP-OCRv5-English", det, hashes["detection"], rec, hashes["recognition"]),
            model_root=model_root, engine=engine, dpi=144)
        providers = {"detection": engine.text_det.session.session.get_providers(),
                     "recognition": engine.text_rec.session.session.get_providers()}
        candidates = result["candidates"]
        rowtext = ["".join("".join(str(row.get("text", "")) for row in c["ordered_text_confidence"]).upper().split()) for c in candidates]
        has_vector = any(VECTOR_EXPECTED in t for t in rowtext)
        has_image = any(IMAGE_EXPECTED in t for t in rowtext)
        checks = {"vector_text_is_pdf_content": "VECTOR TEXT TEST 2026" in vector_text,
            "single_page_one_candidate": len(candidates) == 1 and candidates[0].get("page") == 1,
            "render_snapshot_sha_matches_pdf": result["original_sha256"] == pdf_hash,
            "candidate_page_chunk_mapping": len(candidates) == 1 and candidates[0].get("existing_chunk_id") == "synthetic-existing-page-chunk-1",
            "dpi_144_and_render_geometry_recorded": len(candidates) == 1 and candidates[0].get("render_dpi") == 144 and bool(candidates[0].get("rendered_page_pixels")) and bool(candidates[0].get("pixmap_irect")) and bool(candidates[0].get("page_rect_points")) and bool(candidates[0].get("page_rotation_degrees") is not None),
            "vector_text_ocr_detected": has_vector, "bitmap_ocr_detected": has_image,
            "provider_cpu_only": providers == {"detection": ["CPUExecutionProvider"], "recognition": ["CPUExecutionProvider"]},
            "fake_authorization_invoked": bool(authorized),
            "local_english_artifact_hashes_verified": True,
            "caller_config_image_sha_verified": True,
            "module_import_origins_verified": True}
        report.update({"status": "passed" if all(checks.values()) else "failed", "checks": checks,
            "runtime_root": str(ROOT), "pdf_path": str(pdf_path), "pdf_sha256": pdf_hash,
            "independent_pdf_sha256": prep.sha(pdf_path), "source_bitmap_size": source_size,
            "source_bitmap_sha256": hashes["image"], "sha256": hashes,
            "providers_after_inference": providers, "authorization": "fake_allow_only",
            "candidate_count": len(candidates), "coverage_status": result["coverage_status"],
            "pdf_source": {"source_document_id": result["source_document_id"], "source_version": result["source_version"],
                "original_sha256": result["original_sha256"], "original_sha256_provenance": result["original_sha256_provenance"],
                "page_chunk_mapping_provenance": result["page_chunk_mapping_provenance"], "synthetic_only": True},
            "full_candidates": candidates, "candidate_ocr_joined_rows": rowtext,
            "limitations": report["limitations"] + result["limitations"],
            "execution_limitations": ["rendered page hash differs from source bitmap hash by design; they are recorded separately",
                "caller-provided page_chunk_ids are not checked against an index", "fake authorization is not real ACL",
                "Python origin checks do not verify native libraries", "post-inference provider inspection is corroborating evidence only"],
            "network_guard": "socket connect/connect_ex only; not OS-wide network isolation",
            "thread_environment_cap": 1, "render_output_directory": result["output_directory"]})
        _ = job_kernel, job_handle
    except Exception as exc:
        report["execution_error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        if out is None:
            try:
                out = reserve_failure_output()
            except Exception:
                out = None
        if out is not None:
            report["output_directory"] = str(out)
            try:
                with (out / "result.json").open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            except Exception as exc:
                report["report_write_error"] = f"{type(exc).__name__}: {exc}"
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
