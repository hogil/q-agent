from dataclasses import replace
import json

import pytest

from research.fbm_separated_relevance_roster_synthetic_20261102 import (
    RosterSample,
    build_rosters,
    create_schedule_manifest,
)


def cohort():
    rows = [RosterSample("q0", "qf", "query", "A", "center")]
    # Deliberately skew the metadata to prove each query still receives the
    # prescribed 3-per-cell roster and 6/6/3 task positives.
    for i, (cls, pos) in enumerate([
        ("A", "center"), ("A", "center"), ("A", "center"),
        ("A", "ring"), ("A", "ring"), ("A", "ring"), ("B", "center"),
        ("B", "center"), ("B", "center"), ("B", "ring"), ("B", "ring"),
        ("B", "ring"), ("A", "center"), ("A", "center"),
    ]):
        rows.append(RosterSample(f"g{i:02d}", f"gf{i:02d}", "gallery", cls, pos))
    return rows


def test_common_roster_and_relevance_counts_under_imbalance():
    rows = cohort()
    manifest = create_schedule_manifest(rows, "synthetic-smoke-v1")
    result = build_rosters(rows, "synthetic-smoke-v1", manifest)["q0"]
    q = next(row for row in rows if row.blind_id == "q0")
    by_id = {row.blind_id: row for row in rows}
    cell_counts = {(cls, pos): 0 for cls in ("same", "different")
                   for pos in ("same", "different")}
    for candidate_id in result["roster"]:
        g = by_id[candidate_id]
        cell = ("same" if q.true_class == g.true_class else "different",
                "same" if q.position_stratum == g.position_stratum else "different")
        cell_counts[cell] += 1
    assert set(cell_counts.values()) == {3}
    assert len(result["roster"]) == 12
    assert len(result["class_only"]) == 6
    assert len(result["position_only"]) == 6
    assert len(result["joint"]) == 3
    assert set(result["class_only"]) <= set(result["roster"])
    assert set(result["position_only"]) <= set(result["roster"])
    assert set(result["joint"]) <= set(result["roster"])


def test_deterministic_under_input_reordering():
    rows = cohort()
    manifest = create_schedule_manifest(rows, "s1")
    assert manifest == create_schedule_manifest(list(reversed(rows)), "s1")
    assert build_rosters(rows, "s1", manifest) == build_rosters(
        list(reversed(rows)), "s1", manifest
    )
    assert create_schedule_manifest(rows, "s1") != create_schedule_manifest(rows, "s2")


@pytest.mark.parametrize("mutator, message", [
    (lambda x: x + [x[-1]], "duplicate blind ID"),
    (lambda x: x + [replace(x[-1], blind_id="other")], "duplicate family ID"),
    (lambda x: x + [replace(x[-1], blind_id="other", split="holdout")], "split must"),
])
def test_bad_ids_families_and_split_leakage_fail_closed(mutator, message):
    with pytest.raises(ValueError, match=message):
        create_schedule_manifest(mutator(cohort()), "s1")


def test_query_family_leakage_and_insufficient_cell_fail_closed():
    rows = cohort()
    rows.append(RosterSample("g-self", "qf", "gallery", "A", "center"))
    with pytest.raises(ValueError, match="family split leakage"):
        create_schedule_manifest(rows, "s1")
    too_few = [r for r in cohort() if r.blind_id not in {"g00", "g01", "g02"}]
    with pytest.raises(ValueError, match="need 3"):
        create_schedule_manifest(too_few, "s1")


def test_multiple_queries_have_frozen_balanced_schedule_and_manifest_is_checked():
    rows = cohort()
    rows.append(RosterSample("q1", "qf1", "query", "A", "center"))
    manifest = create_schedule_manifest(rows, "balanced-v1")
    round_tripped = json.loads(json.dumps(manifest))
    assert round_tripped["layer_counts"] == manifest["layer_counts"]
    built = build_rosters(rows, "balanced-v1", round_tripped)
    assert set(built) == {"q0", "q1"}
    assert manifest["schedule_id"] == "balanced-v1"
    bad = {**round_tripped, "assignments": {**round_tripped["assignments"], "q0": {}}}
    with pytest.raises(ValueError, match="manifest mismatch"):
        build_rosters(rows, "balanced-v1", bad)
    bad_counts = {**round_tripped, "layer_counts": []}
    with pytest.raises(ValueError, match="manifest mismatch"):
        build_rosters(rows, "balanced-v1", bad_counts)


def test_four_position_strata_balance_achievable_case():
    rows = [RosterSample("q0", "qf", "query", "A", "center")]
    i = 0
    for cls in ("A", "B"):
        for pos in ("center", "ring", "notch", "edge"):
            for _ in range(3):
                rows.append(RosterSample(f"g{i:02d}", f"gf{i:02d}", "gallery", cls, pos))
                i += 1
    manifest = create_schedule_manifest(rows, "four-strata")
    assert manifest == create_schedule_manifest(rows, "four-strata")
    assert create_schedule_manifest(list(reversed(rows)), "four-strata") == manifest
    assert len(manifest["layer_counts"]) == 1
    assert set(manifest["layer_counts"][0]["other_position_counts"].values()) == {2}
    selected = [sid for cell, ids in manifest["assignments"]["q0"].items()
                if cell.endswith("_different") for sid in ids]
    by_id = {row.blind_id: row for row in rows}
    counts = {pos: sum(by_id[sid].position_stratum == pos for sid in selected)
              for pos in ("ring", "notch", "edge")}
    assert counts == {"ring": 2, "notch": 2, "edge": 2}


def test_four_position_unachievable_balance_fails_closed():
    rows = [RosterSample("q0", "qf", "query", "A", "center")]
    values = [("A", "center")] * 3 + [("B", "center")] * 3
    values += [("A", "ring")] * 2 + [("A", "notch")]
    values += [("B", "ring")] * 2 + [("B", "edge")]
    for i, (cls, pos) in enumerate(values):
        rows.append(RosterSample(f"g{i:02d}", f"gf{i:02d}", "gallery", cls, pos))
    with pytest.raises(ValueError, match="cannot balance"):
        create_schedule_manifest(rows, "three-strata")
