"""Local, synthetic image comparison service for the ImageTools HTTP contract.

This module is intentionally a demo algorithm.  It reads only registered
``/assets/`` files from the configured static root and never reports semantic
defects or verified physical alignment.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import io
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

from incident_tools import ToolError


SEM_MODEL = "sem-demo-v1"
OVERLAY_MODEL = "overlay-demo-v1"
_MODEL_BY_MODALITY = {"sem": SEM_MODEL, "overlay": OVERLAY_MODEL}
_ASSET_FIELDS = {
    "asset_id",
    "incident_id",
    "lot_id",
    "wafer_id",
    "item",
    "step",
    "equipment",
    "modality",
    "coordinate_system",
    "acquisition",
    "acquired_at",
    "revision",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_SYNTHETIC_MARKERS = ("synthetic", "fixture", "합성", "ai 생성")
_MAX_SCOPE_IDS = 100
_MAX_VECTOR_POINTS = 4096
_MAX_IMAGE_PIXELS = 25_000_000
_FEATURE_VERSION = 2
_FIXTURE_VERSION = "synthetic-common-grid-v2"


def _string(value: Any, code: str, limit: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ToolError(code)
    return value


def _asset_id(value: Any, code: str = "INVALID_IMAGE_ASSET") -> str:
    value = _string(value, code)
    if "/" in value or "\\" in value or _ID_SCHEME.match(value):
        raise ToolError(code)
    return value


def _as_of(value: Any) -> str:
    value = _string(value, "INVALID_AS_OF", 10)
    if not _DATE_RE.fullmatch(value):
        raise ToolError("INVALID_AS_OF")
    try:
        _datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError("INVALID_AS_OF") from exc
    return value


def _timestamp(value: Any) -> str:
    value = _string(value, "INVALID_IMAGE_ASSET")
    try:
        parsed = _datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError("INVALID_IMAGE_ASSET") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ToolError("INVALID_IMAGE_ASSET")
    return value


def _date_not_after(value: str, as_of: str) -> None:
    parsed = _datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.date() > _datetime.date.fromisoformat(as_of):
        raise ToolError("INVALID_IMAGE_ASSET")


def _finite(value: Any) -> float:
    if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value):
        raise ToolError("INVALID_OVERLAY_VECTORS")
    return float(value)


def _synthetic_text(value: Any) -> bool:
    return isinstance(value, str) and any(marker in value.casefold() for marker in _SYNTHETIC_MARKERS)


def _copy_vectors(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list) or not value or len(value) > _MAX_VECTOR_POINTS:
        raise ToolError("INVALID_OVERLAY_VECTORS")
    vectors = []
    for point in value:
        if not isinstance(point, dict) or not {"x", "y", "dx", "dy"}.issubset(point):
            raise ToolError("INVALID_OVERLAY_VECTORS")
        row = {key: _finite(point[key]) for key in ("x", "y", "dx", "dy")}
        if "contributors" in point:
            row["contributors"] = _finite(point["contributors"])
        vectors.append(row)
    return vectors


class DemoImageService:
    """Serve registered synthetic SEM assets and deterministic overlay fixtures."""

    model_ids = _MODEL_BY_MODALITY

    def __init__(self, raw_data: dict, static_root: str | Path, incident_map: Any,
                 model_root: str | Path | None = None):
        self.static_root = Path(static_root).expanduser().resolve()
        self.asset_root = (self.static_root / "assets").resolve()
        self.model_root = Path(model_root).expanduser().resolve() if model_root is not None else None
        self._models: dict[str, dict[str, Any]] = {}
        if not isinstance(raw_data, dict):
            raise ToolError("SYNTHETIC_RAW_REQUIRED")
        if "incidents" in raw_data:
            if raw_data.get("synthetic") is not True or not isinstance(raw_data["incidents"], dict):
                raise ToolError("SYNTHETIC_RAW_REQUIRED")
            self.records = raw_data["incidents"]
        else:
            self.records = raw_data
        if not self.records or any(not isinstance(key, str) or not isinstance(value, dict)
                                   for key, value in self.records.items()):
            raise ToolError("SYNTHETIC_RAW_REQUIRED")
        self.incident_rows = self._normalize_incident_map(incident_map)

    @staticmethod
    def _normalize_incident_map(incident_map: Any) -> list[tuple[str, dict]]:
        if incident_map is None:
            return []
        pairs: list[tuple[str, dict]] = []
        values = incident_map.items() if isinstance(incident_map, dict) else enumerate(incident_map) if isinstance(incident_map, list) else ()
        for key, row in values:
            if not isinstance(row, dict):
                continue
            keys = [key] if isinstance(key, str) else []
            for field in ("incident_id", "incident_number"):
                if isinstance(row.get(field), str):
                    keys.append(row[field])
            for candidate in dict.fromkeys(keys):
                pairs.append((candidate, row))
        return pairs

    def _record_for_incident_id(self, incident_id: str) -> tuple[str, dict]:
        for number, record in self.records.items():
            if incident_id == number:
                return number, record
            for candidate, row in self.incident_rows:
                if candidate == number and incident_id in {row.get("incident_id"), row.get("incident_number")}:
                    return number, record
        raise ToolError("IMAGE_SCOPE_INVALID")

    @staticmethod
    def _scope(payload: dict) -> tuple[list[str], str, str]:
        if not isinstance(payload, dict):
            raise ToolError("INVALID_IMAGE_REQUEST")
        actor = _string(payload.get("actor"), "INVALID_ACTOR")
        incident_ids = payload.get("incident_ids")
        if (not isinstance(incident_ids, list) or not incident_ids or len(incident_ids) > _MAX_SCOPE_IDS
                or any(type(value) is not str or not value.strip() for value in incident_ids)
                or len(set(incident_ids)) != len(incident_ids)):
            raise ToolError("IMAGE_SCOPE_INVALID")
        item = _string(payload.get("item"), "INVALID_ITEM")
        as_of = _as_of(payload.get("as_of"))
        return incident_ids, item, as_of

    @staticmethod
    def _modality(payload: dict) -> str:
        modality = payload.get("modality")
        if modality not in _MODEL_BY_MODALITY:
            raise ToolError("INVALID_MODALITY")
        return modality

    @staticmethod
    def _fab_index(record: dict) -> dict[tuple[str, str], dict]:
        engineering = record.get("engineering")
        fab = engineering.get("fab") if isinstance(engineering, dict) else None
        if not isinstance(fab, list):
            raise ToolError("INVALID_IMAGE_ASSET")
        result = {}
        for row in fab:
            if not isinstance(row, dict):
                raise ToolError("INVALID_IMAGE_ASSET")
            pair = (row.get("lotId"), row.get("waferId"))
            if any(type(value) is not str or not value.strip() for value in pair):
                raise ToolError("INVALID_IMAGE_ASSET")
            if pair in result:
                raise ToolError("INVALID_IMAGE_ASSET")
            result[pair] = row
        return result

    def _raw_vectors(self, record: dict, raw_asset: dict) -> Any:
        for key in ("overlay_vectors", "overlayVectors", "vectors"):
            if key in raw_asset:
                return raw_asset[key]
        for key in ("overlay_vectors", "overlayVectors"):
            value = record.get(key)
            if isinstance(value, dict):
                for lookup in (raw_asset.get("id"),
                               f"{raw_asset.get('lotId')}:{raw_asset.get('waferId')}"):
                    if lookup in value:
                        candidate = value[lookup]
                        return candidate.get("points") if isinstance(candidate, dict) else candidate
            elif isinstance(value, list):
                return value
        return None

    def _assets_for(self, incident_id: str, number: str, record: dict, item: str,
                    modality: str, as_of: str) -> list[dict]:
        if modality == "overlay":
            return self._overlay_assets(incident_id, number, record, item, as_of)
        # The normalized loader removes its top-level synthetic flag.  Each
        # registered media row still carries a synthetic provenance marker.
        assets_source = record.get("sem_assets")
        if not isinstance(assets_source, list):
            raise ToolError("INVALID_IMAGE_ASSET")
        fab = self._fab_index(record)
        result = []
        for raw_asset in assets_source:
            if not isinstance(raw_asset, dict):
                raise ToolError("INVALID_IMAGE_ASSET")
            for field in ("id", "lotId", "waferId", "src"):
                _string(raw_asset.get(field), "INVALID_IMAGE_ASSET")
            if not (_synthetic_text(raw_asset.get("provenance"))
                    or _synthetic_text(raw_asset.get("description"))
                    or raw_asset["id"].startswith("SYN-")):
                raise ToolError("SYNTHETIC_RAW_REQUIRED")
            fab_row = fab.get((raw_asset["lotId"], raw_asset["waferId"]))
            if fab_row is None:
                raise ToolError("INVALID_IMAGE_ASSET")
            raw_item = raw_asset.get("item")
            if raw_item is not None and raw_item != item:
                continue
            acquired_at = raw_asset.get("acquired_at", raw_asset.get("acquiredAt", fab_row.get("timestamp")))
            acquired_at = _timestamp(acquired_at)
            _date_not_after(acquired_at, as_of)
            asset_id = _asset_id(raw_asset["id"])
            src = raw_asset["src"]
            if not src.startswith("/assets/") or "\\" in src or "//" in src[1:]:
                raise ToolError("INVALID_IMAGE_ASSET")
            relative = PurePosixPath(src.removeprefix("/assets/"))
            if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
                raise ToolError("INVALID_IMAGE_ASSET")
            revision = raw_asset.get("revision", "synthetic-asset-v1")
            coordinate = raw_asset.get("coordinate_system", raw_asset.get("coordinateSystem", "synthetic-wafer-xy"))
            acquisition = raw_asset.get("acquisition", "synthetic-acquisition-v1")
            step = raw_asset.get("step", fab_row.get("step"))
            equipment = raw_asset.get("equipment", fab_row.get("equipment"))
            for value in (revision, coordinate, acquisition, step, equipment):
                _string(value, "INVALID_IMAGE_ASSET")
            result.append({
                "asset_id": asset_id,
                "incident_id": incident_id,
                "lot_id": raw_asset["lotId"],
                "wafer_id": raw_asset["waferId"],
                "item": item,
                "step": step,
                "equipment": equipment,
                "modality": modality,
                "coordinate_system": coordinate,
                "acquisition": acquisition,
                "acquired_at": acquired_at,
                "revision": revision,
                "_src": src,
                "_vectors": self._raw_vectors(record, raw_asset),
                "_number": number,
            })
        return result

    def _overlay_assets(self, incident_id: str, number: str, record: dict,
                        item: str, as_of: str) -> list[dict]:
        if not number.startswith("SYN-"):
            raise ToolError("SYNTHETIC_RAW_REQUIRED")
        signals = record.get("engineering", {}).get("signals", [])
        steps = {signal["step"] for signal in signals if signal.get("item") == item}
        if not steps:
            return []
        result = []
        for (lot, wafer), row in self._fab_index(record).items():
            if row.get("step") not in steps:
                continue
            acquired_at = _timestamp(row.get("timestamp"))
            if _datetime.datetime.fromisoformat(acquired_at.replace("Z", "+00:00")).date().isoformat() > as_of:
                continue
            identity = json.dumps([incident_id, lot, wafer, item], separators=(",", ":"))
            asset_id = "SYN-OVL-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            vectors = self._raw_vectors(record, {**row, "id": asset_id})
            version_data = json.dumps([_FIXTURE_VERSION, row, vectors], sort_keys=True)
            revision = "v2-" + hashlib.sha256(version_data.encode()).hexdigest()[:24]
            result.append({
                "asset_id": asset_id, "incident_id": incident_id,
                "lot_id": lot, "wafer_id": wafer, "item": item,
                "step": _string(row.get("step"), "INVALID_IMAGE_ASSET"),
                "equipment": _string(row.get("equipment"), "INVALID_IMAGE_ASSET"),
                "modality": "overlay", "coordinate_system": _FIXTURE_VERSION,
                "acquisition": "synthetic-vector-fixture-v2",
                "acquired_at": acquired_at, "revision": revision, "_vectors": vectors,
            })
        return result

    def _registered(self, incident_ids: list[str], item: str, modality: str, as_of: str) -> dict[str, dict]:
        registered: dict[str, dict] = {}
        for incident_id in incident_ids:
            number, record = self._record_for_incident_id(incident_id)
            for asset in self._assets_for(incident_id, number, record, item, modality, as_of):
                if asset["asset_id"] in registered:
                    raise ToolError("INVALID_IMAGE_ASSET")
                registered[asset["asset_id"]] = asset
        return registered

    @staticmethod
    def _public_asset(asset: dict) -> dict:
        return {field: asset[field] for field in _ASSET_FIELDS}

    def assets(self, payload: dict) -> dict:
        """Implement the ``POST /assets`` response expected by ImageTools."""
        incident_ids, item, as_of = self._scope(payload)
        modality = self._modality(payload)
        registered = self._registered(incident_ids, item, modality, as_of)
        return {"assets": [self._public_asset(asset) for asset in registered.values()]}

    @staticmethod
    def _fixture_vectors(lot_id: str, wafer_id: str) -> list[dict[str, float]]:
        # Cross-language tests execute makeOverlayFixture and compare every point.
        encoded = json.dumps([lot_id, wafer_id], separators=(",", ":"), ensure_ascii=False)
        seed = 0x811C9DC5
        for char in encoded:
            code = ord(char)
            if code > 0xFFFF:
                code = 0xD800 + ((code - 0x10000) >> 10)
            seed = ((seed ^ code) * 0x01000193) & 0xFFFFFFFF
        phase = (seed % 10000) / 10000
        points = []
        synthetic_lot = re.fullmatch(r"SYN-LOT-\d+-\d+", lot_id) is not None
        for row in range(8):
            for column in range(8):
                base_x, base_y = -14 + column * 4, -14 + row * 4
                if math.hypot(base_x, base_y) > 15:
                    continue
                x, y = base_x, base_y
                dx = 1.05 * math.sin(x / 5 + phase * 4) - 0.42 * math.cos(y / 4 - phase * 2)
                dy = 0.95 * math.cos(y / 5 - phase * 3) + 0.38 * math.sin(x / 4 + phase * 5)
                if synthetic_lot and wafer_id == "W01":
                    dx += 0.22 * x
                    dy += 0.22 * y
                elif synthetic_lot and wafer_id == "W03":
                    dx += 2.4
                    dy -= 1.8
                points.append({
                    "x": x,
                    "y": y,
                    "dx": dx,
                    "dy": dy,
                })
        return points

    @staticmethod
    def _vectors(asset: dict) -> tuple[list[dict[str, float]], str]:
        if asset["_vectors"] is not None:
            return _copy_vectors(asset["_vectors"]), "explicit synthetic vector array"
        return DemoImageService._fixture_vectors(asset["lot_id"], asset["wafer_id"]), "frontend/server synthetic-common-grid-v2 fixture"

    @staticmethod
    def _read_grayscale(path: Path) -> tuple[int, int, list[int]]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ToolError("PILLOW_REQUIRED_FOR_DEMO_IMAGES") from exc
        try:
            with Image.open(path) as image:
                width, height = image.size
                if not width or not height or width * height > _MAX_IMAGE_PIXELS:
                    raise ToolError("IMAGE_TOO_LARGE")
                gray = image.convert("L")
                gray.load()
                return width, height, list(gray.getdata())
        except ToolError:
            raise
        except (OSError, ValueError) as exc:
            raise ToolError("INVALID_IMAGE_ASSET") from exc

    @staticmethod
    def _sem_features(metrics: dict[str, Any]) -> list[float]:
        """Texture-tolerant line connectivity; no filenames or class labels."""
        import numpy as np
        from PIL import Image, ImageFilter
        from scipy.ndimage import label
        pixels = np.asarray(metrics["pixels"], dtype=np.uint8).reshape(metrics["height"], metrics["width"])
        raster = Image.fromarray(pixels).resize((256, 256)).filter(ImageFilter.GaussianBlur(1))
        gray = np.asarray(raster, dtype=float)
        low, high = np.percentile(gray, [10, 90])
        mask = gray > (low + high) / 2
        components, _ = label(mask)
        # Cropped edge stripes are not broken lines in the toy connectivity task.
        border = np.unique(np.concatenate((components[:, 0], components[:, -1])))
        mask &= ~np.isin(components, border)
        components, _ = label(mask)
        areas = np.bincount(components.ravel())[1:]
        areas = areas[areas > mask.size * 0.002]
        if not len(areas):
            return [0.0, 0.0, 0.0]
        runs = (np.diff(np.pad(mask.astype(int), ((0, 0), (1, 0))), axis=1) == 1).sum(axis=1)
        median = float(np.median(areas))
        return [float(areas.max() / median),
                float(len(areas) / max(1.0, np.median(runs))),
                float(np.mean(areas < median * 0.7))]

    @staticmethod
    def _overlay_features(vectors: list[dict[str, float]]) -> list[float]:
        if not vectors:
            raise ToolError("INVALID_OVERLAY_VECTORS")
        xs = [point["x"] for point in vectors]
        ys = [point["y"] for point in vectors]
        dxs = [point["dx"] for point in vectors]
        dys = [point["dy"] for point in vectors]
        magnitudes = [math.hypot(dx, dy) for dx, dy in zip(dxs, dys)]
        def mean(values: list[float]) -> float:
            return sum(values) / len(values)
        def std(values: list[float]) -> float:
            center = mean(values)
            return math.sqrt(sum((value - center) ** 2 for value in values) / len(values))
        def covariance(left: list[float], right: list[float]) -> float:
            left_mean, right_mean = mean(left), mean(right)
            return mean([(a - left_mean) * (b - right_mean) for a, b in zip(left, right)])
        radius = max(math.hypot(x, y) for x, y in zip(xs, ys)) or 1.0
        return [
            mean(dxs), mean(dys), std(dxs), std(dys), mean(magnitudes), std(magnitudes),
            covariance(xs, dxs) / radius, covariance(ys, dys) / radius,
            covariance(xs, dys) / radius, covariance(ys, dxs) / radius,
            len(vectors) / 64.0,
        ]

    def _model(self, modality: str) -> dict[str, Any]:
        if modality in self._models:
            return self._models[modality]
        if self.model_root is None:
            raise ToolError("DEMO_IMAGE_MODEL_REQUIRED")
        model_dir = self.model_root / modality
        metadata_path, arrays_path = model_dir / "model.json", model_dir / "model.npz"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            artifact_bytes = arrays_path.read_bytes()
            import numpy as np
            arrays = np.load(io.BytesIO(artifact_bytes), allow_pickle=False)
            mean = np.asarray(arrays["mean"], dtype=float)
            scale = np.asarray(arrays["scale"], dtype=float)
            coefficients = np.asarray(arrays["coefficients"], dtype=float)
            intercept = np.asarray(arrays["intercept"], dtype=float)
            arrays.close()
        except ToolError:
            raise
        except (ImportError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ToolError("DEMO_IMAGE_MODEL_INVALID") from exc
        if (not isinstance(metadata, dict) or metadata.get("modality") != modality
                or metadata.get("model") != _MODEL_BY_MODALITY[modality]
                or metadata.get("feature_version") != _FEATURE_VERSION
                or type(metadata.get("model_version")) is not str or not metadata["model_version"].strip()
                or not isinstance(metadata.get("classes"), list)
                or len(metadata["classes"]) < 2 or any(not isinstance(value, str) for value in metadata["classes"])):
            raise ToolError("DEMO_IMAGE_MODEL_INVALID")
        feature_count = mean.size
        if (mean.ndim != 1 or scale.shape != mean.shape or coefficients.ndim != 2
                or coefficients.shape[1] != feature_count or intercept.shape != (coefficients.shape[0],)
                or coefficients.shape[0] != len(metadata["classes"])
                or np.any(~np.isfinite(mean)) or np.any(~np.isfinite(scale))
                or np.any(scale <= 0) or np.any(~np.isfinite(coefficients)) or np.any(~np.isfinite(intercept))):
            raise ToolError("DEMO_IMAGE_MODEL_INVALID")
        threshold = metadata.get("ood_threshold")
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or threshold <= 0:
            raise ToolError("DEMO_IMAGE_MODEL_INVALID")
        metrics = metadata.get("metrics")
        if (not isinstance(metrics, dict) or type(metrics.get("holdout_accuracy")) not in (int, float)
                or not math.isfinite(metrics["holdout_accuracy"])
                or not 0 <= metrics["holdout_accuracy"] <= 1):
            raise ToolError("DEMO_IMAGE_MODEL_INVALID")
        training = metadata.get("training")
        if (not isinstance(training, dict) or not isinstance(training.get("algorithm"), str)
                or type(training.get("train_seed")) is not int
                or type(training.get("holdout_seed")) is not int
                or type(training.get("train_count")) is not int
                or type(training.get("holdout_count")) is not int):
            raise ToolError("DEMO_IMAGE_MODEL_INVALID")
        artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
        config_metadata = dict(metadata)
        recorded_artifact_hash = config_metadata.pop("artifact_hash", None)
        recorded_config_hash = config_metadata.pop("config_hash", None)
        recorded_version = config_metadata.pop("model_version", None)
        config_hash = hashlib.sha256(json.dumps(
            config_metadata, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        expected_version = f"{metadata['model']}+weights-{artifact_hash[:12]}-config-{config_hash[:12]}"
        if (recorded_artifact_hash != artifact_hash or recorded_config_hash != config_hash
                or recorded_version != expected_version):
            raise ToolError("DEMO_IMAGE_MODEL_INVALID")
        loaded = {"metadata": metadata, "mean": mean, "scale": scale,
                  "coefficients": coefficients, "intercept": intercept,
                  "threshold": float(threshold)}
        self._models[modality] = loaded
        return loaded

    @staticmethod
    def _predict(model: dict[str, Any], features: list[float]) -> tuple[str, float, float]:
        import numpy as np
        vector = np.asarray(features, dtype=float)
        if vector.shape != model["mean"].shape or np.any(~np.isfinite(vector)):
            raise ToolError("DEMO_IMAGE_FEATURE_INVALID")
        z = (vector - model["mean"]) / model["scale"]
        logits = model["coefficients"] @ z + model["intercept"]
        logits -= np.max(logits)
        probabilities = np.exp(logits)
        probabilities /= np.sum(probabilities)
        index = int(np.argmax(probabilities))
        distance = float(np.linalg.norm(z))
        return model["metadata"]["classes"][index], float(probabilities[index]), distance

    def _image_metrics(self, asset: dict) -> dict[str, Any]:
        relative = PurePosixPath(asset["_src"].removeprefix("/assets/"))
        path = (self.asset_root / Path(*relative.parts)).resolve()
        try:
            path.relative_to(self.asset_root)
        except ValueError as exc:
            raise ToolError("INVALID_IMAGE_ASSET") from exc
        width, height, pixels = self._read_grayscale(path)
        count = len(pixels)
        mean = sum(pixels) / count
        variance = sum((value - mean) ** 2 for value in pixels) / count
        edge_count = 0
        for row in range(height):
            for column in range(width):
                index = row * width + column
                if column + 1 < width and abs(pixels[index] - pixels[index + 1]) >= 18:
                    edge_count += 1
                if row + 1 < height and abs(pixels[index] - pixels[index + width]) >= 18:
                    edge_count += 1
        possible_edges = width * (height - 1) + height * (width - 1)
        return {
            "width": width,
            "height": height,
            "mean_gray": mean,
            "contrast_std_gray": math.sqrt(variance),
            "edge_fraction": edge_count / possible_edges if possible_edges else 0.0,
            "pixels": pixels,
        }

    @staticmethod
    def _sem_findings(first: dict, second: dict) -> list[str]:
        findings = [
            f"synthetic grayscale baseline: A {first['width']}x{first['height']}, mean={first['mean_gray']:.3f}, contrast_std={first['contrast_std_gray']:.3f}, edge_fraction={first['edge_fraction']:.6f}",
            f"synthetic grayscale baseline: B {second['width']}x{second['height']}, mean={second['mean_gray']:.3f}, contrast_std={second['contrast_std_gray']:.3f}, edge_fraction={second['edge_fraction']:.6f}",
            f"measured contrast delta_std={abs(first['contrast_std_gray'] - second['contrast_std_gray']):.6f}; edge_fraction_delta={abs(first['edge_fraction'] - second['edge_fraction']):.6f}",
        ]
        if (first["width"], first["height"]) == (second["width"], second["height"]):
            mae = sum(abs(a - b) for a, b in zip(first["pixels"], second["pixels"])) / len(first["pixels"])
            findings.append(f"same-shape unregistered pixel baseline: mean_absolute_gray_delta={mae:.6f}/255")
        else:
            findings.append("unregistered pixel delta unavailable because raster dimensions differ")
        return findings

    @staticmethod
    def _overlay_findings(first: dict, second: dict, source_a: str, source_b: str) -> list[str]:
        first_by_coordinate = {(point["x"], point["y"]): point for point in first["vectors"]}
        second_by_coordinate = {(point["x"], point["y"]): point for point in second["vectors"]}
        coordinates = sorted(set(first_by_coordinate) & set(second_by_coordinate))
        paired = len(coordinates)
        deltas = [math.hypot(first_by_coordinate[key]["dx"] - second_by_coordinate[key]["dx"],
                             first_by_coordinate[key]["dy"] - second_by_coordinate[key]["dy"])
                  for key in coordinates]
        magnitudes = [math.hypot(first_by_coordinate[key]["dx"], first_by_coordinate[key]["dy"])
                      for key in coordinates]
        mean_delta = sum(deltas) / paired if paired else None
        rms_delta = math.sqrt(sum(value * value for value in deltas) / paired) if paired else None
        return [
            f"vector baseline sources: A={source_a}; B={source_b}",
            f"vector counts: A={len(first['vectors'])}, B={len(second['vectors'])}, exact_coordinate_matches={paired}, missing_from_A={len(set(second_by_coordinate) - set(first_by_coordinate))}, missing_from_B={len(set(first_by_coordinate) - set(second_by_coordinate))}",
            f"measured vector delta: mean={mean_delta:.6f} nm, rms={rms_delta:.6f} nm" if paired else "measured vector delta unavailable: no paired points",
            f"A mean vector magnitude={sum(magnitudes) / paired:.6f} nm" if paired else "A mean vector magnitude unavailable",
        ]

    def _historical_findings(self, assets: list[dict], features: list[list[float]],
                             model: dict, modality: str) -> list[str]:
        import numpy as np
        findings = []
        for owner, asset, feature in zip(("A", "B"), assets, features):
            _, record = self._record_for_incident_id(asset["incident_id"])
            references = record.get("image_history", [])
            from workbench_data import _validate_image_history
            try:
                _validate_image_history(references)
            except ValueError as exc:
                raise ToolError("INVALID_IMAGE_HISTORY") from exc
            acquired = _datetime.datetime.fromisoformat(asset["acquired_at"].replace("Z", "+00:00"))
            candidates = []
            for ref in references:
                if (ref["modality"] != modality or ref["item"] != asset["item"]
                        or ref["step"] != asset["step"]
                        or not _synthetic_text(ref["provenance"])):
                    continue
                occurred = _datetime.datetime.fromisoformat(ref["occurred_at"].replace("Z", "+00:00"))
                if occurred >= acquired:
                    continue
                if modality == "sem":
                    metrics = self._image_metrics({"_src": ref["src"]})
                    ref_feature = self._sem_features(metrics)
                else:
                    vectors = _copy_vectors(ref["vectors"])
                    current_vectors, _ = self._vectors(asset)
                    if ({(p["x"], p["y"]) for p in vectors}
                            != {(p["x"], p["y"]) for p in current_vectors}):
                        continue
                    ref_feature = self._overlay_features(vectors)
                distance = float(np.sqrt(np.mean(((np.asarray(feature) - ref_feature) / model["scale"]) ** 2)))
                ref_class, _, ref_ood = self._predict(model, ref_feature)
                candidates.append((distance, ref["id"], ref, ref_class, ref_ood))
            for rank, (distance, _, ref, ref_class, ref_ood) in enumerate(sorted(candidates)[:2], 1):
                findings.append(
                    f"synthetic historical candidate: owner={owner}, rank={rank}, reference_id={ref['id']}, "
                    f"incident_number={ref['incident_number']}, occurred_at={ref['occurred_at']}, "
                    f"descriptor_distance={distance:.6f} (lower is closer), reference_class={ref_class}, "
                    f"reference_ood={ref_ood > model['threshold']}; separate reference, not current impact scope"
                )
        return findings

    def compare(self, payload: dict) -> dict:
        """Implement the ``POST /compare`` response expected by ImageTools."""
        incident_ids, item, as_of = self._scope(payload)
        modality = self._modality(payload)
        request_id = _string(payload.get("request_id"), "INVALID_IMAGE_COMPARE_RESULT")
        model = _string(payload.get("model"), "INVALID_IMAGE_COMPARE_RESULT")
        if model != _MODEL_BY_MODALITY[modality]:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        asset_ids = payload.get("asset_ids")
        revisions = payload.get("asset_revisions")
        if (not isinstance(asset_ids, list) or len(asset_ids) != 2
                or any(not isinstance(value, str) for value in asset_ids)
                or len(set(asset_ids)) != 2):
            raise ToolError("IMAGE_ASSET_IDS_REQUIRED")
        asset_ids = [_asset_id(value) for value in asset_ids]
        if not isinstance(revisions, list) or len(revisions) != 2:
            raise ToolError("IMAGE_ASSET_REVISIONS_REQUIRED")
        revisions = [_string(value, "INVALID_IMAGE_COMPARE_RESULT") for value in revisions]
        registered = self._registered(incident_ids, item, modality, as_of)
        if any(asset_id not in registered for asset_id in asset_ids):
            raise ToolError("IMAGE_ASSET_UNKNOWN")
        assets = [registered[asset_id] for asset_id in asset_ids]
        if any(asset["revision"] != revision for asset, revision in zip(assets, revisions)):
            raise ToolError("IMAGE_ASSET_REVISION_MISMATCH")
        for field in ("step", "coordinate_system", "acquisition"):
            if assets[0][field] != assets[1][field]:
                raise ToolError("IMAGE_COMPARISON_INCOMPATIBLE")

        model_data = self._model(modality)
        if modality == "sem":
            first = self._image_metrics(assets[0])
            second = self._image_metrics(assets[1])
            findings = self._sem_findings(first, second)
            features = [self._sem_features(first), self._sem_features(second)]
            label_a, confidence_a, distance_a = self._predict(model_data, features[0])
            label_b, confidence_b, distance_b = self._predict(model_data, features[1])
            findings.extend([
                f"trained synthetic SEM classifier: A class={label_a}, confidence={confidence_a:.6f}, ood={distance_a > model_data['threshold']}",
                f"trained synthetic SEM classifier: B class={label_b}, confidence={confidence_b:.6f}, ood={distance_b > model_data['threshold']}",
                f"classifier holdout accuracy recorded by training run={model_data['metadata']['metrics']['holdout_accuracy']:.6f}",
            ])
            limitations = [
                "trained only on generated synthetic SEM classes; classifier output is not a production SEM model",
                "physical registration, magnification, scale, and alignment are unverified",
                "class/confidence is synthetic-distribution evidence only; no production semantic defect verdict is returned",
            ]
        else:
            first_vectors, source_a = self._vectors(assets[0])
            second_vectors, source_b = self._vectors(assets[1])
            findings = self._overlay_findings(
                {"vectors": first_vectors}, {"vectors": second_vectors}, source_a, source_b
            )
            features = [self._overlay_features(first_vectors), self._overlay_features(second_vectors)]
            label_a, confidence_a, distance_a = self._predict(model_data, features[0])
            label_b, confidence_b, distance_b = self._predict(model_data, features[1])
            findings.extend([
                f"trained synthetic overlay classifier: A class={label_a}, confidence={confidence_a:.6f}, ood={distance_a > model_data['threshold']}",
                f"trained synthetic overlay classifier: B class={label_b}, confidence={confidence_b:.6f}, ood={distance_b > model_data['threshold']}",
                f"classifier holdout accuracy recorded by training run={model_data['metadata']['metrics']['holdout_accuracy']:.6f}",
            ])
            limitations = [
                "trained only on generated synthetic vector classes; classifier output is not a production metrology model",
                "shared synthetic grid coordinates permit numerical pairing only; physical alignment remains unverified",
                "physical registration and semantic defect interpretation are unverified; class/confidence is synthetic-distribution evidence only",
            ]
        historical = self._historical_findings(assets, features, model_data, modality)
        findings.extend(historical)
        limitations.append("historical candidates use a configured synthetic reference library, not production incident retrieval; descriptor distance is not a probability or verified physical similarity" if historical else "no eligible historical reference in the configured synthetic library")
        return {
            "request_id": request_id,
            "model": model,
            "model_version": model_data["metadata"]["model_version"],
            "item": item,
            "modality": modality,
            "asset_ids": asset_ids,
            "asset_revisions": revisions,
            "status": "INCOMPARABLE",
            "alignment_verified": False,
            "similarity": None,
            "findings": findings,
            "limitations": limitations,
            "artifact_ids": [],
        }
