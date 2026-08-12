#!/usr/bin/env python
"""Final structural and Word-render checks for the ref11 v6 native DOCX."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from zipfile import ZipFile

import win32com.client as win32
from lxml import etree


HERE = Path(__file__).resolve().parent
DOCX = (
    Path(sys.argv[1]).resolve()
    if len(sys.argv) > 1
    else HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v6_codex.docx"
)
BOXES = HERE / "out" / "boxes_ref11_v3_alignment_v6.json"
WD_STATISTIC_LINES = 1
TEAL = ("12B5B0", "0E9C97", "7FD1CE", "E6F7F6", "B7E6E4")
REQUIRED_TEXT = (
    "1. 해결하려는 문제 - 이상 감지 이후 분석과 판정이 대부분 Manual이다",
    "사례형 시나리오",
    "교차 조사 4h+",
    "E2E 전체 Process 재설계",
    "L0 정보 제공",
    "L2 승인 후 실행",
    "L3 조건부 자동조치",
    "3Q 그림자",
    "LLM Wiki",
    "Graph RAG",
    "현재 회귀 기준선, recall@10",
    "운영 목표 0건",
    "미승인 L2 조치 실행",
    "IIII. 경영효과",
    "200억",
    "57.5배",
    "6.3일",
    "설계 문서 31종",
    "GPU 수요 등록 완료",
)


def main() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
    items = [item for page in pages for item in page["items"]]

    with ZipFile(DOCX) as package:
        media = [name for name in package.namelist() if name.startswith("word/media/")]
        raster = [name for name in media if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg"}]
        if len(media) != 4 or raster or any(not name.endswith(".svg") for name in media):
            raise RuntimeError(f"unexpected media inventory: {media}")
        document = etree.fromstring(package.read("word/document.xml"))
        ns = {
            "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        }
        nontext_teal = []
        for anchor in document.xpath(".//wp:anchor", namespaces=ns):
            name = anchor.find("wp:docPr", ns).get("name", "")
            if name.endswith("_text"):
                continue
            serialized = etree.tostring(anchor).decode("utf-8").upper()
            if any(color in serialized for color in TEAL):
                nontext_teal.append(name)
        for name in media:
            serialized = package.read(name).decode("utf-8").upper()
            if any(color in serialized for color in TEAL):
                nontext_teal.append(name)
        if nontext_teal:
            raise RuntimeError(f"teal remains in non-text graphics: {nontext_teal}")

    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(str(DOCX), ReadOnly=True, OpenAndRepair=False)
    line_mismatches = []
    height_overflow = []
    shape_text = []
    try:
        page_count = int(doc.ComputeStatistics(2))
        if page_count != 5:
            raise RuntimeError(f"page count: {page_count}")
        if doc.Shapes.Count != len(items):
            raise RuntimeError(f"shape count: Word={doc.Shapes.Count}, JSON={len(items)}")

        for index, item in enumerate(items, start=1):
            stable_name = f"AX{index:04d}_{item['kind']}"
            shape = doc.Shapes.Item(stable_name)
            if item["kind"] != "text":
                continue
            shape_text.append(shape.TextFrame.TextRange.Text.rstrip("\r"))
            expected = int(item.get("browser_lines", 1))
            actual = int(shape.TextFrame.TextRange.ComputeStatistics(WD_STATISTIC_LINES))
            if actual != expected:
                line_mismatches.append((stable_name, expected, actual))
            try:
                bound_height = float(shape.TextFrame2.TextRange.BoundHeight)
                if bound_height > float(shape.Height) + 0.75:
                    height_overflow.append((stable_name, round(bound_height, 2), round(float(shape.Height), 2)))
            except Exception:
                pass
    finally:
        doc.Close(SaveChanges=0)
        word.Quit()

    joined_text = "\n".join(shape_text)
    compact_text = "".join(joined_text.split())
    missing = [value for value in REQUIRED_TEXT if "".join(value.split()) not in compact_text]
    forbidden = [value for value in ("심사 60",) if "".join(value.split()) in compact_text]

    print(f"pages=5 shapes={len(items)} media=4svg raster=0")
    print(f"line_mismatches={len(line_mismatches)}")
    print(f"height_overflow={len(height_overflow)}")
    print(f"required_missing={len(missing)} forbidden_present={len(forbidden)}")
    if line_mismatches:
        print(line_mismatches[:20])
    if height_overflow:
        print(height_overflow[:20])
    if missing:
        print(missing)
    if forbidden:
        print(forbidden)
    if line_mismatches or height_overflow or missing or forbidden:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
