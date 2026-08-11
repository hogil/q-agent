#!/usr/bin/env python
"""Remove Word-generated PNG fallbacks while retaining the source SVGs."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import win32com.client as win32
from lxml import etree


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v3.docx"
TARGET = HERE / "out" / "AX_Award_지원서_ref11_v3_editable_v4.docx"
PDF = TARGET.with_suffix(".pdf")

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
ASVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def rewrite_package() -> tuple[int, int]:
    with ZipFile(SOURCE) as source_zip:
        document = etree.fromstring(source_zip.read("word/document.xml"))
        rels = etree.fromstring(source_zip.read("word/_rels/document.xml.rels"))
        content_types = etree.fromstring(source_zip.read("[Content_Types].xml"))

        png_ids = set()
        converted = 0
        ns = {"a": A_NS, "asvg": ASVG_NS}
        embed = f"{{{R_NS}}}embed"
        for blip in document.xpath(".//a:blip", namespaces=ns):
            svg_blips = blip.xpath(".//asvg:svgBlip", namespaces=ns)
            if not svg_blips:
                continue
            fallback_id = blip.get(embed)
            svg_id = svg_blips[0].get(embed)
            if fallback_id and svg_id:
                png_ids.add(fallback_id)
                blip.set(embed, svg_id)
                converted += 1

        removed_targets = set()
        for rel in list(rels):
            if rel.get("Id") in png_ids:
                removed_targets.add("word/" + rel.get("Target", ""))
                rels.remove(rel)

        for default in list(content_types):
            if (
                default.tag == f"{{{CT_NS}}}Default"
                and default.get("Extension", "").lower() == "png"
            ):
                content_types.remove(default)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as temp_file:
            temp_path = Path(temp_file.name)
        try:
            with ZipFile(temp_path, "w", ZIP_DEFLATED) as target_zip:
                for item in source_zip.infolist():
                    if item.filename in removed_targets:
                        continue
                    if item.filename == "word/document.xml":
                        data = etree.tostring(
                            document, xml_declaration=True, encoding="UTF-8", standalone=True
                        )
                    elif item.filename == "word/_rels/document.xml.rels":
                        data = etree.tostring(
                            rels, xml_declaration=True, encoding="UTF-8", standalone=True
                        )
                    elif item.filename == "[Content_Types].xml":
                        data = etree.tostring(
                            content_types,
                            xml_declaration=True,
                            encoding="UTF-8",
                            standalone=True,
                        )
                    else:
                        data = source_zip.read(item.filename)
                    target_zip.writestr(item, data)
            shutil.copy2(temp_path, TARGET)
        finally:
            temp_path.unlink(missing_ok=True)
    return converted, len(removed_targets)


def verify_with_word() -> int:
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(str(TARGET), ReadOnly=True, OpenAndRepair=False)
    try:
        pages = doc.ComputeStatistics(2)
        doc.ExportAsFixedFormat(str(PDF), ExportFormat=17)
        return pages
    finally:
        doc.Close(SaveChanges=0)
        word.Quit()


def main() -> None:
    converted, removed = rewrite_package()
    pages = verify_with_word()
    print(f"svg direct references: {converted}")
    print(f"raster fallbacks removed: {removed}")
    print(f"pages: {pages}")
    print(TARGET)
    print(PDF)


if __name__ == "__main__":
    main()
