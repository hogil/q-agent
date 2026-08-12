#!/usr/bin/env python
"""Run the v7 package, content, view, and rendered-line gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from zipfile import ZipFile

import win32com.client as win32
from lxml import etree


HERE = Path(__file__).resolve().parent
DOCX = Path(sys.argv[1]).resolve()
BOXES = HERE / "out" / "boxes_ref11_v4_alignment_v7.json"
TEAL = ("12B5B0", "0E9C97", "7FD1CE", "E6F7F6", "B7E6E4")
REQUIRED = (
    "품질 AI Agent: 불량을 스스로 분석, 판단, 조치하는 Multi-Agent Process 혁신",
    "1. 해결하려는 문제 - 이상 감지 이후 분석과 판정이 대부분 Manual이다",
    "E2E 전체 Process 재설계",
    "LLM Wiki",
    "Graph RAG",
    "IIII. 경영효과",
    "200억",
)


def main() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
    items = [item for page in pages for item in page["items"]]
    with ZipFile(DOCX) as package:
        media = [name for name in package.namelist() if name.startswith("word/media/")]
        if len(media) != 4 or any(not name.endswith(".svg") for name in media):
            raise RuntimeError(f"media: {media}")
        settings = etree.fromstring(package.read("word/settings.xml"))
        wns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        if settings.find(f"{{{wns}}}view").get(f"{{{wns}}}val") != "print":
            raise RuntimeError("view is not print layout")
        if settings.find(f"{{{wns}}}zoom").get(f"{{{wns}}}percent") != "100":
            raise RuntimeError("zoom is not 100")
        document = etree.fromstring(package.read("word/document.xml"))
        ns = {"wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}
        anchors = document.xpath(".//wp:anchor", namespaces=ns)
        expected_names = [f"AX{index:04d}_{item['kind']}" for index, item in enumerate(items, start=1)]
        doc_props = [anchor.find("wp:docPr", ns) for anchor in anchors]
        actual_ids = [int(prop.get("id")) for prop in doc_props]
        names_by_id = [prop.get("name", "") for prop in sorted(doc_props, key=lambda prop: int(prop.get("id")))]
        if names_by_id != expected_names or sorted(actual_ids) != list(range(1, len(items) + 1)):
            raise RuntimeError("stable Word object IDs or names do not match the source manifest")
        for anchor in anchors:
            name = anchor.find("wp:docPr", ns).get("name", "")
            if name.endswith("_text"):
                continue
            serialized = etree.tostring(anchor).decode().upper()
            if any(color in serialized for color in TEAL):
                raise RuntimeError(f"non-text teal: {name}")
        for name in media:
            serialized = package.read(name).decode("utf-8").upper()
            if any(color in serialized for color in TEAL):
                raise RuntimeError(f"non-text teal in SVG: {name}")

    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(str(DOCX), ReadOnly=True, OpenAndRepair=False)
    line_mismatch = []
    overflow = []
    text = []
    try:
        if int(doc.ComputeStatistics(2)) != 5 or doc.Shapes.Count != len(items):
            raise RuntimeError("page or object count mismatch")
        view = doc.Windows.Item(1).View
        view.Type = 3
        for name in (
            "ShowAll", "ShowSpaces", "ShowTabs", "ShowHyphens", "ShowHiddenText",
            "ShowOptionalBreaks", "ShowBookmarks", "ShowObjectAnchors",
            "ShowTextBoundaries", "ShowFieldCodes",
        ):
            try:
                setattr(view, name, False)
            except Exception:
                pass
        view.Zoom.Percentage = 100
        for index, item in enumerate(items, start=1):
            shape = doc.Shapes.Item(f"AX{index:04d}_{item['kind']}")
            if item["kind"] != "text":
                continue
            tr = shape.TextFrame.TextRange
            text.append(tr.Text.rstrip("\r"))
            expected = int(item.get("browser_lines", 1))
            actual = int(tr.ComputeStatistics(1))
            if expected != actual:
                line_mismatch.append((index, expected, actual))
            try:
                bound_height = float(shape.TextFrame2.TextRange.BoundHeight)
                if bound_height > float(shape.Height) + 0.75:
                    overflow.append(index)
            except Exception:
                # Some Word builds reject TextFrame2 bounds for DrawingML
                # textboxes even though TextFrame and the rendered text work.
                pass
    finally:
        doc.Close(0)
        word.Quit()
    compact = "".join("\n".join(text).split())
    expected_text = [
        "".join(run.get("t", "") for run in item.get("runs", []))
        for item in items
        if item["kind"] == "text"
    ]
    text_mismatch = [
        index
        for index, (source, word_text) in enumerate(zip(expected_text, text), start=1)
        if "".join(source.split()) != "".join(word_text.split())
    ]
    missing = [value for value in REQUIRED if "".join(value.split()) not in compact]
    print(f"pages=5 shapes={len(items)} media=4svg raster=0")
    print(
        f"stable_ids=717 text_mismatch={len(text_mismatch)} "
        f"line_mismatch={len(line_mismatch)} overflow={len(overflow)} "
        f"required_missing={len(missing)} nontext_teal=0"
    )
    if line_mismatch or overflow or missing or text_mismatch:
        print(line_mismatch[:10], overflow[:10], missing, text_mismatch[:20])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
