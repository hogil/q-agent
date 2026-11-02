#!/usr/bin/env python3
"""Gated, synthetic-only CPU bridge from ConvNeXtV2 embeddings to the FBM catalog.

No weights are loaded and no model inference is run by default. A model run requires
the parent audit gate environment variable in addition to --run.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tempfile
import sys
import time
from pathlib import Path

from fbm_embedding_catalog_20261030 import (
    CatalogError, EmbeddingSpec, FBMEmbeddingCatalog, REPRESENTATIONS,
    _is_reparse_point, _reject_symlink_parents,
)

DIM = 128
MODEL_ID = "convnextv2_base.fcmae_ft_in22k_in1k_384+fbm_projection"
PREPROCESS = "RGB; unmasked; Resize(384,384,bilinear); ToTensor[0,1]; Normalize(mean=(0.485,0.456,0.406),std=(0.229,0.224,0.225)); GAP(H,W); projection; L2"
AS_OF = "2026-10-30T00:00:00Z"
INCIDENT_SCOPE = ("SYNTHETIC-FBM-RESEARCH-ONLY",)
ACTOR = "synthetic-smoke-actor"


def _progress(stage: str) -> None:
    print(f"[fbm-smoke] {stage}", file=sys.stderr, flush=True)


def _png(arr) -> bytes:
    import numpy as np
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr, "RGB").save(out, format="PNG")
    return out.getvalue()


def _job_memory_cap() -> None:
    """Apply a 2.5 GiB Windows Job Object cap; fail closed outside Windows."""
    if os.name != "nt":
        raise RuntimeError("--run requires Windows Job Object memory enforcement")
    import ctypes
    from ctypes import wintypes

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class EXT_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = EXT_LIMIT()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_JOB_MEMORY
    info.JobMemoryLimit = int(2.5 * 1024**3)
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())


def _load_encoder(backbone_path: Path, head_path: Path,
                  expected_backbone_sha256: str, expected_head_sha256: str):
    """Load only trusted tensor checkpoints; architecture follows grouping_deploy.py."""
    _progress("torch/timm import start")
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    import torch.nn as nn
    import torch.nn.functional as F
    import timm
    _progress("torch/timm import complete")
    def sha(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    if not backbone_path.is_file() or not head_path.is_file():
        raise ValueError("explicit trusted checkpoint paths must exist")
    _progress("checkpoint hashing start")
    bb_hash, head_hash = sha(backbone_path), sha(head_path)
    _progress("checkpoint hashing complete")
    if bb_hash != expected_backbone_sha256.lower() or head_hash != expected_head_sha256.lower():
        raise ValueError("checkpoint SHA-256 mismatch against explicit expected values")
    _progress("backbone model load start")
    bb_sd = torch.load(backbone_path, weights_only=True, map_location="cpu")
    if isinstance(bb_sd, dict) and "state_dict" in bb_sd:
        bb_sd = bb_sd["state_dict"]
    for prefix in ("model.", "backbone.", "module."):
        if isinstance(bb_sd, dict) and any(k.startswith(prefix) for k in bb_sd):
            bb_sd = {(k[len(prefix):] if k.startswith(prefix) else k): v for k, v in bb_sd.items()}
    backbone = timm.create_model("convnextv2_base.fcmae_ft_in22k_in1k_384",
                                 pretrained=False, num_classes=0, global_pool="")
    # forward_features() + manual GAP bypasses the classifier; retain strict
    # validation for every other checkpoint tensor.
    classifier_keys = {"head.fc.weight", "head.fc.bias"}
    model_keys = set(backbone.state_dict())
    bb_sd = {k: v for k, v in bb_sd.items()
             if not (k in classifier_keys and k not in model_keys)}
    backbone.load_state_dict(bb_sd, strict=True)

    _progress("projection model load start")
    head_state = torch.load(head_path, weights_only=True, map_location="cpu")
    proj_sd = head_state["proj"] if isinstance(head_state, dict) and "proj" in head_state else head_state
    proj_sd = {(k[4:] if k.startswith("net.") else k): v for k, v in proj_sd.items()}
    projection = nn.Sequential(nn.Linear(1024, 1024, bias=False), nn.BatchNorm1d(1024),
                               nn.ReLU(inplace=True), nn.Linear(1024, DIM))
    projection.load_state_dict(proj_sd)
    adapt = None
    gamma = 0.0
    if isinstance(head_state, dict) and "adapt" in head_state:
        ad_sd = head_state["adapt"]
        hidden = ad_sd["0.weight"].shape[0]
        adapt = nn.Sequential(nn.Linear(1024, hidden), nn.GELU(), nn.Linear(hidden, 1024))
        adapt.load_state_dict(ad_sd)
        gamma = head_state.get("gamma", 0.0)
    _progress("model load complete")

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.projection = projection
            self.adapt = adapt

        def forward(self, x):
            if self.adapt is not None:
                g = gamma.to(x.device) if torch.is_tensor(gamma) else gamma
                x = x + g * self.adapt(x)
            return self.projection(x)

    return backbone.eval(), Head().eval(), bb_hash, head_hash, F


def _disable_network() -> None:
    """Block Python socket connection attempts for this research smoke process."""
    import socket

    def blocked(*args, **kwargs):
        raise RuntimeError("network access is disabled for the research smoke")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked


def _smoke(backbone_path: Path, head_path: Path,
           expected_backbone_sha256: str, expected_head_sha256: str,
           persist_synthetic: bool = False) -> dict:
    _progress("smoke entry")
    _progress("job memory cap setup start")
    _job_memory_cap()
    _progress("job memory cap setup complete")
    _disable_network()
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"):
        os.environ[name] = "1"
    _progress("numpy/torch/torchvision import start")
    import numpy as np
    import torch
    from PIL import Image
    from torchvision import transforms as T
    _progress("numpy/torch/torchvision import complete")

    backbone, head, bb_hash, head_hash, F = _load_encoder(
        backbone_path, head_path, expected_backbone_sha256, expected_head_sha256)
    backbone.eval()
    head.eval()
    checkpoint_hash = hashlib.sha256((bb_hash + head_hash).encode("ascii")).hexdigest()
    transform = T.Compose([T.Resize((384, 384), interpolation=T.InterpolationMode.BILINEAR),
                           T.ToTensor(), T.Normalize([0.485, 0.456, 0.406],
                                                     [0.229, 0.224, 0.225])])
    rng = np.random.default_rng(41030)
    grid = rng.integers(0, 256, size=(48, 64), dtype=np.uint8)
    yy, xx = np.indices(grid.shape)
    raw_view = np.repeat(grid[:, :, None], 3, axis=2)
    object_view = np.stack((grid, (xx * 3 + yy) % 256,
                            ((xx // 8 + yy // 8) * 31) % 256), axis=2).astype(np.uint8)
    originals = {"raw_fbm": _png(raw_view), "object_id_yield": _png(object_view)}
    queries = {"raw_fbm": _png(np.roll(raw_view, 1, axis=1)),
               "object_id_yield": _png(np.roll(object_view, 1, axis=1))}
    vectors = {}
    _progress("inference start")
    with torch.inference_mode():
        for rep, raw in {**originals, **{f"query_{k}": v for k, v in queries.items()}}.items():
            x = transform(Image.open(io.BytesIO(raw)).convert("RGB")).unsqueeze(0)
            pooled = backbone.forward_features(x).mean(dim=(2, 3))
            vec = F.normalize(head(pooled.float()), dim=1)[0]
            if vec.numel() != DIM or not torch.isfinite(vec).all() or abs(float(vec.norm()) - 1) > 1e-5:
                raise RuntimeError("embedding contract failed (expected 128 finite unit-norm values)")
            vectors[rep] = vec.tolist()
    _progress("inference complete")

    _progress("catalog search phase start")
    def verify_catalog(catalog, *, reopened: bool = False) -> None:
        for rep in sorted(REPRESENTATIONS):
            spec = EmbeddingSpec(MODEL_ID, checkpoint_hash, PREPROCESS, DIM, rep)
            expected_digest = hashlib.sha256(originals[rep]).hexdigest()
            if catalog.get_raw(asset_id=f"synthetic-{rep}", source_revision="v1",
                representation=rep, actor=ACTOR, incident_scope=INCIDENT_SCOPE,
                as_of=AS_OF) != originals[rep]:
                raise RuntimeError("original PNG bytes changed")
            response = catalog.search(query_vector=vectors[f"query_{rep}"], spec=spec, actor=ACTOR,
                incident_scope=INCIDENT_SCOPE, as_of=AS_OF, top_k=2)
            if len(response) != 1 or response[0].asset_id != f"synthetic-{rep}" or response[0].raw_sha256 != expected_digest:
                raise RuntimeError(f"same-representation query/gallery retrieval failed: {rep}")

    def populate_and_verify(root: Path, reopen: bool) -> None:
        catalog = FBMEmbeddingCatalog(root, authorize=lambda actor, incident, op:
                                      actor == ACTOR and incident in INCIDENT_SCOPE and op in {"read", "write"})
        try:
            for rep in sorted(REPRESENTATIONS):
                spec = EmbeddingSpec(MODEL_ID, checkpoint_hash, PREPROCESS, DIM, rep)
                digest = catalog.add(asset_id=f"synthetic-{rep}", source_revision="v1",
                    raw_bytes=originals[rep], vector=vectors[rep], spec=spec,
                    source_time=AS_OF, available_at=AS_OF, incident_id=INCIDENT_SCOPE[0],
                    lot_id=None, wafer_id=None, actor=ACTOR, incident_scope=INCIDENT_SCOPE)
                if digest != hashlib.sha256(originals[rep]).hexdigest():
                    raise RuntimeError("catalog returned unexpected raw-byte digest")
            verify_catalog(catalog)
        finally:
            catalog.close()
        if reopen:
            catalog = FBMEmbeddingCatalog.open_existing(root, authorize=lambda actor, incident, op:
                actor == ACTOR and incident in INCIDENT_SCOPE and op in {"read", "write"})
            try:
                verify_catalog(catalog, reopened=True)
            finally:
                catalog.close()

    persisted_path = None
    if persist_synthetic:
        project_var = Path(__file__).resolve().parents[1] / "var"
        if _is_reparse_point(project_var) or not project_var.is_dir():
            raise CatalogError("persistent mode requires an existing real project var directory")
        var_root = project_var / "fbm-research"
        _reject_symlink_parents(var_root)
        if var_root.exists():
            if _is_reparse_point(var_root) or not var_root.is_dir():
                raise CatalogError("persistent research path must be a real directory")
        else:
            var_root.mkdir(exist_ok=False)
        _reject_symlink_parents(var_root)
        if _is_reparse_point(var_root) or not var_root.is_dir():
            raise CatalogError("persistent research path is unsafe")
        root = var_root / f"cpu-encoder-smoke-{time.time_ns()}-{os.getpid()}"
        populate_and_verify(root, reopen=True)
        persisted_path = str(root.resolve(strict=True))
    else:
        with tempfile.TemporaryDirectory(prefix="qagent-fbm-smoke-") as td:
            populate_and_verify(Path(td) / "catalog", reopen=False)
    _progress("catalog search phase complete")
    return {"status": "pass", "representations": sorted(REPRESENTATIONS),
            "checkpoint_sha256": checkpoint_hash, "dimension": DIM,
            "preprocess": PREPROCESS, "as_of": AS_OF, "scope": list(INCIDENT_SCOPE),
            "synthetic_only": True,
            "representation_note": "approximate renderings from one common synthetic grid/metadata; no real raw-byte semantics assumed",
            "hash_provenance": "hash identifies current local bytes; no authenticity guarantee",
            "temporary_index_removed": not persist_synthetic,
            "persistent_catalog_path": persisted_path,
            "persistence_verified": bool(persist_synthetic)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="check structure without loading weights")
    parser.add_argument("--run", action="store_true", help="run synthetic model/catalog smoke")
    parser.add_argument("--persist-synthetic", action="store_true",
                        help="retain synthetic-only catalog under var/fbm-research and verify reopen")
    parser.add_argument("--backbone", type=Path, help="explicit trusted ConvNeXtV2 checkpoint")
    parser.add_argument("--head", type=Path, help="explicit trusted projection checkpoint")
    parser.add_argument("--expected-backbone-sha256", help="expected digest from trusted local provenance")
    parser.add_argument("--expected-head-sha256", help="expected digest from trusted local provenance")
    args = parser.parse_args()
    if args.run:
        if os.environ.get("QAGENT_FBM_MODEL_LOAD_GATE") != "PARENT_AUDITED_20261030":
            parser.error("model loading is gated pending parent audit/resource approval")
        if not args.backbone or not args.head or not args.expected_backbone_sha256 or not args.expected_head_sha256:
            parser.error("--run requires checkpoint paths and expected SHA-256 values")
        _progress("run dispatch")
        print(json.dumps(_smoke(args.backbone.resolve(strict=True), args.head.resolve(strict=True),
                                args.expected_backbone_sha256, args.expected_head_sha256,
                                persist_synthetic=args.persist_synthetic), indent=2))
        return 0
    if args.self_check:
        assert REPRESENTATIONS == {"raw_fbm", "object_id_yield"} and DIM == 128
        assert "unmasked" in PREPROCESS and "384,384" in PREPROCESS and "RGB" in PREPROCESS
        import numpy as np
        payload = _png(np.zeros((2, 3, 3), dtype=np.uint8))
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        print(json.dumps({"status": "structural-self-check-pass", "weights_loaded": False,
                          "inference_run": False, "synthetic_png_bytes": len(payload),
                          "representations": sorted(REPRESENTATIONS)}, indent=2))
        return 0
    parser.error("choose --self-check or explicitly gated --run")


if __name__ == "__main__":
    raise SystemExit(main())
