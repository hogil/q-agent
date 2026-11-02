"""Bounded, deterministic spatial analysis for registered wafer/chip maps.

This module reports image-derived candidates and morphology only. It does not
assign defect labels, infer causes, or equate a similar-looking image with a
repeated motif. Source coordinates remain separate: wafer pixels, die grid
coordinates, chip-local pixels, and failbit bit coordinates are not synonyms.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
_MAX_CROPS = 20
_MAX_REGIONS = 8
_CROP_COORD_RE = re.compile(r"_x(-?\d+)_y(-?\d+)_b[^.]+$", re.IGNORECASE)
_FORBIDDEN_DATASET_RE = re.compile(r"wm.?811|mixed.?wm", re.IGNORECASE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _opaque_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path, error: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError(error) from None
    if not isinstance(value, dict):
        raise ValueError(error)
    return value


def _safe_source_path(value: Any, root: Path, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("reference index contains an invalid asset path")
    path = Path(value).resolve()
    if not path.is_relative_to(root) or _FORBIDDEN_DATASET_RE.search(str(path)):
        raise ValueError("reference asset is outside the allowed source root")
    if must_exist and (not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES):
        raise ValueError("reference image is unavailable")
    return path


def _components(mask: np.ndarray, *, min_size: int = 1, diagonal: bool = False) -> list[dict[str, int]]:
    """Small-image 4-connected component extraction without a skimage dependency."""
    mask = np.asarray(mask, dtype=bool)
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    result: list[dict[str, int]] = []
    for flat in np.flatnonzero(mask):
        y, x = divmod(int(flat), width)
        if visited[y, x]:
            continue
        visited[y, x] = True
        stack = [(y, x)]
        count = 0
        x0 = x1 = x
        y0 = y1 = y
        while stack:
            cy, cx = stack.pop()
            if diagonal:
                for dy, dx in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            count += 1
            x0, x1 = min(x0, cx), max(x1, cx)
            y0, y1 = min(y0, cy), max(y1, cy)
            if cy and mask[cy - 1, cx] and not visited[cy - 1, cx]:
                visited[cy - 1, cx] = True
                stack.append((cy - 1, cx))
            if cy + 1 < height and mask[cy + 1, cx] and not visited[cy + 1, cx]:
                visited[cy + 1, cx] = True
                stack.append((cy + 1, cx))
            if cx and mask[cy, cx - 1] and not visited[cy, cx - 1]:
                visited[cy, cx - 1] = True
                stack.append((cy, cx - 1))
            if cx + 1 < width and mask[cy, cx + 1] and not visited[cy, cx + 1]:
                visited[cy, cx + 1] = True
                stack.append((cy, cx + 1))
        if count >= min_size:
            result.append({"pixels": count, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    result.sort(key=lambda item: (-item["pixels"], item["y0"], item["x0"]))
    return result


def _rgb_small(path: Path, max_side: int) -> tuple[Image.Image, tuple[int, int]]:
    try:
        with Image.open(path) as source:
            original = source.size
            image = source.convert("RGB")
            image.thumbnail((max_side, max_side), Image.Resampling.NEAREST)
            return image.copy(), original
    except (OSError, ValueError):
        raise ValueError("reference image could not be decoded") from None


def _wafer_regions(path: Path, asset_hash: str) -> dict[str, Any]:
    image, original_size = _rgb_small(path, 256)
    rgb = np.asarray(image, dtype=np.int16)
    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    mask = (saturation >= 32) & (rgb.max(axis=2) >= 45)
    components = _components(mask, min_size=3, diagonal=True)
    height, width = mask.shape
    kept = []
    for component in components:
        area = component["pixels"] / float(height * width)
        touches_border = (component["x0"] == 0 or component["y0"] == 0
                          or component["x1"] == width - 1 or component["y1"] == height - 1)
        # Large edge-connected color fields are often the wafer background or border.
        if touches_border or area > 0.18:
            continue
        kept.append((component, area))
    regions = []
    for index, (component, area) in enumerate(kept[:_MAX_REGIONS]):
        regions.append({
            "region_id": _opaque_id(f"{asset_hash}:region:{index}"),
            "bbox_norm": {
                "x0": round(component["x0"] / width, 5),
                "y0": round(component["y0"] / height, 5),
                "x1": round((component["x1"] + 1) / width, 5),
                "y1": round((component["y1"] + 1) / height, 5),
            },
            "area_fraction": round(area, 7),
        })
    return {
        "status": "candidate_regions" if regions else "no_candidate_color_regions",
        "method": "saturation_mask_8_connected_components_edge_and_area_filtered",
        "candidate_region_count": len(kept),
        "regions_returned": len(regions),
        "regions": regions,
        "analysis_resolution": list(image.size),
        "source_resolution": list(original_size),
        "interpretation": "image-color candidates only; no defect label or accuracy claim",
        "limitation": "monochrome or low-saturation anomalies may not form a candidate region",
    }


def _grid_mean(array: np.ndarray, grid: int = 16) -> np.ndarray:
    height, width = array.shape
    y_edges = np.linspace(0, height, grid + 1, dtype=int)
    x_edges = np.linspace(0, width, grid + 1, dtype=int)
    return np.asarray([
        [array[y_edges[y]:y_edges[y + 1], x_edges[x]:x_edges[x + 1]].mean()
         for x in range(grid)] for y in range(grid)
    ], dtype=np.float32)


def _chip_morphology(path: Path) -> tuple[dict[str, Any], np.ndarray | None, bool, np.ndarray]:
    image, original_size = _rgb_small(path, 128)
    rgb = np.asarray(image, dtype=np.float32)
    if rgb.shape[0] > 12 and rgb.shape[1] > 12:
        rgb = rgb[4:-4, 4:-4]
    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    gray = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gx = np.diff(gray, axis=1, prepend=gray[:, :1])
    gy = np.diff(gray, axis=0, prepend=gray[:1, :])
    magnitude = np.hypot(gx, gy)
    angle = np.mod(np.arctan2(gy, gx), np.pi)
    weights = magnitude.ravel()
    bins = np.minimum((angle.ravel() * (8.0 / np.pi)).astype(np.int32), 7)
    orientation = np.bincount(bins, weights=weights, minlength=8).astype(np.float32)
    if orientation.sum():
        orientation /= orientation.sum()
    color_mask = saturation >= 32
    colored_components = _components(color_mask, min_size=2)
    p50, p98 = np.percentile(magnitude, (50, 98))
    edge_map = np.clip((magnitude - p50) / max(float(p98 - p50), 1e-5), 0, 1)
    color_map = color_mask.astype(np.float32)
    edge_grid = _grid_mean(edge_map)
    color_grid = _grid_mean(color_map)
    # Center each spatial map so uniform background or a common border cannot
    # create a recurrence match on its own.
    spatial_edge = edge_grid.ravel() - edge_grid.mean()
    spatial_color = color_grid.ravel() - color_grid.mean()
    orient_delta = orientation - 1.0 / len(orientation)
    color_channels = np.bincount(np.argmax(rgb, axis=2).ravel(), weights=color_map.ravel(), minlength=3)
    if color_channels.sum():
        color_channels /= color_channels.sum()
    color_delta = color_channels - 1.0 / len(color_channels)
    descriptor = np.concatenate((spatial_edge * 2.0, spatial_color * 2.0,
                                 orient_delta, color_delta * 0.5)).astype(np.float32)
    norm = float(np.linalg.norm(descriptor))
    usable = norm > 1e-7
    if usable:
        descriptor /= norm
    motif_signal = (float(np.std(edge_grid)) >= 0.018
                    or float(color_map.mean()) >= 0.004)
    # Prefer colored failbit-map marks; for monochrome assets use high-gradient
    # pixels. The returned mask is aligned chip-local pixel space, not bit space.
    if float(color_map.mean()) >= 0.003:
        overlap_mask = color_mask
    else:
        edge_threshold = float(np.percentile(magnitude, 99))
        overlap_mask = magnitude >= edge_threshold
    dominant_orientation = int(np.argmax(orientation)) if orientation.size else 0
    features = {
        "status": "morphology_features_only",
        "source_resolution": list(original_size),
        "analysis_resolution": [int(rgb.shape[1]), int(rgb.shape[0])],
        "edge_density_top_quantile": round(float(np.mean(magnitude >= np.percentile(magnitude, 85))), 5),
        "color_activity_fraction": round(float(color_map.mean()), 5),
        "color_component_count": len(colored_components),
        "dominant_component_fraction_of_color_pixels": round(
            colored_components[0]["pixels"] / max(1, int(color_map.sum())), 5
        ) if colored_components else 0.0,
        "orientation_histogram_8_bins": [round(float(value), 5) for value in orientation],
        "dominant_orientation_bin": dominant_orientation,
        "interpretation": "chip-local morphology descriptor; not a defect class",
    }
    return features, descriptor if usable else None, motif_signal, overlap_mask


def _registration(
    crop_path: Path,
    crop_size: tuple[int, int],
    positions_by_die: dict[tuple[int, int], dict[str, Any]],
    wafer_size: tuple[int, int],
    die_bounds: tuple[int, int, int, int],
    crop_coordinates: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if crop_coordinates is not None:
        try:
            die_x = int(crop_coordinates.get("x_abs", crop_coordinates.get("die_x")))
            die_y = int(crop_coordinates.get("y_abs", crop_coordinates.get("die_y")))
        except (TypeError, ValueError):
            return None
    else:
        match = _CROP_COORD_RE.search(crop_path.stem)
        if not match:
            return None
        die_x, die_y = int(match.group(1)), int(match.group(2))
    row = positions_by_die.get((die_x, die_y))
    rect = row.get("rect") if isinstance(row, dict) else None
    if not isinstance(rect, dict):
        return None
    try:
        x0, y0, x1, y1 = (int(rect[key]) for key in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError):
        return None
    width, height = wafer_size
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        return None
    min_x, min_y, max_x, max_y = die_bounds
    return {
        "die_key": (die_x, die_y),
        "die_id": _opaque_id(f"die:{die_x}:{die_y}"),
        "die_position_norm": [round((x0 + x1) / (2 * width), 5),
                              round((y0 + y1) / (2 * height), 5)],
        "relative_die_position": [
            round((die_x - min_x) / max(1, max_x - min_x), 5),
            round((die_y - min_y) / max(1, max_y - min_y), 5),
        ],
        "rect_width_pixels": x1 - x0,
        "rect_height_pixels": y1 - y0,
        "crop_size_pixels": list(crop_size),
    }


def _largest_overlap_group(
    masks: list[np.ndarray], threshold: float
) -> tuple[list[int], list[float]]:
    if len(masks) < 3:
        return [], []
    similarity = np.eye(len(masks), dtype=np.float32)
    for left in range(len(masks)):
        a = masks[left].astype(bool, copy=False)
        for right in range(left + 1, len(masks)):
            b = masks[right].astype(bool, copy=False)
            if a.shape != b.shape:
                continue
            denominator = int(a.sum()) + int(b.sum())
            score = 2.0 * int(np.logical_and(a, b).sum()) / denominator if denominator else 0.0
            similarity[left, right] = similarity[right, left] = score
    best: list[int] = []
    for seed in sorted(range(len(masks)), key=lambda i: (-int(np.sum(similarity[i] >= threshold)), i)):
        candidates = [i for i in range(len(masks)) if i != seed and similarity[seed, i] >= threshold]
        group = [seed]
        for candidate in candidates:
            if all(similarity[candidate, chosen] >= threshold for chosen in group):
                group.append(candidate)
        if len(group) > len(best):
            best = group
    pair_scores = [float(similarity[left, right]) for n, left in enumerate(best)
                   for right in best[n + 1:]]
    return best, pair_scores


def _analyze_cohort(cohort: dict[str, Any], source_root: Path, max_chip_crops: int,
                    similarity_threshold: float, origin: str,
                    source_provenance: str) -> dict[str, Any]:
    wafer_path = _safe_source_path(cohort.get("wafer_image"), source_root)
    positions_path_value = cohort.get("positions_path")
    if not isinstance(positions_path_value, str):
        raise ValueError("reference cohort is missing positions metadata")
    positions_path = Path(positions_path_value).resolve()
    if not positions_path.is_relative_to(source_root) or not positions_path.is_file():
        raise ValueError("reference positions metadata is unavailable")
    positions = _read_json(positions_path, "reference positions metadata is invalid")
    position_rows = positions.get("chips")
    if not isinstance(position_rows, list):
        raise ValueError("reference positions metadata has no chip coordinate rows")
    positions_by_die: dict[tuple[int, int], dict[str, Any]] = {}
    duplicate_dies: set[tuple[int, int]] = set()
    for row in position_rows:
        if not isinstance(row, dict):
            continue
        try:
            key = (int(row["x_abs"]), int(row["y_abs"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key in duplicate_dies:
            continue
        if key in positions_by_die:
            positions_by_die.pop(key, None)
            duplicate_dies.add(key)
        else:
            positions_by_die[key] = row
    coordinates = list(positions_by_die)
    if not coordinates:
        raise ValueError("reference positions contain no unique die coordinates")
    die_bounds = (min(x for x, _ in coordinates), min(y for _, y in coordinates),
                  max(x for x, _ in coordinates), max(y for _, y in coordinates))
    with Image.open(wafer_path) as im:
        wafer_size = im.size
    wafer_hash = _sha256(wafer_path)
    wafer_features = _wafer_regions(wafer_path, wafer_hash)

    crop_values = cohort.get("chip_crops")
    if not isinstance(crop_values, list):
        raise ValueError("reference cohort has no chip crop list")
    crop_specs = crop_values[:max_chip_crops]
    crop_paths = []
    per_chip = []
    registered = []
    hashes = []
    for crop_spec in crop_specs:
        if isinstance(crop_spec, dict):
            crop_value = crop_spec.get("path")
            crop_coordinates = crop_spec
        else:
            crop_value = crop_spec
            crop_coordinates = None
        crop_path = _safe_source_path(crop_value, source_root)
        crop_paths.append(crop_path)
        asset_hash = _sha256(crop_path)
        with Image.open(crop_path) as im:
            crop_size = im.size
        registration = _registration(crop_path, crop_size, positions_by_die, wafer_size,
                                     die_bounds, crop_coordinates)
        features, descriptor, motif_signal, overlap_mask = _chip_morphology(crop_path)
        chip_id = _opaque_id(asset_hash)
        per_chip.append({
            "chip_id": chip_id,
            "asset_sha256": asset_hash,
            "registration_status": "registered_to_positions_rect" if registration else "unregistered",
            "die_position_norm": registration["die_position_norm"] if registration else None,
            "morphology": features,
        })
        hashes.append(asset_hash)
        if registration and descriptor is not None:
            registered.append({"chip_id": chip_id, "registration": registration,
                               "overlap_mask": overlap_mask, "motif_signal": motif_signal,
                               "descriptor_usable": True})
        elif registration:
            registered.append({"chip_id": chip_id, "registration": registration,
                               "overlap_mask": overlap_mask, "motif_signal": motif_signal,
                               "descriptor_usable": False})

    eligible = [row for row in registered if row["descriptor_usable"] and row["motif_signal"]]
    selected_masks = [row["overlap_mask"] for row in eligible]
    group, pair_scores = _largest_overlap_group(selected_masks, similarity_threshold)
    support_ids = [eligible[i]["chip_id"] for i in group]
    registered_dies = {row["registration"]["die_key"] for row in registered}
    if len(registered_dies) < 3 or len(selected_masks) < 3:
        recurrence_status = "insufficient_registered_motif_signal"
    elif len(group) >= 3 and len({eligible[i]["registration"]["die_key"] for i in group}) >= 3:
        recurrence_status = "candidate_repeated_motif"
    else:
        recurrence_status = "no_repeated_motif_above_threshold"
    recurrence = {
        "status": recurrence_status,
        "method": "direct_aligned_chip_pixel_mask_overlap_dice",
        "similarity_threshold": similarity_threshold,
        "registered_chip_count": len(registered),
        "distinct_registered_die_count": len(registered_dies),
        "motif_signal_chip_count": len(eligible),
        "supporting_chip_ids": support_ids,
        "supporting_pair_count": len(pair_scores),
        "mean_support_pair_similarity": round(float(np.mean(pair_scores)), 5) if pair_scores else None,
        "limitations": [
            "recurrence requires direct mask overlap across at least three registered distinct dies",
            "direct chip-pixel overlap is evaluated only after coordinate registration; image count and embeddings alone are not recurrence evidence",
            "registration uses crop filename die coordinates plus positions chip coordinates and wafer pixel rects",
            "overlap assumes compatible chip-crop orientation; positions metadata does not provide per-chip rotation correction",
            "threshold is an engineering heuristic, not calibrated accuracy or defect truth",
        ],
    }
    return {
        "provenance": {
            "origin": origin,
            "source_provenance": source_provenance,
            "synthetic_metadata_marker": origin in {"jsonmetadata_synthetic", "procedural_synthetic"},
            "wafer_asset_sha256": wafer_hash,
            "positions_sha256": _sha256(positions_path),
            "chip_asset_sha256": hashes,
        },
        "coordinate_semantics": {
            "wafer_pixel": "positions.chips[].rect addresses pixels in the wafer map image",
            "die_grid": "positions.chips[].x_abs/y_abs and crop filename _x/_y identify die positions",
            "chip_pixel": "coordinates local to each chip crop image",
            "failbit_bit": "not present in this reference contract; bit_x/bit_y are not inferred from die or pixel coordinates",
        },
        "grains": {
            "wafer_local_anomaly": wafer_features,
            "chip_internal_motif": {
                "status": "morphology_features_only",
                "registered_chip_count": len(registered),
                "unregistered_chip_count": len(per_chip) - len(registered),
                "chips": per_chip,
                "interpretation": "local shape statistics do not establish a defect label",
            },
            "cross_chip_repeated_motif": recurrence,
        },
        "bounds": {"chip_crops_analyzed": len(crop_paths), "max_chip_crops": max_chip_crops,
                   "regions_returned": wafer_features["regions_returned"]},
        "accuracy_claim": False,
    }


def analyze_reference_maps(
    index_path: str | Path,
    *,
    max_chip_crops: int = 20,
    similarity_threshold: float = 0.90,
) -> dict[str, Any]:
    """Analyze one private reference cohort without returning source filenames.

    The index must identify a source root, one cohort wafer image, a positions
    JSON, and registered chip-crop paths. This function reads source assets in
    place and never writes or copies them.
    """
    if type(max_chip_crops) is not int or not 1 <= max_chip_crops <= _MAX_CROPS:
        raise ValueError("max_chip_crops must be between 1 and 20")
    if not isinstance(similarity_threshold, (int, float)) or not 0 < similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be in (0, 1]")
    index_file = Path(index_path).resolve()
    index = _read_json(index_file, "reference index is invalid")
    root_value = index.get("source_root")
    if not isinstance(root_value, str):
        raise ValueError("reference index has no source root")
    source_root = Path(root_value).resolve()
    cohorts = index.get("cohorts")
    if not isinstance(cohorts, list) or len(cohorts) != 1 or not isinstance(cohorts[0], dict):
        raise ValueError("reference index must contain exactly one bounded cohort")
    if _FORBIDDEN_DATASET_RE.search(str(source_root)):
        raise ValueError("WM-811K and mixedWM inputs are excluded")
    cohort = cohorts[0]
    origin = cohort.get("origin", "unverified")
    if origin not in {"unverified", "jsonmetadata_synthetic", "procedural_synthetic"}:
        origin = "unverified"
    source_provenance = cohort.get("source_provenance", "unverified")
    if not isinstance(source_provenance, str):
        source_provenance = "unverified"
    result = _analyze_cohort(cohort, source_root, max_chip_crops, float(similarity_threshold),
                             origin, source_provenance)
    result["provenance"]["synthetic"] = origin in {"jsonmetadata_synthetic", "procedural_synthetic"}
    result["provenance"]["source"] = "private_reference_index"
    return result


def _settings_data(settings: Any) -> dict[str, Any]:
    data = settings.get("data") if isinstance(settings, dict) else getattr(settings, "data", None)
    if not isinstance(data, dict):
        raise ValueError("configured settings are required")
    return data


def _demo_paths(settings: Any) -> tuple[dict[str, Any], dict[str, Any], Path, Path, int]:
    data = _settings_data(settings)
    platform = data.get("platform")
    paths = data.get("paths")
    if (not isinstance(platform, dict) or not isinstance(platform.get("map_analysis"), dict)
            or platform["map_analysis"].get("enabled") is not True):
        raise ValueError("platform.map_analysis.enabled must be true")
    if data.get("environment") not in {"demo", "test"}:
        raise ValueError("map analysis demo requires demo/test environment")
    if not isinstance(paths, dict) or not isinstance(paths.get("data_root"), str):
        raise ValueError("paths.data_root is required")
    config = platform["map_analysis"]
    subdirectory = config.get("subdirectory")
    if not isinstance(subdirectory, str) or not subdirectory.strip():
        raise ValueError("platform.map_analysis.subdirectory is required")
    relative = Path(subdirectory)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("map analysis subdirectory must stay inside paths.data_root")
    data_root = Path(paths["data_root"]).resolve()
    output_dir = (data_root / relative).resolve()
    if not output_dir.is_relative_to(data_root) or output_dir == data_root:
        raise ValueError("map analysis output must stay below paths.data_root")
    seed = platform.get("seed")
    if type(seed) is not int:
        raise ValueError("platform.seed must be an integer")
    database = data.get("database", {}).get("sqlite_file")
    if not isinstance(database, str):
        raise ValueError("database.sqlite_file is required")
    database_path = Path(database).resolve()
    if not database_path.is_relative_to(data_root):
        raise ValueError("configured synthetic database must stay inside paths.data_root")
    if database_path == output_dir:
        raise ValueError("map analysis output cannot replace the configured database")
    reserved = (data_root / "platform-manifest.json").resolve()
    if output_dir == reserved or output_dir.is_relative_to(reserved):
        raise ValueError("map analysis output cannot replace the platform manifest")
    return data, config, data_root, output_dir, seed


def _sql_ident(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("configured map-analysis table mapping is invalid")
    return '"' + value + '"'


def _table_mapping(mapping: Any, required: set[str]) -> tuple[str, dict[str, str]]:
    if not isinstance(mapping, dict) or not isinstance(mapping.get("columns"), dict):
        raise ValueError("configured map-analysis table mapping is incomplete")
    columns = mapping["columns"]
    if not required.issubset(columns):
        raise ValueError("configured map-analysis logical columns are incomplete")
    return _sql_ident(mapping.get("name")), {key: _sql_ident(columns[key]) for key in required}


def _datetime_value(value: Any, timezone_name: str):
    from datetime import datetime

    if not isinstance(value, str):
        raise ValueError("synthetic map timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("synthetic map timestamp is invalid") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def _next_midnight(as_of: str, timezone_name: str):
    from datetime import datetime, time

    try:
        next_date = date.fromisoformat(as_of) + timedelta(days=1)
    except (TypeError, ValueError):
        raise ValueError("as_of must be an ISO date") from None
    return datetime.combine(next_date, time.min, ZoneInfo(timezone_name))


def _read_registered_wafers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Read only the synthetic incident/lot/wafer/chip registry from SQLite."""
    if data.get("environment") not in {"demo", "test"} or data.get("database", {}).get("read_only") is not True:
        raise ValueError("map registry lookup requires a read-only demo/test database")
    database_path = Path(data["database"]["sqlite_file"]).resolve()
    if not database_path.is_file():
        raise ValueError("configured synthetic database is unavailable")
    core = data.get("tables", {})
    platform = data.get("platform", {})
    incident_table, incident_cols = _table_mapping(core.get("incident"),
                                                   {"incident_id", "incident_number", "occurred_at"})
    lot_table, lot_cols = _table_mapping(core.get("lot_list"), {"incident_ref", "lot_id"})
    wafer_table, wafer_cols = _table_mapping(core.get("wafer_list"),
                                             {"incident_ref", "lot_id", "wafer_id"})
    source_tables = platform.get("tables", {})
    measure_table, measure_cols = _table_mapping(source_tables.get("measure"),
                                                 {"incident_id", "lot_id", "wafer_id", "chip_id",
                                                  "die_x", "die_y", "available_at", "synthetic"})
    uri = database_path.as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        incident_sql = (
            f"SELECT {incident_cols['incident_id']} AS incident_id, "
            f"{incident_cols['incident_number']} AS incident_number, "
            f"{incident_cols['occurred_at']} AS occurred_at "
            f"FROM {incident_table} WHERE {incident_cols['incident_id']} LIKE 'synp-%' "
            f"ORDER BY {incident_cols['incident_number']} LIMIT ?"
        )
        configured_count = platform.get("incident_count")
        if type(configured_count) is not int or not 1 <= configured_count <= 5000:
            raise ValueError("platform.incident_count is invalid")
        incident_rows = con.execute(incident_sql, (configured_count + 1,)).fetchall()
        if len(incident_rows) != configured_count:
            raise ValueError("synthetic incident registry count does not match configuration")
        lot_wafer_sql = (
            f"SELECT DISTINCT l.{lot_cols['lot_id']} AS lot_id, "
            f"w.{wafer_cols['wafer_id']} AS wafer_id "
            f"FROM {lot_table} l JOIN {wafer_table} w ON "
            f"l.{lot_cols['incident_ref']}=w.{wafer_cols['incident_ref']} AND "
            f"l.{lot_cols['lot_id']}=w.{wafer_cols['lot_id']} "
            f"WHERE l.{lot_cols['incident_ref']}=? "
            f"ORDER BY l.{lot_cols['lot_id']}, w.{wafer_cols['wafer_id']} LIMIT 1"
        )
        chip_sql = (
            f"SELECT {measure_cols['chip_id']} AS chip_id, {measure_cols['die_x']} AS die_x, "
            f"{measure_cols['die_y']} AS die_y, MAX({measure_cols['available_at']}) AS available_at "
            f"FROM {measure_table} WHERE {measure_cols['incident_id']}=? "
            f"AND {measure_cols['lot_id']}=? AND {measure_cols['wafer_id']}=? "
            f"AND {measure_cols['synthetic']}=1 "
            f"GROUP BY {measure_cols['chip_id']}, {measure_cols['die_x']}, {measure_cols['die_y']} "
            f"ORDER BY {measure_cols['die_y']}, {measure_cols['die_x']}, {measure_cols['chip_id']}"
        )
        registry = []
        for incident in incident_rows:
            incident_id = incident["incident_id"]
            incident_number = incident["incident_number"]
            if not isinstance(incident_id, str) or not re.fullmatch(r"synp-\d{4,}", incident_id):
                raise ValueError("non-synthetic incident identifier in synthetic registry")
            if not isinstance(incident_number, str) or not re.fullmatch(r"SYN-P-\d{4,}", incident_number):
                raise ValueError("non-synthetic incident number in synthetic registry")
            lot_wafer = con.execute(lot_wafer_sql, (incident_id,)).fetchone()
            if not lot_wafer:
                raise ValueError("synthetic incident has no registered Lot/Wafer")
            lot_id, wafer_id = lot_wafer["lot_id"], lot_wafer["wafer_id"]
            chip_rows = con.execute(chip_sql, (incident_id, lot_id, wafer_id)).fetchall()
            chips = []
            seen_chip_ids, seen_coords = set(), set()
            availability = []
            for row in chip_rows:
                chip_id = row["chip_id"]
                try:
                    die_x, die_y = int(row["die_x"]), int(row["die_y"])
                except (TypeError, ValueError):
                    raise ValueError("synthetic chip registry has invalid die coordinates") from None
                if not isinstance(chip_id, str) or not chip_id or chip_id in seen_chip_ids or (die_x, die_y) in seen_coords:
                    raise ValueError("synthetic chip registry contains duplicate composite keys")
                seen_chip_ids.add(chip_id)
                seen_coords.add((die_x, die_y))
                availability.append(row["available_at"])
                chips.append({"chip_id": chip_id, "die_x": die_x, "die_y": die_y})
            if len(chips) < 6 or any(not isinstance(value, str) for value in availability):
                raise ValueError("synthetic wafer has fewer than six available registered chips")
            registry.append({"incident_id": incident_id, "incident_number": incident_number,
                             "occurred_at": incident["occurred_at"], "lot_id": lot_id,
                             "wafer_id": wafer_id, "chips": chips,
                             "available_at": max(availability)})
        return registry
    except sqlite3.Error:
        raise ValueError("read-only synthetic map registry query failed") from None
    finally:
        if "con" in locals():
            con.close()


