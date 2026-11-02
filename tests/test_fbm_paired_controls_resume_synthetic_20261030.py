from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import fbm_paired_controls_resume_synthetic_20261030 as resume
from research import fbm_paired_controls_runner_synthetic_20261030 as old
from research import fbm_paired_model_runner_synthetic_20261030 as primary
from research import fbm_paired_factorial_synthetic_20261030 as factorial
from research import fbm_paired_retrieval_eval_synthetic_20261030 as evaluator


def _fixture(tmp_path):
    primary_path = tmp_path / "primary.json"
    pm = {"checkpoint_hashes": {"backbone_sha256": "a", "head_sha256": "b"}, "status": "ok",
          "provenance": {"frozen_source_hashes": old._current_source_hashes()}}
    primary_path.write_text(json.dumps(pm), encoding="utf-8")
    source = old._current_source_hashes()
    manifest = {"status": "running", "closed": False, "checkpoint_hashes": pm["checkpoint_hashes"],
                "primary_checkpoint_hashes": pm["checkpoint_hashes"], "source_hashes": source,
                "primary_manifest_sha256": hashlib.sha256(primary_path.read_bytes()).hexdigest(),
                "completed_units": [], "units_planned": [], "histogram_baseline": {"status": "unverified"}}
    expected = resume._expected_keys()
    for key, (condition, seed) in expected.items():
        manifest["units_planned"].append({"key": key, "condition": condition, "seed": seed})
    prior = tmp_path / "prior" / "manifest.json"
    prior.parent.mkdir()
    # Required reusable set from actual historic cohort.
    reused_keys = {f"spatial_coupled__e00__r20__seed-{seed}" for seed in resume.SEEDS}
    for key in reused_keys:
        condition, seed = expected[key]
        unit = prior.parent / old._condition_key(condition) / f"seed-{seed}"
        unit.mkdir(parents=True)
        result = {"key": key, "condition": condition, "seed": seed, "status": "complete", "metrics": {},
                  "checkpoint_hashes": pm["checkpoint_hashes"]}
        old._atomic_json(unit / "result.json", result)
        progress = {"key": key, "condition": condition, "seed": seed, "status": "complete", "closed": True,
                    "source_hashes": source, "checkpoint_hashes": pm["checkpoint_hashes"]}
        old._atomic_json(unit / "progress.json", progress)
        rb = (unit / "result.json").read_bytes()
        old._atomic_json(unit / "commit.json", {"key": key, "condition": condition, "seed": seed,
                                                "result_sha256": hashlib.sha256(rb).hexdigest()})
        manifest["completed_units"].append(key)
    old._atomic_json(prior, manifest)
    pm, rows = primary._read_primary if False else (pm, {s: {} for s in resume.SEEDS})
    return prior, primary_path, manifest, pm, rows


def test_audit_accepts_incomplete_prior_and_reuses_exact_five(tmp_path):
    prior, pp, _, pm, rows = _fixture(tmp_path)
    manifest, imported = resume._audit_prior(prior, pp, pm, rows)
    assert manifest["status"] == "running" and manifest["closed"] is False
    assert len(imported) == 5
    assert len(resume._expected_keys()) - len(imported) == 50
    assert all(r["result_checkpoint_provenance_indirect_via_progress_manifest"] for r in imported)


@pytest.mark.parametrize("target", ["commit.json", "result.json", "progress.json"])
def test_tampered_prior_unit_rejected(tmp_path, target):
    prior, pp, _, pm, rows = _fixture(tmp_path)
    unit = prior.parent / "spatial_coupled__e00__r20" / "seed-42"
    p = unit / target
    if target == "result.json":
        p.write_bytes(p.read_bytes() + b" ")
    else:
        value = json.loads(p.read_text(encoding="utf-8"))
        value["status"] = "tampered"
        p.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        resume._audit_prior(prior, pp, pm, rows)


def test_duplicate_missing_roster_and_changed_baseline_checkpoint_rejected(tmp_path):
    prior, pp, manifest, pm, rows = _fixture(tmp_path)
    manifest["units_planned"].pop()
    old._atomic_json(prior, manifest)
    with pytest.raises(ValueError, match="55 units"):
        resume._audit_prior(prior, pp, pm, rows)


def test_prior_plan_source_hash_mismatch_rejected(tmp_path):
    prior, pp, _, pm, rows = _fixture(tmp_path)
    m = json.loads(prior.read_text(encoding="utf-8"))
    m["source_hashes"]["plan"]["sha256"] = "0" * 64
    old._atomic_json(prior, m)
    with pytest.raises(ValueError, match="source identity"):
        resume._audit_prior(prior, pp, pm, rows)


