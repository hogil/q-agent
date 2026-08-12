#!/usr/bin/env python
"""Build the stable-ID native ref11 DOCX, then apply exact OOXML layout rules."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
from pathlib import Path

from build_ref11_v3_editable_docx_v5 import transform_boxes, transform_svgs


HERE = Path(__file__).resolve().parent
RAW = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_native_raw.docx"
FINAL = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_codex.docx"
STRIPPED = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_codex_stripped.docx"
BOXES_V5 = HERE / "out" / "boxes_ref11_v3_alignment_v5.json"
BOXES_V6 = HERE / "out" / "boxes_ref11_v3_alignment_v6.json"
LINE_MANIFEST = HERE / "out" / "ref11_v6_line_manifest.json"
SCALING = HERE / "out" / "ref11_v6_scaling.json"
HTML = HERE / "html" / "AX_Award_지원서_ref11_v3.html"
SOURCE_BOXES = HERE / "out" / "boxes_ref11_v3_alignment_v5_source.json"
SOURCE_SVGS = HERE / "out" / "fig_ref11_v3_alignment_v5_source"


def add_browser_line_breaks() -> None:
    pages = json.loads(BOXES_V5.read_text(encoding="utf-8"))
    manifest = json.loads(LINE_MANIFEST.read_text(encoding="utf-8"))
    object_index = 0
    for page, page_manifest in zip(pages, manifest):
        records = iter(page_manifest)
        for item in page["items"]:
            object_index += 1
            if item["kind"] != "text":
                continue
            record = next(records)
            raw = "".join(run.get("t", "") for run in item.get("runs", []))
            if raw != record["raw"]:
                raise RuntimeError("line manifest text mismatch")
            boundaries = set(record["soft"] or [])
            if object_index == 57:
                boundaries.clear()
            rebuilt = []
            offset = 0
            for run in item.get("runs", []):
                text = run.get("t", "")
                if text == "\n":
                    rebuilt.append(run)
                    offset += 1
                    continue
                start = 0
                for local in range(1, len(text) + 1):
                    absolute = offset + local
                    if absolute not in boundaries:
                        continue
                    if local > start:
                        part = dict(run)
                        part["t"] = text[start:local]
                        rebuilt.append(part)
                    if not rebuilt or rebuilt[-1].get("t") != "\n":
                        rebuilt.append({"t": "\n"})
                    start = local
                if start < len(text):
                    part = dict(run)
                    part["t"] = text[start:]
                    rebuilt.append(part)
                offset += len(text)
            item["runs"] = rebuilt
            item["browser_lines"] = raw.count("\n") + len(boundaries) + 1
    BOXES_V6.write_text(json.dumps(pages, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    subprocess.run([
        sys.executable,
        str(HERE / "extract_boxes.py"),
        str(HTML),
        str(SOURCE_BOXES),
        str(SOURCE_SVGS),
    ], cwd=HERE, check=True)
    transform_boxes()
    transform_svgs()
    subprocess.run([sys.executable, str(HERE / "extract_ref11_line_manifest.py")], cwd=HERE, check=True)
    add_browser_line_breaks()
    env = os.environ.copy()
    env.update({
        "AX_SKIP_TEXT_MEASURE": "1",
        "AX_EXACT_FONT": "Malgun Gothic",
        "AX_TEXT_PAD_X": "0",
        "AX_TEXT_PAD_Y": "0",
        "AX_TEXT_TOP_SHIFT": "0",
        "AX_TEXT_EXTRA_H": "0",
        "AX_EXACT_FONT_K": "1.0",
    })
    subprocess.run([
        sys.executable,
        str(HERE / "build_docx_v48.py"),
        "ref11_v3_editable_v6_native_raw",
        str(BOXES_V6),
        str(HERE / "out" / "fig_ref11_v3_alignment_v5"),
        "exact",
    ], cwd=HERE, check=True, env=env)
    generated = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_native_raw.docx"
    if generated != RAW:
        shutil.copy2(generated, RAW)

    # First create an unscaled Malgun Gothic document, then measure only the
    # objects that Word would wrap beyond the browser's recorded line count.
    SCALING.unlink(missing_ok=True)
    subprocess.run([sys.executable, str(HERE / "build_ref11_v6_codex.py")], cwd=HERE, check=True)
    subprocess.run([
        sys.executable,
        str(HERE / "measure_ref11_v5_scaling.py"),
        str(FINAL),
        str(BOXES_V6),
        str(SCALING),
    ], cwd=HERE, check=True)
    subprocess.run([sys.executable, str(HERE / "build_ref11_v6_codex.py")], cwd=HERE, check=True)
    subprocess.run([
        sys.executable,
        str(HERE / "strip_ref11_svg_fallbacks.py"),
        str(FINAL),
        str(STRIPPED),
    ], cwd=HERE, check=True)
    shutil.move(STRIPPED, FINAL)
    stripped_pdf = STRIPPED.with_suffix(".pdf")
    if stripped_pdf.exists():
        shutil.move(stripped_pdf, FINAL.with_suffix(".pdf"))
    subprocess.run([
        sys.executable,
        str(HERE / "qa_ref11_v6_final.py"),
        str(FINAL),
    ], cwd=HERE, check=True)
    print(FINAL)


if __name__ == "__main__":
    main()
