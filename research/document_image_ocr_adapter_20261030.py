"""Research-only OCR candidate adapter; never persists images or live indexes.

RapidOCR API fields are based on its official usage docs. A real RapidOCR
engine is deliberately disabled here: deployment-specific network isolation,
local config verification and runner integration are not established. Tests
use only a synthetic injected engine. This is not a verified site ACL adapter.
Path checks reduce symlink/reparse exposure but cannot prevent filesystem races
between checks and open; deployment still needs an isolated trusted workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import stat
from typing import Any, Callable, Mapping


MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


class OCRAdapterError(ValueError):
    """Raised when authorization, local input, provenance, or output is invalid."""


@dataclass(frozen=True)
class OCRModelConfig:
    version: str
    detection_model_path: Path
    detection_sha256: str
    recognition_model_path: Path
    recognition_sha256: str


def _has_reparse_attribute(info: Any) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _checked_root(root: Path | None) -> Path:
    if root is None or not Path(root).is_absolute():
        raise OCRAdapterError("an absolute trusted allowlist root is required")
    raw = Path(root)
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise OCRAdapterError("allowlist root is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or _has_reparse_attribute(info):
            raise OCRAdapterError("allowlist root cannot traverse symlink/reparse points")
    return raw.resolve(strict=True)


def _checked_path(path: Path, root: Path | None, *, label: str) -> Path:
    allow_root = _checked_root(root)
    candidate = Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise OCRAdapterError(f"{label} path must be absolute and contain no '..'")
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise OCRAdapterError(f"{label} is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or _has_reparse_attribute(info):
            raise OCRAdapterError(f"{label} path contains a symlink/reparse point")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(allow_root)
    except (OSError, ValueError) as exc:
        raise OCRAdapterError(f"{label} is outside its allowlisted root") from exc
    if not resolved.is_file():
        raise OCRAdapterError(f"{label} is not a regular file")
    return resolved


def _read_bounded_image(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise OCRAdapterError("image exceeds configured byte limit")
    return data


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise OCRAdapterError(f"{field} must be a 64-character SHA-256 hex digest")
    return value.lower()


def _validate_metadata(metadata: Mapping[str, Any], as_of: datetime) -> datetime:
    required = ("source_document_id", "source_version", "original_sha256", "page", "region_id", "region_coords", "chunk_id", "available_at")
    if not isinstance(metadata, Mapping) or any(key not in metadata or metadata[key] is None for key in required):
        raise OCRAdapterError("source metadata is incomplete")
    for key in ("source_document_id", "source_version", "region_id", "chunk_id"):
        if not isinstance(metadata[key], str) or not metadata[key].strip():
            raise OCRAdapterError(f"{key} must be a non-empty string")
    _valid_sha256(metadata["original_sha256"], "original_sha256")
    page = metadata["page"]
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise OCRAdapterError("page must be a positive integer")
    coords = metadata["region_coords"]
    if not isinstance(coords, (list, tuple)) or len(coords) != 4:
        raise OCRAdapterError("region_coords must contain four numeric values")
    try:
        values = [float(v) for v in coords]
    except (TypeError, ValueError) as exc:
        raise OCRAdapterError("region_coords must contain four numeric values") from exc
    if any(not math.isfinite(v) for v in values) or values[0] < 0 or values[1] < 0 or values[2] <= values[0] or values[3] <= values[1]:
        raise OCRAdapterError("region_coords must be finite [left, top, right, bottom]")
    available = metadata["available_at"]
    for value in (available, as_of):
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise OCRAdapterError("available_at and as_of must be timezone-aware datetimes")
    if available.astimezone(timezone.utc) > as_of.astimezone(timezone.utc):
        raise OCRAdapterError("source is unavailable at the requested as_of time")
    return available


def _parse_output(result: Any, width: int, height: int) -> list[dict[str, Any]]:
    try:
        boxes, texts, scores = result.boxes, result.txts, result.scores
    except AttributeError as exc:
        raise OCRAdapterError("OCR result must expose boxes, txts, and scores") from exc
    if boxes is None or texts is None or scores is None or not (len(boxes) == len(texts) == len(scores)):
        raise OCRAdapterError("OCR boxes, text, and confidence must have matching lengths")
    parsed = []
    for box, text, score in zip(boxes, texts, scores):
        if not isinstance(text, str):
            raise OCRAdapterError("OCR text must be a string")
        try:
            points = [[float(point[0]), float(point[1])] for point in box]
            confidence = float(score)
        except (TypeError, ValueError, IndexError) as exc:
            raise OCRAdapterError("invalid OCR box or confidence") from exc
        if len(points) != 4 or any(not math.isfinite(v) for p in points for v in p):
            raise OCRAdapterError("each OCR box must contain four finite points")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise OCRAdapterError("OCR confidence must be between 0 and 1")
        if any(x < 0 or x > width or y < 0 or y > height for x, y in points):
            raise OCRAdapterError("OCR coordinates fall outside the image")
        parsed.append({"text": text, "confidence": confidence, "box": points})
    return parsed


def extract_ocr_candidate(
    *, image_path: Path, source_root: Path, metadata: Mapping[str, Any],
    model: OCRModelConfig, model_root: Path,
    authorize_source: Callable[[Mapping[str, Any]], bool] | None,
    as_of: datetime, engine: Any | None = None,
) -> dict[str, Any]:
    """Produce source-derived OCR candidates linked to an existing chunk.

    ``original_sha256`` is caller-asserted document provenance and is labelled
    as such; this function independently records the actual image byte hash.
    Authorization must enforce the actual source policy in its trusted caller.
    """
    if authorize_source is None or not callable(authorize_source):
        raise OCRAdapterError("source authorization callback is required")
    available_at = _validate_metadata(metadata, as_of)
    try:
        authorized = authorize_source(metadata)
    except Exception as exc:
        raise OCRAdapterError("source authorization decision failed") from exc
    if authorized is not True:
        raise OCRAdapterError("source authorization denied")

    image = _checked_path(image_path, source_root, label="image")
    image_bytes = _read_bounded_image(image)
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()
    try:
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as im:
            width, height = im.size
    except Exception as exc:
        raise OCRAdapterError("cannot read local image dimensions") from exc
    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
        raise OCRAdapterError("image dimensions exceed the configured limit")
    coords = [float(v) for v in metadata["region_coords"]]
    if coords[2] > width or coords[3] > height:
        raise OCRAdapterError("source region falls outside the image")

    det = _checked_path(model.detection_model_path, model_root, label="detection checkpoint")
    rec = _checked_path(model.recognition_model_path, model_root, label="recognition checkpoint")
    det_hash = _valid_sha256(model.detection_sha256, "detection_sha256")
    rec_hash = _valid_sha256(model.recognition_sha256, "recognition_sha256")
    if _sha256_file(det) != det_hash or _sha256_file(rec) != rec_hash:
        raise OCRAdapterError("configured checkpoint hash mismatch")
    if not isinstance(model.version, str) or not model.version.strip():
        raise OCRAdapterError("model version is required")
    fingerprint = hashlib.sha256(f"{model.version}:{det_hash}:{rec_hash}".encode()).hexdigest()

    if engine is None:
        raise OCRAdapterError("real RapidOCR startup is disabled pending verified local config and network isolation")
    try:
        result = engine(image_bytes)
    except Exception as exc:
        raise OCRAdapterError("OCR inference failed") from exc
    regions = _parse_output(result, width, height)
    return {
        "kind": "ocr_text_candidate",
        "source_document_id": metadata["source_document_id"],
        "source_version": metadata["source_version"],
        "original_sha256": metadata["original_sha256"].lower(),
        "original_sha256_provenance": "caller_asserted_unverified",
        "image_sha256": image_sha256,
        "page": metadata["page"], "region_id": metadata["region_id"],
        "region_coords": coords,
        "coordinate_frame": metadata.get("coordinate_frame", "image_pixels"),
        "image_size": {"width": width, "height": height},
        "ordered_text_confidence": regions,
        "model_version": model.version,
        "model_checkpoint_sha256": {"detection": det_hash, "recognition": rec_hash},
        "model_fingerprint": fingerprint,
        "model_checkpoint_provenance": "configured_checkpoint_hashes_unbound_to_engine",
        "model_fingerprint_provenance": "caller_asserted_unverified",
        "available_at": available_at.isoformat(), "as_of": as_of.isoformat(),
        "existing_chunk_id": metadata["chunk_id"],
        "status": "candidate_unreviewed",
    }
