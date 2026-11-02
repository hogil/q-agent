"""In-memory wiring smoke for separated synthetic FBM evaluation helpers.

All scores and masks are fixed synthetic fixtures. This module does not call
or train a model and makes no claim about real data or research readiness.
"""
from __future__ import annotations

import hashlib
from typing import Any

from research.fbm_split_integrity_synthetic_20261102 import MaskRecord, validate_split_integrity
from research.fbm_mask_symmetry_candidates_synthetic_20261102 import (
    find_mask_symmetry_candidates,
)
from research.fbm_mask_near_duplicate_candidates_synthetic_20261102 import (
    find_mask_near_duplicate_candidates,
)
from research.fbm_frozen_artifacts_synthetic_20261102 import (
    ARTIFACT_ROLES,
    Artifact,
    validate_frozen_artifacts,
)
from research.fbm_separated_relevance_roster_synthetic_20261102 import (
    RosterSample,
    build_rosters,
    create_schedule_manifest,
)
from research.fbm_separated_rank_metrics_synthetic_20261102 import score_separated_rank_metrics


SCHEDULE_ID = "fixed-synthetic-smoke-v1"
_MASK_SHAPE = (192, 192)
_MASK_SIZE = 192 * 192
_JACCARD_DEMO_THRESHOLD = 0.90  # Illustrative synthetic value; not validated.
_ARTIFACT_CREATED_AT = "2026-11-01T00:00:00Z"
_ARTIFACT_CUTOFF_UTC = "2026-11-01T00:00:00Z"


def _mask(seed: int) -> bytes:
    """Return a deterministic nonempty binary mask with a unique pixel."""
    bits = bytearray(_MASK_SIZE)
    bits[seed] = 1
    bits[(seed * 193 + 17) % _MASK_SIZE] = 1
    return bytes(bits)


def _rotate_90(mask: bytes) -> bytes:
    size = _MASK_SHAPE[0]
    return bytes(mask[(size - 1 - col) * size + row]
                 for row in range(size) for col in range(size))


def _jaccard_demo_masks() -> tuple[bytes, bytes]:
    """Create a 20-pixel mask and its rotated version with one added pixel."""
    size = _MASK_SHAPE[0]
    base = bytearray(_MASK_SIZE)
    for index in range(20):
        base[(index + 2) * size + (index * 3 + 5)] = 1
    rotated = bytearray(_rotate_90(bytes(base)))
    rotated[90 * size + 90] = 1
    return bytes(base), bytes(rotated)


def _synthetic_artifact_preflight(failure: str | None = None) -> dict[str, Any]:
    artifacts: dict[str, Artifact] = {}
    expected_sha256: dict[str, str] = {}
    for role in ARTIFACT_ROLES:
        content = f"synthetic-fake-{role}-bytes-v1".encode("ascii")
        created_at = _ARTIFACT_CREATED_AT
        if failure == "tampered" and role == "encoder":
            content += b"-tampered"
        if failure == "after_cutoff" and role == "encoder":
            created_at = "2026-11-02T00:00:00Z"
        if failure != "missing" or role != "code":
            artifacts[role] = Artifact(f"synthetic-{role}-v1", content, created_at)
        expected_sha256[role] = hashlib.sha256(
            f"synthetic-fake-{role}-bytes-v1".encode("ascii")
        ).hexdigest()
    report = validate_frozen_artifacts(artifacts, expected_sha256, _ARTIFACT_CUTOFF_UTC)
    return {
        "valid": report.valid,
        "cutoff_utc": report.cutoff_utc,
        "artifact_created_at_utc": _ARTIFACT_CREATED_AT,
        "verified_artifact_ids": list(report.verified_artifact_ids),
        "expected_sha256": expected_sha256,
        "validation_scope": report.scope,
        "manifest_provenance": "generated inside this smoke; does not establish a trusted pre-evaluation freeze",
        "model_use": "fake artifact bytes only; no actual model is used",
        "encoder_metadata_isolation": "not established by this byte/hash/time check",
    }


