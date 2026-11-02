"""Synthetic research encoder for explicit object-id and wafer-yield maps.

All coordinates, inspection states, outcomes, predictions, thresholds, and FBM
references are caller assertions. This module does not interpret production
codes or verify data authority.
"""
from __future__ import annotations

import math
import re
import struct
import zlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

MAX_CELLS = 1_000_000
MAX_CHANNEL_CELLS = 4_000_000
MAX_CLASSES = 256
MAX_LABELS = MAX_CLASSES + len(("OUTSIDE", "MISSING", "UNKNOWN", "PASS", "FAIL", "CONFLICT", "FAIL_UNCLASSIFIED", "MULTI_KNOWN"))
MAX_LABEL_LENGTH = 256
INSPECTION = ("INSPECTED", "NOT_INSPECTED", "UNKNOWN")
OUTCOME = ("PASS", "FAIL", "UNKNOWN")
LABELS = ("OUTSIDE", "MISSING", "UNKNOWN", "PASS", "FAIL", "CONFLICT", "FAIL_UNCLASSIFIED", "MULTI_KNOWN")
UNKNOWN_EVIDENCE = ("PRESENT", "ABSENT", "UNASSESSED")


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def render_palette_rgba(encoded: Mapping[str, Any], palette: Mapping[str, Sequence[int]]) -> bytes:
    """Render encoded semantic labels to an in-memory RGBA PNG using caller colors."""
    if not isinstance(encoded, Mapping) or not isinstance(palette, Mapping):
        raise ValueError("encoded map and palette are required")
    width, height = _int(encoded.get("width"), "width"), _int(encoded.get("height"), "height")
    raster, legend = encoded.get("raster"), encoded.get("legend")
    if (width <= 0 or height <= 0 or width * height > MAX_CELLS or not isinstance(raster, list)
            or len(raster) != height or not isinstance(legend, Mapping) or len(legend) > MAX_LABELS
            or len(palette) > MAX_LABELS):
        raise ValueError("invalid encoded map")
    if any(not isinstance(line, list) or len(line) != width for line in raster):
        raise ValueError("invalid raster row")
    normalized_legend: dict[int, str] = {}
    legend_labels: set[str] = set()
    for index, label in legend.items():
        if (isinstance(index, bool) or not isinstance(index, int) or not isinstance(label, str)
                or not label or len(label) > MAX_LABEL_LENGTH or label in legend_labels):
            raise ValueError("legend requires unique integer indices and unique string labels")
        normalized_legend[index] = label
        legend_labels.add(label)
    used: set[str] = set()
    for line in raster:
        for index in line:
            if isinstance(index, bool) or not isinstance(index, int) or index not in normalized_legend:
                raise ValueError("raster indices must be integers present in the legend")
            used.add(normalized_legend[index])
    if None in used or used != set(palette):
        raise ValueError("palette must define exactly every used label")
    colors: dict[str, tuple[int, int, int, int]] = {}
    seen_colors: set[tuple[int, int, int, int]] = set()
    for label, rgba in palette.items():
        if (not isinstance(label, str) or not label or len(label) > MAX_LABEL_LENGTH
                or not isinstance(rgba, Sequence) or len(rgba) != 4):
            raise ValueError("palette entries require labels and RGBA tuples")
        color = tuple(_int(channel, "RGBA channel") for channel in rgba)
        if any(channel < 0 or channel > 255 for channel in color) or color in seen_colors:
            raise ValueError("RGBA channels must be 0..255 and colors must be unique")
        seen_colors.add(color)
        colors[label] = color
    raw = bytearray()
    for line in raster:
        raw.append(0)  # PNG filter: none
        for index in line:
            label = normalized_legend[index]
            if label not in colors:
                raise ValueError("raster index missing from legend")
            raw.extend(colors[label])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")
    return png


