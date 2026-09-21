"""Train the small, CPU-only synthetic image demo models.

The command writes only its own structured artifacts below ``--model-root``:
JSON metadata, compressed NumPy arrays, generated training/holdout fixtures,
and measured metrics.  It never reads the workbench SEM assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler

from demo_images import DemoImageService, OVERLAY_MODEL, SEM_MODEL, _FEATURE_VERSION


CLASSES = {
    "sem": ("baseline", "bridge", "gap"),
    "overlay": ("nominal", "translation", "radial"),
}


def _sem_bitmap(seed: int, label: str, size: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    pitch = float(rng.uniform(11, 15)) * size / 128
    slope = float(rng.uniform(-0.08, 0.08))
    offset = float(rng.uniform(0, pitch))
    phase = (xx - slope * yy - offset) % pitch
    image = np.where(phase < pitch * 0.5, 175.0, 35.0)
    center = offset + pitch * (int(size / pitch) // 2)
    y0 = int(rng.uniform(0.3, 0.7) * size)
    if label == "bridge":
        region = (abs(yy - y0) < size * 0.025) & (xx - slope * yy > center) & (xx - slope * yy < center + pitch * 1.4)
        image[region] = 175.0
    elif label == "gap":
        region = (abs(yy - y0) < size * 0.035) & (xx - slope * yy > center - 1) & (xx - slope * yy < center + pitch * 0.6)
        image[region] = 35.0
    image += rng.normal(0.0, 4.0, size=(size, size))
    return np.clip(image, 0, 255).astype(np.uint8)


def _overlay_vectors(seed: int, label: str) -> list[dict[str, float]]:
    vectors = DemoImageService._fixture_vectors(f"TRAIN-LOT-{seed}", f"W{seed % 17:02d}")
    for point in vectors:
        if label == "translation":
            point["dx"] += 2.4
            point["dy"] -= 1.8
        elif label == "radial":
            point["dx"] += 0.22 * point["x"]
            point["dy"] += 0.22 * point["y"]
    return vectors


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _make_datasets(model_root: Path, train_per_class: int, holdout_per_class: int, seed: int) -> tuple[dict, dict]:
    train_root = model_root / "data" / "train"
    holdout_root = model_root / "data" / "holdout"
    datasets = {"train": {}, "holdout": {}}
    for split, count, split_seed, root in (
        ("train", train_per_class, seed, train_root),
        ("holdout", holdout_per_class, seed + 100_000, holdout_root),
    ):
        for modality, labels in CLASSES.items():
            examples = []
            for label_index, label in enumerate(labels):
                for index in range(count):
                    example_seed = split_seed + label_index * 10_000 + index
                    if modality == "sem":
                        path = root / "sem" / f"{label}-{index:03d}.png"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        Image.fromarray(_sem_bitmap(example_seed, label)).save(path)
                        width, height, pixels = DemoImageService._read_grayscale(path)
                        features = DemoImageService._sem_features({
                            "width": width, "height": height, "pixels": pixels,
                        })
                        examples.append({"label": label, "features": features, "path": str(path.relative_to(model_root))})
                    else:
                        vectors = _overlay_vectors(example_seed, label)
                        examples.append({"label": label, "features": DemoImageService._overlay_features(vectors),
                                         "vectors": vectors})
            datasets[split][modality] = examples
            if modality == "overlay":
                _write_json(root / "overlay" / "examples.json", examples)
    return datasets["train"], datasets["holdout"]


def _fit_model(model_root: Path, modality: str, train: list[dict], holdout: list[dict], seed: int) -> dict:
    x_train = np.asarray([row["features"] for row in train], dtype=float)
    y_train = np.asarray([row["label"] for row in train])
    x_holdout = np.asarray([row["features"] for row in holdout], dtype=float)
    y_holdout = np.asarray([row["label"] for row in holdout])
    scaler = StandardScaler().fit(x_train)
    scaled_train = scaler.transform(x_train)
    scaled_holdout = scaler.transform(x_holdout)
    classifier = LogisticRegression(max_iter=250, solver="lbfgs", random_state=seed)
    classifier.fit(scaled_train, y_train)
    train_predictions = classifier.predict(scaled_train)
    holdout_predictions = classifier.predict(scaled_holdout)
    coefficients = classifier.coef_
    intercept = classifier.intercept_
    if len(classifier.classes_) == 2 and coefficients.shape[0] == 1:
        coefficients = np.vstack((-coefficients[0], coefficients[0]))
        intercept = np.asarray([-intercept[0], intercept[0]])
    distances = np.linalg.norm(scaled_train, axis=1)
    threshold = max(1.0, float(np.quantile(distances, 0.995) * 1.15))
    metrics = {
        "train_accuracy": float(accuracy_score(y_train, train_predictions)),
        "holdout_accuracy": float(accuracy_score(y_holdout, holdout_predictions)),
        "train_count": int(len(train)),
        "holdout_count": int(len(holdout)),
        "train_seed": int(seed),
        "holdout_seed": int(seed + 100_000),
    }
    model_dir = model_root / modality
    model_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(model_dir / "model.npz", mean=scaler.mean_, scale=scaler.scale_,
                        coefficients=coefficients, intercept=intercept)
    metadata_base = {
        "artifact_format": "demo-image-logreg-json-npz-v1",
        "modality": modality,
        "model": SEM_MODEL if modality == "sem" else OVERLAY_MODEL,
        "feature_version": _FEATURE_VERSION,
        "classes": [str(value) for value in classifier.classes_],
        "ood_threshold": threshold,
        "metrics": metrics,
        "training": {
            "algorithm": "sklearn.linear_model.LogisticRegression(lbfgs)",
            "train_seed": int(seed),
            "holdout_seed": int(seed + 100_000),
            "train_count": int(len(train)),
            "holdout_count": int(len(holdout)),
            "fixture_version": "synthetic-common-grid-v2",
            "sem_generator": "independent sloped line masks with bridge/gap connectivity; no workbench pixels",
        },
        "provenance": {
            "synthetic_only": True,
            "source": "generated train/holdout fixtures",
            "production_correctness": False,
            "assets_used_for_training": [],
        },
    }
    artifact_hash = hashlib.sha256((model_dir / "model.npz").read_bytes()).hexdigest()
    config_hash = hashlib.sha256(json.dumps(
        metadata_base, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    metadata = {
        **metadata_base,
        "model_version": f"{metadata_base['model']}+weights-{artifact_hash[:12]}-config-{config_hash[:12]}",
        "artifact_hash": artifact_hash,
        "config_hash": config_hash,
    }
    _write_json(model_dir / "model.json", metadata)
    return {"modality": modality, **metrics, "ood_threshold": threshold, "model_dir": str(model_dir)}


def train_models(model_root: str | Path, *, train_per_class: int = 12,
                 holdout_per_class: int = 6, seed: int = 20260921) -> dict:
    if train_per_class < 3 or holdout_per_class < 2:
        raise ValueError("each class needs at least 3 train and 2 holdout examples")
    root = Path(model_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    train, holdout = _make_datasets(root, train_per_class, holdout_per_class, seed)
    report = {
        "artifact_root": str(root),
        "synthetic_only": True,
        "models": [
            _fit_model(root, "sem", train["sem"], holdout["sem"], seed),
            _fit_model(root, "overlay", train["overlay"], holdout["overlay"], seed),
        ],
    }
    _write_json(root / "metrics.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the local synthetic image demo models on CPU")
    parser.add_argument("--model-root", required=True, help="directory for demo model artifacts")
    parser.add_argument("--train-per-class", type=int, default=12)
    parser.add_argument("--holdout-per-class", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()
    print(json.dumps(train_models(args.model_root, train_per_class=args.train_per_class,
                                  holdout_per_class=args.holdout_per_class, seed=args.seed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
