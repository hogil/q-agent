"""Synthetic tests only; no real OCR engine or source image is used."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from research.document_image_ocr_adapter_20261030 import (
    OCRAdapterError,
    OCRModelConfig,
    extract_ocr_candidate,
)


class FakeEngine:
    def __init__(self, result):
        self.result = result

    def __call__(self, image_bytes):
        assert isinstance(image_bytes, bytes)
        return self.result


class FakeResult:
    boxes = [[[1, 2], [20, 2], [20, 10], [1, 10]]]
    txts = ("synthetic text",)
    scores = (0.93,)


@pytest.fixture
def setup_case(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    image = root / "synthetic.png"
    # A tiny valid PNG header is insufficient for Pillow, create one locally.
    from PIL import Image
    Image.new("RGB", (32, 24), color="white").save(image)
    models = tmp_path / "models"
    models.mkdir()
    det, rec = models / "det.onnx", models / "rec.onnx"
    det.write_bytes(b"synthetic det checkpoint")
    rec.write_bytes(b"synthetic rec checkpoint")
    cfg = OCRModelConfig("synthetic-model-v1", det, hashlib.sha256(det.read_bytes()).hexdigest(), rec, hashlib.sha256(rec.read_bytes()).hexdigest())
    available = datetime(2026, 10, 29, tzinfo=timezone.utc)
    as_of = datetime(2026, 10, 30, tzinfo=timezone.utc)
    metadata = {
        "source_document_id": "doc-synthetic",
        "source_version": "v1",
        "original_sha256": "a" * 64,
        "page": 3,
        "region_id": "figure-2",
        "region_coords": [0, 0, 32, 24],
        "chunk_id": "chunk-synthetic",
        "available_at": available,
    }
    return root, image, models, cfg, metadata, as_of


def run_case(case, **overrides):
    root, image, models, cfg, metadata, as_of = case
    args = dict(image_path=image, source_root=root, metadata=metadata, model=cfg, model_root=models,
                authorize_source=lambda _m: True, as_of=as_of,
                engine=FakeEngine(FakeResult()))
    args.update(overrides)
    return extract_ocr_candidate(**args)


def test_candidate_retains_provenance_geometry_and_ordered_confidence(setup_case):
    item = run_case(setup_case)
    assert item["source_document_id"] == "doc-synthetic"
    assert item["original_sha256"] == "a" * 64
    assert item["original_sha256_provenance"] == "caller_asserted_unverified"
    assert len(item["image_sha256"]) == 64
    assert item["page"] == 3 and item["region_id"] == "figure-2"
    assert item["image_size"] == {"width": 32, "height": 24}
    assert item["ordered_text_confidence"][0]["text"] == "synthetic text"
    assert item["ordered_text_confidence"][0]["confidence"] == 0.93
    assert item["existing_chunk_id"] == "chunk-synthetic"
    assert item["status"] == "candidate_unreviewed"
    assert item["model_checkpoint_provenance"] == "configured_checkpoint_hashes_unbound_to_engine"
    assert item["model_fingerprint_provenance"] == "caller_asserted_unverified"


def test_missing_or_denied_authorization_fails_closed(setup_case):
    with pytest.raises(OCRAdapterError, match="callback"):
        run_case(setup_case, authorize_source=None)
    with pytest.raises(OCRAdapterError, match="denied"):
        run_case(setup_case, authorize_source=lambda _m: False)
    with pytest.raises(OCRAdapterError, match="denied"):
        run_case(setup_case, authorize_source=lambda _m: 1)


def test_future_availability_and_naive_times_rejected(setup_case):
    _, _, _, _, metadata, as_of = setup_case
    metadata["available_at"] = datetime(2026, 10, 31, tzinfo=timezone.utc)
    with pytest.raises(OCRAdapterError, match="unavailable"):
        run_case(setup_case)
    metadata["available_at"] = datetime(2026, 10, 29)
    with pytest.raises(OCRAdapterError, match="timezone-aware"):
        run_case(setup_case)


def test_image_escape_and_checkpoint_hash_mismatch_rejected(setup_case, tmp_path):
    case = setup_case
    outside = tmp_path / "outside.png"
    from PIL import Image
    Image.new("RGB", (2, 2)).save(outside)
    with pytest.raises(OCRAdapterError, match="outside"):
        run_case(case, image_path=outside)
    root, _, *_ = case
    traversal = root / ".." / outside.name
    with pytest.raises(OCRAdapterError, match="'..'"):
        run_case(case, image_path=traversal)
    _, _, _, cfg, *_ = case
    wrong = OCRModelConfig(cfg.version, cfg.detection_model_path, "0" * 64,
                           cfg.recognition_model_path, cfg.recognition_sha256)
    with pytest.raises(OCRAdapterError, match="hash mismatch"):
        run_case(case, model=wrong)
    with pytest.raises(OCRAdapterError, match="outside"):
        run_case(case, model=OCRModelConfig(cfg.version, outside, cfg.detection_sha256,
                    cfg.recognition_model_path, cfg.recognition_sha256), model_root=root)


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan")])
def test_invalid_confidence_rejected(setup_case, score):
    class BadResult(FakeResult):
        scores = (score,)
    _, image, *_ = setup_case
    with pytest.raises(OCRAdapterError, match="confidence"):
        run_case(setup_case, engine=FakeEngine(BadResult()))


def test_invalid_box_and_result_cardinality_rejected(setup_case):
    class BadBox(FakeResult):
        boxes = [[[1, 2], [500, 2], [20, 10], [1, 10]]]
    with pytest.raises(OCRAdapterError, match="coordinates"):
        run_case(setup_case, engine=FakeEngine(BadBox()))
    class Unequal(FakeResult):
        txts = ()
    with pytest.raises(OCRAdapterError, match="lengths"):
        run_case(setup_case, engine=FakeEngine(Unequal()))


def test_missing_source_schema_and_secret_path_rejected(setup_case, tmp_path):
    _, _, _, _, metadata, _ = setup_case
    metadata["chunk_id"] = "chunk-synthetic"
    metadata.pop("chunk_id")
    with pytest.raises(OCRAdapterError, match="incomplete"):
        run_case(setup_case)
    metadata["chunk_id"] = "chunk-synthetic"
    secretish = tmp_path / "api_key.txt"
    secretish.write_text("synthetic-secret", encoding="utf-8")
    with pytest.raises(OCRAdapterError, match="hash mismatch"):
        run_case(setup_case, model=OCRModelConfig("v1", secretish, "0" * 64,
                    setup_case[3].recognition_model_path, setup_case[3].recognition_sha256), model_root=tmp_path)


def test_forged_original_hash_rejected_and_no_real_engine_startup(setup_case):
    _, _, _, _, metadata, _ = setup_case
    metadata["original_sha256"] = "not-a-hash"
    with pytest.raises(OCRAdapterError, match="SHA-256"):
        run_case(setup_case)
    metadata["original_sha256"] = "a" * 64
    with pytest.raises(OCRAdapterError, match="startup is disabled"):
        run_case(setup_case, engine=None)


def test_dst_fold_comparison_uses_utc_instant(setup_case):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    case = setup_case
    metadata = case[4]
    metadata["available_at"] = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1)
    as_of = datetime(2026, 11, 1, 6, 15, tzinfo=timezone.utc)
    with pytest.raises(OCRAdapterError, match="unavailable"):
        run_case(case, as_of=as_of)


def test_malformed_region_fails_before_engine(setup_case):
    _, _, _, _, metadata, _ = setup_case
    metadata["region_coords"] = [0, 0, float("inf"), 24]
    called = []
    with pytest.raises(OCRAdapterError, match="finite"):
        run_case(setup_case, engine=lambda _p: called.append(True))
    assert called == []


def test_engine_receives_same_image_snapshot_used_for_hash(setup_case):
    root, image, *_ = setup_case
    original_bytes = image.read_bytes()

    class MutatingEngine:
        def __call__(self, image_bytes):
            assert image_bytes == original_bytes
            image.write_bytes(b"changed after the adapter snapshot")
            return FakeResult()

    item = run_case(setup_case, engine=MutatingEngine())
    assert item["image_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert image.read_bytes() != original_bytes
