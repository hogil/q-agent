"""Synthetic-only research OCR candidates for embedded PPTX slide pictures.

Only raster a:blip r:embed placements in ppt/slides/slideN.xml are considered.
This does not render slides or establish visibility, caption association, or
production source authorization. No OCR engine is started automatically.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from research.document_image_ocr_adapter_20261030 import (
    MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, OCRAdapterError, _checked_path,
    _parse_output,
)
from research.docx_inline_image_ocr_research_20261030 import (
    MAX_DOCX_BYTES, MAX_ZIP_ENTRIES, MAX_UNCOMPRESSED_BYTES, MAX_XML_BYTES,
    MAX_MEDIA_BYTES, MAX_OCR_IMAGE_BYTES, MAX_OCR_IMAGE_PIXELS,
    _member_name, _xml, _validate, _authorize,
)

MAX_PPTX_BYTES = MAX_DOCX_BYTES
MAX_SLIDES = 512
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _relationships(root: ET.Element, base: str, *, source_part: str | None = None) -> dict[str, tuple[str | None, str | None]]:
    result = {}
    for rel in root.findall("rel:Relationship", NS):
        rid, target = rel.get("Id"), rel.get("Target")
        if not rid or not target or rid in result:
            raise OCRAdapterError("malformed or duplicate relationship")
        mode = rel.get("TargetMode", "Internal")
        if mode not in ("Internal", "External"):
            raise OCRAdapterError("unsupported relationship TargetMode")
        if mode == "External":
            result[rid] = (None, rel.get("Type"))
            continue
        if target.startswith(("/", "\\")) or "\\" in target or ":" in target or any(p in ("", ".") for p in target.split("/")):
            raise OCRAdapterError("unsafe relationship target")
        if source_part is not None:
            from posixpath import normpath
            path = normpath(base + "/" + target)
            if path.startswith("../") or path == "..": raise OCRAdapterError("unsafe relationship target")
        else:
            path = target if target.startswith(base + "/") else base + "/" + target
        _member_name(path)
        result[rid] = (path, rel.get("Type"))
    return result


def _zip_member_name(name: str, *, is_directory: bool) -> str:
    """Validate ZIP names while allowing conventional trailing-slash dirs."""
    checked = name[:-1] if is_directory and name.endswith("/") else name
    _member_name(checked)
    return checked


def _zip_snapshot(data: bytes):
    from io import BytesIO
    archive = None
    try:
        archive = ZipFile(BytesIO(data)); infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES: raise OCRAdapterError("PPTX ZIP entry count exceeds limit")
        entries, total = {}, 0
        for info in infos:
            normalized = _zip_member_name(info.filename, is_directory=info.is_dir())
            if info.is_dir() and info.file_size != 0:
                raise OCRAdapterError("ZIP directory entry must be empty")
            if normalized in entries: raise OCRAdapterError("duplicate ZIP member")
            entries[normalized] = info; total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES: raise OCRAdapterError("PPTX decompressed size exceeds limit")
            if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > 200):
                raise OCRAdapterError("ZIP compression ratio exceeds limit")
            if (info.filename.endswith(".xml") or info.filename.endswith(".rels")) and info.file_size > MAX_XML_BYTES:
                raise OCRAdapterError("PPTX XML exceeds limit")
            if info.filename.startswith("ppt/media/") and info.file_size > MAX_MEDIA_BYTES:
                raise OCRAdapterError("embedded media exceeds limit")
        if "ppt/presentation.xml" not in entries or "ppt/_rels/presentation.xml.rels" not in entries:
            raise OCRAdapterError("PPTX presentation or relationships are missing")
        return archive, entries
    except OCRAdapterError:
        if archive: archive.close()
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        if archive: archive.close()
        raise OCRAdapterError("corrupt or unsupported PPTX ZIP") from None


def extract_pptx_embedded_image_ocr_candidates(
    *, pptx_path: Path, source_root: Path, metadata: Mapping[str, Any], as_of: datetime,
    authorize_source: Callable[[Mapping[str, Any]], bool] | None, engine: Any,
) -> dict[str, Any]:
    """Read authorized synthetic PPTX and return unreviewed OCR candidates.

    Unsupported constructs are explicitly listed as limitations. Corrupt or
    unsafe package structures raise OCRAdapterError; no raw content is returned.
    """
    if authorize_source is None or not callable(authorize_source):
        raise OCRAdapterError("trusted source authorization callback is required")
    if not isinstance(metadata, Mapping):
        raise OCRAdapterError("source metadata must be a mapping")
    if metadata.get("synthetic_fixture") is not True or not isinstance(metadata.get("source_ref"), str) or not metadata["source_ref"].startswith("synthetic://"):
        raise OCRAdapterError("synthetic fixture metadata is required")
    source_available = _validate(metadata, as_of)
    try: _authorize(authorize_source, metadata)
    except Exception: raise OCRAdapterError("source authorization denied or failed") from None
    try: source = _checked_path(Path(pptx_path), Path(source_root), label="PPTX")
    except Exception: raise OCRAdapterError("authorized PPTX source is unavailable") from None
    try:
        with source.open("rb") as stream: snapshot = stream.read(MAX_PPTX_BYTES + 1)
    except OSError as exc:
        raise OCRAdapterError("cannot read authorized PPTX source") from None
    if len(snapshot) > MAX_PPTX_BYTES: raise OCRAdapterError("PPTX exceeds configured byte limit")
    original_hash = hashlib.sha256(snapshot).hexdigest()
    try: archive, entries = _zip_snapshot(snapshot)
    except Exception as exc:
        if isinstance(exc, OCRAdapterError): raise OCRAdapterError(str(exc)) from None
        raise OCRAdapterError("invalid PPTX package") from None
    preflight, limitations = [], [
        "only ppt/slides/slideN.xml Picture shape a:blip r:embed raster placements inspected",
        "referenced external slide/image relationships are rejected; OLE, vector images, groups, notes, masters, charts, tables, captions, text-only and visibility are unsupported",
        "slide visibility, crop, clipping, and final rendered appearance are unverified",
        "OCR derivative extraction/model/index availability is unverified; candidates must not enter an existing search bridge",
    ]
    try:
        def read_xml(name):
            info = entries[name]
            try: raw = archive.read(info)
            except Exception: raise OCRAdapterError("cannot read PPTX XML part") from None
            if len(raw) != info.file_size: raise OCRAdapterError("ZIP entry size mismatch")
            return _xml(raw, name)
        pres = read_xml("ppt/presentation.xml")
        relroot = read_xml("ppt/_rels/presentation.xml.rels")
        pres_rels = _relationships(relroot, "ppt")
        slide_ids = pres.findall("p:sldIdLst/p:sldId", NS)
        if not slide_ids: raise OCRAdapterError("presentation slide order is missing")
        slides = []
        seen_targets = set(); slide_numeric_ids = set()
        for sid in slide_ids:
            numeric_id = sid.get("id")
            if not isinstance(numeric_id, str) or not numeric_id.isascii() or not numeric_id.isdecimal() or int(numeric_id) < 256 or int(numeric_id) > 2147483647:
                raise OCRAdapterError("presentation slide id must be between 256 and 2147483647")
            normalized_id = int(numeric_id)
            if normalized_id in slide_numeric_ids: raise OCRAdapterError("duplicate presentation slide id")
            slide_numeric_ids.add(normalized_id)
            rid = sid.get(f"{{{NS['r']}}}id"); rel = pres_rels.get(rid)
            if not rel or rel[0] is None or rel[1] != SLIDE_REL_TYPE:
                raise OCRAdapterError("presentation slide relationship is unknown, external, or invalid")
            target = rel[0]
            if not re.fullmatch(r"ppt/slides/slide[1-9][0-9]*\.xml", target) or target not in entries:
                raise OCRAdapterError("presentation slide target is missing or invalid")
            if target in seen_targets: raise OCRAdapterError("duplicate presentation slide target")
            seen_targets.add(target); slides.append((target, len(slides) + 1))
        orphan_slides = sorted(n for n in entries if re.fullmatch(r"ppt/slides/slide[1-9][0-9]*\.xml", n) and n not in seen_targets)
        if orphan_slides: limitations.append("orphan slide parts excluded from OCR candidates")
        if len(slides) > MAX_SLIDES: raise OCRAdapterError("slide count exceeds limit")
        picture_shape_count = 0
        for slide_path, slide_ordinal in slides:
            slide_no = int(re.search(r"slide([0-9]+)", slide_path).group(1))
            rel_path = f"ppt/slides/_rels/slide{slide_no}.xml.rels"
            slide = read_xml(slide_path)
            if rel_path not in entries: rels = {}
            else: rels = _relationships(read_xml(rel_path), "ppt/slides", source_part=slide_path)
            shapes = slide.findall(".//p:spTree/p:pic", NS)
            picture_shape_count += len(shapes)
            if picture_shape_count > 512: raise OCRAdapterError("picture count exceeds limit")
            shape_ids = set()
            for nonvisual in slide.findall(".//p:cNvPr", NS):
                raw_id = nonvisual.get("id")
                if not isinstance(raw_id, str) or not raw_id.isascii() or not raw_id.isdecimal() or int(raw_id) > 4294967295:
                    raise OCRAdapterError("shape id must be between 0 and 4294967295")
                normalized_id = int(raw_id)
                if normalized_id in shape_ids: raise OCRAdapterError("duplicate slide shape id")
                shape_ids.add(normalized_id)
            for pic in shapes:
                nv = pic.find("p:nvPicPr/p:cNvPr", NS); shape_id = nv.get("id") if nv is not None else None
                if not isinstance(shape_id, str) or not shape_id.isascii() or not shape_id.isdecimal() or int(shape_id) < 0 or int(shape_id) > 4294967295:
                    raise OCRAdapterError("picture shape id must be between 0 and 4294967295")
                numeric_shape_id = int(shape_id)
                shape_id = str(numeric_shape_id)
                blip = pic.find("p:blipFill/a:blip", NS)
                if blip is None: continue
                rid = blip.get(f"{{{NS['r']}}}embed")
                if rid is None:
                    if blip.get(f"{{{NS['r']}}}link") is not None: limitations.append("linked picture ignored")
                    continue
                rel = rels.get(rid)
                if not rel or rel[0] is None: raise OCRAdapterError("embedded picture relationship missing or external")
                if rel[1] != IMAGE_REL_TYPE: raise OCRAdapterError("embedded picture relationship is not an image")
                target = rel[0]
                if not target.startswith("ppt/media/"): raise OCRAdapterError("embedded picture relationship escapes ppt/media")
                info = entries.get(target)
                if info is None or not info.file_size or info.file_size > MAX_IMAGE_BYTES:
                    raise OCRAdapterError("embedded image missing or exceeds size limit")
                planned_bytes = sum(len(item[5]) for item in preflight) + info.file_size
                if planned_bytes > MAX_OCR_IMAGE_BYTES: raise OCRAdapterError("total OCR image byte budget exceeded")
                anchor = f"{slide_path}#shape-{shape_id}"
                try: _authorize(authorize_source, metadata, anchor)
                except Exception: raise OCRAdapterError("source authorization denied or failed") from None
                try: payload = archive.read(info)
                except (BadZipFile, OSError, RuntimeError): raise OCRAdapterError("cannot decompress authorized embedded image") from None
                if len(payload) != info.file_size: raise OCRAdapterError("ZIP image entry size mismatch")
                try:
                    from io import BytesIO
                    import warnings
                    from PIL import Image
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", Image.DecompressionBombWarning)
                        with Image.open(BytesIO(payload)) as im:
                            width, height = im.size
                            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS: raise OCRAdapterError("image pixel limit exceeded")
                            im.verify()
                except OCRAdapterError: raise
                except Exception: raise OCRAdapterError("unsupported or corrupt embedded raster") from None
                planned_pixels = sum(item[6] * item[7] for item in preflight) + width * height
                if planned_pixels > MAX_OCR_IMAGE_PIXELS: raise OCRAdapterError("total OCR image pixel budget exceeded")
                preflight.append((slide_path, slide_no, slide_ordinal, str(shape_id), anchor, payload, width, height))
    finally:
        archive.close()
    if preflight and engine is None: raise OCRAdapterError("an explicitly injected OCR engine is required")
    candidates = []
    for path, file_no, ordinal, shape_id, anchor, payload, width, height in preflight:
        try: parsed = _parse_output(engine(payload), width, height)
        except Exception: raise OCRAdapterError("OCR inference failed") from None
        chunk = metadata.get("anchor_chunk_ids", {}).get(anchor)
        candidates.append({"kind":"ocr_text_candidate", "source_document_id":metadata["source_document_id"],
            "source_version":metadata["source_version"], "original_sha256":original_hash,
            "original_sha256_provenance":"computed_from_single_pptx_byte_snapshot",
            "image_sha256":hashlib.sha256(payload).hexdigest(), "slide_file_number":file_no,
            "slide_ordinal":ordinal, "slide_ordinal_status":"presentation_order_resolved" if ordinal else "presentation_order_unknown",
            "picture_shape_id":shape_id, "region_id":anchor, "anchor_id":anchor,
            "region_coords":[0.0,0.0,float(width),float(height)], "coordinate_frame":"image_pixels",
            "image_size":{"width":width,"height":height}, "ordered_text_confidence":parsed,
            "source_available_at":source_available.isoformat(), "available_at":None,
            "ocr_derivative_time_status":"unverified", "as_of":as_of.isoformat(),
            "existing_chunk_id":chunk, "chunk_link_status":"caller_asserted_unverified" if chunk else "unlinked",
            "status":"candidate_unreviewed"})
    return {"status":"incomplete", "source_document_id":metadata["source_document_id"],
        "source_version":metadata["source_version"], "original_sha256":original_hash,
        "original_sha256_provenance":"computed_from_single_pptx_byte_snapshot",
        "candidates":candidates, "limitations":limitations, "coverage_status":"incomplete_not_verified"}
