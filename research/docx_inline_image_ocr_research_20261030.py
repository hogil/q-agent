"""Research-only OCR candidates for raster images placed in DOCX main content.

WordprocessingML positions do not provide rendered page numbers or prove final
visibility. This intentionally reports incomplete coverage and never writes
extracted images or candidate artifacts to disk.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import stat
from typing import Any, Callable, Mapping
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from research.document_image_ocr_adapter_20261030 import (
    MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, OCRAdapterError, OCRModelConfig,
    _checked_path, _parse_output, _sha256_file, _valid_sha256,
)

MAX_DOCX_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 4096
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_MEDIA_BYTES = 32 * 1024 * 1024
MAX_PLACEMENTS = 128
MAX_OCR_IMAGE_BYTES = 128 * 1024 * 1024
MAX_OCR_IMAGE_PIXELS = 120_000_000
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _validate(metadata: Mapping[str, Any], as_of: datetime) -> datetime:
    if not isinstance(metadata, Mapping):
        raise OCRAdapterError("source metadata is incomplete")
    for key in ("source_document_id", "source_version"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise OCRAdapterError(f"{key} must be a non-empty string")
    available = metadata.get("available_at")
    if any(not isinstance(v, datetime) or v.utcoffset() is None for v in (available, as_of)):
        raise OCRAdapterError("available_at and as_of must be timezone-aware datetimes")
    if available.astimezone(timezone.utc) > as_of.astimezone(timezone.utc):
        raise OCRAdapterError("source is unavailable at the requested as_of time")
    mapping = metadata.get("anchor_chunk_ids", {})
    if not isinstance(mapping, Mapping):
        raise OCRAdapterError("anchor_chunk_ids must be a mapping")
    for key, value in mapping.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not value.strip():
            raise OCRAdapterError("anchor mapping must contain non-empty IDs")
    return available


def _authorize(callback: Callable, metadata: Mapping[str, Any], anchor: str | None = None) -> None:
    scoped = dict(metadata)
    if anchor is not None:
        scoped["anchor_id"] = anchor
    try:
        allowed = callback(scoped)
    except Exception as exc:
        raise OCRAdapterError("source authorization decision failed") from exc
    if allowed is not True:
        raise OCRAdapterError("source authorization denied")


def _member_name(name: str) -> None:
    if (not name or name.startswith(("/", "\\")) or "\\" in name or
            any(p in ("", ".", "..") for p in name.split("/")) or ":" in name):
        raise OCRAdapterError("unsafe ZIP member path")


def _open_zip_snapshot(data: bytes) -> tuple[ZipFile, dict[str, Any], list[str]]:
    archive = None
    try:
        from io import BytesIO
        archive = ZipFile(BytesIO(data))
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise OCRAdapterError("DOCX ZIP entry count exceeds limit")
        names, total = set(), 0
        for info in infos:
            _member_name(info.filename)
            if info.filename in names:
                raise OCRAdapterError("duplicate ZIP member")
            names.add(info.filename)
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise OCRAdapterError("DOCX decompressed size exceeds limit")
            if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > 200):
                raise OCRAdapterError("ZIP compression ratio exceeds limit")
            if info.filename in ("word/document.xml", "word/_rels/document.xml.rels") and info.file_size > MAX_XML_BYTES:
                raise OCRAdapterError("DOCX XML exceeds limit")
            if info.filename.startswith("word/media/") and info.file_size > MAX_MEDIA_BYTES:
                raise OCRAdapterError("embedded media exceeds limit")
        wanted = {"word/document.xml", "word/_rels/document.xml.rels"}
        if not wanted.issubset(names):
            raise OCRAdapterError("DOCX main document or relationships are missing")
        by_name = {info.filename: info for info in infos}
        return archive, by_name, list(names)
    except OCRAdapterError:
        if archive is not None:
            archive.close()
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        if archive is not None:
            archive.close()
        raise OCRAdapterError("corrupt or unsupported DOCX ZIP") from exc


def _xml(data: bytes, label: str) -> ET.Element:
    if data.startswith(b"\xef\xbb\xbf") or b"\x00" in data[:128]:
        raise OCRAdapterError(f"{label} must be UTF-8 XML")
    try:
        source = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise OCRAdapterError(f"{label} must be UTF-8 XML") from exc
    if "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
        raise OCRAdapterError("DTD and entities are forbidden")
    try:
        return ET.fromstring(source)
    except ET.ParseError as exc:
        raise OCRAdapterError(f"invalid {label}") from exc


def _model_check(model: OCRModelConfig, model_root: Path) -> tuple[str, str]:
    det = _checked_path(model.detection_model_path, model_root, label="detection checkpoint")
    rec = _checked_path(model.recognition_model_path, model_root, label="recognition checkpoint")
    dh, rh = _valid_sha256(model.detection_sha256, "detection_sha256"), _valid_sha256(model.recognition_sha256, "recognition_sha256")
    if _sha256_file(det) != dh or _sha256_file(rec) != rh:
        raise OCRAdapterError("configured checkpoint hash mismatch")
    if not isinstance(model.version, str) or not model.version.strip():
        raise OCRAdapterError("model version is required")
    return dh, rh


def extract_docx_inline_image_ocr_candidates(
    *, docx_path: Path, source_root: Path, metadata: Mapping[str, Any], as_of: datetime,
    authorize_source: Callable[[Mapping[str, Any]], bool] | None,
    model: OCRModelConfig, model_root: Path, engine: Any,
) -> dict[str, Any]:
    """Extract main-part DrawingML image placements and return unpaged candidates."""
    if authorize_source is None or not callable(authorize_source):
        raise OCRAdapterError("trusted source authorization callback is required")
    available = _validate(metadata, as_of)
    _authorize(authorize_source, metadata)
    source = _checked_path(Path(docx_path), Path(source_root), label="DOCX")
    with source.open("rb") as stream:
        snapshot = stream.read(MAX_DOCX_BYTES + 1)
    if len(snapshot) > MAX_DOCX_BYTES:
        raise OCRAdapterError("DOCX exceeds configured byte limit")
    source_hash = hashlib.sha256(snapshot).hexdigest()
    archive, entries, names = _open_zip_snapshot(snapshot)
    try:
        try:
            doc_xml = archive.read(entries["word/document.xml"])
            rel_xml = archive.read(entries["word/_rels/document.xml.rels"])
            if len(doc_xml) != entries["word/document.xml"].file_size or len(rel_xml) != entries["word/_rels/document.xml.rels"].file_size:
                raise OCRAdapterError("ZIP entry size mismatch")
            root = _xml(doc_xml, "document.xml")
            relroot = _xml(rel_xml, "document relationships")
        except (BadZipFile, OSError, RuntimeError) as exc:
            raise OCRAdapterError("corrupt or unsupported DOCX XML entry") from exc
        rels = {}
        external = set()
        for rel in relroot.findall("rel:Relationship", NS):
            rid, target = rel.get("Id"), rel.get("Target")
            if not rid or not target:
                raise OCRAdapterError("malformed document relationship")
            if rid in rels or rid in external:
                raise OCRAdapterError("duplicate relationship ID")
            mode = rel.get("TargetMode", "Internal")
            if mode not in ("Internal", "External"):
                raise OCRAdapterError("unsupported relationship TargetMode")
            if mode == "External":
                external.add(rid)
                rels[rid] = (None, rel.get("Type"))
                continue
            if target.startswith(("/", "\\")) or "\\" in target or ".." in target.split("/"):
                raise OCRAdapterError("unsafe relationship target")
            resolved = target if target.startswith("word/") else "word/" + target
            _member_name(resolved)
            rels[rid] = (resolved, rel.get("Type"))
        dh, rh = _model_check(model, Path(model_root))
        limitations = ["coverage incomplete: only DrawingML a:blip r:embed in document.xml is inspected",
                       "page unknown; layout rendering is required", "visibility, clipping, crop, and final rendering are unverified",
                       "header/footer, VML, vector, linked/external, and unsupported image placements are not OCRed"]
        if external:
            limitations.append("external relationships are ignored; no network fetch is performed")
        for name in names:
            if name.startswith(("word/header", "word/footer")) and name.endswith(".xml"):
                limitations.append("header/footer image relationships were not inspected")
                break
        candidates = []
        placements = root.findall(".//a:blip", NS)
        if len(placements) > MAX_PLACEMENTS:
            raise OCRAdapterError("DOCX image placement count exceeds limit")
        preflight = []
        total_bytes = total_pixels = 0
        for ordinal, blip in enumerate(placements, 1):
            rid = blip.get(f"{{{NS['r']}}}embed")
            if rid is None:
                if blip.get(f"{{{NS['r']}}}link") is not None:
                    limitations.append(f"placement {ordinal}: linked external image ignored")
                continue
            relation = rels.get(rid)
            if relation is None:
                limitations.append(f"placement {ordinal}: missing, external, or non-media relationship omitted")
                continue
            target, rel_type = relation
            if rel_type != IMAGE_REL_TYPE:
                raise OCRAdapterError("embedded image relationship has a non-image Type")
            if target is None or not target.startswith("word/media/"):
                raise OCRAdapterError("embedded image relationship escapes word/media")
            info = entries.get(target)
            if info is None or not info.file_size or info.file_size > MAX_IMAGE_BYTES:
                limitations.append(f"placement {ordinal}: missing or oversized image omitted")
                continue
            anchor_id = f"word/document.xml#drawing-{ordinal}"
            _authorize(authorize_source, metadata, anchor_id)
            try:
                payload = archive.read(info)
            except (BadZipFile, OSError, RuntimeError) as exc:
                raise OCRAdapterError("cannot decompress authorized embedded image") from exc
            if len(payload) != info.file_size or not payload:
                raise OCRAdapterError("ZIP image entry size mismatch")
            try:
                from io import BytesIO
                import warnings
                from PIL import Image, ImageFile
                Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
                ImageFile.LOAD_TRUNCATED_IMAGES = False
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(payload)) as im:
                    width, height = im.size
                    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                        raise OCRAdapterError("image pixel limit exceeded")
                    im.verify()
            except OCRAdapterError:
                raise
            except Exception:
                limitations.append(f"placement {ordinal}: unsupported or corrupt raster omitted")
                continue
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                limitations.append(f"placement {ordinal}: image pixel limit exceeded")
                continue
            total_bytes += len(payload)
            total_pixels += width * height
            if total_bytes > MAX_OCR_IMAGE_BYTES:
                raise OCRAdapterError("total OCR image byte budget exceeded")
            if total_pixels > MAX_OCR_IMAGE_PIXELS:
                raise OCRAdapterError("total OCR image pixel budget exceeded")
            preflight.append((ordinal, anchor_id, payload, width, height))
    finally:
        archive.close()
    if preflight and engine is None:
        raise OCRAdapterError("an explicitly injected OCR engine is required")
    for ordinal, anchor_id, payload, width, height in preflight:
        try:
            parsed = _parse_output(engine(payload), width, height)
        except OCRAdapterError:
            raise
        except Exception as exc:
            raise OCRAdapterError("OCR inference failed") from exc
        chunk = metadata.get("anchor_chunk_ids", {}).get(anchor_id)
        candidates.append({
            "kind": "ocr_text_candidate", "source_document_id": metadata["source_document_id"],
            "source_version": metadata["source_version"], "original_sha256": source_hash,
            "original_sha256_provenance": "computed_from_single_docx_byte_snapshot",
            "image_sha256": hashlib.sha256(payload).hexdigest(), "page": None,
            "page_status": "unknown_requires_layout_rendering", "anchor_id": anchor_id,
            "anchor_part": "word/document.xml", "anchor_ordinal": ordinal,
            "region_id": anchor_id, "region_coords": [0.0, 0.0, float(width), float(height)],
            "coordinate_frame": "image_pixels", "image_size": {"width": width, "height": height},
            "ordered_text_confidence": parsed, "model_version": model.version,
            "model_checkpoint_sha256": {"detection": dh, "recognition": rh},
            "model_checkpoint_provenance": "configured_checkpoint_hashes_unbound_to_engine",
            "model_fingerprint_provenance": "caller_asserted_unverified",
            "available_at": available.isoformat(), "as_of": as_of.isoformat(),
            "existing_chunk_id": chunk, "chunk_link_status": "caller_asserted_unverified" if chunk else "unlinked",
            "status": "candidate_unreviewed",
        })
    if not placements:
        limitations.append("document main part contains no DrawingML raster placements")
    return {"status": "incomplete", "source_document_id": metadata["source_document_id"],
            "source_version": metadata["source_version"], "original_sha256": source_hash,
            "original_sha256_provenance": "computed_from_single_docx_byte_snapshot",
            "candidates": candidates, "limitations": limitations,
            "coverage_status": "incomplete_not_verified"}
