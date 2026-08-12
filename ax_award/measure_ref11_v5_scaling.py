#!/usr/bin/env python
"""Measure the minimum horizontal text scaling needed to preserve HTML line counts."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import win32com.client as win32


HERE = Path(__file__).resolve().parent
DOCX = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v5_codex.docx"
BOXES = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else HERE / "out" / "boxes_ref11_v3_alignment_v5.json"
OUTPUT = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else HERE / "out" / "ref11_v5_scaling.json"
WD_STATISTIC_LINES = 1
SCALING_STEPS = tuple(range(99, 59, -1))


def expected_lines(item: dict) -> int:
    raw = "".join(run.get("t", "") for run in item.get("runs", []))
    explicit = raw.count("\n") + 1
    line_height = item.get("lh") or 0
    geometric = max(1, math.ceil((item["h"] - 0.4) / line_height)) if line_height else explicit
    return max(explicit, geometric)


def main() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
    items = [item for page in pages for item in page["items"]]
    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(str(DOCX), ReadOnly=True)
    result: dict[str, dict[str, object]] = {}
    try:
        if doc.Shapes.Count != len(items):
            raise RuntimeError(f"shape mismatch: Word={doc.Shapes.Count}, JSON={len(items)}")
        for index, item in enumerate(items, start=1):
            if item["kind"] != "text":
                continue
            shape = doc.Shapes.Item(f"AX{index:04d}_{item['kind']}")
            target = item.get("browser_lines", expected_lines(item))
            text_range = shape.TextFrame.TextRange
            actual = int(text_range.ComputeStatistics(WD_STATISTIC_LINES))
            if actual <= target:
                continue
            chosen = None
            for scaling in SCALING_STEPS:
                text_range.Font.Scaling = scaling
                actual = int(text_range.ComputeStatistics(WD_STATISTIC_LINES))
                if actual <= target:
                    chosen = scaling
                    break
            raw = "".join(run.get("t", "") for run in item.get("runs", []))
            result[str(index)] = {
                "scaling": chosen,
                "expected": target,
                "actual": actual,
                "text": raw,
            }
            text_range.Font.Scaling = 100
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        unresolved = sum(1 for value in result.values() if value["scaling"] is None)
        print(f"measured={len(result)} unresolved={unresolved}")
        print(OUTPUT)
    finally:
        doc.Close(SaveChanges=0)
        word.Quit()


if __name__ == "__main__":
    main()
