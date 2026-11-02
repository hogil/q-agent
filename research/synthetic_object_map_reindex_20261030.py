"""In-memory synthetic reindex prototype for known-cnn object maps.

All provenance and fixture checks are caller assertions. This module neither
reads nor writes files and cannot establish real wafer/source identity.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from research.positions_grid_geometry_research_20261030 import (
    positions_to_geometry,
)

MAX_CLASSES = 256
# Research-only allocation guard; this does not state a precise byte budget.
MAX_REINDEX_CELLS = 262_144


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def reindex_synthetic_object_map(positions: Mapping[str, Any], raw_map: Sequence[Sequence[int]],
                                 prediction_rows: Sequence[Sequence[Any]],
                                 class_catalog: Mapping[int, str], *, as_of: datetime,
                                 source_binding: Mapping[str, Any],
                                 validate_binding: Callable[[Mapping[str, Any], datetime], Any],
                                 synthetic_fixture_asserted: bool) -> dict[str, Any]:
    """Return rotated-grid arrays after strict in-memory reconciliation.

    Prediction rows are (x_abs, y_abs, obj_id, obj_label, confidence,
    available_at). Binding and fixture status are caller assertions only.
    """
    cutoff = _aware(as_of, "as_of")
    if synthetic_fixture_asserted is not True:
        raise ValueError("explicit synthetic fixture assertion required")
    if not isinstance(source_binding, Mapping) or not callable(validate_binding):
        raise ValueError("source binding metadata and validate_binding callback required")
    binding_time = _aware(source_binding.get("available_at"), "binding available_at")
    if binding_time > cutoff:
        raise ValueError("source binding is future-dated")
    for source_name in ("positions", "raw_map", "predictions"):
        metadata = source_binding.get(source_name)
        if not isinstance(metadata, Mapping) or any(
                not isinstance(metadata.get(key), str) or not metadata[key].strip()
                for key in ("source_ref", "version")):
            raise ValueError(f"{source_name} source_ref and version metadata required")
        component_time = _aware(metadata.get("available_at"), f"{source_name} available_at")
        if component_time > cutoff:
            raise ValueError(f"{source_name} source is future-dated")
        digest = metadata.get("sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64
                                   or any(c not in "0123456789abcdefABCDEF" for c in digest)):
            raise ValueError(f"{source_name} sha256 must be 64 hexadecimal characters")
    if validate_binding(dict(source_binding), as_of) is not True:
        raise ValueError("source binding callback rejected or binding is future-dated")

    if not isinstance(class_catalog, Mapping) or not class_catalog or len(class_catalog) > MAX_CLASSES:
        raise ValueError("invalid or excessive class catalog")
    catalog: dict[int, str] = {}
    for key, label in class_catalog.items():
        obj_id = _int(key, "catalog class id")
        if not 1 <= obj_id <= 255 or not isinstance(label, str) or not label.strip():
            raise ValueError("catalog ids must be 1..255 with nonempty labels")
        catalog[obj_id] = label
    if len(set(catalog.values())) != len(catalog):
        raise ValueError("catalog labels must be unique")

    if not isinstance(raw_map, Sequence) or isinstance(raw_map, (str, bytes)) or not raw_map:
        raise ValueError("raw_map must be a nonempty 2D sequence")
    map_h = len(raw_map)
    if not all(isinstance(row, Sequence) and not isinstance(row, (str, bytes)) for row in raw_map):
        raise ValueError("raw_map rows must be sequences")
    map_w = len(raw_map[0])
    if map_w <= 0 or map_h * map_w > MAX_REINDEX_CELLS or any(len(row) != map_w for row in raw_map):
        raise ValueError("invalid, ragged, or excessive raw_map dimensions")
    for row in raw_map:
        for value in row:
            value = _int(value, "raw map cell")
            if not 0 <= value <= 255:
                raise ValueError("raw map cells must be in 0..255")

    if not isinstance(positions, Mapping) or not isinstance(positions.get("coord"), Mapping):
        raise ValueError("positions requires coord mapping")
    coord = positions["coord"]
    xmin, xmax = _int(coord.get("x_min_abs"), "x_min_abs"), _int(coord.get("x_max_abs"), "x_max_abs")
    ymin, ymax = _int(coord.get("y_min_abs"), "y_min_abs"), _int(coord.get("y_max_abs"), "y_max_abs")
    if xmax < xmin or ymax < ymin or (xmax-xmin+1) * (ymax-ymin+1) > MAX_REINDEX_CELLS:
        raise ValueError("positions grid exceeds research reindex cell cap")
    chips_input = positions.get("chips")
    if not isinstance(chips_input, list) or len(chips_input) > MAX_REINDEX_CELLS:
        raise ValueError("positions chip count exceeds research reindex cap")
    geometry = positions_to_geometry(positions)
    grid = geometry["original_grid"]
    if (grid["rotated_width"], grid["rotated_height"]) != (map_w, map_h):
        raise ValueError("raw map shape must match rotated grid dimensions")
    rows = prediction_rows
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) > MAX_REINDEX_CELLS:
        raise ValueError("prediction rows must be a bounded sequence")
    position_by_abs = {(p["x_abs"], p["y_abs"]): p for p in geometry["rows"]}
    predicted: dict[tuple[int, int], tuple[int, float]] = {}
    for n, row in enumerate(rows):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 6:
            raise ValueError(f"prediction row {n} must contain six fields")
        x, y = _int(row[0], "prediction x_abs"), _int(row[1], "prediction y_abs")
        obj_id = _int(row[2], "prediction obj_id")
        label, confidence = row[3], row[4]
        available = _aware(row[5], "prediction available_at")
        if available > cutoff:
            raise ValueError("prediction row is future-dated")
        if (x, y) not in position_by_abs:
            raise ValueError("prediction coordinate absent from positions")
        if not (0 <= x < map_w and 0 <= y < map_h):
            raise ValueError("prediction coordinate outside raw map bounds")
        if (x, y) in predicted:
            raise ValueError("duplicate prediction coordinate")
        if obj_id not in catalog or label != catalog[obj_id]:
            raise ValueError("prediction class id/label mismatch")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("confidence must be numeric")
        confidence = float(confidence)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be finite in [0,1]")
        if raw_map[y][x] != obj_id:
            raise ValueError("prediction object id does not match raw map")
        predicted[(x, y)] = (obj_id, confidence)

    # Every nonzero raw cell must be accounted for by both positions and a row.
    for y, raw_row in enumerate(raw_map):
        for x, value in enumerate(raw_row):
            if value and ((x, y) not in position_by_abs or (x, y) not in predicted):
                raise ValueError("unmatched nonzero raw map cell")

    out_w, out_h = grid["rotated_width"], grid["rotated_height"]
    obj_ids = [[None for _ in range(out_w)] for _ in range(out_h)]
    confidences = [[None for _ in range(out_w)] for _ in range(out_h)]
    support = [[False for _ in range(out_w)] for _ in range(out_h)]
    assigned = [[False for _ in range(out_w)] for _ in range(out_h)]
    ambiguous = [[False for _ in range(out_w)] for _ in range(out_h)]
    oob = [[False for _ in range(out_w)] for _ in range(out_h)]
    for p in geometry["rows"]:
        i, j = p["i"], p["j"]
        x, y = p["x_abs"], p["y_abs"]
        support[j][i] = True
        if not (0 <= x < map_w and 0 <= y < map_h):
            oob[j][i] = True
            continue
        item = predicted.get((x, y))
        if item is None:
            ambiguous[j][i] = raw_map[y][x] == 0
            continue
        obj_ids[j][i], confidences[j][i] = item
        assigned[j][i] = True

    has_oob = any(map(any, oob))
    has_ambiguous = any(map(any, ambiguous))
    if has_oob:
        status = "partial_raw_index_oob" if not has_ambiguous else "partial_raw_index_oob_and_unassigned_zero_ambiguous"
    elif has_ambiguous:
        status = "partial_unassigned_zero_ambiguous"
    else:
        status = "complete_assignment_for_supplied_positions"
    return {
        "object_id_grid": obj_ids, "confidence_grid": confidences,
        "support_mask": support, "assigned_mask": assigned,
        "unassigned_zero_ambiguous_mask": ambiguous,
        "raw_index_oob_unrecoverable_mask": oob,
        "mask_semantics": {
            "support_mask": "source positions에 chip 항목이 존재함; inspected/eligible 상태를 뜻하지 않음",
            "assigned_mask": "prediction row와 raw map 양쪽에서 positive object id가 일치함",
            "unassigned_zero_ambiguous_mask": "positions chip의 raw index가 map 안이고 raw cell이 0이며 prediction이 없음; zero 의미는 미확정",
            "raw_index_oob_unrecoverable_mask": "positions chip의 raw absolute index가 raw map bounds 밖이라 재배치 불가",
        },
        "inspection_outcome_verified": False,
        "status": status,
        "claims": {
            "synthetic_fixture_asserted_by_caller": True,
            "binding_and_callback_same_wafer_provenance_caller_asserted_only": True,
            "source_binding_metadata_caller_asserted_unverified": True,
            "source_bytes_hash_or_wafer_identity_verified": False,
            "source_authority_acl_verified": False,
            "geometry_context_and_client_source_link_caller_asserted": True,
            "raw_fbm_unchanged": "in_memory_input_only",
            "same_snapshot_of_map_positions_and_csv_verified": False,
            "classifier_correctness_verified": False,
            "zero_cell_meaning_resolved": False,
        },
        "research_allocation_cap": {"max_grid_cells": MAX_REINDEX_CELLS,
                                    "max_positions_chips": MAX_REINDEX_CELLS,
                                    "max_prediction_rows": MAX_REINDEX_CELLS,
                                    "precise_memory_bytes_claimed": False},
    }
