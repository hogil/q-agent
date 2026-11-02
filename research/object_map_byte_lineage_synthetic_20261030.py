"""Fail-closed byte-lineage gate for caller-supplied synthetic artifacts.

This in-memory research helper verifies caller-asserted hashes and references.
It does not prove causality, authenticity, geometry, registration, ACL, or an
archive that existed at the asserted time.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

ARTIFACTS = ("image", "positions", "checkpoint", "predictions", "object_map")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _fail() -> None:
    # Keep payloads, identifiers, and asserted values out of failure messages.
    raise ValueError("synthetic byte-lineage validation failed")


def validate_synthetic_byte_lineage(artifacts: Mapping[str, Any], manifest: Mapping[str, Any], *,
                                    analysis_at: datetime, cutoff: datetime,
                                    synthetic_fixture_asserted: bool) -> dict[str, Any]:
    """Validate bytes and explicit per-artifact lineage assertions, in memory only."""
    if synthetic_fixture_asserted is not True or not isinstance(artifacts, Mapping) or not isinstance(manifest, Mapping):
        _fail()
    try:
        analysis, limit = _time(analysis_at, "analysis_at"), _time(cutoff, "cutoff")
    except ValueError:
        _fail()
    entries = manifest.get("artifacts")
    if not isinstance(entries, Mapping) or set(entries) != set(ARTIFACTS):
        _fail()  # per-map entry required; global metadata cannot substitute
    if set(artifacts) != set(ARTIFACTS):
        _fail()

    normalized: dict[str, Mapping[str, Any]] = {}
    digests: dict[str, str] = {}
    common: tuple[Any, Any] | None = None
    for name in ARTIFACTS:
        entry, raw = entries.get(name), artifacts.get(name)
        if not isinstance(entry, Mapping) or not isinstance(raw, bytes) or not raw:
            _fail()
        claimed_hash = entry.get("sha256")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if not isinstance(claimed_hash, str) or not HASH_RE.fullmatch(claimed_hash) or claimed_hash != actual_hash:
            _fail()
        if not isinstance(entry.get("artifact_id"), str) or not entry["artifact_id"].strip() or not isinstance(entry.get("version"), str) or not entry["version"].strip():
            _fail()
        try:
            generated = _time(entry.get("generated_at"), f"{name}.generated_at")
            available = _time(entry.get("available_at"), f"{name}.available_at")
        except ValueError:
            _fail()
        if available < generated or generated > analysis or available > analysis or available >= limit:
            _fail()
        if name != "checkpoint":
            key = (entry.get("synthetic_wafer_key"), entry.get("source_revision"))
            if not all(isinstance(x, str) and x.strip() for x in key):
                _fail()
            if common is None:
                common = key
            elif key != common:
                _fail()
        normalized[name] = entry
        digests[name] = actual_hash

    def dependency(child: str, required: tuple[str, ...]) -> None:
        deps = normalized[child].get("dependencies")
        if not isinstance(deps, Mapping) or set(deps) != set(required):
            _fail()
        for parent in required:
            target = normalized[parent]
            ref = deps.get(parent)
            if not isinstance(ref, Mapping) or any(ref.get(k) != target[k] for k in ("artifact_id", "version", "sha256")):
                _fail()
            try:
                parent_available = _time(target["available_at"], f"{parent}.available_at")
                child_generated = _time(normalized[child]["generated_at"], f"{child}.generated_at")
            except ValueError:
                _fail()
            if parent_available > child_generated:
                _fail()

    dependency("predictions", ("image", "positions", "checkpoint"))
    dependency("object_map", ("positions", "predictions"))
    return {
        "status": "bytes_match_causality_unverified",
        "basis": "caller_asserted",
        "synthetic_fixture_only": True,
        "artifacts": {name: {"sha256": digests[name], "artifact_id": normalized[name]["artifact_id"],
                             "version": normalized[name]["version"]} for name in ARTIFACTS},
        "limitations": ["causality_unverified", "authenticity_unverified", "geometry_registration_unverified",
                        "acl_unverified", "not_proof_of_archive_at_asserted_time"],
    }
