#!/usr/bin/env python3
"""Replay persisted synthetic ConvNeXtV2 vectors through dual-view search.

This consumes vectors made by the prior gated encoder run; it does not load a
model or perform inference. The source catalog and run log are checked before
any replay, and only synthetic bytes/vectors are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from research.fbm_embedding_catalog_20261030 import EmbeddingSpec, FBMEmbeddingCatalog
from research.fbm_dual_view_search_20261030 import search_dual_view
from research.fbm_cpu_encoder_smoke_20261030 import (
    ACTOR, AS_OF, DIM, INCIDENT_SCOPE, MODEL_ID, PREPROCESS, _png,
)

RUN_DIR = ROOT / "var" / "fbm_cpu_encoder_persist_20261030_090350_073"
RUN_LOG = RUN_DIR / "stdout.log"
SOURCE_CATALOG = ROOT / "var" / "fbm-research" / "cpu-encoder-smoke-1793318639373779700-204908"
RUN_CHECKPOINT = "92898360d97a0b7583655f6275fbaf8f44ad1af0b9ed7920e974b658b87edaad"
OTHER_SCOPE = ("SYNTHETIC-FBM-RESEARCH-OTHER",)


def _synthetic_sources() -> dict[str, bytes]:
    import numpy as np
    rng = np.random.default_rng(41030)
    grid = rng.integers(0, 256, size=(48, 64), dtype=np.uint8)
    yy, xx = np.indices(grid.shape)
    return {
        "raw_fbm": _png(np.repeat(grid[:, :, None], 3, axis=2)),
        "object_id_yield": _png(np.stack((grid, (xx * 3 + yy) % 256,
            ((xx // 8 + yy // 8) * 31) % 256), axis=2).astype(np.uint8)),
    }


def _read_prior_run() -> tuple[dict, dict[str, tuple[EmbeddingSpec, bytes, tuple[float, ...]]]]:
    meta = json.loads(RUN_LOG.read_text(encoding="utf-8"))
    if (meta.get("status") != "pass" or meta.get("synthetic_only") is not True
            or meta.get("persistence_verified") is not True
            or Path(meta.get("persistent_catalog_path", "")).resolve() != SOURCE_CATALOG.resolve()
            or meta.get("checkpoint_sha256") != RUN_CHECKPOINT
            or meta.get("dimension") != DIM or meta.get("as_of") != AS_OF
            or tuple(meta.get("scope", ())) != INCIDENT_SCOPE):
        raise RuntimeError("prior encoder run log does not match the expected synthetic run")
    sources = _synthetic_sources()
    rows = {}
    db = sqlite3.connect(f"file:{SOURCE_CATALOG / 'catalog.sqlite3'}?mode=ro", uri=True)
    try:
        if (SOURCE_CATALOG / ".fbm-synthetic-research-gallery").read_text(encoding="ascii") != "synthetic-fbm-gallery-v1\n":
            raise RuntimeError("source catalog marker mismatch")
        for rep in ("raw_fbm", "object_id_yield"):
            row = db.execute("""SELECT raw,sha256,vector,dimension,model_id,preprocess_version,
                         checkpoint_sha256,source_time,available_at,incident_id
                         FROM assets WHERE asset_id=? AND revision='v1' AND representation=?""",
                             (f"synthetic-{rep}", rep)).fetchone()
            if row is None:
                raise RuntimeError(f"persisted source is missing {rep}")
            raw, digest, blob, dim, model_id, prep, checkpoint, source_time, available, incident = row
            raw = bytes(raw)
            if (raw != sources[rep] or hashlib.sha256(raw).hexdigest() != digest
                    or dim != DIM or model_id != MODEL_ID or prep != PREPROCESS
                    or checkpoint != RUN_CHECKPOINT
                    or source_time != "2026-10-30T00:00:00.000000Z"
                    or available != "2026-10-30T00:00:00.000000Z" or incident != INCIDENT_SCOPE[0]):
                raise RuntimeError(f"persisted source/provenance assertion failed for {rep}")
            import struct
            vector = struct.unpack(f"!{DIM}d", bytes(blob))
            if abs(sum(v*v for v in vector) ** .5 - 1.0) > 1e-5:
                raise RuntimeError(f"stored vector is not unit norm for {rep}")
            rows[rep] = (EmbeddingSpec(model_id, checkpoint, prep, dim, rep), raw, vector)
    finally:
        db.close()
    return meta, rows


def run() -> dict:
    meta, rows = _read_prior_run()
    auth = lambda actor, incident, op: actor == ACTOR and incident in (*INCIDENT_SCOPE, *OTHER_SCOPE) and op in {"read", "write"}
    with tempfile.TemporaryDirectory(prefix="qagent-fbm-dual-replay-") as tmp:
        catalog = FBMEmbeddingCatalog(Path(tmp) / "gallery", authorize=auth)
        try:
            # Replay the two persisted model vectors as one paired synthetic asset.
            for rep, (spec, raw, vec) in rows.items():
                catalog.add(asset_id="synthetic-pair", source_revision="v1", raw_bytes=raw,
                    vector=vec, spec=spec, source_time=AS_OF, available_at=AS_OF,
                    incident_id=INCIDENT_SCOPE[0], lot_id="LOT-SYN", wafer_id="WAFER-SYN",
                    actor=ACTOR, incident_scope=INCIDENT_SCOPE)
            raw_spec, _, raw_vec = rows["raw_fbm"]
            obj_spec, _, obj_vec = rows["object_id_yield"]
            found = search_dual_view(catalog=catalog, raw_query_vector=raw_vec, raw_spec=raw_spec,
                object_query_vector=obj_vec, object_spec=obj_spec, actor=ACTOR,
                incident_scope=INCIDENT_SCOPE, as_of=AS_OF, top_k_per_view=1)
            if len(found.items) != 1 or found.items[0].pair_status != "paired":
                raise RuntimeError("same-scope dual-view replay did not pair the persisted synthetic record")
            empty = search_dual_view(catalog=catalog, raw_query_vector=raw_vec, raw_spec=raw_spec,
                object_query_vector=obj_vec, object_spec=obj_spec, actor=ACTOR,
                incident_scope=OTHER_SCOPE, as_of=AS_OF, top_k_per_view=1)
            if empty.items or empty.raw_fbm_eligible_count or empty.object_id_yield_eligible_count:
                raise RuntimeError("scope isolation replay returned out-of-scope candidates")
            missing_spec = EmbeddingSpec(obj_spec.model_id, "0" * 64, obj_spec.preprocess_version, DIM, "object_id_yield")
            missing = search_dual_view(catalog=catalog, raw_query_vector=raw_vec, raw_spec=raw_spec,
                object_query_vector=obj_vec, object_spec=missing_spec, actor=ACTOR,
                incident_scope=INCIDENT_SCOPE, as_of=AS_OF, top_k_per_view=1)
            if (not missing.items or missing.object_id_yield_eligible_count != 0
                    or missing.items[0].pair_status != "not_in_returned_top_k_unknown"):
                raise RuntimeError("missing-view uncertainty was not preserved")
            # Add two same-view aliases to create an explicit top-k truncation case.
            for i in range(2):
                catalog.add(asset_id=f"synthetic-raw-alias-{i}", source_revision="v1",
                    raw_bytes=rows["raw_fbm"][1] + bytes([i+1]), vector=raw_vec, spec=raw_spec,
                    source_time=AS_OF, available_at=AS_OF, incident_id=INCIDENT_SCOPE[0],
                    lot_id=f"LOT-ALIAS-{i}", wafer_id=f"WAFER-ALIAS-{i}", actor=ACTOR,
                    incident_scope=INCIDENT_SCOPE)
            truncated = search_dual_view(catalog=catalog, raw_query_vector=raw_vec, raw_spec=raw_spec,
                object_query_vector=obj_vec, object_spec=obj_spec, actor=ACTOR,
                incident_scope=INCIDENT_SCOPE, as_of=AS_OF, top_k_per_view=1)
            if not truncated.raw_fbm_truncated or truncated.raw_fbm_eligible_count != 3:
                raise RuntimeError("raw-view top-k truncation was not reported")
            return {
                "status": "pass", "vector_mode": "persisted_cached_vectors_no_current_process_inference",
                "source_run_log": str(RUN_LOG.resolve()), "source_catalog": str(SOURCE_CATALOG.resolve()),
                "model_id": MODEL_ID, "checkpoint_sha256": RUN_CHECKPOINT, "dimension": DIM,
                "representations": sorted(rows), "source_png_sha256": {k: hashlib.sha256(v[1]).hexdigest() for k,v in rows.items()},
                "source_assertion": "regenerated deterministic synthetic PNG bytes matched persisted catalog bytes and hashes",
                "checks": {"paired_in_primary_scope": True, "second_scope_isolated": True,
                           "missing_view_marked_unknown": True, "truncated_topk_explicit": True},
                "limitations": ["Checkpoint provenance is asserted by the local prior-run log and stored catalog metadata; hashes do not authenticate checkpoint origin.",
                    "Vectors were read from the persisted catalog; this run did not load weights or repeat inference.",
                    "The replay query vectors are the gallery vectors themselves: same-vector self-match; distinct query image inference not tested.",
                    "Both views are approximate renderings from one synthetic grid; no real wafer, object-ID, yield, or production semantics are validated.",
                    "RRF verifies rank-combination mechanics only; no retrieval accuracy or completeness claim is made."]}
        finally:
            catalog.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="verify provenance and replay cached synthetic vectors")
    args = parser.parse_args()
    if not args.run:
        parser.error("choose --run")
    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