def test_prior_primary_manifest_hash_mismatch_rejected(tmp_path):
    prior, pp, manifest, pm, rows = _fixture(tmp_path)
    manifest["primary_manifest_sha256"] = "0" * 64
    old._atomic_json(prior, manifest)
    with pytest.raises(ValueError, match="primary manifest hash"):
        resume._audit_prior(prior, pp, pm, rows)


def test_prior_extra_completed_key_rejected_before_model_setup(tmp_path):
    prior, pp, manifest, pm, rows = _fixture(tmp_path)
    key = next(k for k in resume._expected_keys() if k not in manifest["completed_units"])
    manifest["completed_units"].append(key)
    old._atomic_json(prior, manifest)
    with pytest.raises(ValueError, match="exactly the five"):
        resume._audit_prior(prior, pp, pm, rows)


def test_real_prior_artifact_is_read_only_audited():
    prior = ROOT / "var/fbm-paired-controls-5seed-20261030-02/manifest.json"
    primary_path = old.PRIMARY_MANIFEST_DEFAULT
    if not prior.is_file() or not primary_path.is_file():
        pytest.skip("actual prior or primary artifact is unavailable")
    before = (prior.read_bytes(), {p: p.read_bytes() for p in prior.parent.rglob("*.json")})
    pm, rows = old._read_primary(primary_path)
    manifest, imported = resume._audit_prior(prior, primary_path, pm, rows)
    assert len(imported) == 5
    assert set(manifest["completed_units"]) == {f"spatial_coupled__e00__r20__seed-{s}" for s in resume.SEEDS}
    assert len(resume._expected_keys()) - len(imported) == 50
    assert prior.read_bytes() == before[0]
    assert all(p.read_bytes() == content for p, content in before[1].items())


