from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import fbm_paired_controls_runner_synthetic_20261030 as runner
from research import fbm_paired_factorial_synthetic_20261030 as factorial


def test_light_self_check_declares_exact_nonprimary_matrix_without_weights():
    check = runner._self_check()
    assert check["inference_run"] is False
    assert check["weights_loaded"] is False
    assert len(runner.CONDITIONS) == 11
    assert len({runner._condition_key(c) for c in runner.CONDITIONS}) == 11
    assert all(c != runner.PRIMARY_CONDITION for c in runner.CONDITIONS)
    assert check["planned_units"] == 55


def test_primary_manifest_must_be_closed_five_seed_and_hash_fresh():
    manifest_path = runner.PRIMARY_MANIFEST_DEFAULT
    if not manifest_path.is_file():
        pytest.skip("the frozen primary manifest is not present in this checkout")
    manifest, rows = runner._read_primary(manifest_path)
    assert manifest["closed"] is True
    assert tuple(rows) == factorial.SEEDS

    stale = deepcopy(manifest)
    stale["status"] = "running"
    fake = manifest_path.parent / ".test-stale-primary.json"
    try:
        fake.write_text(json.dumps(stale), encoding="utf-8")
        with pytest.raises(ValueError, match="closed and complete"):
            runner._read_primary(fake)
    finally:
        fake.unlink(missing_ok=True)

    bad_sources = deepcopy(manifest)
    bad_sources["provenance"]["frozen_source_hashes"]["generator"]["sha256"] = "0" * 64
    fake.write_text(json.dumps(bad_sources), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="frozen source hashes"):
            runner._read_primary(fake)
    finally:
        fake.unlink(missing_ok=True)


def test_source_drift_and_output_collision_fail_closed(tmp_path, monkeypatch):
    frozen = runner._current_source_hashes()
    changed = deepcopy(frozen)
    changed["generator"]["sha256"] = "f" * 64
    monkeypatch.setattr(runner, "_current_source_hashes", lambda: changed)
    with pytest.raises(RuntimeError, match="source hash changed"):
        runner._verify_source_identity(frozen, "test")

    output = tmp_path / "already-created"
    output.mkdir()
    with pytest.raises(FileExistsError):
        runner._reserve_output(output)


def test_seed_condition_unit_keys_unique_and_partial_summary_rejected():
    keys = [f"{runner._condition_key(c)}__seed-{s}" for c in runner.CONDITIONS for s in factorial.SEEDS]
    assert len(keys) == len(set(keys)) == 55
    with pytest.raises(ValueError, match="exactly five seed"):
        runner._summarize_condition(runner.CONDITIONS[0], [{"seed": 42, "metrics": {}}])


def test_raw_mask_and_sample_pairing_survives_condition_changes():
    for condition in runner.CONDITIONS:
        runner._verify_mask_pairing(42, condition)
    a = factorial.generate(42, error_rate=0, reject_rate=0)
    b = factorial.generate(42, error_rate=0.2, reject_rate=0.2)
    assert {s.sample_id for s in a} == {s.sample_id for s in b}
    assert {s.metadata["mask_hash"] for s in a} == {s.metadata["mask_hash"] for s in b}
    assert all(s.raw_array.shape == (192, 192) for s in a + b)


def test_realized_rates_report_total_and_nonrejected_error_denominators():
    condition = {"label_policy": "marginal_shuffle", "error_rate": 0.2, "reject_rate": 0.2}
    result = runner._condition_rates(42, condition)
    assert result["fail_defects"] == 24 * 20
    assert result["rejected_defects"] == 24 * 4
    assert result["flipped_known_labels"] == 24 * 4
    assert result["realized_error_rate_all_defects"] == pytest.approx(0.2)
    assert result["realized_error_rate_non_rejected_denominator"] == pytest.approx(0.25)
    assert result["realized_reject_rate_all_defects"] == pytest.approx(0.2)
    assert result["class_coverage"]["A"] + result["class_coverage"]["B"] == result["known_label_defects"]
    assert result["class_coverage"]["unknown_reject"] == result["rejected_defects"]


def test_embedding_cache_reuses_rendered_bytes_across_condition_calls():
    calls = []

    def fake_encoder(rgb, view):
        calls.append((rgb.tobytes(), view))
        return np.array([3.0, 4.0])

    cached, counter = runner.PRIMARY_RUNNER._cached_embedding(fake_encoder, "fixed-spec")
    sample_one = factorial.generate(42, error_rate=0, reject_rate=0)[0]
    sample_two = factorial.generate(42, error_rate=0.2, reject_rate=0.2)[0]
    cached(sample_one.raw_array, "raw")
    cached(sample_two.raw_array, "raw")
    assert len(calls) == 1
    assert counter["count"] == 1


def test_audit_seed_never_satisfies_five_seed_summary_contract():
    with pytest.raises(ValueError, match="exactly five seed"):
        runner._summarize_condition(runner.CONDITIONS[0], [{"seed": 42, "metrics": {}}])


@pytest.mark.parametrize("failed_name", ["result.json", "progress.json", "commit.json", "manifest.json"])
def test_write_failure_never_counts_unit_as_committed(tmp_path, monkeypatch, failed_name):
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    manifest_path = tmp_path / "manifest.json"
    condition = runner.CONDITIONS[0]
    key = f"{runner._condition_key(condition)}__seed-42"
    manifest = {"completed_units": []}
    real_atomic = runner._atomic_json
    failed = {"once": False}

    def injected(path, value):
        if Path(path).name == failed_name and not failed["once"]:
            failed["once"] = True
            raise OSError(f"injected {failed_name} write failure")
        return real_atomic(path, value)

    monkeypatch.setattr(runner, "_atomic_json", injected)
    result = {"key": key, "condition": condition, "seed": 42, "status": "complete",
              "closed": True, "ended_utc": "2026-10-30T00:00:00Z"}
    progress = {"key": key, "condition": condition, "seed": 42, "status": "running", "closed": False}
    with pytest.raises(OSError, match="injected"):
        runner._commit_unit(unit_dir, result, progress, manifest_path, manifest)
    assert failed["once"] is True
    assert key not in manifest["completed_units"]
    assert not runner._validate_unit_commit(unit_dir, key, condition, 42, manifest)
    # No rollback deletes a result that was already written before a later write failed.
    if failed_name != "result.json":
        assert (unit_dir / "result.json").is_file()


def test_commit_requires_matching_result_hash_progress_and_manifest_key(tmp_path):
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    condition = runner.CONDITIONS[0]
    key = f"{runner._condition_key(condition)}__seed-42"
    manifest_path = tmp_path / "manifest.json"
    manifest = {"completed_units": []}
    runner._atomic_json(manifest_path, manifest)
    result = {"key": key, "condition": condition, "seed": 42, "status": "complete",
              "closed": True, "ended_utc": "2026-10-30T00:00:00Z"}
    progress = {"key": key, "condition": condition, "seed": 42, "status": "running", "closed": False}
    runner._commit_unit(unit_dir, result, progress, manifest_path, manifest)
    assert runner._validate_unit_commit(unit_dir, key, condition, 42, manifest)
    changed_manifest = {"completed_units": []}
    assert not runner._validate_unit_commit(unit_dir, key, condition, 42, changed_manifest)
    result_path = unit_dir / "result.json"
    result_path.write_bytes(result_path.read_bytes() + b" ")
    assert not runner._validate_unit_commit(unit_dir, key, condition, 42, manifest)