def _select_chip_rows(chips: list[dict[str, Any]], count: int = 6) -> list[dict[str, Any]]:
    if len(chips) < count:
        raise ValueError("registered wafer has too few chips for map analysis")
    indices = [round(index * (len(chips) - 1) / (count - 1)) for index in range(count)]
    if len(set(indices)) != count:
        raise ValueError("registered wafer does not provide six distinct die positions")
    return [chips[index] for index in indices]


def _draw_chip_pattern(draw: ImageDraw.ImageDraw, mode: str) -> None:
    if mode == "repeated":
        draw.line((16, 32, 48, 32), fill=(35, 135, 75), width=3)
        draw.line((32, 16, 32, 48), fill=(35, 135, 75), width=3)
        draw.line((22, 22, 42, 42), fill=(35, 135, 75), width=2)
    elif mode == "local":
        draw.line((10, 50, 22, 36), fill=(205, 55, 40), width=3)
        draw.ellipse((7, 47, 13, 53), fill=(205, 55, 40))


def _asset_id(record: dict[str, Any], kind: str, chip_id: str | None, digest: str) -> str:
    identity = json.dumps({"incident_id": record["incident_id"], "lot_id": record["lot_id"],
                           "wafer_id": record["wafer_id"], "chip_id": chip_id,
                           "kind": kind, "sha256": digest}, sort_keys=True, separators=(",", ":"))
    return "map-" + digest + "-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _save_png_asset(image: Image.Image, assets_dir: Path, record: dict[str, Any],
                    kind: str, chip_id: str | None) -> tuple[Path, str, str]:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    asset_id = _asset_id(record, kind, chip_id, digest)
    path = assets_dir / f"{asset_id}.png"
    with path.open("xb") as stream:
        stream.write(content)
    return path, digest, asset_id