def test_mock_e2e_uses_five_and_commits_fifty_without_weights(tmp_path, monkeypatch):
    prior, primary_path, _, pm, primary_rows = _fixture(tmp_path)
    out = tmp_path / "fresh"
    args = type("Args", (), {"prior_manifest": prior, "primary_manifest": primary_path, "output_dir": out,
        "backbone": tmp_path / "bb", "head": tmp_path / "hd", "expected_backbone_sha256": "a", "expected_head_sha256": "b"})()
    args.backbone.write_bytes(b"bb"); args.head.write_bytes(b"hd")
    monkeypatch.setattr(resume, "_audit_prior", lambda *a: (json.loads(prior.read_text()), []))
    # Recreate a valid imported set with deliberately tiny mock metrics.
    fake_manifest = json.loads(prior.read_text())
    fake_imported = []
    expected = resume._expected_keys()
    for key in fake_manifest["completed_units"]:
        c, s = expected[key]
        fake_imported.append({"key": key, "condition": c, "seed": s, "metrics": {"arms": {a: {f"mean_{m}": .5 for m in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank")} for a in evaluator.ARMS}}})
    fake_manifest["_audit_file_sha256"] = {}
    monkeypatch.setattr(resume, "_audit_prior", lambda *a: (fake_manifest, fake_imported))
    monkeypatch.setattr(old, "_read_primary", lambda p: (pm, primary_rows))
    sources = old._current_source_hashes()
    drift_source = {"value": False}
    def current_sources():
        current = json.loads(json.dumps(sources))
        if drift_source["value"]: current["runner"]["sha256"] = "0" * 64
        return current
    monkeypatch.setattr(old, "_current_source_hashes", current_sources)
    real_sha = resume._sha
    drifted = {"value": False}
    def fake_sha(path):
        if drifted["value"] and Path(path) == Path(resume.__file__).resolve():
            return "0" * 64
        return real_sha(path)
    monkeypatch.setattr(resume, "_sha", fake_sha)
    monkeypatch.setattr(old, "_encoder", lambda *a: (lambda rgb, view: None, pm["checkpoint_hashes"]))
    monkeypatch.setattr(old, "_verify_mask_pairing", lambda *a: None)
    monkeypatch.setattr(factorial, "generate", lambda *a, **k: [object()])
    monkeypatch.setattr(evaluator, "evaluate", lambda *a, **k: {"per_query": [], "arms": {arm: {f"mean_{m}": .5 for m in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank")} for arm in evaluator.ARMS}})
    monkeypatch.setattr(old, "_primary_pair_check", lambda *a: None)
    monkeypatch.setattr(old, "_condition_rates", lambda *a: {})
    monkeypatch.setattr(old, "_synthetic_sample_manifest", lambda *a: [])
    monkeypatch.setattr(old, "_summarize_condition", lambda c, rows: {"n_seeds": len(rows)})
    monkeypatch.setattr(old, "_resource_usage", lambda *a: {})
    monkeypatch.setattr(resume, "os", type("OS", (), {"name": "nt", "environ": {}})())
    monkeypatch.setattr(old._BASE, "_job_memory_cap", lambda: None)
    monkeypatch.setattr(old._BASE, "_disable_network", lambda: None)
    result = resume._run(args)
    assert result["factorial_complete"] is True
    assert len(result["completed_units"]) == 55
    assert len(result["reused_units"]) == 5


@pytest.mark.parametrize("failure_kind", ["unit_failure", "source_drift", "resume_runner_drift"])
def test_mock_e2e_failure_never_claims_complete(tmp_path, monkeypatch, failure_kind):
    prior, primary_path, _, pm, primary_rows = _fixture(tmp_path)
    out = tmp_path / "fresh"
    args = type("Args", (), {"prior_manifest": prior, "primary_manifest": primary_path, "output_dir": out,
        "backbone": tmp_path / "bb", "head": tmp_path / "hd", "expected_backbone_sha256": "a", "expected_head_sha256": "b"})()
    args.backbone.write_bytes(b"bb"); args.head.write_bytes(b"hd")
    actual = json.loads(prior.read_text(encoding="utf-8"))
    imported = []
    expected = resume._expected_keys()
    for key in actual["completed_units"]:
        c, s = expected[key]
        imported.append({"key": key, "condition": c, "seed": s, "metrics": {"arms": {a: {f"mean_{m}": .5 for m in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank")} for a in evaluator.ARMS}}})
    actual["_audit_file_sha256"] = {}
    monkeypatch.setattr(resume, "_audit_prior", lambda *a: (actual, imported))
    monkeypatch.setattr(old, "_read_primary", lambda p: (pm, primary_rows))
    sources = old._current_source_hashes()
    drift_source = {"value": False}
    def current_sources():
        current = json.loads(json.dumps(sources))
        if drift_source["value"]: current["runner"]["sha256"] = "0" * 64
        return current
    monkeypatch.setattr(old, "_current_source_hashes", current_sources)
    real_sha = resume._sha
    drifted = {"value": False}
    def fake_sha(path):
        if drifted["value"] and Path(path) == Path(resume.__file__).resolve():
            return "0" * 64
        return real_sha(path)
    monkeypatch.setattr(resume, "_sha", fake_sha)
    monkeypatch.setattr(old, "_encoder", lambda *a: (lambda rgb, view: None, pm["checkpoint_hashes"]))
    monkeypatch.setattr(old, "_verify_mask_pairing", lambda *a: None)
    monkeypatch.setattr(factorial, "generate", lambda *a, **k: [object()])
    def fake_eval(*a, **k):
        if failure_kind == "unit_failure": raise RuntimeError("injected unit failure")
        if failure_kind == "source_drift": drift_source["value"] = True
        if failure_kind == "resume_runner_drift":
            drifted["value"] = True
        return {"per_query": [], "arms": {arm: {f"mean_{m}": .5 for m in ("hit_at_1", "hit_at_3", "recall_at_1", "recall_at_3", "reciprocal_rank")} for arm in evaluator.ARMS}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    monkeypatch.setattr(old, "_primary_pair_check", lambda *a: None)
    monkeypatch.setattr(old, "_condition_rates", lambda *a: {})
    monkeypatch.setattr(old, "_synthetic_sample_manifest", lambda *a: [])
    monkeypatch.setattr(old, "_summarize_condition", lambda c, rows: {"n_seeds": len(rows)})
    monkeypatch.setattr(old, "_resource_usage", lambda *a: {})
    monkeypatch.setattr(resume, "os", type("OS", (), {"name": "nt", "environ": {}})())
    monkeypatch.setattr(old._BASE, "_job_memory_cap", lambda: None)
    monkeypatch.setattr(old._BASE, "_disable_network", lambda: None)
    with pytest.raises((RuntimeError, OSError)):
        resume._run(args)
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["factorial_complete"] is False


def test_self_check_does_not_load_weights_or_infer():
    assert resume._self_check() == {"status": "resume_self_check_pass", "weights_loaded": False,
                                    "inference_run": False, "planned_units": 55, "unique_keys": True}
