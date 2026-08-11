#!/usr/bin/env python
"""Build the ref11 v2 application as editable Word objects.

The source HTML is left untouched. Only non-text green/teal fills, borders,
lines, and SVG graphics are converted to luminance-matched grayscale before
the existing native Word-shape builder is invoked.
"""

from __future__ import annotations

import colorsys
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE_BOXES = HERE / "out" / "boxes_ref11_v3_docx.json"
SOURCE_SVGS = HERE / "out" / "fig_ref11_v3_docx"
BUILD_BOXES = HERE / "out" / "boxes_ref11_v3_editable_v3.json"
BUILD_SVGS = HERE / "out" / "fig_ref11_v3_editable_v3"
OUTPUT_STEM = "AX_Award_지원서_ref11_v3_editable_v3"
BUILDER_VERSION = 1123


def is_green_teal(rgb: list[int] | tuple[int, int, int]) -> bool:
    r, g, b = (channel / 255 for channel in rgb)
    hue, saturation, _ = colorsys.rgb_to_hsv(r, g, b)
    degrees = hue * 360
    return 145 <= degrees <= 195 and saturation >= 0.035


def grayscale(rgb: list[int] | tuple[int, int, int]) -> list[int]:
    r, g, b = rgb
    level = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return [level, level, level]


def transform_boxes() -> tuple[int, int]:
    pages = json.loads(SOURCE_BOXES.read_text(encoding="utf-8"))
    changed_fill = 0
    changed_border = 0
    for page in pages:
        for item in page["items"]:
            if item.get("kind") == "box":
                for key in ("bg", "bc"):
                    color = item.get(key)
                    if color and is_green_teal(color):
                        item[key] = grayscale(color)
                        if key == "bg":
                            changed_fill += 1
                        else:
                            changed_border += 1
            elif item.get("kind") == "text":
                converted_runs = []
                for run in item.get("runs", []):
                    color = run.get("color")
                    match = re.match(r"^(\s*[●→✔✓↗↖↩]+\s*)(.*)$", run.get("t", ""))
                    if not color or not is_green_teal(color) or not match:
                        converted_runs.append(run)
                        continue
                    icon, remainder = match.groups()
                    icon_run = dict(run)
                    icon_run["t"] = icon
                    icon_run["color"] = grayscale(color)
                    converted_runs.append(icon_run)
                    if remainder:
                        text_run = dict(run)
                        text_run["t"] = remainder
                        converted_runs.append(text_run)
                item["runs"] = converted_runs
    BUILD_BOXES.write_text(
        json.dumps(pages, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return changed_fill, changed_border


HEX_COLOR = re.compile(r"#([0-9a-fA-F]{6})(?![0-9a-fA-F])")


def transform_svg_text(svg: str) -> tuple[str, int]:
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        raw = match.group(1)
        rgb = [int(raw[i : i + 2], 16) for i in (0, 2, 4)]
        if not is_green_teal(rgb):
            return match.group(0)
        gray = grayscale(rgb)
        changed += 1
        return "#" + "".join(f"{channel:02X}" for channel in gray)

    return HEX_COLOR.sub(replace, svg), changed


def transform_svgs() -> int:
    BUILD_SVGS.mkdir(parents=True, exist_ok=True)
    total = 0
    for source in sorted(SOURCE_SVGS.glob("*.svg")):
        converted, changed = transform_svg_text(source.read_text(encoding="utf-8"))
        (BUILD_SVGS / source.name).write_text(converted, encoding="utf-8")
        total += changed
    return total


def build_docx() -> tuple[Path, Path]:
    env = os.environ.copy()
    env["AX_SKIP_TEXT_MEASURE"] = "1"
    env["AX_EXACT_FONT"] = "Noto Sans KR"
    subprocess.run(
        [
            sys.executable,
            str(HERE / "build_docx_v48.py"),
            str(BUILDER_VERSION),
            str(BUILD_BOXES),
            str(BUILD_SVGS),
            "exact",
        ],
        cwd=HERE,
        check=True,
        env=env,
    )
    generated_docx = HERE / "out" / f"AX_Award_지원서_Q-Agent_v{BUILDER_VERSION}.docx"
    generated_pdf = generated_docx.with_suffix(".pdf")
    final_docx = HERE / "out" / f"{OUTPUT_STEM}.docx"
    final_pdf = HERE / "out" / f"{OUTPUT_STEM}.pdf"
    shutil.copy2(generated_docx, final_docx)
    shutil.copy2(generated_pdf, final_pdf)
    return final_docx, final_pdf


def main() -> None:
    if not SOURCE_BOXES.exists():
        raise SystemExit(f"Missing extracted object list: {SOURCE_BOXES}")
    fill_count, border_count = transform_boxes()
    svg_count = transform_svgs()
    docx_path, pdf_path = build_docx()
    print(
        f"grayscale: fills={fill_count}, borders={border_count}, "
        f"svg colors={svg_count}"
    )
    print(docx_path)
    print(pdf_path)


if __name__ == "__main__":
    main()
