from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import fbm_paired_factorial_synthetic_20261030 as factorial
from research import fbm_paired_model_runner_synthetic_20261030 as runner
from research import fbm_paired_retrieval_eval_synthetic_20261030 as evaluator


def _configure_fake_run(monkeypatch, tmp_path, seeds):
    calls = {"load": 0, "interop": 0, "cap": 0, "network": 0}

    def fake_load_encoder(*args):
        calls["load"] += 1
        calls["interop"] += 1
        return None

    def fake_encoder(backbone, head, expected_backbone, expected_head):
        runner._BASE._load_encoder(backbone, head, expected_backbone, expected_head)
        return (lambda array, view: np.array([1.0, 0.5, 0.25])), {
            "backbone_sha256": "a" * 64, "head_sha256": "b" * 64,
            "checkpoint_sha256": "c" * 64, "encoder_spec_sha256": "d" * 64}

    monkeypatch.setattr(runner, "SEEDS", tuple(seeds))
    monkeypatch.setattr(runner._BASE, "_job_memory_cap", lambda: calls.__setitem__("cap", calls["cap"] + 1))
    monkeypatch.setattr(runner._BASE, "_disable_network", lambda: calls.__setitem__("network", calls["network"] + 1))
    monkeypatch.setattr(runner._BASE, "_load_encoder", fake_load_encoder)
    monkeypatch.setattr(runner, "_encoder", fake_encoder)
    monkeypatch.setenv("QAGENT_FBM_MODEL_LOAD_GATE", runner.RUN_GATE)
    backbone, head = tmp_path / "backbone.pt", tmp_path / "head.pt"
    backbone.write_bytes(b"synthetic test checkpoint path")
    head.write_bytes(b"synthetic test projection path")
    return calls, backbone, head


def test_renderer_shapes_palettes_and_invalid_codes():
    raw = np.zeros((192, 192), dtype=np.uint8)
    raw[3, 4] = 1
    rgb = runner._render(raw, "raw")
    assert rgb.shape == (192, 192, 3)
    assert tuple(rgb[3, 4]) == (255, 255, 255)
    assert tuple(rgb[0, 0]) == (0, 0, 0)

    ids = np.full((192, 192), 3, dtype=np.uint8)
    ids[0, :3] = (0, 1, 2)
    rgb = runner._render(ids, "object_id")
    assert tuple(rgb[0, 0]) == (255, 220, 0)
    assert tuple(rgb[0, 1]) == (255, 0, 0)
    assert tuple(rgb[0, 2]) == (0, 0, 255)
    assert tuple(rgb[1, 1]) == (0, 0, 0)

    yld = np.zeros((192, 192), dtype=np.uint8)
    yld[0, :3] = (0, 1, 255)
    rgb = runner._render(yld, "yield")
    assert [tuple(rgb[0, i]) for i in range(3)] == [(0, 0, 0), (255, 255, 255), (128, 128, 128)]

    combined = np.zeros((192, 192, 2), dtype=np.uint8)
    combined[0, :3] = ((1, 0), (3, 1), (1, 255))
    rgb = runner._render(combined, "object_id_yield")
    assert [tuple(rgb[0, i]) for i in range(3)] == [(255, 0, 0), (255, 255, 255), (128, 128, 128)]

    with pytest.raises(ValueError):
        runner._render(np.zeros((192, 192, 1), dtype=np.uint8), "raw")
    with pytest.raises(ValueError):
        runner._render(np.full((192, 192), 2, dtype=np.uint8), "raw")
    with pytest.raises(ValueError):
        runner._render(np.full((192, 192), 4, dtype=np.uint8), "object_id")
    with pytest.raises(ValueError):
        runner._render(np.full((192, 192, 2), 2, dtype=np.uint8), "object_id_yield")


def test_renderer_uses_only_array_and_view():
    captured = []

    def embed(rgb, view):
        captured.append((rgb.copy(), view))
        return np.array([1.0, 2.0])

    wrapped, _ = runner._cached_embedding(embed, "fake-spec")
    array = np.zeros((192, 192), dtype=np.uint8)
    vector = wrapped(array, "raw")
    assert vector.shape == (2,)
    assert captured[0][0].shape == (192, 192, 3)
    assert captured[0][1] == "raw"
    assert np.isclose(np.linalg.norm(vector), 1.0)


