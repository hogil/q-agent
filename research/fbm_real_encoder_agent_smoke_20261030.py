#!/usr/bin/env python3
"""Opt-in synthetic-only CPU encoder -> FBM catalog -> Agent callback smoke.

Default mode performs only structural checks. A real local checkpoint run requires
explicit checkpoint hashes, --run, and the parent audit gate. No site data, GPU,
network access, or persistent catalog is used.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from skill_loader import freeze
from research.fbm_embedding_catalog_20261030 import EmbeddingSpec, FBMEmbeddingCatalog, REPRESENTATIONS
from research.fbm_agent_catalog_adapter_synthetic_20261030 import SyntheticFBMAgentCatalogAdapter
import agent
from test_agent import ScriptedClient, answer, judge, plan

_BASE_PATH = Path(__file__).with_name("fbm_cpu_encoder_smoke_20261030.py")
_BASE_SPEC = importlib.util.spec_from_file_location("fbm_cpu_encoder_smoke_20261030", _BASE_PATH)
_BASE = importlib.util.module_from_spec(_BASE_SPEC)
assert _BASE_SPEC and _BASE_SPEC.loader
_BASE_SPEC.loader.exec_module(_BASE)

DIM = _BASE.DIM
PREPROCESS = _BASE.PREPROCESS
AS_OF = "2026-03-31"
ACTOR = "synthetic-local-smoke-actor"
INCIDENT_NUMBER = "SYN-2026-01"
MODEL_VERSION = "synthetic-local-smoke"


def _steps(representation: str, incident_id: str, lot_id: str, wafer_id: str):
    return [
        ("router", plan(tool="find_incidents", arguments={"incident_number": INCIDENT_NUMBER},
                         search_mode="sql_exact")),
        ("router", plan(stage="tools", tool="list_incident_lots",
                         arguments={"page_size": 100, "offset": 0})),
        ("router", plan(stage="tools", tool="list_incident_wafers",
                         arguments={"page_size": 100, "offset": 0})),
        ("router", plan(stage="tools", tool="search_similar_fbm", arguments={
            "source_incident_id": incident_id, "lot_id": lot_id, "wafer_id": wafer_id,
            "representation": representation, "top_k": 10})),
        ("judge", judge), ("answer", answer),
    ]


def _synthetic_settings(root: Path) -> Settings:
    data = copy.deepcopy(load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / "demo.yaml").data)
    data["paths"].update(data_root=str(root), golden_file=str(root / "golden.jsonl"),
                         skill_lock_file=str(root / "release.lock.json"))
    data["database"]["sqlite_file"] = str(root / "incidents.sqlite")
    data["meetings"]["sqlite_file"] = str(root / "meetings.sqlite")
    data["relations"].update(source_completeness="declared_complete",
                              wafer_source_completeness="declared_complete",
                              wafer_scope="incident_affected")
    data["fbm_search"] = {"enabled": True, "top_k": 10}
    settings = Settings(data, ())
    freeze(settings=settings)
    generate(settings, include_goldens=False)
    # The generated fixture's declared count must match its synthetic membership rows.
    import sqlite3
    conn = sqlite3.connect(data["database"]["sqlite_file"])
    try:
        conn.execute("UPDATE demo_incident SET affected_wafer_count = "
                     "(SELECT COUNT(*) FROM demo_wafer_list w "
                     "WHERE w.accident_ref = demo_incident.accident_pk)")
        conn.commit()
    finally:
        conn.close()
    return settings


def _make_images():
    import numpy as np
    rng = np.random.default_rng(41030)
    images = {}
    for rep_index, rep in enumerate(sorted(REPRESENTATIONS)):
        # Independent query/gallery canvases: no shared source image or copied bytes.
        query = rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
        gallery = rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
        if rep_index:
            query[:, :, 0] = (query[:, :, 0].astype("uint16") + 53).astype("uint8")
            gallery[:, :, 2] = (gallery[:, :, 2].astype("uint16") + 91).astype("uint8")
        images[rep] = {"query": _BASE._png(query), "gallery": _BASE._png(gallery)}
    return images


def _encode_images(backbone_path: Path, head_path: Path,
                   expected_backbone_sha256: str, expected_head_sha256: str,
                   images: dict[str, dict[str, bytes]]):
    import torch
    from PIL import Image
    from torchvision import transforms as T

    backbone, head, bb_hash, head_hash, F = _BASE._load_encoder(
        backbone_path, head_path, expected_backbone_sha256, expected_head_sha256)
    transform = T.Compose([T.Resize((384, 384), interpolation=T.InterpolationMode.BILINEAR),
                           T.ToTensor(), T.Normalize([0.485, 0.456, 0.406],
                                                     [0.229, 0.224, 0.225])])
    vectors = {}
    with torch.inference_mode():
        for rep, pair in images.items():
            for role, raw in pair.items():
                tensor = transform(Image.open(io.BytesIO(raw)).convert("RGB")).unsqueeze(0)
                pooled = backbone.forward_features(tensor).mean(dim=(2, 3))
                vector = F.normalize(head(pooled.float()), dim=1)[0]
                if (vector.numel() != DIM or not torch.isfinite(vector).all()
                        or abs(float(vector.norm()) - 1) > 1e-5):
                    raise RuntimeError("embedding contract failed")
                vectors[(rep, role)] = vector.tolist()
    checkpoint_hash = hashlib.sha256((bb_hash + head_hash).encode("ascii")).hexdigest()
    return vectors, checkpoint_hash


def _run_agent(settings: Settings, callback, representation: str,
               incident_id: str, lot_id: str, wafer_id: str):
    client = ScriptedClient(_steps(representation, incident_id, lot_id, wafer_id))
    settings.data["runtime"]["max_retries"] = 0
    with patch.object(agent, "RoleClient", return_value=client):
        result = agent.run(settings, "합성 이미지에서 유사 FBM wafer를 검색", ACTOR,
                           as_of=AS_OF, requested_tools=["search_similar_fbm"],
                           fbm_search_query=callback)
    return result, client


def _execute(backbone: Path, head: Path, backbone_sha: str, head_sha: str) -> dict:
    _BASE._progress("CPU job cap and socket restriction setup")
    _BASE._job_memory_cap()
    _BASE._disable_network()
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"):
        os.environ[name] = "1"
    images = _make_images()
    vectors, checkpoint_hash = _encode_images(backbone, head, backbone_sha, head_sha, images)
    with tempfile.TemporaryDirectory(prefix="qagent-fbm-agent-smoke-") as td:
        root = Path(td)
        demo_root = root / "demo"
        demo_root.mkdir()
        settings = _synthetic_settings(demo_root)
        import sqlite3
        conn = sqlite3.connect(settings.data["database"]["sqlite_file"])
        try:
            row = conn.execute("SELECT accident_pk FROM demo_incident WHERE accident_no=?",
                               (INCIDENT_NUMBER,)).fetchone()
            if row is None:
                raise RuntimeError("synthetic incident fixture unavailable")
            incident_id = row[0]
            memberships = conn.execute(
                "SELECT lot_no, wafer_no FROM demo_wafer_list WHERE accident_ref=? ORDER BY lot_no, wafer_no",
                (incident_id,)).fetchall()
        finally:
            conn.close()
        if len(memberships) < 2:
            raise RuntimeError("synthetic incident needs two registered wafers")
        query_lot, query_wafer = memberships[0]
        gallery_lot, gallery_wafer = memberships[1]
        scope = (incident_id,)
        catalog_path = root / "catalog"
        catalog = FBMEmbeddingCatalog(catalog_path, authorize=lambda actor, incident, op:
                                      actor == ACTOR and incident in scope and op in {"read", "write"})
        specs = {rep: EmbeddingSpec(MODEL_VERSION, checkpoint_hash, PREPROCESS, DIM, rep)
                 for rep in sorted(REPRESENTATIONS)}
        query_assets = {}
        query_identities = {}
        try:
            for rep in sorted(REPRESENTATIONS):
                query_asset = f"synthetic-query-{rep}"
                gallery_asset = f"synthetic-gallery-{rep}"
                query_assets[rep] = query_asset
                query_identities[rep] = (incident_id, query_lot, query_wafer)
                for asset, role, lot, wafer in (
                    (query_asset, "query", query_lot, query_wafer),
                    (gallery_asset, "gallery", gallery_lot, gallery_wafer),
                ):
                    catalog.add(asset_id=asset, source_revision="r1", raw_bytes=images[rep][role],
                                vector=vectors[(rep, role)], spec=specs[rep],
                                source_time="2026-03-30T12:00:00Z", available_at="2026-03-30T12:00:00Z",
                                incident_id=incident_id, lot_id=lot, wafer_id=wafer,
                                actor=ACTOR, incident_scope=scope)

            def query_resolver(query_tuple, rep):
                if tuple(query_tuple) != query_identities[rep]:
                    raise ValueError("query resolver received an unexpected synthetic wafer")
                record = catalog.get_asset(asset_id=query_assets[rep], source_revision="r1",
                    representation=rep, actor=ACTOR, incident_scope=scope, as_of=AS_OF,
                    timezone_name="Asia/Seoul")
                return {"incident_id": record.incident_id, "lot_id": record.lot_id,
                    "wafer_id": record.wafer_id, "asset_id": record.asset_id,
                    "revision": record.source_revision, "raw_bytes": record.raw_bytes,
                    "available_at": record.available_at, "sha256": record.sha256,
                    "synthetic_only": True}
            query_resolver.synthetic_only = True

            def cached_encoder(raw, spec):
                rep = spec.representation
                if raw != images[rep]["query"]:
                    raise ValueError("encoder received bytes outside the synthetic query cache")
                return {"vector": vectors[(rep, "query")],
                        "cache_status": "cached_same_process_model_vector"}

            adapter = SyntheticFBMAgentCatalogAdapter(catalog=catalog, specs=specs,
                model_version=MODEL_VERSION, query_resolver=query_resolver,
                encoder=cached_encoder, timezone_name="Asia/Seoul")

            reports = {}
            query_wafer_id = query_wafer
            for rep in sorted(REPRESENTATIONS):
                requested_rep = "object_id_yield_fbm" if rep == "object_id_yield" else rep
                result, _ = _run_agent(settings, adapter, requested_rep,
                                       incident_id, query_lot, query_wafer_id)
                evidence = next((entry["result"] for entry in result.get("evidence", [])
                                 if entry.get("source") == "search_similar_fbm"), None)
                if result.get("status") != "answered" or not evidence:
                    raise RuntimeError("scripted Agent failed to retain validated FBM evidence")
                gallery_hits = [item for item in evidence["items"]
                                if item["asset_id"] == f"synthetic-gallery-{rep}"
                                and item["wafer_id"] == gallery_wafer]
                if not gallery_hits:
                    raise RuntimeError("search did not return a different synthetic gallery wafer")
                query_only_catalog = FBMEmbeddingCatalog(
                    root / f"query-only-{rep}", authorize=lambda actor, incident, op:
                    actor == ACTOR and incident in scope and op in {"read", "write"})
                try:
                    query_only_catalog.add(asset_id=query_assets[rep], source_revision="r1",
                        raw_bytes=images[rep]["query"], vector=vectors[(rep, "query")],
                        spec=specs[rep], source_time="2026-03-30T12:00:00Z",
                        available_at="2026-03-30T12:00:00Z", incident_id=incident_id,
                        lot_id=query_lot, wafer_id=query_wafer, actor=ACTOR,
                        incident_scope=scope)

                    def query_only_resolver(query_tuple, requested_rep):
                        if requested_rep != rep or tuple(query_tuple) != query_identities[rep]:
                            raise ValueError("query-only resolver received an unexpected synthetic wafer")
                        record = query_only_catalog.get_asset(asset_id=query_assets[rep],
                            source_revision="r1", representation=rep, actor=ACTOR,
                            incident_scope=scope, as_of=AS_OF, timezone_name="Asia/Seoul")
                        return {"incident_id": record.incident_id, "lot_id": record.lot_id,
                            "wafer_id": record.wafer_id, "asset_id": record.asset_id,
                            "revision": record.source_revision, "raw_bytes": record.raw_bytes,
                            "available_at": record.available_at, "sha256": record.sha256,
                            "synthetic_only": True}
                    query_only_resolver.synthetic_only = True
                    query_only_adapter = SyntheticFBMAgentCatalogAdapter(
                        catalog=query_only_catalog, specs=specs, model_version=MODEL_VERSION,
                        query_resolver=query_only_resolver, encoder=cached_encoder,
                        timezone_name="Asia/Seoul")
                    query_only_result = query_only_adapter(ACTOR, [incident_id], [],
                        {"incident_id": incident_id, "lot_id": query_lot,
                         "wafer_id": query_wafer}, requested_rep, AS_OF, 10)
                    if query_only_result.get("status") != "NO_MATCH" or query_only_result.get("items"):
                        raise RuntimeError("a query-only catalog must produce NO_MATCH after self-exclusion")
                finally:
                    query_only_catalog.close()
                reports[requested_rep] = {
                    "agent_status": result["status"], "router_tool_sequence": [
                        entry["source"] for entry in result.get("evidence", [])],
                    "query_asset_self_match_present": any(
                        item["asset_id"] == query_assets[rep] and item["revision"] == "r1"
                        for item in evidence["items"]),
                    "query_only_status": query_only_result["status"],
                    "different_wafer_gallery_match_present": True,
                    "source_reported_truncated": evidence["source_reported_truncated"],
                    "gallery_asset_id": gallery_hits[0]["asset_id"],
                    "gallery_similarity": gallery_hits[0]["similarity"],
                    "model_version": MODEL_VERSION,
                    "query_vector_provenance": "cached_same_process_model_vector",
                    "fresh_callback_inference": False,
                    "physical_identity_verified": False,
                }
        finally:
            catalog.close()
    return {"status": "pass", "synthetic_only": True, "model_version": MODEL_VERSION,
            "representations": reports, "dimension": DIM,
            "source_acl_and_physical_identity": "unverified",
            "quality_performance_claim": False, "temporary_catalog_removed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run gated real local CPU inference and Agent smoke")
    parser.add_argument("--backbone", type=Path, help="explicit local backbone checkpoint")
    parser.add_argument("--head", type=Path, help="explicit local projection checkpoint")
    parser.add_argument("--expected-backbone-sha256", help="explicit trusted backbone SHA-256")
    parser.add_argument("--expected-head-sha256", help="explicit trusted projection SHA-256")
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({"status": "structural-self-check-pass", "weights_loaded": False,
                          "inference_run": False, "synthetic_only": True,
                          "representations": sorted(REPRESENTATIONS),
                          "model_version": MODEL_VERSION}, indent=2))
        return 0
    if os.environ.get("QAGENT_FBM_MODEL_LOAD_GATE") != "PARENT_AUDITED_20261030":
        parser.error("--run requires the parent audit/resource gate QAGENT_FBM_MODEL_LOAD_GATE")
    if not all((args.backbone, args.head, args.expected_backbone_sha256, args.expected_head_sha256)):
        parser.error("--run requires --backbone, --head, and both expected SHA-256 values")
    for value in (args.expected_backbone_sha256, args.expected_head_sha256):
        if len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
            parser.error("expected SHA-256 values must be 64 hexadecimal characters")
    output = _execute(args.backbone.resolve(strict=True), args.head.resolve(strict=True),
                       args.expected_backbone_sha256, args.expected_head_sha256)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
