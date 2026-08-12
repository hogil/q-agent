#!/usr/bin/env python
"""Build ref11 v7 without changing any earlier HTML or DOCX version."""

from __future__ import annotations

import asyncio
import colorsys
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from extract_ref11_line_manifest import JS as LINE_JS


HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
HTML = HERE / "html" / "AX_Award_지원서_ref11_v4.html"
SOURCE_BOXES = OUT / "boxes_ref11_v4_alignment_v7_source.json"
SOURCE_SVGS = OUT / "fig_ref11_v4_alignment_v7_source"
BOXES = OUT / "boxes_ref11_v4_alignment_v7.json"
SVGS = OUT / "fig_ref11_v4_alignment_v7"
LINE_MANIFEST = OUT / "ref11_v7_line_manifest.json"
SCALING = OUT / "ref11_v7_scaling.json"
RAW = OUT / "AX_Award_지원서_ref11_v4_editable_v7_native_raw.docx"
FINAL = OUT / "AX_Award_지원서_ref11_v4_editable_v7_codex.docx"
STRIPPED = OUT / "AX_Award_지원서_ref11_v4_editable_v7_codex_stripped.docx"


def is_green_teal(rgb: list[int] | tuple[int, int, int]) -> bool:
    r, g, b = (channel / 255 for channel in rgb)
    hue, saturation, _ = colorsys.rgb_to_hsv(r, g, b)
    return 145 <= hue * 360 <= 195 and saturation >= 0.035


def grayscale(rgb: list[int] | tuple[int, int, int]) -> list[int]:
    r, g, b = rgb
    level = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return [level, level, level]


def transform_assets() -> None:
    pages = json.loads(SOURCE_BOXES.read_text(encoding="utf-8"))
    for page in pages:
        for item in page["items"]:
            if item.get("kind") == "box":
                for key in ("bg", "bc"):
                    color = item.get(key)
                    if color and is_green_teal(color):
                        item[key] = grayscale(color)
            elif item.get("kind") == "text":
                converted = []
                for run in item.get("runs", []):
                    color = run.get("color")
                    match = re.match(r"^(\s*[●→✔✓↗↖↩]+\s*)(.*)$", run.get("t", ""))
                    if not color or not is_green_teal(color) or not match:
                        converted.append(run)
                        continue
                    icon, remainder = match.groups()
                    icon_run = dict(run)
                    icon_run["t"] = icon
                    icon_run["color"] = grayscale(color)
                    converted.append(icon_run)
                    if remainder:
                        text_run = dict(run)
                        text_run["t"] = remainder
                        converted.append(text_run)
                item["runs"] = converted
    BOXES.write_text(json.dumps(pages, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    pattern = re.compile(r"#([0-9a-fA-F]{6})(?![0-9a-fA-F])")
    SVGS.mkdir(parents=True, exist_ok=True)
    for source in sorted(SOURCE_SVGS.glob("*.svg")):
        def replace(match: re.Match[str]) -> str:
            raw = match.group(1)
            rgb = [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
            if not is_green_teal(rgb):
                return match.group(0)
            gray = grayscale(rgb)
            return "#" + "".join(f"{channel:02X}" for channel in gray)

        (SVGS / source.name).write_text(
            pattern.sub(replace, source.read_text(encoding="utf-8")), encoding="utf-8"
        )


async def extract_line_manifest() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 900, "height": 1200})
        await page.goto(HTML.resolve().as_uri())
        await page.wait_for_timeout(500)
        manifest = await page.evaluate(LINE_JS, pages)
        await browser.close()
    unmatched = sum(1 for page in manifest for item in page if item.get("soft") is None)
    if unmatched:
        raise RuntimeError(f"unmatched browser text: {unmatched}")
    LINE_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def add_browser_line_breaks() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
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
                value = run.get("t", "")
                start = 0
                for local in range(1, len(value) + 1):
                    absolute = offset + local
                    if absolute not in boundaries:
                        continue
                    if local > start:
                        part = dict(run)
                        part["t"] = value[start:local]
                        rebuilt.append(part)
                    if not rebuilt or rebuilt[-1].get("t") != "\n":
                        rebuilt.append({"t": "\n"})
                    start = local
                if start < len(value):
                    part = dict(run)
                    part["t"] = value[start:]
                    rebuilt.append(part)
                offset += len(value)
            item["runs"] = rebuilt
            item["browser_lines"] = raw.count("\n") + len(boundaries) + 1
    BOXES.write_text(json.dumps(pages, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    subprocess.run(
        [sys.executable, str(HERE / "extract_boxes.py"), str(HTML), str(SOURCE_BOXES), str(SOURCE_SVGS)],
        cwd=HERE,
        check=True,
    )
    transform_assets()
    asyncio.run(extract_line_manifest())
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
    subprocess.run(
        [sys.executable, str(HERE / "build_docx_v48.py"), "ref11_v4_editable_v7_native_raw", str(BOXES), str(SVGS), "exact"],
        cwd=HERE,
        check=True,
        env=env,
    )
    generated = OUT / "AX_Award_지원서_ref11_v4_editable_v7_native_raw.docx"
    if generated != RAW:
        shutil.copy2(generated, RAW)

    SCALING.unlink(missing_ok=True)
    subprocess.run([sys.executable, str(HERE / "patch_ref11_v7_codex.py")], cwd=HERE, check=True)
    subprocess.run(
        [sys.executable, str(HERE / "measure_ref11_v5_scaling.py"), str(FINAL), str(BOXES), str(SCALING)],
        cwd=HERE,
        check=True,
    )
    subprocess.run([sys.executable, str(HERE / "patch_ref11_v7_codex.py")], cwd=HERE, check=True)
    subprocess.run(
        [sys.executable, str(HERE / "strip_ref11_svg_fallbacks.py"), str(FINAL), str(STRIPPED)],
        cwd=HERE,
        check=True,
    )
    shutil.move(STRIPPED, FINAL)
    if STRIPPED.with_suffix(".pdf").exists():
        shutil.move(STRIPPED.with_suffix(".pdf"), FINAL.with_suffix(".pdf"))
    subprocess.run([sys.executable, str(HERE / "qa_ref11_v7_final.py"), str(FINAL)], cwd=HERE, check=True)
    print(FINAL)


if __name__ == "__main__":
    main()
