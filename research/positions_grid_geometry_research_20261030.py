"""Research-only bridge from positions JSON-like grids to registered geometry.

Physical coordinates and inspection labels are caller assertions; this module
does not verify their production authority or measurement accuracy.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

MAX_GRID_CELLS = 1_000_000
MAX_CHIPS = 1_000_000


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _utc(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _rotation(i: int, j: int, width: int, height: int, rot: int) -> tuple[int, int]:
    if rot == 5:
        return i, j
    if rot == 7:
        return j, width - 1 - i  # Hrot = source width
    if rot == 3:
        return height - 1 - j, i  # Wrot = source height
    return width - 1 - i, height - 1 - j


def _valid_registration(reg: Any, as_of: Any, validator: Any) -> dict[str, Any] | None:
    if not isinstance(reg, Mapping) or not callable(validator):
        return None
    required = ("frame", "wafer_center_col", "wafer_center_row", "pitch_x_mm", "pitch_y_mm",
                "wafer_radius_mm", "axis_sign_x", "axis_sign_y", "source_ref", "version", "available_at")
    if any(k not in reg for k in required) or reg.get("frame") != "rotated-grid":
        return None
    try:
        when, available = _utc(as_of, "as_of"), _utc(reg["available_at"], "available_at")
        for name in ("wafer_center_col", "wafer_center_row"):
            _finite(reg[name], name)
        for name in ("pitch_x_mm", "pitch_y_mm", "wafer_radius_mm"):
            if _finite(reg[name], name) <= 0:
                return None
        if any(_integer(reg[name], name) not in (-1, 1) for name in ("axis_sign_x", "axis_sign_y")):
            return None
        if (available > when or not isinstance(reg["source_ref"], str) or not reg["source_ref"].strip()
                or not isinstance(reg["version"], str) or not reg["version"].strip()):
            return None
        if validator(dict(reg), as_of) is not True:
            return None
        return dict(reg)
    except Exception:
        return None


def _valid_orientation(assertion: Any, validator: Any, as_of: Any, reg: Mapping[str, Any] | None) -> bool:
    if reg is None or not isinstance(assertion, Mapping) or not callable(validator):
        return False
    if not all(isinstance(assertion.get(k), str) and assertion[k].strip()
               for k in ("notch_mapping", "source_ref", "version")):
        return False
    try:
        offset = _finite(assertion["theta_offset_rad"], "theta_offset_rad")
        return (_utc(assertion["available_at"], "orientation available_at") <= _utc(as_of, "as_of")
                and math.isfinite(offset)
                and assertion["source_ref"] == reg["source_ref"] and assertion["version"] == reg["version"]
                and validator(dict(assertion), as_of) is True)
    except Exception:
        return False


def positions_to_geometry(data: Mapping[str, Any], *, registration: Mapping[str, Any] | None = None,
                          as_of: datetime | None = None, validate_registration: Callable[..., Any] | None = None,
                          orientation_assertion: Mapping[str, Any] | None = None,
                          validate_orientation: Callable[..., Any] | None = None,
                          resolve_inspection: Callable[[Mapping[str, Any]], str] | None = None,
                          resolve_defect: Callable[[Mapping[str, Any]], bool | None] | None = None,
                          strata: Any = None) -> dict[str, Any]:
    """Validate source grid and optionally derive caller-registered coordinates."""
    if not isinstance(data, Mapping) or not isinstance(data.get("coord"), Mapping) or not isinstance(data.get("chips"), list):
        raise ValueError("input requires coord mapping and chips list")
    c = data["coord"]
    xmin, xmax = (_integer(c.get(k), k) for k in ("x_min_abs", "x_max_abs"))
    ymin, ymax = (_integer(c.get(k), k) for k in ("y_min_abs", "y_max_abs"))
    rot = _integer(c.get("rot_code"), "rot_code")
    if rot not in (0, 3, 5, 7) or xmax < xmin or ymax < ymin:
        raise ValueError("invalid bounds or rotation code")
    width, height = xmax-xmin+1, ymax-ymin+1
    rw, rh = (height, width) if rot in (3, 7) else (width, height)
    if (_integer(c.get("tiles_w_rot"), "tiles_w_rot") != rw or _integer(c.get("tiles_h_rot"), "tiles_h_rot") != rh):
        raise ValueError("rotated dimensions do not match calculated dimensions")
    if width*height > MAX_GRID_CELLS or not data["chips"] or len(data["chips"]) > MAX_CHIPS:
        raise ValueError("empty or excessive grid/chip count")
    parsed, seen_abs, seen_rot, seen_cal = [], set(), set(), set()
    for n, chip in enumerate(data["chips"]):
        if not isinstance(chip, Mapping):
            raise ValueError(f"chip {n} must be a mapping")
        xa, ya, xc, yc = (_integer(chip.get(k), f"chip {n} {k}") for k in ("x_abs", "y_abs", "x_cal", "y_cal"))
        i0, j0 = xa-xmin, ya-ymin
        if not (0 <= i0 < width and 0 <= j0 < height):
            raise ValueError(f"chip {n} source coordinate outside bounds")
        i, j = _rotation(i0, j0, width, height, rot)
        if not (0 <= i < rw and 0 <= j < rh):
            raise ValueError(f"chip {n} rotated coordinate outside dimensions")
        expected_x = i-(rw//2-1) if rw % 2 == 0 else i-rw//2
        expected_y = j-rh//2
        if (xc, yc) != (expected_x, expected_y):
            raise ValueError(f"chip {n} stored centered coordinate mismatch")
        if (xa, ya) in seen_abs or (i, j) in seen_rot or (xc, yc) in seen_cal:
            raise ValueError("duplicate source, rotated, or stored coordinates")
        seen_abs.add((xa, ya)); seen_rot.add((i, j)); seen_cal.add((xc, yc))
        parsed.append((chip, xa, ya, i, j, xc, yc))

    reg = _valid_registration(registration, as_of, validate_registration) if registration is not None else None
    orientation_ok = _valid_orientation(orientation_assertion, validate_orientation, as_of, reg)
    out = []
    for chip, xa, ya, i, j, xc, yc in parsed:
        item = {"x_abs": xa, "y_abs": ya, "i0": xa-xmin, "j0": ya-ymin, "i": i, "j": j,
                "x_cal": xc, "y_cal": yc,
                "grid_geometric_center_offset": {"col": i-(rw-1)/2, "row": j-(rh-1)/2},
                "physical": None, "physical_status": "unavailable_registration_missing_or_unvalidated"}
        if reg is not None:
            cc, cr = _finite(reg["wafer_center_col"], "wafer_center_col"), _finite(reg["wafer_center_row"], "wafer_center_row")
            px, py = _finite(reg["pitch_x_mm"], "pitch_x_mm"), _finite(reg["pitch_y_mm"], "pitch_y_mm")
            radius = _finite(reg["wafer_radius_mm"], "wafer_radius_mm")
            dx = (i-cc)*px*reg["axis_sign_x"]
            dy = (j-cr)*py*reg["axis_sign_y"]
            nx, ny = dx/radius, dy/radius
            r2 = nx*nx+ny*ny
            if not all(math.isfinite(v) for v in (nx, ny, r2)) or r2 > 1.0+1e-12:
                raise ValueError("registered chip lies outside wafer disk")
            theta = None if r2 == 0 or not orientation_ok else math.atan2(ny, nx)+_finite(orientation_assertion["theta_offset_rad"], "theta_offset_rad")
            item["physical"] = {"x": nx, "y": ny, "radius_fraction": math.sqrt(r2), "theta_rad": theta,
                "orientation_unavailable_reason": "origin_or_orientation_not_independently_validated" if theta is None else None,
                "strata": strata, "registration_source_ref": reg["source_ref"], "registration_version": reg["version"],
                "frame": "rotated-grid", "pitch_x_mm": px, "pitch_y_mm": py,
                "axis_sign_x": reg["axis_sign_x"], "axis_sign_y": reg["axis_sign_y"],
                "axis_and_offset_provenance": "caller_asserted_unverified",
                "provenance": "caller_asserted_unverified"}
            item["physical_status"] = "available_caller_asserted_unverified"
        out.append(item)

    inspection = None
    if resolve_inspection is not None or resolve_defect is not None:
        if not callable(resolve_inspection) or not callable(resolve_defect):
            raise ValueError("both inspection and defect resolvers are required")
        counts = {"eligible_inspected": 0, "not_inspected": 0, "unknown": 0, "outcome_missing": 0, "outcomes": 0}
        eligible_rows, analysis_rows = [], []
        analysis_ready = reg is not None and strata is not None and _valid_strata(strata)
        for row, (chip, *_rest) in zip(out, parsed):
            status = resolve_inspection(chip)
            if type(status) is not str or status not in ("eligible_inspected", "not_inspected", "unknown"):
                raise ValueError("invalid inspection status")
            if status == "unknown": counts["unknown"] += 1; continue
            if status == "not_inspected": counts["not_inspected"] += 1; continue
            counts["eligible_inspected"] += 1
            defect = resolve_defect(chip)
            if defect is not None and type(defect) is not bool:
                raise ValueError("defect resolver must return bool or None")
            if defect is None:
                counts["outcome_missing"] += 1; continue
            counts["outcomes"] += 1
            eligible_rows.append({**row, "inspection_status": status, "defect": defect})
            if analysis_ready:
                physical = row["physical"]
                analysis_rows.append({"x": physical["x"], "y": physical["y"], "defect": defect, "strata": strata})
        points = [(row["physical"]["x"], row["physical"]["y"]) for row in out if row["physical"] is not None]
        if len(points) != len(set(points)):
            analysis_ready = False
            analysis_reason = "registered_coordinates_collapse_to_duplicate_normalized_points"
        else:
            analysis_reason = None if analysis_ready else "validated_registration_and_scalar_caller_strata_required"
        angular_ready = analysis_ready and orientation_ok
        if analysis_ready and not orientation_ok:
            angular_reason = "orientation_not_independently_validated"
        elif not analysis_ready:
            angular_reason = analysis_reason
        else:
            angular_reason = None
        angular_rows = None
        if angular_ready:
            angular_rows = []
            angle = _finite(orientation_assertion["theta_offset_rad"], "theta_offset_rad")
            cosine, sine = math.cos(angle), math.sin(angle)
            for row in analysis_rows:
                angular_rows.append({**row, "x": row["x"]*cosine-row["y"]*sine,
                                     "y": row["x"]*sine+row["y"]*cosine})
        inspection = {"counts": counts, "explicit_eligibility_coverage": counts["eligible_inspected"]/len(out),
            "outcome_coverage": counts["outcomes"]/counts["eligible_inspected"] if counts["eligible_inspected"] else 0.0,
            "eligible_outcome_rows": eligible_rows, "analysis_rows": analysis_rows if analysis_ready else None,
            "analysis_rows_unavailable_reason": analysis_reason,
            "angular_analysis_rows": angular_rows, "angular_analysis_rows_unavailable_reason": angular_reason,
            "source_accuracy_or_authority_verified": False}
    return {"original_grid": {"x_min_abs": xmin, "x_max_abs": xmax, "y_min_abs": ymin, "y_max_abs": ymax,
        "width": width, "height": height, "rotated_width": rw, "rotated_height": rh, "rot_code": rot,
        "status": "validated_source_coordinates_only"}, "rows": out, "inspection": inspection,
        "physical_geometry_provenance": "caller_asserted_unverified" if reg else None}


def _valid_strata(value: Any) -> bool:
    if isinstance(value, bool): return False
    if isinstance(value, str): return bool(value.strip())
    if isinstance(value, int): return True
    if isinstance(value, float): return math.isfinite(value)
    if isinstance(value, tuple):
        return bool(value) and all(_valid_strata_scalar(item) for item in value)
    return False


def _valid_strata_scalar(value: Any) -> bool:
    if isinstance(value, bool): return False
    if isinstance(value, str): return bool(value.strip())
    if isinstance(value, int): return True
    if isinstance(value, float): return math.isfinite(value)
    return False
