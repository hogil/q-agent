from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import inspect
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import fbm_histogram_control_synthetic_20261030 as control
from research import fbm_paired_factorial_synthetic_20261030 as generator


def test_encoder_interface_and_counts_are_only_array_view():
    assert tuple(inspect.signature(control.count_encoder).parameters) == ("image_array", "view")
    image = np.zeros((192, 192), dtype=np.uint8)
    image.flat[:10] = 1
    image.flat[10:20] = 2
    assert np.array_equal(control.count_encoder(image, "object_id"), [10, 10])
    assert np.array_equal(control.count_encoder(np.stack((image, image), axis=-1), "object_id_yield"), [10, 10])
    assert np.array_equal(control.count_encoder(image, "yield"), [1, 1])
    with pytest.raises(ValueError, match="unexpected view"):
        control.count_encoder(image, "metadata")


def test_baseline_does_not_access_sample_labels_or_metadata():
    samples = generator.generate(42)
    sample = samples[0]
    # Encoder accepts no Sample object, and its output is solely determined by passed pixels.
    arr = sample.object_id_arrays_by_policy["spatial_coupled"]
    before = control.count_encoder(arr, "object_id")
    altered = replace(sample, wafer_class="hidden", metadata={"forbidden": True}, known_label_map=np.zeros_like(arr))
    assert altered.wafer_class == "hidden"
    assert np.array_equal(control.count_encoder(arr.copy(), "object_id"), before)


def test_expected_counts_are_checked_from_each_input_array():
    samples = generator.generate(42)
    control._validate_counts(samples)
    sample = samples[0]
    changed = sample.object_id_arrays_by_policy["spatial_coupled"].copy()
    changed[tuple(np.argwhere(changed == 1)[0])] = 3
    maps = dict(sample.object_id_arrays_by_policy)
    maps["spatial_coupled"] = changed
    samples[0] = replace(sample, object_id_arrays_by_policy=maps)
    with pytest.raises(ValueError, match="expected input-array A/B counts"):
        control._validate_counts(samples)


def test_self_check_is_weight_free_and_writes_nothing():
    result = control.self_check()
    assert result["status"] == "self_check_pass"
    assert result["inference_run"] is False
    assert result["output_written"] is False


def test_existing_output_is_rejected_before_primary_run(tmp_path):
    out = tmp_path / "occupied"
    out.mkdir()
    with pytest.raises(FileExistsError):
        control.run(tmp_path, out)


def test_frozen_source_gate_rejects_mismatch():
    with pytest.raises(RuntimeError, match="frozen generator source mismatch"):
        control._frozen_sources({"provenance": {"frozen_source_hashes": {"generator": {}, "evaluator": {}}}})
