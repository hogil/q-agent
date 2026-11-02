"""Synthetic-only CPU classifiers for configured platform SEM and Trend rows."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import StandardScaler


FORMAT_VERSION = 2
METHOD = "sklearn.StandardScaler+LogisticRegression"
IDENT = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
MODALITIES = ("sem", "trend")


def _guard(settings: Any) -> dict:
    data = settings.data
    platform = data.get("platform")
    if (not isinstance(platform, dict) or platform.get("enabled") is not True
            or data.get("environment") not in ("demo", "test")):
        raise ValueError("synthetic platform models require platform.enabled and demo/test environment")
    return platform


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved, base = path.expanduser().resolve(), root.expanduser().resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(f"{label} must stay under its configured root") from None
    return resolved


def _model_path(settings: Any, modality: str) -> Path:
    if modality not in MODALITIES:
        raise ValueError("unsupported synthetic model modality")
    profile = "image" if modality == "sem" else "trend"
    model = settings.data["models"][profile]
    filename = model.get("checkpoint_file", "")
    if (not isinstance(filename, str) or not filename.endswith(".npz")
            or Path(filename).name != filename):
        raise ValueError(f"models.{profile}.checkpoint_file must be an .npz filename")
    root = Path(settings.data["paths"]["model_root"])
    folder = _inside(Path(model["local_dir"]), root, f"models.{profile}.local_dir")
    return _inside(folder / filename, root, f"models.{profile}.checkpoint_file")


def _quote(value: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("platform source mapping must use simple SQL identifiers")
    return '"' + value + '"'


def sem_features(image: Any) -> list[float]:
    """Extract 16 bounded grayscale pixel descriptors without labels or asset metadata."""
    if isinstance(image, Image.Image):
        pixels = np.asarray(image.convert("L"), dtype=np.float64) / 255.0
    else:
        pixels = np.asarray(image)
        if pixels.ndim == 3:
            pixels = np.asarray(Image.fromarray(pixels.astype(np.uint8)).convert("L"))
        pixels = pixels.astype(np.float64)
        if pixels.size and pixels.max() > 1:
            pixels /= 255.0
    if pixels.ndim != 2 or min(pixels.shape) < 8 or max(pixels.shape) > 512:
        raise ValueError("SEM training image dimensions must be 8..512 grayscale pixels")
    if not np.isfinite(pixels).all():
        raise ValueError("SEM pixels must be finite")
    h, w = pixels.shape
    margin_y, margin_x = max(1, h // 8), max(1, w // 8)
    center = pixels[margin_y:h - margin_y, margin_x:w - margin_x]
    border = np.concatenate((pixels[0], pixels[-1], pixels[1:-1, 0], pixels[1:-1, -1]))
    horizontal = np.diff(pixels, axis=1)
    vertical = np.diff(pixels, axis=0)
    differences = np.concatenate((np.abs(horizontal).ravel(), np.abs(vertical).ravel()))
    stripe = pixels[:, w // 3:(2 * w) // 3]
    features = [
        float(pixels.mean()), float(pixels.std()), float(pixels.min()), float(pixels.max()),
        *np.quantile(pixels, [0.1, 0.25, 0.5, 0.75, 0.9]).tolist(),
        float(np.mean(np.abs(horizontal))), float(np.mean(np.abs(vertical))),
        float(center.mean()), float(border.mean()), float(center.mean() - border.mean()),
        float(stripe.std()), float(np.quantile(differences, 0.9)),
    ]
    return [float(value) for value in features]


def trend_features(values: Any, timestamps: Any = None) -> list[float]:
    """Summarize a raw time-ordered signal; timestamps only define slope spacing."""
    series = np.asarray(values, dtype=np.float64).reshape(-1)
    if len(series) < 8 or not np.isfinite(series).all():
        raise ValueError("Trend series requires at least 8 finite values")
    differences = np.diff(series)
    early = float(series[:max(1, len(series) // 4)].mean())
    late = float(series[-max(1, len(series) // 4):].mean())
    if timestamps is None:
        x = np.linspace(0.0, 1.0, len(series))
    else:
        parsed = np.asarray(timestamps, dtype=np.float64).reshape(-1)
        if len(parsed) != len(series) or not np.isfinite(parsed).all():
            raise ValueError("Trend timestamps must align with values")
        span = parsed[-1] - parsed[0]
        x = (parsed - parsed[0]) / span if span > 0 else np.linspace(0.0, 1.0, len(series))
    slope = float(np.polyfit(x, series, 1)[0])
    centered = series - series.mean()
    scale = float(series.std())
    skew = float(np.mean(centered ** 3) / (scale ** 3)) if scale else 0.0
    kurtosis = float(np.mean(centered ** 4) / (scale ** 4) - 3.0) if scale else 0.0
    return [float(value) for value in [
        series.mean(), series.std(), series.min(), series.max(),
        *np.quantile(series, [0.1, 0.5, 0.9]).tolist(),
        early, late, late - early, slope,
        np.mean(np.abs(differences)), differences.std(), np.max(np.abs(differences)),
        skew, kurtosis,
    ]]


def _db(settings: Any) -> sqlite3.Connection:
    db = settings.data.get("database", {})
    if db.get("dialect") != "sqlite":
        raise ValueError("synthetic platform model training requires SQLite")
    path = Path(db.get("sqlite_file", "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError("configured platform SQLite database is unavailable")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _source_rows(settings: Any, modality: str) -> list[dict]:
    platform = _guard(settings)
    mapping = platform.get("tables", {}).get(modality)
    if not isinstance(mapping, dict) or not isinstance(mapping.get("columns"), dict):
        raise ValueError(f"platform.tables.{modality} mapping is required")
    columns = mapping["columns"]
    needed = ("incident_id", "storage_ref", "sha256", "training_label", "synthetic") if modality == "sem" else (
        "incident_id", "item", "timestamp", "value", "training_label", "synthetic")
    if not set(needed).issubset(columns):
        raise ValueError(f"platform.tables.{modality} is missing training columns")
    selected = ",".join(_quote(columns[field]) + " AS " + _quote(field) for field in needed)
    table = _quote(mapping.get("name"))
    with closing(_db(settings)) as con:
        invalid = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {_quote(columns['synthetic'])} IS NOT 1").fetchone()[0]
        if invalid:
            raise ValueError(f"platform {modality} table contains non-synthetic rows")
        result = [dict(row) for row in con.execute(f"SELECT {selected} FROM {table} WHERE {_quote(columns['synthetic'])}=1")]
    return result


def _sem_dataset(settings: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = _source_rows(settings, "sem")
    root = Path(settings.data["paths"]["image_root"]).expanduser().resolve()
    features, labels, groups = [], [], []
    for row in rows:
        group, label, reference = row["incident_id"], row["training_label"], row["storage_ref"]
        if not all(isinstance(value, str) and value for value in (group, label, reference)):
            raise ValueError("SEM synthetic training rows require incident, label and storage_ref")
        relative = Path(reference)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("SEM storage_ref must be a safe relative image path")
        path = _inside(root / relative, root, "SEM storage_ref")
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("SEM training image is missing or exceeds 8 MiB")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not isinstance(row["sha256"], str) or digest.casefold() != row["sha256"].casefold():
            raise ValueError("SEM training image SHA-256 mismatch")
        with Image.open(path) as image:
            image.load()
            features.append(sem_features(image))
        labels.append(label); groups.append(group)
    return np.asarray(features, dtype=np.float64), np.asarray(labels, dtype=str), np.asarray(groups, dtype=str)


def _trend_dataset(settings: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = _source_rows(settings, "trend")
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        incident, item, label = row["incident_id"], row["item"], row["training_label"]
        if not all(isinstance(value, str) and value for value in (incident, item, label)):
            raise ValueError("Trend synthetic rows require incident_id, item and training_label")
        grouped.setdefault((incident, item), []).append(row)
    features, labels, groups = [], [], []
    from datetime import datetime
    for (incident, _item), points in sorted(grouped.items()):
        points.sort(key=lambda row: row["timestamp"])
        row_labels = {row["training_label"] for row in points}
        if len(row_labels) != 1:
            raise ValueError("Trend training_label must be constant within incident and item")
        try:
            timestamps = [datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp() for row in points]
            values = [float(row["value"]) for row in points]
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Trend training rows require parseable timestamps and numeric values") from None
        features.append(trend_features(values, timestamps)); labels.append(next(iter(row_labels))); groups.append(incident)
    return np.asarray(features, dtype=np.float64), np.asarray(labels, dtype=str), np.asarray(groups, dtype=str)


def _split(groups: np.ndarray, labels: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    unique_groups = np.unique(groups)
    if len(unique_groups) < 5:
        raise ValueError("at least five distinct synthetic incidents are required per modality")
    for attempt in range(100):
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed + attempt)
        train, holdout = next(splitter.split(np.zeros(len(groups)), labels, groups))
        if set(labels[train]) == set(labels) and set(labels[holdout]) == set(labels):
            if set(groups[train]) & set(groups[holdout]):
                raise AssertionError("incident groups leaked across train/holdout")
            return train, holdout
    raise ValueError("could not produce an incident-disjoint split containing every class")


def _metadata(settings: Any, modality: str, train_groups: int, holdout_groups: int,
              accuracy: float, classes: list[str], feature_count: int,
              train_ids: set[str], holdout_ids: set[str], trained_at: str) -> dict:
    def group_hash(groups: set[str]) -> str:
        payload = json.dumps(sorted(groups), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    return {
        "format_version": FORMAT_VERSION, "modality": modality, "method": METHOD,
        "synthetic": True, "source": "configured platform synthetic SQLite table and procedural SEM assets",
        "recipe": "incident-group 80/20 split; StandardScaler fit on train rows only; LogisticRegression max_iter=500",
        "seed": settings.data["platform"]["seed"], "config_hash": settings.config_hash,
        "training_data_as_of": _training_data_as_of(settings), "trained_at": trained_at,
        "train_groups": train_groups, "train_incident_count": train_groups,
        "train_incident_ids_sha256": group_hash(train_ids),
        "holdout_groups": holdout_groups, "holdout_incident_count": holdout_groups,
        "holdout_incident_ids_sha256": group_hash(holdout_ids), "accuracy": accuracy,
        "classes": classes, "feature_count": feature_count,
        "limitation": "Synthetic holdout accuracy is not real-data performance or generalization evidence.",
        "wm_811k_used": False,
    }


def _training_data_as_of(settings: Any) -> str:
    path = Path(settings.data["paths"]["data_root"]) / "platform-manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("as_of")
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return "unknown"


def _write_npz(path: Path, scaler: StandardScaler, classifier: LogisticRegression, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata_bytes = np.frombuffer(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"), dtype=np.uint8)
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            np.savez_compressed(stream, mean=np.asarray(scaler.mean_, dtype=np.float64),
                                scale=np.asarray(scaler.scale_, dtype=np.float64),
                                coef=np.asarray(classifier.coef_, dtype=np.float64),
                                intercept=np.asarray(classifier.intercept_, dtype=np.float64),
                                classes=np.asarray(classifier.classes_, dtype=str), metadata_json=metadata_bytes)
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def train_models(settings: Any) -> dict:
    """Fit CPU-only synthetic SEM/Trend models and write non-pickle NPZ checkpoints."""
    platform = _guard(settings)
    if type(platform.get("seed")) is not int:
        raise ValueError("platform.seed must be an integer")
    paths = {modality: _model_path(settings, modality) for modality in MODALITIES}
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("refusing to overwrite an existing synthetic platform model")
    datasets = {"sem": _sem_dataset(settings), "trend": _trend_dataset(settings)}
    reports = []
    fitted = []
    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for modality, (x, y, groups) in datasets.items():
        if x.ndim != 2 or len(x) != len(y) or len(y) != len(groups) or len(x) < 5:
            raise ValueError(f"insufficient {modality} synthetic training rows")
        if not np.isfinite(x).all() or len(np.unique(y)) < 2:
            raise ValueError(f"{modality} features must be finite and have multiple classes")
        train, holdout = _split(groups, y, platform["seed"])
        scaler = StandardScaler().fit(x[train])
        classifier = LogisticRegression(max_iter=500, random_state=platform["seed"])
        classifier.fit(scaler.transform(x[train]), y[train])
        accuracy = float(np.mean(classifier.predict(scaler.transform(x[holdout])) == y[holdout]))
        if not math.isfinite(accuracy) or not 0 <= accuracy <= 1:
            raise ValueError("synthetic holdout accuracy is invalid")
        train_ids, holdout_ids = set(groups[train]), set(groups[holdout])
        if train_ids & holdout_ids:
            raise AssertionError("incident groups leaked across train/holdout")
        metadata = _metadata(settings, modality, len(train_ids), len(holdout_ids), accuracy,
                             [str(value) for value in classifier.classes_], x.shape[1],
                             train_ids, holdout_ids, trained_at)
        fitted.append((paths[modality], scaler, classifier, metadata))
        reports.append({"modality": modality, "method": METHOD, "train_groups": len(train_ids),
                        "holdout_groups": len(holdout_ids), "accuracy": accuracy,
                        "class_count": len(classifier.classes_), "unclassified_rows": 0})
    created_paths = []
    try:
        for path, scaler, classifier, metadata in fitted:
            _write_npz(path, scaler, classifier, metadata)
            created_paths.append(path)
    except Exception:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    return {"synthetic": True, "models": reports,
            "paths": {modality: str(path) for modality, path in paths.items()},
            "notice": "Synthetic holdout scores do not establish real-data performance or generalization."}


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as bundle:
        metadata = json.loads(np.asarray(bundle["metadata_json"], dtype=np.uint8).tobytes().decode("utf-8"))
        if not isinstance(metadata, dict):
            return None
        if (metadata.get("format_version") != FORMAT_VERSION or metadata.get("synthetic") is not True
                or metadata.get("modality") not in MODALITIES):
            return None
        as_of = metadata.get("training_data_as_of")
        if as_of != "unknown":
            try:
                if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
                    return None
            except ValueError:
                return None
        config_hash = metadata.get("config_hash")
        if not isinstance(config_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", config_hash):
            return None
        for split in ("train", "holdout"):
            count = metadata.get(split + "_incident_count")
            digest = metadata.get(split + "_incident_ids_sha256")
            if (type(count) is not int or count < 1 or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                return None
            if metadata.get(split + "_groups") != count:
                return None
        trained_at_value = metadata.get("trained_at")
        if not isinstance(trained_at_value, str):
            return None
        try:
            trained_at = datetime.fromisoformat(trained_at_value)
        except ValueError:
            return None
        if trained_at.tzinfo is None or trained_at.utcoffset() != timezone.utc.utcoffset(trained_at):
            return None
        if (metadata.get("wm_811k_used") is not False or not isinstance(metadata.get("accuracy"), (int, float))
                or not math.isfinite(metadata["accuracy"]) or not 0 <= metadata["accuracy"] <= 1):
            return None
        arrays = {key: np.asarray(bundle[key]) for key in ("mean", "scale", "coef", "intercept", "classes")}
    if (arrays["mean"].ndim != 1 or arrays["scale"].shape != arrays["mean"].shape
            or arrays["coef"].ndim != 2 or arrays["coef"].shape[1] != len(arrays["mean"])
            or arrays["intercept"].shape != (arrays["coef"].shape[0],)
            or arrays["classes"].ndim != 1 or len(arrays["classes"]) < 2
            or arrays["coef"].shape[0] != (1 if len(arrays["classes"]) == 2 else len(arrays["classes"]))
            or not all(np.isfinite(arrays[key]).all() for key in ("mean", "scale", "coef", "intercept"))
            or not (arrays["scale"] > 0).all()):
        return None
    return {"metadata": metadata, **arrays}


def model_status(settings: Any) -> dict:
    _guard(settings)
    training_data_as_of = _training_data_as_of(settings)
    models = []
    for modality in MODALITIES:
        profile = settings.data['models']['image' if modality == 'sem' else 'trend']
        if not profile['enabled']:
            continue
        path = _model_path(settings, modality)
        try:
            loaded = _load(path)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            loaded = None
        item = {"modality": modality, "status": "NOT_TRAINED",
                "training_data_as_of": training_data_as_of, "checkpoint_path": str(path.resolve())}
        if loaded:
            meta = loaded["metadata"]
            item.update({"status": "READY", "method": meta["method"],
                         "train_groups": meta["train_groups"], "holdout_groups": meta["holdout_groups"],
                         "accuracy": meta["accuracy"],
                         "training_data_as_of": meta["training_data_as_of"],
                         "config_hash": meta["config_hash"]})
        models.append(item)
    ready = all(item["status"] == "READY" for item in models)
    return {"status": "DISABLED" if not models else "READY" if ready else "NOT_TRAINED", "synthetic": True,
            "training_data_as_of": training_data_as_of, "models": models,
            "notice": "Synthetic holdout accuracy is not real-data performance or generalization evidence."}


def predict(settings: Any, modality: str, features: Any) -> dict:
    """Return a synthetic-distribution class score, or an explicit NOT_TRAINED result."""
    _guard(settings)
    if modality not in MODALITIES:
        raise ValueError("unsupported synthetic model modality")
    if not settings.data['models']['image' if modality == 'sem' else 'trend']['enabled']:
        return {'status': 'DISABLED', 'synthetic': True, 'modality': modality,
                'limitation': 'The configured model profile is disabled.'}
    try:
        model = _load(_model_path(settings, modality))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        model = None
    if model is None:
        return {"status": "NOT_TRAINED", "synthetic": True, "modality": modality,
                "limitation": "No trained synthetic checkpoint is available."}
    values = np.asarray(features, dtype=np.float64).reshape(1, -1)
    if values.shape[1] != len(model["mean"]) or not np.isfinite(values).all():
        raise ValueError("prediction feature vector has invalid shape or values")
    scaled = (values[0] - model["mean"]) / model["scale"]
    logits = model["coef"] @ scaled + model["intercept"]
    classes = [str(value) for value in model["classes"]]
    if len(classes) == 2 and len(logits) == 1:
        positive = 1.0 / (1.0 + math.exp(-float(np.clip(logits[0], -60, 60))))
        probabilities = np.asarray([1.0 - positive, positive])
    else:
        logits = logits - np.max(logits)
        probabilities = np.exp(logits) / np.exp(logits).sum()
    best = int(np.argmax(probabilities))
    return {"status": "OK", "synthetic": True, "modality": modality,
            "label": classes[best], "score": float(probabilities[best]),
            "method": model["metadata"]["method"],
            "limitation": "Synthetic-distribution score only; not a production verdict."}
