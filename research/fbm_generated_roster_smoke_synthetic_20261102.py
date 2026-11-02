"""Wire synthetic class/position masks through split validation and roster scheduling.

This is a local synthetic data-path smoke only. Opaque-ID randomness is a
caller assertion; this script cannot verify an entropy source. The returned
cohort_id_audit and selection_audit are local analysis artifacts containing
IDs together with class/regime metadata; do not pass them to encoder inputs or
a blinded evaluator.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any

from research.fbm_class_position_synthetic_generator_20261102 import (
    REGIMES,
    ROLES,
    Sample,
    generate,
)
from research.fbm_separated_relevance_roster_synthetic_20261102 import (
    RosterSample,
    build_rosters,
    create_schedule_manifest,
)
from research.fbm_split_integrity_synthetic_20261102 import (
    MaskRecord,
    validate_split_integrity,
)

SEED = 20261102
SCHEDULE_ID = "generated-roster-smoke-synthetic-20261102-v1"
FAMILY_COUNTS = {role: 1 for role in ROLES} | {"gallery": 6, "query": 2}
LIMITATION = (
    "Synthetic roster wiring only; no real FBM, encoder, retrieval performance, "
    "causal, or near-duplicate validation. Opaque-ID randomness is caller-asserted."
)


def _hash(sample_id: str) -> str:
    return hashlib.sha256(f"generated-roster-smoke-v1|{sample_id}".encode()).hexdigest()


def _mask_records(samples: list[Sample]) -> list[MaskRecord]:
    return [MaskRecord(
        sample_id=sample.sample_id,
        family_id=sample.family_id,
        role=sample.role,
        mask_bytes=sample.raw_array.tobytes(),
        shape=tuple(sample.raw_array.shape),
        dtype="uint8",
    ) for sample in samples]


def _choose(samples: list[Sample]) -> tuple[list[Sample], dict[str, Any]]:
    """Preallocate classes by opaque-ID hash, then keep one variant per family."""
    chosen: list[Sample] = []
    audit: dict[str, Any] = {}
    for role in ("gallery", "query"):
        audit[role] = {}
        for regime in REGIMES:
            families: dict[str, list[Sample]] = {}
            for sample in samples:
                if sample.role == role and sample.regime == regime:
                    families.setdefault(sample.family_id, []).append(sample)
            ordered = sorted(
                families.items(),
                key=lambda item: min(_hash(sample.sample_id) for sample in item[1]),
            )
            expected = 6 if role == "gallery" else 2
            if len(ordered) != expected or any(len(pair) != 2 for _, pair in ordered):
                raise ValueError(f"unexpected {role}/{regime} family or pair count")
            if any({sample.true_class for sample in pair} != {"A", "B"} for _, pair in ordered):
                raise ValueError(f"each {role}/{regime} family must contain exactly one A/B pair")
            classes = ("A", "A", "A", "B", "B", "B") if role == "gallery" else ("A", "B")
            entries = []
            for (family_id, pair), klass in zip(ordered, classes):
                sample = next(s for s in pair if s.true_class == klass)
                chosen.append(sample)
                entries.append({
                    "family_id": family_id,
                    "sample_id": sample.sample_id,
                    "sample_id_hash": _hash(sample.sample_id),
                    "selected_class": klass,
                })
            audit[role][regime] = entries
    return chosen, audit


def _cell_counts(query: RosterSample, roster_ids: tuple[str, ...], by_id: dict[str, RosterSample]) -> dict[str, int]:
    counts = Counter()
    for candidate_id in roster_ids:
        candidate = by_id[candidate_id]
        class_relation = "same" if candidate.true_class == query.true_class else "different"
        position_relation = "same" if candidate.position_stratum == query.position_stratum else "different"
        counts[f"{class_relation}_{position_relation}"] += 1
    return dict(sorted(counts.items()))


def run_smoke(*, samples: list[Sample] | None = None) -> dict[str, Any]:
    cohort = samples if samples is not None else generate(SEED, family_counts=FAMILY_COUNTS)
    if len(cohort) != 66:
        raise ValueError(f"expected 66 generated samples, got {len(cohort)}")
    # Validate the complete cohort before selecting one member of each A/B pair.
    split_audit = validate_split_integrity(_mask_records(cohort))
    selected, selection_audit = _choose(cohort)
    roster_samples = [RosterSample(
        blind_id=sample.sample_id,
        family_id=sample.family_id,
        split=sample.role,
        true_class=sample.true_class,
        position_stratum=sample.regime,
    ) for sample in selected]
    manifest = create_schedule_manifest(roster_samples, SCHEDULE_ID)
    roundtrip = json.loads(json.dumps(manifest, sort_keys=True))
    rosters = build_rosters(roster_samples, SCHEDULE_ID, roundtrip)
    by_id = {sample.blind_id: sample for sample in roster_samples}
    counts = {}
    for query_id, roster in rosters.items():
        q = by_id[query_id]
        cells = _cell_counts(q, roster["roster"], by_id)
        if len(roster["roster"]) != 12 or set(cells.values()) != {3}:
            raise ValueError(f"{query_id}: roster must have 3 candidates in each 2x2 cell")
        if tuple(map(len, (roster["class_only"], roster["position_only"], roster["joint"]))) != (6, 6, 3):
            raise ValueError(f"{query_id}: unexpected relevance counts")
        counts[query_id] = {
            "cell_counts": cells,
            "candidate_count": len(roster["roster"]),
            "relevance_counts": {key: len(roster[key]) for key in ("class_only", "position_only", "joint")},
        }
    return {
        "status": "synthetic_generated_roster_smoke_only",
        "limitation": LIMITATION,
        "audit_artifact_scope": (
            "cohort_id_audit and selection_audit contain IDs with class/regime metadata; "
            "local analysis only, never encoder input or blinded-evaluator input"
        ),
        "opaque_id_randomness": "caller assertion; generator output is not an entropy audit",
        "generated_sample_count": len(cohort),
        "role_sample_counts": dict(sorted(Counter(s.role for s in cohort).items())),
        "cohort_id_audit": [
            {
                "role": sample.role,
                "regime": sample.regime,
                "family_id": sample.family_id,
                "sample_id": sample.sample_id,
                "sample_id_hash": _hash(sample.sample_id),
            }
            for sample in sorted(cohort, key=lambda item: (item.role, item.regime, item.family_id, item.true_class))
        ],
        "selected_role_sample_counts": dict(sorted(Counter(s.role for s in selected).items())),
        "selection_audit": selection_audit,
        "split_audit": split_audit,
        "schedule_manifest": roundtrip,
        "schedule_manifest_json_roundtrip_validated": True,
        "query_roster_checks": counts,
    }


if __name__ == "__main__":
    print(json.dumps(run_smoke(), sort_keys=True))