def _fixtures(*, exact_duplicate: bool = False, family_leakage: bool = False,
              ancestry_leakage: bool = False, symmetry_candidate: bool = False,
              jaccard_candidate: bool = False):
    roles = ("pilot", "development", "gallery", "query", "holdout")
    masks = [_mask(i) for i in range(len(roles))]
    if exact_duplicate:
        masks[1] = masks[0]
    if symmetry_candidate:
        masks[1] = _rotate_90(masks[0])
    if jaccard_candidate:
        masks[0], masks[1] = _jaccard_demo_masks()
    records = [
        MaskRecord(
            sample_id=f"smoke-{role}",
            family_id=("family-pilot" if family_leakage and role == "development" else f"family-{role}"),
            role=role,
            mask_bytes=masks[i],
            shape=_MASK_SHAPE,
            dtype="uint8",
            ancestry=("shared-pilot-root",)
            if ancestry_leakage and role in {"pilot", "development"} else (),
        )
        for i, role in enumerate(roles)
    ]

    # Two queries, with 12 distinct gallery families. Four cells each have
    # three candidates; true labels/strata are relevance-only metadata.
    samples = []
    for qi, (klass, pos) in enumerate((("A", "north"), ("B", "south"))):
        samples.append(RosterSample(f"q{qi}", f"q-family-{qi}", "query", klass, pos))
    gallery_index = 0
    for qi, (qklass, qpos) in enumerate((("A", "north"), ("B", "south"))):
        for same_class in (True, False):
            for same_pos in (True, False):
                for _ in range(3):
                    klass = qklass if same_class else ("B" if qklass == "A" else "A")
                    pos = qpos if same_pos else ("south" if qpos == "north" else "north")
                    samples.append(RosterSample(
                        f"g{gallery_index:02d}", f"g-family-{gallery_index:02d}",
                        "gallery", klass, pos,
                    ))
                    gallery_index += 1
    return records, samples


def run_smoke(*, exact_duplicate: bool = False, family_leakage: bool = False,
              ancestry_leakage: bool = False,
              symmetry_candidate: bool = False,
              jaccard_demo: bool = False,
              artifact_preflight: bool = False,
              artifact_failure: str | None = None) -> dict[str, Any]:
    """Run split audit, frozen roster schedule, and synthetic score metrics."""
    records, samples = _fixtures(
        exact_duplicate=exact_duplicate,
        family_leakage=family_leakage,
        ancestry_leakage=ancestry_leakage,
        symmetry_candidate=symmetry_candidate,
        jaccard_candidate=jaccard_demo,
    )
    split_audit = validate_split_integrity(records)
    symmetry_audit = find_mask_symmetry_candidates(records)
    jaccard_audit = (
        find_mask_near_duplicate_candidates(records, _JACCARD_DEMO_THRESHOLD)
        if jaccard_demo else None
    )
    artifact_audit = (
        _synthetic_artifact_preflight(artifact_failure) if artifact_preflight else None
    )
    manifest = create_schedule_manifest(samples, SCHEDULE_ID)
    rosters = build_rosters(samples, SCHEDULE_ID, manifest)

    # Identical fixed scores are applied to every 12-candidate query roster.
    # No encoder or learned score generator is involved.
    metrics: dict[str, Any] = {}
    for query_id, roster in rosters.items():
        ids = roster["roster"]
        if len(ids) != 12:
            raise ValueError(f"{query_id}: expected 12 candidates, got {len(ids)}")
        metrics[query_id] = score_separated_rank_metrics(
            scores={candidate_id: float(11 - index) for index, candidate_id in enumerate(ids)},
            relevance={
                name: set(roster[name])
                for name in ("class_only", "position_only", "joint")
            },
            schedule_id=SCHEDULE_ID,
            asserted_class_label_free_blind_ids=True,
            asserted_encoder_metadata_isolated=True,
        )

    return {
        "status": "synthetic_pipeline_smoke_only",
        "scores_are_fixed_synthetic_values": True,
        "model_called_or_trained": False,
        "split_audit": split_audit,
        "symmetry_candidate_audit": symmetry_audit,
        "jaccard_demo_audit": jaccard_audit,
        "artifact_preflight": artifact_audit,
        "schedule_manifest": manifest,
        "rosters": {qid: {key: list(value) for key, value in roster.items()}
                    for qid, roster in rosters.items()},
        "rank_metrics": metrics,
        "assertions": {
            "metadata_lineage": "caller assertion only; not independently verified",
            "blindness_and_encoder_metadata_isolation": "caller assertion only; not independently verified",
        },
        "unverified": [
            "near-duplicate geometry",
            "rotation/reflection duplicates",
            "lineage completeness and dataset authenticity",
            "encoder boundary and freeze",
        ],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_smoke(), sort_keys=True))