def encode_object_id_yield_map(*, width: int, height: int, rows: Sequence[Mapping[str, Any]],
                               thresholds: Mapping[int, Any], as_of: datetime,
                               fbm_snapshot: Mapping[str, Any],
                               support_mask: Sequence[Sequence[bool]]) -> dict[str, Any]:
    """Encode explicit rows into integer raster(s), preserving unknowns and provenance."""
    width, height = _int(width, "width"), _int(height, "height")
    if width <= 0 or height <= 0 or width * height > MAX_CELLS:
        raise ValueError("invalid or excessive grid dimensions")
    as_of_utc = _time(as_of, "as_of")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("rows must be a sequence")
    if len(rows) > width * height:
        raise ValueError("row count exceeds grid capacity")
    if not isinstance(thresholds, Mapping):
        raise ValueError("thresholds must be a mapping")
    if not isinstance(fbm_snapshot, Mapping) or fbm_snapshot.get("provenance") != "caller_asserted":
        raise ValueError("fbm_snapshot must be caller_asserted")
    if (not isinstance(fbm_snapshot.get("reference"), str) or not fbm_snapshot["reference"].strip()
            or not isinstance(fbm_snapshot.get("hash"), str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", fbm_snapshot["hash"]) is None):
        raise ValueError("FBM snapshot reference and 64-character hex hash are required")
    if not isinstance(support_mask, Sequence) or len(support_mask) != height or any(
            not isinstance(line, Sequence) or len(line) != width for line in support_mask):
        raise ValueError("support_mask must be an explicit height by width matrix")
    if any(type(value) is not bool for line in support_mask for value in line):
        raise ValueError("support_mask values must be booleans")
    support = [value for line in support_mask for value in line]
    threshold_values: dict[int, float] = {}
    threshold_provenance: dict[int, dict[str, Any]] = {}
    for class_id, spec in thresholds.items():
        class_id = _int(class_id, "threshold class id")
        if class_id <= 0 or not isinstance(spec, Mapping):
            raise ValueError("thresholds require positive class ids and mappings")
        value = spec.get("threshold")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= value <= 1:
            continue
        if not all(isinstance(spec.get(k), str) and spec[k].strip() for k in ("source", "version")):
            continue
        try:
            available = _time(spec.get("available_at"), "threshold available_at")
        except ValueError:
            continue
        if available <= as_of_utc:
            threshold_values[class_id] = float(value)
            threshold_provenance[class_id] = {"threshold": float(value), "source": spec["source"],
                "version": spec["version"], "available_at": available.isoformat(),
                "provenance": "caller_asserted_unverified"}

    # Bound actual as-of class channels before allocating their per-cell arrays.
    timely_class_ids: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue  # Detailed validation reports the input error below.
        preds = row.get("predictions", [])
        if not isinstance(preds, list):
            continue
        for pred in preds:
            if not isinstance(pred, Mapping):
                continue
            try:
                available = _time(pred.get("available_at"), "prediction available_at")
            except ValueError:
                continue
            if available > as_of_utc:
                continue
            cid = pred.get("id")
            if isinstance(cid, int) and not isinstance(cid, bool) and cid > 0:
                timely_class_ids.add(cid)
    channel_class_ids = timely_class_ids | set(threshold_values)
    if len(channel_class_ids) > MAX_CLASSES:
        raise ValueError("class count exceeds limit")
    if width * height * len(channel_class_ids) > MAX_CHANNEL_CELLS:
        raise ValueError("actual class-channel cell budget exceeded")

    n = width * height
    valid = [False] * n
    present = [False] * n
    inspection_map = ["MISSING"] * n
    outcome_map = ["MISSING"] * n
    label_map = ["MISSING" if inside else "OUTSIDE" for inside in support]
    known_channels: dict[int, list[int | None]] = {}
    score_channels: dict[int, list[float | None]] = {}
    unknown_evidence_channel = ["UNASSESSED"] * n
    unknown_evidence_provenance: list[dict[str, Any] | None] = [None] * n
    prediction_status: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    provenance: list[dict[str, Any] | None] = [None] * n
    seen: set[tuple[int, int]] = set()

    for row_no, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"row {row_no} must be a mapping")
        col, r = _int(row.get("col"), "col"), _int(row.get("row"), "row")
        if not (0 <= col < width and 0 <= r < height):
            raise ValueError("coordinate outside grid")
        if (col, r) in seen:
            raise ValueError("duplicate coordinate")
        seen.add((col, r)); idx = r * width + col
        if not support[idx]:
            raise ValueError("row coordinate is outside explicit wafer support")
        ins, out = row.get("inspection"), row.get("outcome")
        if ins not in INSPECTION or out not in OUTCOME:
            raise ValueError("inspection/outcome must use explicit enumerated values")
        preds = row.get("predictions", [])
        if not isinstance(preds, list):
            raise ValueError("predictions must be a list")
        unknown = row.get("unknown_evidence")
        if unknown is not None:
            if not isinstance(unknown, Mapping) or unknown.get("status") not in UNKNOWN_EVIDENCE:
                raise ValueError("unknown_evidence requires PRESENT, ABSENT, or UNASSESSED status")
            unknown_status = unknown["status"]
            if unknown_status in ("PRESENT", "ABSENT"):
                if all(isinstance(unknown.get(k), str) and unknown[k].strip() for k in ("source", "version")):
                    try:
                        unknown_available = _time(unknown.get("available_at"), "unknown_evidence available_at")
                    except ValueError:
                        unknown_available = None
                    if unknown_available is not None and unknown_available <= as_of_utc:
                        unknown_evidence_channel[idx] = unknown_status
                        unknown_evidence_provenance[idx] = {"source": unknown["source"], "version": unknown["version"],
                            "available_at": unknown_available.isoformat(), "provenance": "caller_asserted_unverified"}
        accepted: list[int] = []
        row_scores: dict[int, float | None] = {}
        row_channel_values: dict[int, int | None] = {}
        seen_classes: set[int] = set()
        for pred_no, pred in enumerate(preds):
            if not isinstance(pred, Mapping):
                raise ValueError("prediction must be a mapping")
            cid = _int(pred.get("id"), "prediction id")
            if cid <= 0:
                raise ValueError("prediction id must be positive")
            if len(str(cid)) > MAX_LABEL_LENGTH - len("KNOWN:"):
                raise ValueError("prediction id exceeds label length limit")
            if cid in seen_classes:
                raise ValueError("duplicate prediction class id for coordinate")
            seen_classes.add(cid)
            score = pred.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or not 0 <= score <= 1:
                raise ValueError("prediction score must be finite and within [0,1]")
            if not all(isinstance(pred.get(k), str) and pred[k].strip() for k in ("source", "version")):
                raise ValueError("prediction source and version are required")
            available = _time(pred.get("available_at"), "prediction available_at")
            if available > as_of_utc:
                continue
            status = "unverified"
            channel_value = None
            if cid in threshold_values:
                meets_threshold = float(score) >= threshold_values[cid]
                if ins == "INSPECTED":
                    status = "accepted" if meets_threshold else "below_threshold"
                    channel_value = 1 if meets_threshold else 0
                else:
                    status = "threshold_met_inspection_unconfirmed" if meets_threshold else "threshold_not_met_inspection_unconfirmed"
                if meets_threshold and ins == "INSPECTED":
                    accepted.append(cid)
            prediction_status[idx].append({"id": cid, "score": float(score), "status": status,
                "source": pred["source"], "version": pred["version"], "available_at": available.isoformat()})
            row_scores[cid] = float(score)
            row_channel_values[cid] = channel_value
        valid[idx] = True
        present[idx] = True
        inspection_map[idx], outcome_map[idx] = ins, out
        for cid in set(accepted) | set(row_scores):
            known_channels.setdefault(cid, [None] * n)
            score_channels.setdefault(cid, [None] * n)
            known_channels[cid][idx] = row_channel_values[cid]
            score_channels[cid][idx] = row_scores[cid]
        if out != "UNKNOWN" and ins != "INSPECTED":
            label = "CONFLICT"
        elif out == "FAIL" and not accepted:
            label = "FAIL_UNCLASSIFIED"
        elif out == "PASS" and ins == "INSPECTED" and accepted:
            label = "CONFLICT"
        elif len(set(accepted)) > 1:
            label = "MULTI_KNOWN"
        elif len(set(accepted)) == 1:
            label = f"KNOWN:{accepted[0]}"
        elif out == "FAIL":
            label = "FAIL"
        elif out == "PASS":
            label = "PASS"
        else:
            label = "UNKNOWN"
        provenance[idx] = {"provenance": "caller_asserted_unverified", "fbm_snapshot": dict(fbm_snapshot)}
        label_map[idx] = label

    label_set = list(LABELS) + sorted({x for x in label_map if isinstance(x, str) and x.startswith("KNOWN:")})
    legend = {i: label for i, label in enumerate(label_set)}
    label_indices = {label: i for i, label in legend.items()}
    raster = [label_indices[label] for label in label_map]
    return {"width": width, "height": height, "raster": [raster[y*width:(y+1)*width] for y in range(height)],
            "legend": legend, "support_mask": [support[y*width:(y+1)*width] for y in range(height)],
            "present_mask": [present[y*width:(y+1)*width] for y in range(height)],
            "valid_mask": [valid[y*width:(y+1)*width] for y in range(height)],
            "inspection": [inspection_map[y*width:(y+1)*width] for y in range(height)],
            "outcome": [outcome_map[y*width:(y+1)*width] for y in range(height)],
            "known_channels": {k: [v[y*width:(y+1)*width] for y in range(height)] for k, v in known_channels.items()},
            "score_channels": {k: [v[y*width:(y+1)*width] for y in range(height)] for k, v in score_channels.items()},
            "unknown_evidence": [unknown_evidence_channel[y*width:(y+1)*width] for y in range(height)],
            "unknown_evidence_provenance": [unknown_evidence_provenance[y*width:(y+1)*width] for y in range(height)],
            "prediction_status": [prediction_status[y*width:(y+1)*width] for y in range(height)],
            "provenance": [provenance[y*width:(y+1)*width] for y in range(height)],
            "threshold_provenance": threshold_provenance,
            "resource_limits": {"max_cells": MAX_CELLS, "max_classes": MAX_CLASSES,
                "max_class_channel_cells": MAX_CHANNEL_CELLS},
            "multi_known_information_loss_warning": "MULTI_KNOWN raster label summarizes; per-class channels preserve all positives",
            "raw_fbm_modified": False, "semantic_palette": None,
            "visualization_note": "caller palette colors are display-only; learning-input performance is unverified",
            "interpretation": "synthetic caller assertions only; no production labels, thresholds, ACL, or user data verified"}


