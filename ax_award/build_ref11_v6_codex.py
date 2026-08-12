#!/usr/bin/env python
"""Create a layout-stable ref11 DOCX by patching native Word shapes in OOXML."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree


HERE = Path(__file__).resolve().parent
BOXES = HERE / "out" / "boxes_ref11_v3_alignment_v6.json"
SCALING = HERE / "out" / "ref11_v6_scaling.json"
SOURCE = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_native_raw.docx"
TARGET = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_codex.docx"

CM = 28.3464567
EMU_PER_PT = 12700
PAGE_W_CM, PAGE_H_CM = 21.0, 29.7
M_L, M_T, M_R, M_B = 2.54, 3.0, 2.54, 2.54
SRC = dict(x0=96, y0=113.3858, x1=698, y1=1027.0)

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}
W = f"{{{NS['w']}}}"
TEXT_TOP_OFFSETS = {
    # Browser SVG text baselines do not map exactly to Malgun Gothic in Word.
    # Lift the tiny register label so it does not cover the approval label.
    140: -1.75,
}
TEXT_FONT_OVERRIDES = {
    # This inline label uses the source HTML font so the following sentence
    # keeps the same visual gap without moving either text frame.
    57: "Noto Sans KR",
}
TEXT_SCALING_OVERRIDES = {
    57: 90,
}
TEXT_WIDTH_EXTRAS = {
    # Transparent text frames may use the empty area beside the source node.
    # This restores the browser glyph proportions without moving any visible
    # box, connector, or SVG element.
    57: 5.0,
    90: 6.0,
    121: 8.0,
    123: 8.0,
    128: 12.0,
    136: 5.0,
    139: 50.0,
    142: 25.0,
    404: 11.0,
    406: 15.0,
    410: 55.0,
    411: 50.0,
}


def expected_lines(item: dict) -> int:
    raw = "".join(run.get("t", "") for run in item.get("runs", []))
    explicit = raw.count("\n") + 1
    line_height = item.get("lh") or 0
    geometric = max(1, math.ceil((item["h"] - 0.4) / line_height)) if line_height else explicit
    return max(explicit, geometric)


def set_zero_property(ppr: etree._Element, name: str) -> None:
    node = ppr.find(f"{W}{name}")
    if node is None:
        node = etree.SubElement(ppr, f"{W}{name}")
    node.set(f"{W}val", "0")


def patch_document(xml: bytes, items: list[dict], scaling: dict[str, dict[str, object]]) -> bytes:
    root = etree.fromstring(xml)
    anchors = root.xpath(".//wp:anchor", namespaces=NS)
    if len(anchors) != len(items):
        raise RuntimeError(f"anchor mismatch: XML={len(anchors)}, JSON={len(items)}")
    anchors_by_name = {}
    for anchor in anchors:
        doc_pr = anchor.find("wp:docPr", NS)
        if doc_pr is not None:
            anchors_by_name[doc_pr.get("name")] = anchor

    dst_w = (PAGE_W_CM - M_L - M_R) * CM
    dst_h = (PAGE_H_CM - M_T - M_B) * CM
    src_w, src_h = SRC["x1"] - SRC["x0"], SRC["y1"] - SRC["y0"]
    scale = min(dst_w / src_w, dst_h / src_h)
    off_x = M_L * CM + (dst_w - src_w * scale) / 2
    off_y = M_T * CM

    z_base = {"box": 1000, "svg": 500000, "text": 1000000}
    for index, item in enumerate(items, start=1):
        stable_name = f"AX{index:04d}_{item['kind']}"
        anchor = anchors_by_name.get(stable_name)
        if anchor is None:
            raise RuntimeError(f"missing native shape: {stable_name}")
        left = off_x + (item["x"] - SRC["x0"]) * scale
        top = off_y + (item["y"] - SRC["y0"]) * scale + TEXT_TOP_OFFSETS.get(index, 0.0)
        width = max(item["w"] * scale + TEXT_WIDTH_EXTRAS.get(index, 0.0), 1.0)
        height = max(item["h"] * scale, 1.0)

        pos_h = anchor.find("wp:positionH/wp:posOffset", NS)
        pos_v = anchor.find("wp:positionV/wp:posOffset", NS)
        extent = anchor.find("wp:extent", NS)
        if pos_h is not None:
            pos_h.text = str(round(left * EMU_PER_PT))
        if pos_v is not None:
            pos_v.text = str(round(top * EMU_PER_PT))
        if extent is not None:
            extent.set("cx", str(round(width * EMU_PER_PT)))
            extent.set("cy", str(round(height * EMU_PER_PT)))
        for child_extent in anchor.xpath(".//a:xfrm/a:ext", namespaces=NS):
            child_extent.set("cx", str(round(width * EMU_PER_PT)))
            child_extent.set("cy", str(round(height * EMU_PER_PT)))

        anchor.set("relativeHeight", str(z_base[item["kind"]] + index))
        anchor.set("allowOverlap", "1")
        doc_pr = anchor.find("wp:docPr", NS)
        if doc_pr is not None:
            doc_pr.set("name", stable_name)

        if item["kind"] != "text":
            continue

        font_name = TEXT_FONT_OVERRIDES.get(index, "Malgun Gothic")
        for fonts in anchor.xpath(".//w:rFonts", namespaces=NS):
            for key in ("ascii", "hAnsi", "eastAsia", "cs"):
                fonts.set(f"{W}{key}", font_name)
        for ppr in anchor.xpath(".//w:pPr", namespaces=NS):
            set_zero_property(ppr, "autoSpaceDE")
            set_zero_property(ppr, "autoSpaceDN")
            set_zero_property(ppr, "snapToGrid")
        for width_node in anchor.xpath(".//w:rPr/w:w", namespaces=NS):
            width_node.getparent().remove(width_node)
        scale_value = TEXT_SCALING_OVERRIDES.get(index) or scaling.get(str(index), {}).get("scaling")
        if scale_value:
            for run_props in anchor.xpath(".//w:rPr", namespaces=NS):
                width_node = etree.SubElement(run_props, f"{W}w")
                width_node.set(f"{W}val", str(scale_value))
        for body_pr in anchor.xpath(".//wps:bodyPr", namespaces=NS):
            body_pr.set("wrap", "square")
            body_pr.set("horzOverflow", "overflow")
            body_pr.set("vertOverflow", "overflow")

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def main() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
    items = [item for page in pages for item in page["items"]]
    scaling = json.loads(SCALING.read_text(encoding="utf-8")) if SCALING.exists() else {}
    shutil.copy2(SOURCE, TARGET)
    with ZipFile(TARGET) as source_zip:
        document = patch_document(source_zip.read("word/document.xml"), items, scaling)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as temp_file:
            temp_path = Path(temp_file.name)
        try:
            with ZipFile(temp_path, "w", ZIP_DEFLATED) as target_zip:
                for info in source_zip.infolist():
                    data = document if info.filename == "word/document.xml" else source_zip.read(info.filename)
                    target_zip.writestr(info, data)
            shutil.move(temp_path, TARGET)
        finally:
            temp_path.unlink(missing_ok=True)
    print(TARGET)


if __name__ == "__main__":
    main()
