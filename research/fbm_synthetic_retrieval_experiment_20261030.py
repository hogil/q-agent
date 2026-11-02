#!/usr/bin/env python3
"""Gated synthetic multi-candidate retrieval probe for the local FBM encoder.

The two image representations are paired renders of the same synthetic wafer.
They do not claim to model production object IDs, measures, or yield semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fbm_cpu_encoder_smoke_20261030 as smoke
from fbm_embedding_catalog_20261030 import (
    EmbeddingSpec, FBMEmbeddingCatalog, _is_reparse_point, _reject_symlink_parents,
)

CLASSES = ("center", "edge", "ring", "random")
REPRESENTATIONS = ("raw_fbm", "object_id_yield")
SEED_BASE = 20261030
DEFECT_COUNT = 10
DEFECT_RADIUS = 3
SIZE = 192
RADIAL_BANDS = {"center": (0.0, 20.0), "ring": (42.0, 52.0),
                "edge": (76.0, 86.0), "random": (0.0, 86.0)}
ID_SEED_OFFSET = 500_000
AS_OF = "2026-10-30T00:00:00Z"
SCOPE = ("SYNTHETIC-FBM-RETRIEVAL-ONLY",)
ACTOR = "synthetic-retrieval-actor"


def _render(seed: int, label: str):
    import numpy as np
    rng = np.random.default_rng(seed)
    if label not in RADIAL_BANDS:
        raise ValueError("unknown pattern class")
    # Independent uniform-area locations within each radial band, rounded to pixels.
    # Exact center-pixel collisions are resampled; rendered disk overlaps remain allowed.
    low, high = RADIAL_BANDS[label]
    coords: list[tuple[int, int]] = []
    while len(coords) < DEFECT_COUNT:
        theta = float(rng.uniform(0, 2 * np.pi))
        radius = math.sqrt(float(rng.uniform(low * low, high * high)))
        x = int(round(96 + radius * math.cos(theta)))
        y = int(round(96 + radius * math.sin(theta)))
        if (y, x) not in coords:
            coords.append((y, x))
    yy, xx = np.ogrid[:SIZE, :SIZE]
    mask = np.zeros((SIZE, SIZE), dtype=np.uint8)
    for y, x in coords:
        mask[(yy - y) ** 2 + (xx - x) ** 2 <= DEFECT_RADIUS ** 2] = 255
    # Paired views share the exact base defect mask, but encode it differently.
    raw = np.repeat(mask[:, :, None], 3, axis=2)
    # Synthetic proxy only: independently assign known IDs A/B and unknown ID
    # to defects; normal/yield background has its own distinct color.
    id_seed = seed + ID_SEED_OFFSET
    id_rng = np.random.default_rng(id_seed)
    assignments = np.array(["known_A"] * 4 + ["known_B"] * 4 + ["unknown"] * 2)
    id_rng.shuffle(assignments)
    colors = {"normal_yield": (24, 40, 56), "known_A": (230, 50, 45),
              "known_B": (35, 210, 225), "unknown": (235, 170, 35)}
    object_view = np.empty((SIZE, SIZE, 3), dtype=np.uint8)
    object_view[:, :] = colors["normal_yield"]
    nearest = np.full((SIZE, SIZE), np.inf)
    for (y, x), object_id in zip(coords, assignments):
        distance = (yy - y) ** 2 + (xx - x) ** 2
        closer = (distance <= DEFECT_RADIUS ** 2) & (distance < nearest)
        object_view[closer] = colors[str(object_id)]
        nearest[closer] = distance[closer]
    overlap_pairs = sum((y1-y2)**2 + (x1-x2)**2 <= (2 * DEFECT_RADIUS) ** 2
                        for i, (y1, x1) in enumerate(coords) for y2, x2 in coords[i+1:])
    metadata = {"coordinates": coords, "id_seed": id_seed,
                "id_assignments": [str(x) for x in assignments],
                "defect_overlap_pairs": int(overlap_pairs),
                "rendered_defect_pixel_count": int(mask.sum() // 255)}
    return raw, object_view, metadata


def _png(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


def _seed(label_index: int, split: str, item_index: int) -> int:
    split_index = 0 if split == "gallery" else 1
    return SEED_BASE + label_index * 10_000 + split_index * 100 + item_index


def _build_items():
    """Return 16 independent wafer inputs, each with paired PNG views."""
    items = []
    for li, label in enumerate(CLASSES):
        for split in ("gallery", "query"):
            for ix in range(2):
                seed = _seed(li, split, ix)
                raw, obj, metadata = _render(seed, label)
                items.append({"asset_id": f"{split}-{label}-{ix}", "label": label,
                              "split": split, "seed": seed,
                              **metadata,
                              "bytes": {"raw_fbm": _png(raw), "object_id_yield": _png(obj)}})
    all_hashes = [hashlib.sha256(item["bytes"][rep]).hexdigest()
                  for item in items for rep in REPRESENTATIONS]
    if len(all_hashes) != len(set(all_hashes)):
        raise RuntimeError("independent wafer views contain duplicate PNG bytes")
    return items


def _gallery_items(items):
    return tuple(item for item in items if item["split"] == "gallery")


def _aggregate(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["query_label"], []).append(row)
    def metrics(selected):
        n = len(selected)
        return {"queries": n,
                "top1_correct": sum(bool(r["ranking"]) and r["ranking"][0]["label"] == r["query_label"] for r in selected),
                "top3_correct": sum(any(x["label"] == r["query_label"] for x in r["ranking"][:3]) for r in selected),
                "top1_accuracy": (sum(bool(r["ranking"]) and r["ranking"][0]["label"] == r["query_label"] for r in selected) / n if n else None),
                "top3_accuracy": (sum(any(x["label"] == r["query_label"] for x in r["ranking"][:3]) for r in selected) / n if n else None)}
    return {"by_query_class": {label: metrics(rows_) for label, rows_ in groups.items()},
            "overall": metrics(rows)}


def _resource_guard() -> dict:
    if os.name != "nt":
        raise RuntimeError("--run requires Windows Job Object enforcement")
    import ctypes
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MEMORYSTATUSEX(); status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    available = int(status.ullAvailPhys)
    if available < 5 * 1024**3:
        raise RuntimeError(f"pre-run guard: need >=5 GiB available physical RAM; got {available}")
    commit_available = int(status.ullAvailPageFile)
    if commit_available < 6 * 1024**3:
        raise RuntimeError(f"pre-run guard: need >=6 GiB available commit; got {commit_available}")
    var_root = Path(__file__).resolve().parents[1] / "var"
    if not var_root.is_dir() or var_root.is_symlink():
        raise RuntimeError("pre-run guard: existing real project var directory required")
    free = shutil.disk_usage(var_root).free
    if free < 20 * 1024**3:
        raise RuntimeError(f"pre-run guard: need >=20 GiB free on output volume; got {free}")
    return {"available_physical_ram_bytes": available,
            "available_commit_bytes": commit_available, "free_disk_bytes": free,
            "minimum_available_physical_ram_bytes": 5 * 1024**3,
            "minimum_available_commit_bytes": 6 * 1024**3,
            "minimum_free_disk_bytes": 20 * 1024**3}


def _run(args) -> dict:
    # Resource checks and unique output reservation happen before model imports/loads.
    resources = _resource_guard()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = os.environ["BLIS_NUM_THREADS"] = "1"
    smoke._job_memory_cap()
    smoke._disable_network()
    var_root = Path(__file__).resolve().parents[1] / "var"
    parent = var_root / "fbm-research"
    _reject_symlink_parents(parent)
    if _is_reparse_point(parent) or not parent.is_dir():
        raise RuntimeError("existing real var/fbm-research directory required")
    output_root = parent / f"retrieval-{time.time_ns()}-{os.getpid()}"
    _reject_symlink_parents(output_root)
    output_root.mkdir(exist_ok=False)
    catalog_root = output_root / "catalog"
    backbone, head, bb_hash, head_hash, F = smoke._load_encoder(
        args.backbone.resolve(strict=True), args.head.resolve(strict=True),
        args.expected_backbone_sha256, args.expected_head_sha256)
    import torch
    from PIL import Image
    from torchvision import transforms as T
    checkpoint_hash = hashlib.sha256((bb_hash + head_hash).encode("ascii")).hexdigest()
    spec_for = lambda rep: EmbeddingSpec(smoke.MODEL_ID, checkpoint_hash, smoke.PREPROCESS, smoke.DIM, rep)
    transform = T.Compose([T.Resize((384, 384), interpolation=T.InterpolationMode.BILINEAR),
                           T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    items = _build_items()
    embeddings = {}
    with torch.inference_mode():
        for item in items:
            for rep in REPRESENTATIONS:
                x = transform(Image.open(io.BytesIO(item["bytes"][rep])).convert("RGB")).unsqueeze(0)
                pooled = backbone.forward_features(x).mean(dim=(2, 3))
                vec = F.normalize(head(pooled.float()), dim=1)[0]
                if vec.numel() != smoke.DIM or not torch.isfinite(vec).all() or abs(float(vec.norm()) - 1) > 1e-5:
                    raise RuntimeError("encoder vector contract failed")
                embeddings[(item["asset_id"], rep)] = vec.tolist()
    catalog = FBMEmbeddingCatalog(catalog_root, authorize=lambda a, i, op:
        a == ACTOR and i in SCOPE and op in {"read", "write"})
    try:
        for item in _gallery_items(items):
            for rep in REPRESENTATIONS:
                catalog.add(asset_id=item["asset_id"], source_revision="v1",
                    raw_bytes=item["bytes"][rep], vector=embeddings[(item["asset_id"], rep)],
                    spec=spec_for(rep), source_time=AS_OF, available_at=AS_OF,
                    incident_id=SCOPE[0], lot_id=None, wafer_id=None,
                    actor=ACTOR, incident_scope=SCOPE)
        rows = {rep: [] for rep in REPRESENTATIONS}
        for item in items:
            if item["split"] != "query":
                continue
            for rep in REPRESENTATIONS:
                response = catalog.search(query_vector=embeddings[(item["asset_id"], rep)],
                    spec=spec_for(rep), actor=ACTOR, incident_scope=SCOPE, as_of=AS_OF,
                    top_k=8, exclude_asset_id=item["asset_id"],
                    exclude_sha256=hashlib.sha256(item["bytes"][rep]).hexdigest())
                ranking = [{"rank": rank, "asset_id": hit.asset_id,
                            "label": hit.asset_id.split("-")[1], "similarity": hit.similarity,
                            "seed": next(x["seed"] for x in _gallery_items(items) if x["asset_id"] == hit.asset_id),
                            "raw_sha256": hit.raw_sha256}
                           for rank, hit in enumerate(response, 1)]
                expected_gallery_ids = {x["asset_id"] for x in _gallery_items(items)}
                if (len(ranking) != 8 or response.eligible_count != 8
                        or {r["asset_id"] for r in ranking} != expected_gallery_ids
                        or any(r["asset_id"] == item["asset_id"] for r in ranking)):
                    raise RuntimeError("retrieval candidate set/self-exclusion contract failed")
                rows[rep].append({"query_asset_id": item["asset_id"], "query_label": item["label"],
                                  "query_seed": item["seed"], "representation": rep,
                                  "ranking": ranking})
    finally:
        catalog.close()
    result = {"status": "synthetic_retrieval_complete", "experiment_scope": "small synthetic functionality probe",
              "claims": {"statistical_performance": False, "real_world_performance": False,
                         "object_id_measure_yield_semantics": False},
              "model_id": smoke.MODEL_ID, "checkpoint_sha256": checkpoint_hash,
              "backbone_sha256": bb_hash, "head_sha256": head_hash,
              "preprocess": smoke.PREPROCESS, "dimension": smoke.DIM,
              "resource_snapshot_before_model_load": resources,
              "design": {"classes": list(CLASSES), "gallery_per_class": 2, "query_per_class": 2,
                         "gallery_wafers": 8, "query_wafers": 8,
                         "representations": list(REPRESENTATIONS), "defects_per_wafer": DEFECT_COUNT,
                         "defect_radius_pixels": DEFECT_RADIUS,
                         "radial_bands_pixels_before_discretization": RADIAL_BANDS,
                         "seed_base": SEED_BASE, "id_assignment_seed_offset": ID_SEED_OFFSET,
                         "defect_pixel_distribution": "independent uniform-area sampling within class radial band; integer-pixel rounding",
                         "defect_center_collision_policy": "resample exact duplicate center pixels",
                         "defect_disk_overlap_policy": "allowed; nearest-center ID color wins in object proxy",
                         "seeds": [x["seed"] for x in items],
                         "paired_renders_from_same_base_wafer": True,
                         "independent_gallery_query_inputs": True,
                         "random_pattern_spatially_independent": True},
              "object_id_yield_proxy_note": "Synthetic per-wafer known_A/known_B/unknown defect IDs and normal_yield background colors; not actual CNN, internal IDs, measures, yield mappings, or production rendering.",
              "wafer_manifest": [{"asset_id": x["asset_id"], "label": x["label"],
                                  "split": x["split"], "seed": x["seed"],
                                  "defect_count": len(x["coordinates"]),
                                  "id_assignment_seed": x["id_seed"],
                                  "id_assignment_counts": {k: x["id_assignments"].count(k) for k in ("known_A", "known_B", "unknown")},
                                  "overlap_pairs": x["defect_overlap_pairs"],
                                  "rendered_defect_pixel_count": x["rendered_defect_pixel_count"],
                                  "raw_fbm_sha256": hashlib.sha256(x["bytes"]["raw_fbm"]).hexdigest(),
                                  "object_id_yield_sha256": hashlib.sha256(x["bytes"]["object_id_yield"]).hexdigest()}
                                 for x in items],
              "results": {rep: {"queries": rows[rep], "metrics": _aggregate(rows[rep])} for rep in REPRESENTATIONS},
              "output_directory": str(output_root.resolve())}
    out = output_root / "retrieval_results.json"
    with out.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


def _self_check() -> dict:
    import numpy as np
    items = _build_items()
    assert len(items) == 16
    assert len({x["seed"] for x in items}) == 16
    assert all(len(x["coordinates"]) == DEFECT_COUNT for x in items)
    gallery = _gallery_items(items)
    queries = tuple(x for x in items if x["split"] == "query")
    assert len(gallery) == len(queries) == 8
    assert {x["split"] for x in gallery} == {"gallery"}
    assert {x["split"] for x in queries} == {"query"}
    for item in items:
        raw, obj, metadata = _render(item["seed"], item["label"])
        assert raw.shape == obj.shape == (SIZE, SIZE, 3)
        assert item["bytes"]["raw_fbm"] != item["bytes"]["object_id_yield"]
        assert metadata["coordinates"] == item["coordinates"]
        assert len(metadata["id_assignments"]) == DEFECT_COUNT
        assert metadata["id_assignments"].count("known_A") == 4
        assert metadata["id_assignments"].count("known_B") == 4
        assert metadata["id_assignments"].count("unknown") == 2
        low, high = RADIAL_BANDS[item["label"]]
        radii = [math.hypot(y - 96, x - 96) for y, x in item["coordinates"]]
        assert all(low - 1 <= radius <= high + 1 for radius in radii)
        from PIL import Image
        raw_pixels = np.asarray(Image.open(io.BytesIO(item["bytes"]["raw_fbm"])))[:, :, 0] > 0
        object_pixels = np.asarray(Image.open(io.BytesIO(item["bytes"]["object_id_yield"])))
        assert np.array_equal(raw_pixels, np.any(object_pixels != np.array([24, 40, 56]), axis=2))

    # Exercise the same catalog path without loading weights: only gallery assets
    # are inserted, and every query sees exactly those eight gallery candidates.
    rows = {rep: [] for rep in REPRESENTATIONS}
    with tempfile.TemporaryDirectory(prefix="qagent-fbm-retrieval-check-") as td:
        cat = FBMEmbeddingCatalog(Path(td) / "catalog", authorize=lambda a, i, op:
            a == ACTOR and i in SCOPE and op in {"read", "write"})
        try:
            checkpoint_hash = "0" * 64
            specs = {rep: EmbeddingSpec("synthetic-check", checkpoint_hash, "self-check", 4, rep)
                     for rep in REPRESENTATIONS}
            def toy_vector(label):
                return [float(label == wanted) for wanted in CLASSES]
            for item in gallery:
                for rep in REPRESENTATIONS:
                    cat.add(asset_id=item["asset_id"], source_revision="v1", raw_bytes=item["bytes"][rep],
                        vector=toy_vector(item["label"]), spec=specs[rep], source_time=AS_OF,
                        available_at=AS_OF, incident_id=SCOPE[0], lot_id=None, wafer_id=None,
                        actor=ACTOR, incident_scope=SCOPE)
            gallery_ids = {x["asset_id"] for x in gallery}
            for item in queries:
                for rep in REPRESENTATIONS:
                    response = cat.search(query_vector=toy_vector(item["label"]), spec=specs[rep],
                        actor=ACTOR, incident_scope=SCOPE, as_of=AS_OF, top_k=8,
                        exclude_asset_id=item["asset_id"],
                        exclude_sha256=hashlib.sha256(item["bytes"][rep]).hexdigest())
                    assert response.eligible_count == len(response) == 8
                    assert {hit.asset_id for hit in response} == gallery_ids
                    assert all(hit.asset_id.startswith("gallery-") for hit in response)
                    rows[rep].append({"query_label": item["label"],
                        "ranking": [{"label": hit.asset_id.split("-")[1]} for hit in response]})
        finally:
            cat.close()
    metrics = {rep: _aggregate(rows[rep])["overall"] for rep in REPRESENTATIONS}
    assert all(v["queries"] == 8 and v["top1_correct"] == 8 and v["top3_correct"] == 8
               for v in metrics.values())
    return {"status": "synthetic_generation_and_rank_aggregation_pass", "weights_loaded": False,
            "inference_run": False, "wafer_inputs": len(items), "paired_views": len(items) * 2,
            "gallery_only_catalog_candidates": len(gallery),
            "query_wafer_inputs_not_indexed": len(queries),
            "unique_png_hashes": len(items) * 2, "seed_base": SEED_BASE,
            "class_radial_bands_verified": RADIAL_BANDS,
            "object_id_assignment_counts_per_wafer": {"known_A": 4, "known_B": 4, "unknown": 2},
            "rank_aggregation_catalog_path": metrics}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-check", action="store_true")
    p.add_argument("--run", action="store_true", help="explicitly load local encoder and run the synthetic retrieval probe")
    p.add_argument("--backbone", type=Path)
    p.add_argument("--head", type=Path)
    p.add_argument("--expected-backbone-sha256")
    p.add_argument("--expected-head-sha256")
    a = p.parse_args()
    if a.self_check:
        print(json.dumps(_self_check(), indent=2)); return 0
    if not a.run:
        p.error("choose --self-check or explicitly gated --run")
    if os.environ.get("QAGENT_FBM_MODEL_LOAD_GATE") != "PARENT_AUDITED_20261030":
        p.error("model loading requires QAGENT_FBM_MODEL_LOAD_GATE=PARENT_AUDITED_20261030")
    if not (a.backbone and a.head and a.expected_backbone_sha256 and a.expected_head_sha256):
        p.error("--run requires explicit checkpoint paths and caller-pinned SHA-256 values")
    print(json.dumps(_run(a), indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
