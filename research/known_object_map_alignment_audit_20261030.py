"""Research-only structural comparison of source positions and object-grid indices.

This audit covers every chip in the supplied positions mapping, not only chips
that may have been used as model input. It cannot establish source identity,
object-map provenance, raw/object matches, or physical alignment.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from research.positions_grid_geometry_research_20261030 import positions_to_geometry


def audit_object_map_alignment(data: Mapping[str, Any], *, object_map_width: int,
                               object_map_height: int) -> dict[str, Any]:
    """Compare raw absolute indices and validated rotated indices to map bounds."""
    for name, value in (("object_map_width", object_map_width), ("object_map_height", object_map_height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    geometry = positions_to_geometry(data)
    raw_oob = rotated_oob = differing = 0
    rows = []
    for row in geometry["rows"]:
        raw = (row["x_abs"], row["y_abs"])
        rotated = (row["i"], row["j"])
        raw_in = 0 <= raw[0] < object_map_width and 0 <= raw[1] < object_map_height
        rotated_in = 0 <= rotated[0] < object_map_width and 0 <= rotated[1] < object_map_height
        raw_oob += not raw_in
        rotated_oob += not rotated_in
        differing += raw != rotated
        rows.append({"raw_gx": raw[0], "raw_gy": raw[1], "rotated_i": rotated[0], "rotated_j": rotated[1],
                     "raw_in_object_map_bounds": raw_in, "rotated_in_object_map_bounds": rotated_in,
                     "indices_differ": raw != rotated})

    coord = geometry["original_grid"]
    shape_mismatch = (coord["rotated_width"] != object_map_width or
                      coord["rotated_height"] != object_map_height)
    return {
        "scope": "all_position_chips",
        "source_grid": dict(coord),
        "object_map_shape": {"width": object_map_width, "height": object_map_height},
        "counts": {"chips": len(rows), "raw_indices_out_of_bounds": raw_oob,
                   "rotated_indices_out_of_bounds": rotated_oob, "raw_rotated_indices_differ": differing},
        "duplicate_positions_policy": "reject_before_audit",
        "shape_mismatch": shape_mismatch,
        "alignment_status": "structural_index_mapping_mismatch" if raw_oob or rotated_oob or differing or shape_mismatch
                            else "structural_index_mapping_consistent",
        "rows": rows,
        "claims": {"raw_object_match_verified": False, "source_identity_verified": False,
                   "object_output_provenance_verified": False, "model_or_class_alignment_verified": False,
                   "physical_alignment_verified": False, "rect_to_grid_edges_verified": False,
                   "classifier_crop_or_saved_object_grid_corruption_confirmed": False},
        "limitations": ["Structural audit only; no automatic rewrite or data persistence.",
                        "All position chips are checked; this scope may differ from model inputs with b>=200.",
                        "Rect coordinates are not compared with coord.grid_edges; structural consistency does not establish crop alignment.",
                        "ROI and source JSON identity, and whether the object output came from this source, require separate verification."],
    }
