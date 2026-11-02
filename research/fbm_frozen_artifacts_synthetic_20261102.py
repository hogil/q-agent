"""Fail-closed validation of caller-supplied synthetic frozen artifact bytes.

This validates byte/hash/time consistency only. It cannot certify provenance,
evaluation ordering, model use, callable closure, or metadata isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Mapping


ARTIFACT_ROLES = ("encoder", "checkpoint", "preprocessing", "code")
_UTC_CUTOFF = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ArtifactValidationError(ValueError):
    """Raised when the supplied manifest and artifacts do not satisfy contract."""


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    content: bytes
    created_at: str


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    cutoff_utc: str
    verified_artifact_ids: tuple[str, ...]
    scope: str = (
        "Validates supplied bytes, SHA-256 values, IDs, and timestamps only; "
        "does not prove freeze-before-evaluation, provenance, operational model use, "
        "callable-closure isolation, or metadata isolation."
    )


def _parse_cutoff(value: str) -> datetime:
    if not isinstance(value, str) or not _UTC_CUTOFF.fullmatch(value):
        raise ArtifactValidationError("cutoff must be canonical timezone-aware UTC ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ArtifactValidationError("cutoff is not a valid timestamp") from exc


def _parse_created_at(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ArtifactValidationError("created_at must be an ISO-8601 timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactValidationError("created_at is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactValidationError("created_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_frozen_artifacts(
    artifacts: Mapping[str, Artifact],
    expected_sha256: Mapping[str, str],
    cutoff_utc: str,
) -> ValidationReport:
    """Validate role→artifact ID→bytes against a pre-sealed digest manifest."""
    cutoff = _parse_cutoff(cutoff_utc)
    if not isinstance(artifacts, Mapping) or not isinstance(expected_sha256, Mapping):
        raise ArtifactValidationError("artifacts and expected_sha256 must be mappings")
    if set(artifacts) != set(ARTIFACT_ROLES) or set(expected_sha256) != set(ARTIFACT_ROLES):
        raise ArtifactValidationError("all and only required artifact roles must be supplied")

    ids: set[str] = set()
    verified: list[str] = []
    for role in ARTIFACT_ROLES:
        artifact = artifacts[role]
        if not isinstance(artifact, Artifact):
            raise ArtifactValidationError(f"{role}: expected Artifact")
        if not isinstance(artifact.artifact_id, str) or not artifact.artifact_id.strip():
            raise ArtifactValidationError(f"{role}: artifact_id must be nonempty")
        if artifact.artifact_id in ids:
            raise ArtifactValidationError("artifact IDs must be unique")
        ids.add(artifact.artifact_id)
        if not isinstance(artifact.content, bytes):
            raise ArtifactValidationError(f"{role}: content must be bytes")
        created = _parse_created_at(artifact.created_at)
        if created > cutoff:
            raise ArtifactValidationError(f"{role}: created_at is after cutoff")
        expected = expected_sha256[role]
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise ArtifactValidationError(f"{role}: expected SHA-256 must be 64 lowercase hex characters")
        actual = hashlib.sha256(artifact.content).hexdigest()
        if actual != expected:
            raise ArtifactValidationError(f"{role}: SHA-256 mismatch")
        verified.append(artifact.artifact_id)

    return ValidationReport(True, cutoff_utc, tuple(verified))