def _render_case(case_dir: Path, output_dir: Path, record: dict[str, Any],
                 scenario: str, seed: int) -> dict[str, Any]:
    chips = record["chips"]
    selected = _select_chip_rows(chips)
    min_x, max_x = min(c["die_x"] for c in chips), max(c["die_x"] for c in chips)
    min_y, max_y = min(c["die_y"] for c in chips), max(c["die_y"] for c in chips)
    cell = 64
    grid_width, grid_height = max_x - min_x + 1, max_y - min_y + 1
    canvas = max(1024, (max(grid_width, grid_height) + 2) * cell)
    margin_x = (canvas - grid_width * cell) // 2
    margin_y = (canvas - grid_height * cell) // 2
    center, radius = canvas // 2, int(canvas * 0.49)
    wafer = Image.new("RGB", (canvas, canvas), (205, 231, 250))
    draw = ImageDraw.Draw(wafer)
    draw.ellipse((center - radius, center - radius, center + radius, center + radius),
                 fill=(239, 239, 237), outline=(120, 126, 130), width=2)
    positions = []
    rectangles = {}
    for chip in chips:
        x0 = margin_x + (chip["die_x"] - min_x) * cell
        y0 = margin_y + (chip["die_y"] - min_y) * cell
        rect = {"x0": x0, "y0": y0, "x1": x0 + cell, "y1": y0 + cell}
        rectangles[chip["chip_id"]] = rect
        draw.rectangle((x0, y0, x0 + cell, y0 + cell), outline=(185, 190, 193), width=1)
        positions.append({"incident_id": record["incident_id"], "lot_id": record["lot_id"],
                          "wafer_id": record["wafer_id"], "chip_id": chip["chip_id"],
                          "x_abs": chip["die_x"], "y_abs": chip["die_y"],
                          "die_x": chip["die_x"], "die_y": chip["die_y"], "rect": rect})
    repeated_crop_indices = set(range(4)) if scenario == "repeated_motif" else set(range(1, 4)) if scenario == "combined" else set()
    local_crop_indices = {0} if scenario in {"local_only", "combined"} else set()
    for index, chip in enumerate(selected):
        rect = rectangles[chip["chip_id"]]
        if index in local_crop_indices:
            draw.line((rect["x0"] + 10, rect["y0"] + 10, rect["x1"] - 10, rect["y1"] - 10),
                      fill=(210, 65, 45), width=4)
        if index in repeated_crop_indices:
            draw.line((rect["x0"] + 12, (rect["y0"] + rect["y1"]) // 2,
                       rect["x1"] - 12, (rect["y0"] + rect["y1"]) // 2), fill=(40, 145, 85), width=4)
            draw.line(((rect["x0"] + rect["x1"]) // 2, rect["y0"] + 12,
                       (rect["x0"] + rect["x1"]) // 2, rect["y1"] - 12), fill=(40, 145, 85), width=4)
    assets_dir = output_dir / "assets"
    wafer_path, wafer_digest, wafer_asset_id = _save_png_asset(wafer, assets_dir, record, "wafer", None)

    crop_paths = []
    composite_keys = []
    chip_asset_rows = []
    for index, chip in enumerate(selected):
        rng = np.random.default_rng(seed + int(record["incident_number"].split("-")[-1]) * 10_007 + index)
        noise = rng.integers(0, 5, size=(cell, cell, 1), dtype=np.uint8)
        gray = np.broadcast_to(np.asarray([232], dtype=np.uint8), (cell, cell, 1)) + noise
        image = Image.fromarray(np.repeat(gray, 3, axis=2), mode="RGB")
        chip_draw = ImageDraw.Draw(image)
        if index in repeated_crop_indices:
            _draw_chip_pattern(chip_draw, "repeated")
        if index in local_crop_indices:
            _draw_chip_pattern(chip_draw, "local")
        crop_path, digest, asset_id = _save_png_asset(image, assets_dir, record, "chip", chip["chip_id"])
        crop_paths.append(crop_path)
        chip_asset_rows.append({"asset_id": asset_id, "kind": "chip", "sha256": digest,
                                "storage_relpath": str(crop_path.relative_to(output_dir)),
                                "lot_id": record["lot_id"], "wafer_id": record["wafer_id"],
                                "chip_id": chip["chip_id"]})
        composite_keys.append({"incident_id": record["incident_id"], "lot_id": record["lot_id"],
                               "wafer_id": record["wafer_id"], "chip_id": chip["chip_id"],
                               "die_x": chip["die_x"], "die_y": chip["die_y"]})

    positions_path = case_dir / "positions.json"
    positions_path.write_text(json.dumps({
        "synthetic": True,
        "source": "registered synthetic incident/lot/wafer/measure chip registry",
        "map_semantics": "new procedural spatial measurement illustration; not an existing failbit image",
        "coordinate_semantics": {"x_abs_y_abs": "die_grid", "die_x_die_y": "measure table die coordinates",
                                 "rect": "wafer_image_pixels", "chip_pixels": "crop_local",
                                 "failbit_bits": "not supplied"},
        "coord": {"canvas": {"width": canvas, "height": canvas},
                  "x_min_abs": min_x, "x_max_abs": max_x, "y_min_abs": min_y, "y_max_abs": max_y},
        "chips": positions,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = case_dir / "reference-index.json"
    index_path.write_text(json.dumps({
        "schema_version": 1, "source_root": str(output_dir),
        "cohorts": [{"wafer_image": str(wafer_path), "positions_path": str(positions_path),
                     "chip_crops": [{"path": str(path), "x_abs": chip["die_x"], "y_abs": chip["die_y"]}
                                    for path, chip in zip(crop_paths, selected)],
                     "origin": "procedural_synthetic", "source_provenance": "registered_platform_measure_fixture"}],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assets = [{
        "asset_id": wafer_asset_id,
        "kind": "wafer", "sha256": wafer_digest,
        "storage_relpath": str(wafer_path.relative_to(output_dir)),
        "lot_id": record["lot_id"], "wafer_id": record["wafer_id"], "chip_id": None,
    }, *chip_asset_rows]
    return {"wafer_image": str(wafer_path.relative_to(output_dir)),
            "positions_file": str(positions_path.relative_to(case_dir)),
            "index_file": str(index_path.relative_to(case_dir)),
            "selected_composite_keys": composite_keys,
            "registered_chip_count": len(chips), "crop_count": len(crop_paths),
            "assets": assets}


def generate_demo_maps(settings: Any, *, seed: int | None = None) -> dict[str, Any]:
    """Create deterministic map illustrations under configured paths.data_root.

    The target directory must not already exist. These are demonstrations, not
    golden/evaluation data or evidence about a physical process.
    """
    data, config, data_root, output_dir, configured_seed = _demo_paths(settings)
    if seed is not None and type(seed) is not int:
        raise ValueError("seed must be an integer")
    seed = configured_seed if seed is None else seed
    if output_dir.exists():
        raise FileExistsError("map analysis output already exists; refusing to overwrite")
    registry = _read_registered_wafers(data)
    if not registry:
        raise ValueError("synthetic incident registry is empty")
    timezone_name = data.get("runtime", {}).get("timezone", "UTC")
    for record in registry:
        _datetime_value(record["occurred_at"], timezone_name)
        _datetime_value(record["available_at"], timezone_name)
    data_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=False)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir()
    demo_cases: dict[str, Any] = {}
    scenarios = ("normal", "local_only", "repeated_motif", "combined")
    for case_index, record in enumerate(registry):
        scenario = scenarios[case_index % len(scenarios)]
        case_dir = output_dir / f"case-{case_index + 1:04d}"
        case_dir.mkdir()
        rendered = _render_case(case_dir, output_dir, record, scenario, seed)
        demo_cases[record["incident_id"]] = {**{key: record[key] for key in
            ("incident_number", "occurred_at", "available_at", "lot_id", "wafer_id")},
            "illustration_mode": scenario,
            "selected_composite_keys": rendered["selected_composite_keys"],
            "registered_chip_count": rendered["registered_chip_count"],
            "crop_count": rendered["crop_count"],
            "assets": rendered["assets"],
            "case_directory": f"case-{case_index + 1:04d}",
            "index_file": str(Path(f"case-{case_index + 1:04d}") / rendered["index_file"])}

    manifest = {
        "schema_version": 1, "synthetic": True, "seed": seed,
        "wm_811k_excluded": True, "mixedwm_excluded": True,
        "map_semantics": "new synthetic spatial measurement illustration; distinct from existing failbit assets",
        "limitations": ["illustration-only synthetic maps", "not a golden or evaluation set",
                        "no defect accuracy or causal claim", "source composite keys are private under paths.data_root"],
        "cases": demo_cases,
    }
    manifest_path = output_dir / "map-analysis-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "GENERATED", "synthetic": True,
            "output_ref": "paths.data_root/platform.map_analysis.subdirectory",
            "case_count": len(demo_cases), "chip_crop_count": sum(row["crop_count"] for row in demo_cases.values()),
            "wm_811k_used": False, "mixedwm_used": False}


def analyze_demo_case(settings: Any, incident_id: str, as_of: str) -> dict[str, Any]:
    """Resolve only generated synthetic maps for an already validated demo incident.

    The caller must first establish the incident scope through the incident
    Adapter. This wrapper never merges private reference imagery into incident
    evidence and applies the generated map availability cutoff.
    """
    if not isinstance(incident_id, str) or not incident_id or len(incident_id) > 128:
        raise ValueError("invalid synthetic incident identifier")
    data, _config, _data_root, output_dir, _ = _demo_paths(settings)
    timezone_name = data.get("runtime", {}).get("timezone", "UTC")
    cutoff = _next_midnight(as_of, timezone_name)
    manifest_path = output_dir / "map-analysis-manifest.json"
    manifest = _read_json(manifest_path, "synthetic map manifest is unavailable")
    if manifest.get("synthetic") is not True:
        raise ValueError("map manifest is not marked synthetic")
    cases = manifest.get("cases")
    record = cases.get(incident_id) if isinstance(cases, dict) else None
    if not isinstance(record, dict):
        return {"status": "NO_SYNTHETIC_MAP_REFERENCE", "synthetic": True,
                "incident_id": incident_id, "as_of": as_of, "accuracy_claim": False}
    try:
        occurred_at = _datetime_value(record.get("occurred_at"), timezone_name)
        available_at = _datetime_value(record.get("available_at"), timezone_name)
    except ValueError:
        return {"status": "MAP_TIMESTAMP_INVALID", "synthetic": True,
                "incident_id": incident_id, "as_of": as_of, "accuracy_claim": False}
    if occurred_at >= cutoff or available_at >= cutoff:
        return {"status": "MAP_NOT_AVAILABLE_AS_OF", "synthetic": True,
                "incident_id": incident_id, "as_of": as_of, "accuracy_claim": False}
    relative_index = record.get("index_file")
    if not isinstance(relative_index, str):
        raise ValueError("synthetic map manifest entry is invalid")
    index_path = (output_dir / relative_index).resolve()
    if not index_path.is_relative_to(output_dir) or not index_path.is_file():
        raise ValueError("synthetic map index is unavailable")
    result = analyze_reference_maps(index_path)
    result['provenance']['source'] = 'generated_synthetic_registered_maps'
    stored_assets = record.get("assets")
    if (not isinstance(stored_assets, list) or len(stored_assets) != 7
            or sum(isinstance(asset, dict) and asset.get("kind") == "wafer" for asset in stored_assets) != 1
            or sum(isinstance(asset, dict) and asset.get("kind") == "chip" for asset in stored_assets) != 6):
        raise ValueError("synthetic map asset registry is incomplete")
    public_assets = []
    for asset in stored_assets:
        if not isinstance(asset, dict) or asset.get("kind") not in {"wafer", "chip"}:
            raise ValueError("synthetic map asset registry is invalid")
        public_assets.append({key: asset.get(key) for key in
                              ("asset_id", "kind", "sha256", "lot_id", "wafer_id", "chip_id")})
    return {"status": "OK", "synthetic": True, "incident_id": incident_id, "as_of": as_of,
            "map_semantics": manifest.get("map_semantics"),
            "assets": public_assets,
            "provenance": {"kind": "procedural_synthetic_demo", "manifest_sha256": _sha256(manifest_path),
                           "index_sha256": _sha256(index_path), "private_reference_merged": False},
            "analysis": result, "accuracy_claim": False}


def demo_asset(settings: Any, asset_id: str) -> bytes:
    """Read one generated PNG by opaque ID, confined to configured map-analysis output."""
    match = re.fullmatch(r"map-([a-f0-9]{64})-[a-f0-9]{16}", asset_id) if isinstance(asset_id, str) else None
    if match is None:
        raise ValueError("invalid map asset identifier")
    _data, _config, _data_root, output_dir, _seed = _demo_paths(settings)
    path = (output_dir / "assets" / f"{asset_id}.png").resolve()
    if not path.is_relative_to(output_dir) or path.suffix.lower() != ".png" or not path.is_file():
        raise ValueError("map asset is unavailable")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("map asset exceeds the configured response bound")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != match.group(1):
        raise ValueError("map asset hash mismatch")
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("map asset is not a PNG")
    return content
