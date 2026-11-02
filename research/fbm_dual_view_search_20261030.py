"""Fail-closed dual-view search over the synthetic FBM embedding catalog.

This is a caller-scoped research wrapper. Pairing, source identity and geometry
are caller_asserted_unverified; it does not validate production wafer lineage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from research.fbm_embedding_catalog_20261030 import (
    EmbeddingSpec, FBMEmbeddingCatalog, SearchResult,
)


REPRESENTATIONS = ("raw_fbm", "object_id_yield")
RRF_K = 60


@dataclass(frozen=True)
class DualViewResult:
    rank: int
    rrf_score: float
    pair_status: str
    raw_fbm: SearchResult | None
    object_id_yield: SearchResult | None
    identity_provenance: str
    source_provenance: str
    geometry_provenance: str


@dataclass(frozen=True)
class DualViewResponse:
    items: tuple[DualViewResult, ...]
    raw_fbm_eligible_count: int
    object_id_yield_eligible_count: int
    raw_fbm_truncated: bool
    object_id_yield_truncated: bool
    top_k_per_view: int
    rrf_k: int
    actor: str
    incident_scope: tuple[str, ...]
    as_of: str
    limitations: tuple[str, ...]


def search_dual_view(*, catalog: FBMEmbeddingCatalog,
                     raw_query_vector, raw_spec: EmbeddingSpec,
                     object_query_vector, object_spec: EmbeddingSpec,
                     actor: str, incident_scope, as_of: str,
                     top_k_per_view: int, rrf_k: int = RRF_K,
                     timezone_name: str | None = None) -> DualViewResponse:
    """Search both views with identical caller scope and fuse ranks only.

    Each view is first limited to ``top_k_per_view`` by catalog.search. Thus
    the union and RRF ranking are approximate and make no cross-view recall or
    completeness guarantee.
    """
    if raw_spec.representation != REPRESENTATIONS[0] or object_spec.representation != REPRESENTATIONS[1]:
        raise ValueError("spec representations must be raw_fbm and object_id_yield respectively")
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if not isinstance(as_of, str):
        raise ValueError("as_of must be a timezone-aware datetime or date with timezone_name")
    date_only = len(as_of) == 10
    if date_only and timezone_name is None:
        raise ValueError("as_of must be a timezone-aware datetime or date-only with timezone_name")
    try:
        parsed_as_of = None if date_only else datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of must be a timezone-aware datetime") from exc
    if not date_only and (parsed_as_of.tzinfo is None or parsed_as_of.utcoffset() is None):
        raise ValueError("as_of must be a timezone-aware datetime")
    normalized_as_of = (as_of if date_only else parsed_as_of.astimezone(timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z"))
    if isinstance(incident_scope, (str, bytes)):
        raise ValueError("incident_scope must be an iterable of incident IDs, not a string")
    scope = tuple(sorted(set(incident_scope)))
    # Do not catch either call: authorization, validation, or catalog failures
    # must fail the entire operation without returning partial results.
    raw = catalog.search(query_vector=raw_query_vector, spec=raw_spec,
                         actor=actor, incident_scope=scope, as_of=as_of,
                         timezone_name=timezone_name,
                         top_k=top_k_per_view)
    obj = catalog.search(query_vector=object_query_vector, spec=object_spec,
                         actor=actor, incident_scope=scope, as_of=as_of,
                         timezone_name=timezone_name,
                         top_k=top_k_per_view)

    raw_items, obj_items = tuple(raw.items), tuple(obj.items)
    # Pair only when the full asserted identity tuple is unique in both views.
    def identity(row: SearchResult):
        return (row.asset_id, row.source_revision, row.incident_id,
                row.lot_id, row.wafer_id)

    from collections import defaultdict
    raw_by, obj_by = defaultdict(list), defaultdict(list)
    for row in raw_items:
        raw_by[identity(row)].append(row)
    for row in obj_items:
        obj_by[identity(row)].append(row)
    # Rank score by original view rank. Similarity magnitudes are never mixed.
    scores: dict[tuple, float] = {}
    for view, rows in ((REPRESENTATIONS[0], raw_items), (REPRESENTATIONS[1], obj_items)):
        for rank, row in enumerate(rows, 1):
            key = (view, identity(row))
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)

    candidates = []
    consumed = set()
    for ident in set(raw_by) | set(obj_by):
        left, right = raw_by.get(ident, []), obj_by.get(ident, [])
        if len(left) == len(right) == 1 and ident[3] and ident[4]:
            lrow, rrow = left[0], right[0]
            if (lrow.asset_id, lrow.source_revision, lrow.incident_id, lrow.lot_id, lrow.wafer_id) == (rrow.asset_id, rrow.source_revision, rrow.incident_id, rrow.lot_id, rrow.wafer_id):
                key_l, key_r = (REPRESENTATIONS[0], ident), (REPRESENTATIONS[1], ident)
                candidates.append((-(scores[key_l] + scores[key_r]), ident, lrow, rrow, "paired"))
                consumed.update((key_l, key_r))
    for view, rows in ((REPRESENTATIONS[0], raw_items), (REPRESENTATIONS[1], obj_items)):
        for row in rows:
            key = (view, identity(row))
            if key in consumed:
                continue
            candidates.append((-scores[key], (view, *identity(row)), row if view == REPRESENTATIONS[0] else None,
                               row if view == REPRESENTATIONS[1] else None,
                               "not_in_returned_top_k_unknown"))
    candidates.sort(key=lambda x: (x[0], repr(x[1])))
    items = tuple(DualViewResult(i, -score, status, left, right,
                                 "caller_asserted_unverified", "caller_asserted_unverified",
                                 "caller_asserted_unverified")
                  for i, (score, _, left, right, status) in enumerate(candidates, 1))
    return DualViewResponse(items, raw.eligible_count, obj.eligible_count,
                            raw.truncated, obj.truncated, top_k_per_view, rrf_k,
                            actor, scope, normalized_as_of,
                            ("Synthetic catalog only; caller-supplied actor, scope, model source and pairing are unverified.",
                             "Per-view top-k truncation makes the union approximate; absence from a returned top-k is unknown.",
                             "No actual wafer identity, geometry, production source, or site authorization is validated."))


def response_dict(response: DualViewResponse) -> dict[str, Any]:
    """JSON-friendly rendering for research callers."""
    return asdict(response)
