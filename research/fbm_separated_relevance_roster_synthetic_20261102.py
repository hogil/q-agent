"""Deterministic synthetic gallery rosters for separated FBM relevance tasks.

This module only builds/validates candidate rosters. It does not load data,
encoders, or models and makes no claims about real wafers or site performance.
It checks family IDs only; five-role ancestry and near-duplicate audits are out
of scope. Returned relevance IDs/metadata must be kept outside encoder inputs;
this module cannot audit a caller's encoder boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from functools import lru_cache
from typing import Iterable


CELLS = (("same", "same"), ("same", "different"),
         ("different", "same"), ("different", "different"))
TASKS = ("class_only", "position_only", "joint")


@dataclass(frozen=True)
class RosterSample:
    blind_id: str
    family_id: str
    split: str
    true_class: str
    position_stratum: str


def _validate(samples: list[RosterSample]) -> None:
    if not samples:
        raise ValueError("samples must not be empty")
    ids = [s.blind_id for s in samples]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("missing or duplicate blind ID")
    families = [s.family_id for s in samples]
    if any(not x for x in families):
        raise ValueError("missing family ID")
    allowed = {"query", "gallery"}
    if any(s.split not in allowed for s in samples) or {s.split for s in samples} != allowed:
        raise ValueError("split must contain query and gallery only")
    family_splits: dict[str, set[str]] = {}
    family_roles: dict[tuple[str, str], int] = {}
    for s in samples:
        family_splits.setdefault(s.family_id, set()).add(s.split)
        key = (s.family_id, s.split)
        family_roles[key] = family_roles.get(key, 0) + 1
    if any(len(splits) > 1 for splits in family_splits.values()):
        raise ValueError("family split leakage")
    if any(count > 1 for count in family_roles.values()):
        raise ValueError("duplicate family ID within split")
    if any(not s.true_class or not s.position_stratum for s in samples):
        raise ValueError("true class and position stratum are required for relevance only")


def _cell(q: RosterSample, g: RosterSample) -> tuple[str, str]:
    return ("same" if q.true_class == g.true_class else "different",
            "same" if q.position_stratum == g.position_stratum else "different")


def create_schedule_manifest(samples: Iterable[RosterSample], schedule_id: str) -> dict[str, object]:
    """Precompute balanced blind-hash assignments in a JSON-safe manifest.

    Balance is checked only among gallery position strata different from the
    query position. Position quotas are solved before IDs are selected; blind
    hashes then order candidates within each assigned cell/position.
    Returned assignments contain JSON-safe lists and can be frozen as JSON.
    """
    cohort = list(samples)
    _validate(cohort)
    if not schedule_id:
        raise ValueError("schedule_id must not be empty")
    queries = sorted((s for s in cohort if s.split == "query"), key=lambda s: s.blind_id)
    gallery = [s for s in cohort if s.split == "gallery"]
    assignments: dict[str, dict[str, list[str]]] = {}
    layers: dict[tuple[str, str], list[RosterSample]] = {}
    for q in queries:
        layers.setdefault((q.true_class, q.position_stratum), []).append(q)

    def compositions(total: int, capacities: tuple[int, ...]):
        values = [0] * len(capacities)
        def visit(index: int, remaining: int):
            if index == len(capacities):
                if remaining == 0:
                    yield tuple(values)
                return
            for amount in range(min(capacities[index], remaining) + 1):
                values[index] = amount
                yield from visit(index + 1, remaining - amount)
        yield from visit(0, total)

    layer_counts: list[dict[str, object]] = []
    for layer, layer_queries in sorted(layers.items()):
        layer_queries.sort(key=lambda q: hashlib.sha256(
            f"fbm-roster-v1|{schedule_id}|query-order|{q.blind_id}".encode("utf-8")
        ).hexdigest())
        query_position = layer[1]
        other_positions = {g.position_stratum for g in gallery if g.position_stratum != query_position}
        if not other_positions:
            raise ValueError(f"query stratum {layer}: no different position strata")
        position_order = sorted(other_positions, key=lambda pos: min(
            hashlib.sha256(f"fbm-roster-v1|{schedule_id}|{layer_queries[0].blind_id}|position|{g.blind_id}".encode()).hexdigest()
            for g in gallery if g.position_stratum == pos
        ))
        query_options = []
        for q in layer_queries:
            by_cell = {cell: [] for cell in CELLS}
            for g in gallery:
                if g.family_id != q.family_id:
                    by_cell[_cell(q, g)].append(g)
            fixed, diff = {}, {}
            for class_relation in ("same", "different"):
                fixed_name = f"{class_relation}_same"
                fixed_candidates = by_cell[(class_relation, "same")]
                if len(fixed_candidates) < 3:
                    raise ValueError(f"{q.blind_id}: cell {fixed_name} has {len(fixed_candidates)} candidates; need 3")
                fixed_candidates.sort(key=lambda g: hashlib.sha256(
                    f"fbm-roster-v1|{schedule_id}|{q.blind_id}|{fixed_name}|{g.blind_id}".encode()
                ).hexdigest())
                fixed[fixed_name] = fixed_candidates[:3]
                diff_name = f"{class_relation}_different"
                cell_candidates = by_cell[(class_relation, "different")]
                if len(cell_candidates) < 3:
                    raise ValueError(f"{q.blind_id}: cell {diff_name} has {len(cell_candidates)} candidates; need 3")
                diff[diff_name] = {
                    pos: sorted((g for g in cell_candidates if g.position_stratum == pos), key=lambda g: hashlib.sha256(
                        f"fbm-roster-v1|{schedule_id}|{q.blind_id}|{diff_name}|{g.blind_id}".encode()
                    ).hexdigest()) for pos in position_order
                }
            query_options.append((q, fixed, diff))

        slots = [(qi, name) for qi in range(len(query_options))
                 for name in ("same_different", "different_different")]

        @lru_cache(maxsize=None)
        def solve(slot: int, counts: tuple[int, ...]):
            if slot == len(slots):
                return () if max(counts) - min(counts) <= 1 else None
            qi, name = slots[slot]
            capacities = tuple(len(query_options[qi][2][name][pos]) for pos in position_order)
            for allocation in compositions(3, capacities):
                next_counts = tuple(a + b for a, b in zip(counts, allocation))
                tail = solve(slot + 1, next_counts)
                if tail is not None:
                    return (allocation,) + tail
            return None

        allocations = solve(0, tuple(0 for _ in position_order))
        if allocations is None:
            raise ValueError(f"query stratum {layer}: different-position schedule cannot balance")
        final_counts = [0] * len(position_order)
        cursor = 0
        for q, fixed, diff in query_options:
            q_assignments: dict[str, list[str]] = {
                name: [g.blind_id for g in values] for name, values in fixed.items()
            }
            for name in ("same_different", "different_different"):
                allocation = allocations[cursor]
                cursor += 1
                chosen = []
                for pos_index, amount in enumerate(allocation):
                    chosen.extend(g.blind_id for g in diff[name][position_order[pos_index]][:amount])
                    final_counts[pos_index] += amount
                q_assignments[name] = chosen
            assignments[q.blind_id] = q_assignments
        layer_counts.append({
            "query_class": layer[0],
            "query_position": layer[1],
            "other_position_counts": {
                position: count for position, count in zip(position_order, final_counts)
            },
        })
    return {"schedule_id": schedule_id, "assignments": assignments, "layer_counts": layer_counts}


def build_rosters(
    samples: Iterable[RosterSample],
    schedule_id: str,
    schedule_manifest: dict[str, object],
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Validate a frozen JSON-safe manifest and build common rosters/relevance sets.

    True metadata defines cells/relevance only. Manifest ordering uses blind
    IDs only; returned relevance IDs must not be passed to an encoder.
    """
    cohort = list(samples)
    _validate(cohort)
    expected = create_schedule_manifest(cohort, schedule_id)
    if schedule_manifest != expected:
        raise ValueError("schedule manifest mismatch")
    queries = sorted((s for s in cohort if s.split == "query"), key=lambda q: hashlib.sha256(
        f"fbm-roster-v1|{schedule_id}|query-order|{q.blind_id}".encode("utf-8")
    ).hexdigest())
    by_id = {s.blind_id: s for s in cohort}
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    assignments = schedule_manifest["assignments"]
    for q in queries:
        cell_map = assignments[q.blind_id]
        chosen = [by_id[sid] for cell in CELLS for sid in cell_map[f"{cell[0]}_{cell[1]}"]]
        ids_by_task = {task: [] for task in TASKS}
        for g in chosen:
            same_class, same_position = _cell(q, g)
            if same_class == "same":
                ids_by_task["class_only"].append(g.blind_id)
            if same_position == "same":
                ids_by_task["position_only"].append(g.blind_id)
            if same_class == same_position == "same":
                ids_by_task["joint"].append(g.blind_id)
        roster_ids = tuple(sorted(g.blind_id for g in chosen))
        result[q.blind_id] = {"roster": roster_ids, **{
            task: tuple(sorted(ids)) for task, ids in ids_by_task.items()
        }}
    return result

