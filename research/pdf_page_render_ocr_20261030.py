"""Research-only OCR over rendered, visible PDF page crops.

The pixel-to-page transform is reported for provenance; precise coordinate
mapping has not been validated. Filesystem checks cannot eliminate TOCTOU races.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import math
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

from research.document_image_ocr_adapter_20261030 import (
    OCRAdapterError, OCRModelConfig, extract_ocr_candidate,
)
from research.pdf_image_ocr_research_20261030 import (
    MAX_PDF_BYTES, MAX_PAGES, _checked_file, _checked_output_directory, _metadata_check,
)

MAX_PAGE_PIXELS = 40_000_000
MAX_TOTAL_PIXELS = 120_000_000


def extract_pdf_rendered_page_ocr_candidates(
    *, pdf_path: Path, source_root: Path, metadata: Mapping[str, Any],
    authorize_source: Callable[[Mapping[str, Any]], bool] | None, as_of: datetime,
    output_root: Path, model: OCRModelConfig, model_root: Path, engine: Any,
    dpi: int = 150,
) -> dict[str, Any]:
    """Render each mapped page from one bounded snapshot and pass PNGs to OCR."""
    if authorize_source is None or not callable(authorize_source):
        raise OCRAdapterError("trusted source authorization callback is required")
    _metadata_check(metadata, as_of)
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 200:
        raise OCRAdapterError("dpi must be an integer from 72 through 200")
    try:
        authorized = authorize_source(metadata)
    except Exception as exc:
        raise OCRAdapterError("source authorization decision failed") from exc
    if authorized is not True:
        raise OCRAdapterError("source authorization denied")
    mapping = metadata.get("page_chunk_ids")
    if not isinstance(mapping, Mapping) or not mapping:
        raise OCRAdapterError("page_chunk_ids must map page numbers to existing chunk IDs")

    source = _checked_file(Path(pdf_path), Path(source_root), "PDF")
    with source.open("rb") as stream:
        pdf_bytes = stream.read(MAX_PDF_BYTES + 1)
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise OCRAdapterError("PDF exceeds configured byte limit")
    original_hash = hashlib.sha256(pdf_bytes).hexdigest()
    outroot = _checked_output_directory(Path(output_root))
    import fitz
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise OCRAdapterError("cannot parse PDF snapshot") from exc
    candidates = []
    limitations = [
        "coverage is limited to rendered visible crop; OCR completeness is not guaranteed",
        "low resolution, annotations (disabled), hidden layers, fonts, visual clipping, and false positives may affect results",
        "pixel-to-page coordinate mapping is recorded but not validated for precision",
        "OCR engine and authorization are caller-injected; ACL and engine-hash binding are unverified",
        "path validation cannot eliminate filesystem TOCTOU races",
    ]
    try:
        workdir = None
        with document:
            if document.needs_pass:
                raise OCRAdapterError("encrypted PDF is unsupported")
            if document.page_count < 1:
                raise OCRAdapterError("PDF has no pages")
            if document.page_count > MAX_PAGES:
                raise OCRAdapterError("PDF exceeds configured page limit")
            for page_number in range(1, document.page_count + 1):
                if page_number not in mapping:
                    raise OCRAdapterError(f"no caller-provided chunk mapping for page {page_number}")
            estimates = []
            for page in document:
                rect = page.rect
                width_points, height_points = float(rect.width), float(rect.height)
                if (not math.isfinite(width_points) or not math.isfinite(height_points)
                        or width_points <= 0 or height_points <= 0):
                    raise OCRAdapterError("page geometry must be finite and positive")
                width = math.ceil(width_points * dpi / 72) + 1
                height = math.ceil(height_points * dpi / 72) + 1
                pixels = width * height
                if width < 1 or height < 1 or pixels > MAX_PAGE_PIXELS:
                    raise OCRAdapterError("rendered page exceeds configured pixel limit")
                estimates.append(pixels)
            if sum(estimates) > MAX_TOTAL_PIXELS:
                raise OCRAdapterError("PDF exceeds configured total render pixel limit")
            # No output side effect occurs before every page passes structural,
            # mapping, geometry, and conservative rounded-pixel preflight.
            workdir = Path(tempfile.mkdtemp(prefix="pdf-page-render-ocr-", dir=outroot))
            total_actual = 0
            for page_index, page in enumerate(document):
                pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False, annots=False)
                actual = int(pix.width) * int(pix.height)
                total_actual += actual
                if pix.width < 1 or pix.height < 1 or actual > MAX_PAGE_PIXELS:
                    raise OCRAdapterError("rendered page exceeds configured pixel limit")
                if total_actual > MAX_TOTAL_PIXELS:
                    raise OCRAdapterError("PDF exceeds configured total render pixel limit")
                page_number = page_index + 1
                png_path = workdir / f"page-{page_number}.png"
                png_path.write_bytes(pix.tobytes("png"))
                rect, cropbox = page.rect, page.cropbox
                matrix = page.derotation_matrix
                info = {
                    "source_document_id": metadata["source_document_id"],
                    "source_version": metadata["source_version"],
                    "original_sha256": original_hash, "page": page_number,
                    "region_id": f"rendered-page-{page_number}",
                    "region_coords": [0, 0, pix.width, pix.height],
                    "coordinate_frame": "rendered_page_pixels",
                    "chunk_id": mapping[page_number],
                    "available_at": metadata["available_at"],
                    "rendered_page_pixels": {"width": pix.width, "height": pix.height},
                    "page_rect_points": [float(v) for v in rect],
                    "page_cropbox_points": [float(v) for v in cropbox],
                    "page_rotation_degrees": int(page.rotation), "render_dpi": dpi,
                    "pixmap_irect": [int(v) for v in pix.irect],
                    "derotation_matrix": [float(v) for v in matrix],
                }
                candidate = extract_ocr_candidate(
                    image_path=png_path, source_root=workdir, metadata=info,
                    model=model, model_root=model_root, authorize_source=authorize_source,
                    as_of=as_of, engine=engine,
                )
                for key in ("rendered_page_pixels", "page_rect_points", "page_cropbox_points",
                            "page_rotation_degrees", "render_dpi", "pixmap_irect", "derotation_matrix"):
                    candidate[key] = info[key]
                candidate["page_chunk_id_provenance"] = "caller_asserted_mapping_unverified_against_index"
                candidate["original_sha256"] = original_hash
                candidate["original_sha256_provenance"] = "computed_from_single_pdf_byte_snapshot"
                candidates.append(candidate)
            if document.is_repaired:
                limitations.append("PDF parser repaired malformed structure; render completeness is uncertain")
    except Exception:
        # Once rendering begins, keep the diagnostic directory and any pages
        # already rendered; preflight failures create no directory.
        raise
    return {"status": "incomplete", "coverage_status": "incomplete_not_verified",
            "source_document_id": metadata["source_document_id"], "source_version": metadata["source_version"],
            "original_sha256": original_hash, "original_sha256_provenance": "computed_from_single_pdf_byte_snapshot",
            "page_chunk_mapping_provenance": "caller_asserted_mapping_unverified_against_index",
            "candidates": candidates, "limitations": limitations, "output_directory": str(workdir)}
