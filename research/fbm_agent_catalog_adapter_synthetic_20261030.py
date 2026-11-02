"""Synthetic-only adapter from the Q-Agent FBM callback to the research catalog."""
from __future__ import annotations

import hashlib
from datetime import date, time, timedelta
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from research.fbm_embedding_catalog_20261030 import EmbeddingSpec, FBMEmbeddingCatalog


class SyntheticFBMAgentCatalogAdapter:
    """Connect explicitly injected synthetic query assets/encoders to catalog.search.

    Catalog authorization and scope callbacks remain synthetic assertions. The
    resolver and AssetRecord comparison checks synthetic catalog metadata only;
    it does not establish site ACL, physical origin, or immutable provenance.
    """

    def __init__(self, *, catalog: FBMEmbeddingCatalog,
                 specs: Mapping[str, EmbeddingSpec], model_version: str,
                 query_resolver: Callable, encoder: Callable, timezone_name: str):
        if not isinstance(catalog, FBMEmbeddingCatalog):
            raise ValueError("catalog must be a synthetic FBMEmbeddingCatalog")
        if not isinstance(specs, Mapping) or set(specs) != {"raw_fbm", "object_id_yield"}:
            raise ValueError("specs must explicitly define both representations")
        for rep, spec in specs.items():
            if not isinstance(spec, EmbeddingSpec) or spec.representation != rep:
                raise ValueError("each EmbeddingSpec must match its catalog representation")
        if not isinstance(model_version, str) or not model_version.strip():
            raise ValueError("model_version must be nonempty")
        if not callable(query_resolver) or getattr(query_resolver, "synthetic_only", False) is not True:
            raise ValueError("query_resolver must be callable and declare synthetic_only=True")
        if not callable(encoder):
            raise ValueError("encoder must be callable")
        if not isinstance(timezone_name, str) or not timezone_name:
            raise ValueError("timezone_name is required")
        ZoneInfo(timezone_name)
        self.catalog, self.specs = catalog, dict(specs)
        self.model_version, self.query_resolver, self.encoder = model_version, query_resolver, encoder
        self.timezone_name = timezone_name

    def __call__(self, actor, incident_ids, historical_incident_ids, query_wafer,
                 representation, as_of, top_k):
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor must be nonempty")
        if representation not in ("raw_fbm", "object_id_yield_fbm"):
            raise ValueError("unsupported app representation")
        if not isinstance(incident_ids, (list, tuple)) or not incident_ids:
            raise ValueError("incident_ids must be a nonempty list or tuple")
        if not isinstance(historical_incident_ids, (list, tuple)):
            raise ValueError("historical_incident_ids must be a list or tuple")
        current, historical = set(incident_ids), set(historical_incident_ids)
        if len(current) != len(incident_ids) or len(historical) != len(historical_incident_ids) or current & historical:
            raise ValueError("incident scopes must be unique and disjoint")
        if any(not isinstance(v, str) or not v.strip() for v in current | historical):
            raise ValueError("incident IDs must be nonempty strings")
        if not isinstance(query_wafer, Mapping):
            raise ValueError("query_wafer must be a mapping")
        query_tuple = tuple(query_wafer.get(k) for k in ("incident_id", "lot_id", "wafer_id"))
        if any(not isinstance(v, str) or not v.strip() for v in query_tuple) or query_tuple[0] not in current:
            raise ValueError("query wafer must identify a current incident wafer")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be from 1 to 100")
        if not isinstance(as_of, str) or len(as_of) != 10:
            raise ValueError("as_of must be an ISO date")
        try:
            cutoff_date = date.fromisoformat(as_of)
            if cutoff_date.isoformat() != as_of:
                raise ValueError
            zone = ZoneInfo(self.timezone_name)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date") from exc
        from datetime import datetime
        datetime.combine(cutoff_date + timedelta(days=1), time.min, zone)

        rep = "object_id_yield" if representation == "object_id_yield_fbm" else "raw_fbm"
        spec = self.specs[rep]
        resolved = self.query_resolver(query_tuple, rep)
        if not isinstance(resolved, Mapping):
            raise ValueError("query resolver must return a mapping")
        required = {"incident_id", "lot_id", "wafer_id", "asset_id", "revision",
                    "raw_bytes", "available_at", "sha256", "synthetic_only"}
        if set(resolved) != required or resolved.get("synthetic_only") is not True:
            raise ValueError("resolver result must be an explicit synthetic query asset")
        if tuple(resolved[k] for k in ("incident_id", "lot_id", "wafer_id")) != query_tuple:
            raise ValueError("resolved query wafer identity does not match query_wafer")
        raw = resolved["raw_bytes"]
        digest = hashlib.sha256(raw).hexdigest() if isinstance(raw, bytes) else None
        if digest is None or digest != resolved["sha256"]:
            raise ValueError("query asset SHA-256 mismatch")
        record = self.catalog.get_asset(asset_id=resolved["asset_id"], source_revision=resolved["revision"],
            representation=rep, actor=actor, incident_scope=current, as_of=as_of,
            timezone_name=self.timezone_name)
        asserted_identity = (resolved["incident_id"], resolved["lot_id"], resolved["wafer_id"],
            resolved["available_at"], resolved["asset_id"], resolved["revision"], rep, raw, digest)
        catalog_identity = (record.incident_id, record.lot_id, record.wafer_id,
            record.available_at, record.asset_id, record.source_revision,
            record.representation, record.raw_bytes, record.sha256)
        if asserted_identity != catalog_identity:
            raise ValueError("resolved query identity/metadata does not match catalog record")
        if (record.model_id, record.preprocess_version, record.checkpoint_sha256.lower(), record.dimension) != (
                spec.model_id, spec.preprocess_version, spec.checkpoint_sha256.lower(), spec.dimension):
            raise ValueError("catalog query embedding metadata does not match selected spec")
        encoded = self.encoder(raw, spec)
        vector = encoded.get("vector") if isinstance(encoded, Mapping) else encoded
        search = self.catalog.search(query_vector=vector, spec=spec, actor=actor,
            incident_scope=current | historical, as_of=as_of, top_k=top_k,
            exclude_asset_revision=(record.asset_id, record.source_revision),
            timezone_name=self.timezone_name)
        items = []
        for rank, hit in enumerate(search.items, 1):
            if hit.incident_id in current:
                relation = "direct"
            elif hit.incident_id in historical:
                relation = "historical_candidate"
            else:
                raise ValueError("catalog returned incident outside requested scope")
            items.append({"incident_id": hit.incident_id, "lot_id": hit.lot_id,
                "wafer_id": hit.wafer_id, "asset_id": hit.asset_id,
                "revision": hit.source_revision, "available_at": hit.available_at,
                "rank": rank, "similarity": hit.similarity, "relation": relation})
        response = {"status": "OK" if items else "NO_MATCH", "as_of": as_of,
            "representation": representation,
            "query": {"incident_id": query_tuple[0], "lot_id": query_tuple[1],
                "wafer_id": query_tuple[2], "asset_id": resolved["asset_id"],
                "revision": resolved["revision"], "available_at": resolved["available_at"]},
            "items": items, "model_id": spec.model_id, "model_version": self.model_version,
            "preprocess_version": spec.preprocess_version,
            "checkpoint_sha256": spec.checkpoint_sha256.lower(), "truncated": search.truncated}
        return response
