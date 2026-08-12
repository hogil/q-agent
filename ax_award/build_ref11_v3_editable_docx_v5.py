#!/usr/bin/env python
"""Build the alignment-corrected, fully editable ref11 v3 Word document."""

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
SOURCE_BOXES = HERE / "out" / "boxes_ref11_v3_alignment_v5_source.json"
SOURCE_SVGS = HERE / "out" / "fig_ref11_v3_alignment_v5_source"
BUILD_BOXES = HERE / "out" / "boxes_ref11_v3_alignment_v5.json"
BUILD_SVGS = HERE / "out" / "fig_ref11_v3_alignment_v5"
RAW_DOCX = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v5_raw.docx"
FINAL_DOCX = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v5_codex.docx"
STRIPPED_DOCX = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v5_codex_stripped.docx"
BUILDER_VERSION = 1126


def is_green_teal(rgb: list[int] | tuple[int, int, int]) -> bool:
    r, g, b = (channel / 255 for channel in rgb)
    hue, saturation, _ = colorsys.rgb_to_hsv(r, g, b)
    return 145 <= hue * 360 <= 195 and saturation >= 0.035


def grayscale(rgb: list[int] | tuple[int, int, int]) -> list[int]:
    r, g, b = rgb
    level = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return [level, level, level]


def transform_boxes() -> None:
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
    BUILD_BOXES.write_text(
        json.dumps(pages, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def transform_svgs() -> None:
    pattern = re.compile(r"#([0-9a-fA-F]{6})(?![0-9a-fA-F])")
    BUILD_SVGS.mkdir(parents=True, exist_ok=True)
    for source in sorted(SOURCE_SVGS.glob("*.svg")):
        def replace(match: re.Match[str]) -> str:
            raw = match.group(1)
            rgb = [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
            if not is_green_teal(rgb):
                return match.group(0)
            gray = grayscale(rgb)
            return "#" + "".join(f"{channel:02X}" for channel in gray)

        text = pattern.sub(replace, source.read_text(encoding="utf-8"))
        (BUILD_SVGS / source.name).write_text(text, encoding="utf-8")


def main() -> None:
    transform_boxes()
    transform_svgs()
    env = os.environ.copy()
    env.update({
        "AX_SKIP_TEXT_MEASURE": "1",
        "AX_EXACT_FONT": "Malgun Gothic",
        "AX_TEXT_PAD_X": "0.8",
        "AX_TEXT_PAD_Y": "1.35",
        "AX_TEXT_TOP_SHIFT": "0.1",
        "AX_EXACT_FONT_K": "1.0",
    })
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
    generated = HERE / "out" / f"AX_Award_지원서_Q-Agent_v{BUILDER_VERSION}.docx"
    shutil.copy2(generated, RAW_DOCX)
    shutil.copy2(RAW_DOCX, FINAL_DOCX)
    subprocess.run(
        [sys.executable, str(HERE / "repair_ref11_v5_alignment.py")],
        cwd=HERE,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(HERE / "fix_ref11_v5_wrapping.py")],
        cwd=HERE,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(HERE / "strip_ref11_svg_fallbacks.py"), str(FINAL_DOCX), str(STRIPPED_DOCX)],
        cwd=HERE,
        check=True,
    )
    shutil.move(STRIPPED_DOCX, FINAL_DOCX)
    print(FINAL_DOCX)


if __name__ == "__main__":
    main()