def test_mocked_two_seed_run_loads_once_and_uses_two_argument_callback(tmp_path, monkeypatch):
    if runner.os.name != "nt":
        pytest.skip("runner resource cap requires Windows")
    calls = {"load": 0, "interop": 0, "cap": 0, "network": 0, "inputs": []}

    class FakeTorch:
        @staticmethod
        def set_num_interop_threads(value):
            assert value == 1
            calls["interop"] += 1

    def fake_load_encoder(*args):
        calls["load"] += 1
        FakeTorch.set_num_interop_threads(1)
        return None

    def fake_encoder(backbone, head, expected_backbone, expected_head):
        runner._BASE._load_encoder(backbone, head, expected_backbone, expected_head)

        def compute(rgb, view):
            assert isinstance(rgb, np.ndarray)
            assert rgb.shape == (192, 192, 3)
            assert view in ("raw", "object_id", "yield", "object_id_yield")
            calls["inputs"].append((rgb.copy(), view))
            return np.array([1.0, 0.25, 0.5])

        embed, _cache = runner._cached_embedding(compute, "mock-encoder-spec")
        return embed, {"backbone_sha256": "a" * 64, "head_sha256": "b" * 64,
                       "checkpoint_sha256": "c" * 64, "encoder_spec_sha256": "d" * 64}

    monkeypatch.setattr(runner, "SEEDS", (42, 1))
    monkeypatch.setattr(runner._BASE, "_job_memory_cap", lambda: calls.__setitem__("cap", calls["cap"] + 1))
    monkeypatch.setattr(runner._BASE, "_disable_network", lambda: calls.__setitem__("network", calls["network"] + 1))
    monkeypatch.setattr(runner._BASE, "_load_encoder", fake_load_encoder)
    monkeypatch.setattr(runner, "_encoder", fake_encoder)
    monkeypatch.setenv("QAGENT_FBM_MODEL_LOAD_GATE", runner.RUN_GATE)
    out = tmp_path / "run-output"
    backbone, head = tmp_path / "backbone.pt", tmp_path / "head.pt"
    backbone.write_bytes(b"synthetic test checkpoint path")
    head.write_bytes(b"synthetic test projection path")

    assert runner.main(["--run", "--output-dir", str(out), "--seed", "42",
                        "--backbone", str(backbone), "--head", str(head),
                        "--expected-backbone-sha256", "a" * 64,
                        "--expected-head-sha256", "b" * 64]) == 0
    # The test asks for two seeds by adjusting the allowed cohort tuple and omitting --seed.
    # The first call above intentionally ran one seed; now validate full orchestration in a
    # separate fresh output tree with the same fake encoder.
    assert calls["load"] == 1
    assert calls["interop"] == 1
    assert calls["cap"] == calls["network"] == 1
    first_manifest = __import__("json").loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest["closed"] is True
    assert len(first_manifest["results"]) == 1
    assert first_manifest["results"][0]["closed"] is True
    assert calls["inputs"] and all(isinstance(image, np.ndarray) for image, _ in calls["inputs"])

    # Run the intended two-seed path without reusing any existing output.
    calls.update(load=0, interop=0, cap=0, network=0, inputs=[])
    out2 = tmp_path / "run-output-two"
    assert runner.main(["--run", "--output-dir", str(out2), "--backbone", str(backbone),
                        "--head", str(head), "--expected-backbone-sha256", "a" * 64,
                        "--expected-head-sha256", "b" * 64]) == 0
    import json
    manifest = json.loads((out2 / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["closed"] is True
    assert manifest["factorial_complete"] is False
    assert [row["seed"] for row in manifest["results"]] == [42, 1]
    assert all(row["closed"] is True for row in manifest["results"])
    assert len(manifest["provenance"]["encoder_source_sha256"]) == 64
    for row in manifest["results"]:
        assert row["encoder_source_sha256"] == manifest["provenance"]["encoder_source_sha256"]
        usage = row["resource_usage"]
        assert usage["wall_elapsed_seconds"] >= 0
        assert usage["process_cpu_seconds"] >= 0
        assert "process-lifetime cumulative" in usage["peak_scope"]
        if usage["peak_process_working_set_bytes"] is None:
            assert usage["peak_process_working_set_reason"]
    assert calls["load"] == calls["interop"] == 1
    assert calls["cap"] == calls["network"] == 1
    assert calls["inputs"] and all(isinstance(image, np.ndarray) for image, _ in calls["inputs"])


def test_cache_keys_rendered_bytes_view_and_encoder_spec():
    calls = []

    def fake(rgb, view):
        calls.append(view)
        return np.array([3.0, 4.0])

    first, counter = runner._cached_embedding(fake, "spec-A")
    arr = np.zeros((192, 192), dtype=np.uint8)
    one = first(arr, "raw")
    two = first(arr.copy(), "raw")
    assert calls == ["raw"]
    assert counter["count"] == 1
    assert np.array_equal(one, two)

    first(arr, "yield")
    assert calls == ["raw", "yield"]
    second, second_counter = runner._cached_embedding(fake, "spec-B")
    second(arr, "raw")
    assert calls == ["raw", "yield", "raw"]
    assert second_counter["count"] == 1


def test_duplicate_cross_split_group_and_incomplete_cohort_rejected():
    samples = factorial.generate(42)
    query_index = next(i for i, s in enumerate(samples) if s.split == "query")
    gallery_group = next(s.lineage_group_id for s in samples if s.split == "gallery")
    samples[query_index] = replace(samples[query_index], lineage_group_id=gallery_group)
    with pytest.raises(ValueError, match="lineage group crosses"):
        evaluator._validate_cohort(samples, 0.0, 0.0)

    samples = factorial.generate(42)
    with pytest.raises(ValueError, match="expected exactly 12 gallery and 12 query"):
        evaluator._validate_cohort(samples[:-1], 0.0, 0.0)


def test_incomplete_manifest_cannot_claim_factorial_completion():
    assert len(runner.UNRUN_CONDITIONS) == 11
    assert runner._self_check()["inference_run"] is False
    assert runner._self_check()["unrun_factorial_conditions"] == 11


def test_resource_usage_formula_and_memory_failure_are_explicit_null():
    mark = {"wall_monotonic": 10.0, "process_cpu": 4.0}
    measured = runner._resource_usage(mark, wall_end=12.5, cpu_end=4.75,
                                      memory_reader=lambda: (4096, None))
    assert measured["wall_elapsed_seconds"] == 2.5
    assert measured["process_cpu_seconds"] == 0.75
    assert measured["peak_process_working_set_bytes"] == 4096
    assert measured["peak_process_working_set_reason"] is None
    assert "process-lifetime cumulative" in measured["peak_scope"]

    def unavailable():
        raise OSError("test unavailable")

    missing = runner._resource_usage(mark, wall_end=12.0, cpu_end=4.5, memory_reader=unavailable)
    assert missing["peak_process_working_set_bytes"] is None
    assert "OSError: test unavailable" in missing["peak_process_working_set_reason"]


def test_run_cli_fails_closed_without_audited_environment_gate(monkeypatch):
    monkeypatch.delenv("QAGENT_FBM_MODEL_LOAD_GATE", raising=False)
    with pytest.raises(SystemExit) as exc:
        runner.main(["--run", "--output-dir", "unused", "--backbone", "bb",
                     "--head", "hd", "--expected-backbone-sha256", "0" * 64,
                     "--expected-head-sha256", "1" * 64])
    assert exc.value.code == 2


def test_five_seed_primary_summary_uses_seed_level_statistics(tmp_path, monkeypatch):
    if runner.os.name != "nt":
        pytest.skip("runner resource cap requires Windows")
    calls, backbone, head = _configure_fake_run(monkeypatch, tmp_path, (42, 1, 2, 3, 4))
    deltas = {42: 0.5, 1: -0.1, 2: 0.0, 3: 0.3, 4: -0.2}

    def fake_evaluate(samples, embedding_fn, **kwargs):
        seed = samples[0].master_seed
        assert len(samples) == 24
        return {"seed": seed, "gallery_count": 12, "query_count": 12,
                "paired_mean_differences_vs_raw": {"object_id_yield": {"hit_at_3": deltas[seed]}},
                "query_rows_are_not_independent_replicates": True}

    monkeypatch.setattr(runner.EVALUATOR, "evaluate", fake_evaluate)
    out = tmp_path / "five-seed"
    runner.main(["--run", "--output-dir", str(out), "--backbone", str(backbone),
                 "--head", str(head), "--expected-backbone-sha256", "a" * 64,
                 "--expected-head-sha256", "b" * 64])
    import json
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    summary = manifest["five_seed_primary_summary"]
    values = [deltas[s] for s in (42, 1, 2, 3, 4)]
    assert manifest["closed"] is True
    assert summary["independent_unit"] == "master_seed"
    assert summary["query_rows_are_not_independent_replicates"] is True
    assert summary["n"] == 5
    assert summary["seed_deltas"] == values
    assert summary["mean"] == pytest.approx(np.mean(values))
    assert summary["median"] == pytest.approx(np.median(values))
    assert summary["population_sd"] == pytest.approx(np.std(values, ddof=0))
    assert summary["range"] == [min(values), max(values)]
    assert calls["load"] == calls["interop"] == calls["cap"] == calls["network"] == 1


def test_intermediate_seed_error_closes_failure_manifests_and_preserves_prior_result(tmp_path, monkeypatch):
    if runner.os.name != "nt":
        pytest.skip("runner resource cap requires Windows")
    _calls, backbone, head = _configure_fake_run(monkeypatch, tmp_path, (42, 1))

    def fake_evaluate(samples, embedding_fn, **kwargs):
        seed = samples[0].master_seed
        if seed == 1:
            raise ValueError("mock seed failure")
        return {"seed": seed, "gallery_count": 12, "query_count": 12,
                "paired_mean_differences_vs_raw": {"object_id_yield": {"hit_at_3": 0.25}}}

    monkeypatch.setattr(runner.EVALUATOR, "evaluate", fake_evaluate)
    out = tmp_path / "seed-failure"
    with pytest.raises(ValueError, match="mock seed failure"):
        runner.main(["--run", "--output-dir", str(out), "--backbone", str(backbone),
                     "--head", str(head), "--expected-backbone-sha256", "a" * 64,
                     "--expected-head-sha256", "b" * 64])
    import json
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    first_progress = json.loads((out / "seed-42/progress.json").read_text(encoding="utf-8"))
    failed_progress = json.loads((out / "seed-1/progress.json").read_text(encoding="utf-8"))
    assert (out / "seed-42/result.json").is_file()
    assert not (out / "seed-1/result.json").exists()
    assert first_progress["closed"] is True
    assert failed_progress["status"] == "failed_or_interrupted"
    assert failed_progress["closed"] is True
    assert manifest["status"] == "failed_or_interrupted"
    assert manifest["closed"] is True
    assert len(manifest["results"]) == 1
    assert "five_seed_primary_summary" not in manifest


def test_midrun_source_mutation_blocks_following_seed_and_completion(tmp_path, monkeypatch):
    if runner.os.name != "nt":
        pytest.skip("runner resource cap requires Windows")
    _calls, backbone, head = _configure_fake_run(monkeypatch, tmp_path, (42, 1))
    baseline = runner._current_source_hashes()
    counter = {"n": 0}

    def mutate_second_seed_check():
        counter["n"] += 1
        snapshot = {key: dict(value) for key, value in baseline.items()}
        if counter["n"] >= 4:
            snapshot["plan"]["sha256"] = "f" * 64
        return snapshot

    monkeypatch.setattr(runner, "_current_source_hashes", mutate_second_seed_check)
    monkeypatch.setattr(runner.EVALUATOR, "evaluate", lambda samples, embedding_fn, **kwargs:
                        {"seed": samples[0].master_seed, "gallery_count": 12, "query_count": 12,
                         "paired_mean_differences_vs_raw": {"object_id_yield": {"hit_at_3": 0.0}}})
    out = tmp_path / "source-mutation"
    with pytest.raises(RuntimeError, match="source hash changed before seed 1"):
        runner.main(["--run", "--output-dir", str(out), "--backbone", str(backbone),
                     "--head", str(head), "--expected-backbone-sha256", "a" * 64,
                     "--expected-head-sha256", "b" * 64])
    import json
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert (out / "seed-42/result.json").is_file()
    assert not (out / "seed-1/result.json").exists()
    assert manifest["status"] == "failed_or_interrupted"
    assert manifest["closed"] is True
    assert len(manifest["results"]) == 1
    assert "five_seed_primary_summary" not in manifest

