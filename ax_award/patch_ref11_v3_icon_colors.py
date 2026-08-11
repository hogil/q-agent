#!/usr/bin/env python
"""Gray only teal icon glyphs in the editable ref11 Word document."""

from __future__ import annotations

from pathlib import Path

import win32com.client as win32


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v2.docx"
TARGET = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v3.docx"
PDF = TARGET.with_suffix(".pdf")
ICONS = set("●→✔✓↗↖↩")


def bgr(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


COLOR_MAP = {
    bgr((18, 181, 176)): bgr((146, 146, 146)),
    bgr((14, 156, 151)): bgr((135, 135, 135)),
    bgr((127, 209, 206)): bgr((191, 191, 191)),
    bgr((183, 230, 228)): bgr((219, 219, 219)),
    bgr((230, 247, 246)): bgr((243, 243, 243)),
}


def main() -> None:
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    word.ScreenUpdating = False
    doc = word.Documents.Open(str(SOURCE), ReadOnly=False)
    changed = 0
    try:
        for shape in doc.Shapes:
            try:
                if not shape.TextFrame.HasText:
                    continue
                text_range = shape.TextFrame.TextRange
                text = text_range.Text.rstrip("\r")
                for index, character in enumerate(text, start=1):
                    if character not in ICONS:
                        continue
                    char_range = text_range.Characters.Item(index)
                    original = int(char_range.Font.Color)
                    replacement = COLOR_MAP.get(original)
                    if replacement is None:
                        continue
                    char_range.Font.Color = replacement
                    changed += 1
            except Exception:
                continue
        doc.SaveAs2(str(TARGET), FileFormat=16)
        doc.ExportAsFixedFormat(str(PDF), ExportFormat=17)
        pages = doc.ComputeStatistics(2)
        print(f"icon glyphs changed: {changed}")
        print(f"pages: {pages}")
        print(TARGET)
        print(PDF)
    finally:
        doc.Close(SaveChanges=0)
        word.ScreenUpdating = True
        word.Quit()


if __name__ == "__main__":
    main()
