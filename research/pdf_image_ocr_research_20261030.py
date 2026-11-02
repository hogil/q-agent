"""Research-only extraction of embedded PDF raster placements for OCR.

PyMuPDF image placement boxes describe PDF page geometry; they do not prove
that the pixels are visible after clipping, overlays, masks, or compositing.
Path checks cannot eliminate filesystem races between validation and opening.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import stat
import tempfile
from typing import Any, Callable, Mapping

from research.document_image_ocr_adapter_20261030 import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    OCRAdapterError,
    OCRModelConfig,
    extract_ocr_candidate,
)

MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGES = 128
MAX_REGIONS = 128


def _reparse(info: Any) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _checked_file(path: Path, root: Path, label: str) -> Path:
    if not root.is_absolute() or not path.is_absolute() or ".." in path.parts:
        raise OCRAdapterError(f"{label} path must be absolute and contained")
    for candidate in (root, *root.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or _reparse(info):
            raise OCRAdapterError(f"{label} path traverses symlink/reparse point")
    current = Path(path.anchor)
    anchor_info = current.lstat()
    if stat.S_ISLNK(anchor_info.st_mode) or _reparse(anchor_info):
        raise OCRAdapterError(f"{label} path traverses symlink/reparse point")
    for part in path.parts[1:]:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or _reparse(info):
            raise OCRAdapterError(f"{label} path traverses symlink/reparse point")
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise OCRAdapterError(f"{label} is outside its allowlisted root") from exc
    if not resolved.is_file():
        raise OCRAdapterError(f"{label} is not a regular file")
    return resolved


def _checked_output_directory(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise OCRAdapterError("output_root must be an existing absolute directory")
    current = Path(path.anchor)
    anchor_info = current.lstat()
    if stat.S_ISLNK(anchor_info.st_mode) or _reparse(anchor_info):
        raise OCRAdapterError("output_root traverses symlink/reparse point")
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise OCRAdapterError("output_root must already exist") from exc
        if stat.S_ISLNK(info.st_mode) or _reparse(info):
            raise OCRAdapterError("output_root traverses symlink/reparse point")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise OCRAdapterError("output_root must be an existing directory")
    return resolved


def _metadata_check(metadata: Mapping[str, Any], as_of: datetime) -> None:
    required = ("source_document_id", "source_version", "page_chunk_ids", "available_at")
    if not isinstance(metadata, Mapping) or any(k not in metadata or metadata[k] is None for k in required):
        raise OCRAdapterError("source metadata is incomplete")
    for key in ("source_document_id", "source_version"):
        if not isinstance(metadata[key], str) or not metadata[key].strip():
            raise OCRAdapterError(f"{key} must be a non-empty string")
    available = metadata["available_at"]
    if any(not isinstance(v, datetime) or v.utcoffset() is None for v in (available, as_of)):
        raise OCRAdapterError("available_at and as_of must be timezone-aware datetimes")
    if available.astimezone(timezone.utc) > as_of.astimezone(timezone.utc):
        raise OCRAdapterError("source is unavailable at the requested as_of time")
    mapping = metadata["page_chunk_ids"]
    if not isinstance(mapping, Mapping) or not mapping:
        raise OCRAdapterError("page_chunk_ids must map page numbers to existing chunk IDs")
    for page, chunk_id in mapping.items():
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise OCRAdapterError("page_chunk_ids keys must be positive page numbers")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise OCRAdapterError("page_chunk_ids values must be non-empty strings")


def extract_pdf_image_ocr_candidates(
    *, pdf_path: Path, source_root: Path, metadata: Mapping[str, Any],
    authorize_source: Callable[[Mapping[str, Any]], bool] | None,
    as_of: datetime, output_root: Path, model: OCRModelConfig,
    model_root: Path, engine: Any,
) -> dict[str, Any]:
    """Extract raster placements, run the existing image OCR adapter, report limitations."""
    if authorize_source is None or not callable(authorize_source):
        raise OCRAdapterError("trusted source authorization callback is required")
    _metadata_check(metadata, as_of)
    try:
        authorized = authorize_source(metadata)
    except Exception as exc:
        raise OCRAdapterError("source authorization decision failed") from exc
    if authorized is not True:
        raise OCRAdapterError("source authorization denied")

    source = _checked_file(Path(pdf_path), Path(source_root), "PDF")
    with source.open("rb") as stream:
        pdf_bytes = stream.read(MAX_PDF_BYTES + 1)
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise OCRAdapterError("PDF exceeds configured byte limit")
    original_hash = hashlib.sha256(pdf_bytes).hexdigest()
    outroot = _checked_output_directory(Path(output_root))
    workdir = Path(tempfile.mkdtemp(prefix="pdf-ocr-", dir=outroot))
    candidates: list[dict[str, Any]] = []
    limitations: list[str] = []
    try:
        import fitz
        try:
            document = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise OCRAdapterError("cannot parse PDF snapshot") from exc
        with document:
            if document.needs_pass:
                raise OCRAdapterError("encrypted PDF is unsupported")
            if document.page_count < 1:
                raise OCRAdapterError("PDF has no pages")
            if document.page_count > MAX_PAGES:
                raise OCRAdapterError("PDF exceeds configured page limit")
            seen = 0
            limitations.append("coverage incomplete: clipping, occlusion, compositing, and crop transforms are not verified")
            page_infos = []
            for page_index in range(document.page_count):
                page = document[page_index]
                try:
                    infos = page.get_image_info(xrefs=True)
                except Exception as exc:
                    raise OCRAdapterError(f"cannot enumerate raster placements on page {page_index + 1}") from exc
                if infos and page_index + 1 not in metadata["page_chunk_ids"]:
                    raise OCRAdapterError(f"no caller-provided chunk mapping for image page {page_index + 1}")
                page_infos.append(infos)
            for page_index in range(document.page_count):
                page = document[page_index]
                page_number = page_index + 1
                try:
                    if page.get_drawings():
                        limitations.append(f"page {page_index + 1}: vector graphics are not OCR regions")
                except Exception as exc:
                    raise OCRAdapterError(f"cannot inspect vector graphics on page {page_index + 1}") from exc
                infos = page_infos[page_index]
                if not infos:
                    continue
                for placement_index, info in enumerate(infos, 1):
                    seen += 1
                    if seen > MAX_REGIONS:
                        raise OCRAdapterError("PDF exceeds configured image placement limit")
                    xref = int(info.get("xref", 0))
                    if xref <= 0:
                        limitations.append(f"page {page_index + 1} placement {placement_index}: inline/unknown xref image unsupported")
                        continue
                    info_width, info_height = int(info.get("width", 0)), int(info.get("height", 0))
                    if info_width < 1 or info_height < 1 or info_width * info_height > MAX_IMAGE_PIXELS:
                        limitations.append(f"page {page_number} placement {placement_index}: image-info pixel limit exceeded before extraction")
                        continue
                    try:
                        extracted = document.extract_image(xref)
                        image_bytes = extracted["image"]
                        width, height = int(extracted["width"]), int(extracted["height"])
                    except Exception as exc:
                        raise OCRAdapterError(f"cannot extract image xref {xref} on page {page_index + 1}") from exc
                    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
                        limitations.append(f"page {page_index + 1} placement {placement_index}: empty or oversized image omitted")
                        continue
                    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                        limitations.append(f"page {page_index + 1} placement {placement_index}: image pixel limit exceeded")
                        continue
                    rect = fitz.Rect(info["bbox"])
                    if not all(map(lambda v: float("-inf") < v < float("inf"), rect)):
                        limitations.append(f"page {page_index + 1} placement {placement_index}: invalid bbox omitted")
                        continue
                    transform = info.get("transform", (1, 0, 0, 1, 0, 0))
                    rotated = abs(float(transform[1])) > 1e-6 or abs(float(transform[2])) > 1e-6
                    if rotated:
                        limitations.append(f"page {page_number} placement {placement_index}: rotated image bbox is axis-aligned envelope")
                    page_rotation = int(page.rotation)
                    try:
                        unrotated_bounds = fitz.Rect(page.cropbox)
                        if not unrotated_bounds.contains(rect):
                            limitations.append(f"page {page_number} placement {placement_index}: bbox extends beyond unrotated cropbox bounds")
                    except Exception:
                        limitations.append(f"page {page_number} placement {placement_index}: unrotated bounds check unavailable")
                    info_has_mask = bool(info.get("has-mask", False))
                    extracted_smask = int(extracted.get("smask", 0) or 0)
                    image_flags = info.get("flags")
                    if info_has_mask or extracted_smask:
                        limitations.append(f"page {page_number} placement {placement_index}: bitmap mask/alpha compositing may differ from visible pixels")
                    # A unique file per placement preserves repeated xref placements.
                    suffix = extracted.get("ext", "bin")
                    image_path = workdir / f"p{page_index + 1}-r{placement_index}.{suffix}"
                    with image_path.open("xb") as stream:
                        stream.write(image_bytes)
                    region_id = f"page-{page_number}-placement-{placement_index}-xref-{xref}"
                    item_metadata = {
                        "source_document_id": metadata["source_document_id"],
                        "source_version": metadata["source_version"],
                        "original_sha256": original_hash,
                        "page": page_number,
                        "region_id": region_id,
                        "region_coords": [0, 0, width, height],
                        "coordinate_frame": "image_pixels",
                        "page_bbox": [float(v) for v in rect],
                        "page_bbox_coordinate_frame": "PyMuPDF unrotated page coordinates (points; origin top-left; axis-aligned bbox)",
                        "page_rotation_degrees": page_rotation,
                        "chunk_id": metadata["page_chunk_ids"][page_number],
                        "available_at": metadata["available_at"],
                    }
                    candidate = extract_ocr_candidate(
                        image_path=image_path, source_root=workdir, metadata=item_metadata,
                        model=model, model_root=model_root, authorize_source=authorize_source,
                        as_of=as_of, engine=engine,
                    )
                    candidate["page_bbox"] = item_metadata["page_bbox"]
                    candidate["page_bbox_coordinate_frame"] = item_metadata["page_bbox_coordinate_frame"]
                    candidate["page_rotation_degrees"] = page_rotation
                    candidate["page_chunk_id_provenance"] = "caller_asserted_mapping_unverified_against_index"
                    candidate["image_flags"] = image_flags
                    candidate["image_smask_xref"] = extracted_smask
                    candidate["visibility_status"] = "coverage_incomplete_not_verified"
                    candidates.append(candidate)
            if seen == 0:
                limitations.append("PDF contains no extractable embedded raster placements")
            if document.is_repaired:
                limitations.append("PDF parser repaired malformed structure; placement completeness is uncertain")
        status = "incomplete"
        return {
            "status": status,
            "source_document_id": metadata["source_document_id"],
            "source_version": metadata["source_version"],
            "original_sha256": original_hash,
            "original_sha256_provenance": "computed_from_single_pdf_byte_snapshot",
            "page_chunk_mapping_provenance": "caller_asserted_mapping_unverified_against_index",
            "candidates": candidates,
            "limitations": limitations,
            "coverage_status": "incomplete_not_verified",
            "output_directory": str(workdir),
        }
    except Exception:
        # Preserve the temp directory and contents for diagnosis on failure.
        raise
