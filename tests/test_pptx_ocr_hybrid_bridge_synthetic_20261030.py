"""Synthetic bridge exercise only; not real OCR, ACL, or internal-index proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from research.pptx_ocr_hybrid_bridge_synthetic_20261030 import (
    PPTXBridgeError, bind_pptx_candidate, search_bound_pptx,
)
from research.ocr_temporal_scoped_hybrid_20261030 import ScopedTemporalError
from research.pptx_embedded_image_ocr_synthetic_20261030 import extract_pptx_embedded_image_ocr_candidates


UTC = timezone.utc
AS_OF = "2026-03-20"
CUTOFF = datetime(2026, 3, 21, tzinfo=UTC)
ANALYSIS_AT = datetime(2026, 3, 22, 12, tzinfo=UTC)
SOURCE_AT = datetime(2026, 3, 1, 9, tzinfo=UTC)
OCR_AT = datetime(2026, 3, 2, 9, tzinfo=UTC)
EMBED_AT = datetime(2026, 3, 3, 9, tzinfo=UTC)
IMAGE = "a" * 64
SNAPSHOT = "b" * 64


def fixture():
    source = {"document_id": "doc-syn", "chunk_id": "chunk-source", "version": "v3",
              "source_ref": "synthetic://pptx-1", "incident_ids": ["INC-SYN-1"],
              "available_at": SOURCE_AT.isoformat(), "status": "active", "relation": "direct",
              "synthetic_fixture": True}
    anchor = "ppt/slides/slide4.xml#shape-9"
    candidate = {"source_document_id": "doc-syn", "source_version": "v3", "existing_chunk_id": "chunk-source",
                 "chunk_link_status": "caller_asserted_unverified", "slide_ordinal": 2,
                 "slide_file_number": 4, "slide_ordinal_status": "presentation_order_resolved",
                 "picture_shape_id": "9", "anchor_id": anchor, "image_sha256": IMAGE,
                 "original_sha256": SNAPSHOT, "region_coords": [2, 3, 120, 80],
                 "image_size": {"width": 128, "height": 96}, "source_available_at": SOURCE_AT.isoformat(),
                 "available_at": None,
                 "ordered_text_confidence": [{"text": "synthetic bearing temperature", "confidence": 0.93}],
                 "status": "candidate_unreviewed"}
    locator = {"locator_type": "pptx_embedded_picture", "slide_ordinal": 2, "slide_file_number": 4,
               "picture_shape_id": "9", "anchor_id": anchor, "image_sha256": IMAGE,
               "source_snapshot_sha256": SNAPSHOT, "image_bbox": [2, 3, 120, 80],
               "coordinate_frame": "image_pixels", "image_size": {"width": 128, "height": 96},
               "originating_chunk_id": "chunk-source", "ocr_confidence": [0.93]}
    artifacts = {
        "source_version": {"id": "doc-syn", "version": "v3", "available_at": SOURCE_AT},
        "ocr_model": {"id": "ocr-syn-model", "version": "1", "available_at": SOURCE_AT},
        "ocr_output": {"id": "ocr-syn", "version": "1", "available_at": OCR_AT, "generated_at": OCR_AT,
                       "dependencies": {"source_version": {"id": "doc-syn", "version": "v3"},
                                        "ocr_model": {"id": "ocr-syn-model", "version": "1"}}},
        "embedding_model": {"id": "embed-syn-model", "version": "1", "available_at": OCR_AT},
        "embedding_output": {"id": "embed-syn", "version": "1", "available_at": EMBED_AT, "generated_at": EMBED_AT,
                             "dependencies": {"ocr_output": {"id": "ocr-syn", "version": "1"},
                                              "embedding_model": {"id": "embed-syn-model", "version": "1"}}},
        "index_snapshot": {"id": "index-syn", "version": "1", "available_at": EMBED_AT, "generated_at": EMBED_AT,
                           "dependencies": {"ocr_output": {"id": "ocr-syn", "version": "1"},
                                            "embedding_output": {"id": "embed-syn", "version": "1"}}},
    }
    manifest = {"provenance": "caller_asserted_unverified_synthetic_manifest", "image_sha256": IMAGE,
                "anchor_id": anchor, "source_snapshot_sha256": SNAPSHOT, "candidate_available_at": None}
    for name in ("ocr_output", "embedding_output"):
        manifest[name] = {k: artifacts[name][k] for k in ("id", "version", "available_at", "generated_at")}
        manifest[name]["binding"] = {"image_sha256": IMAGE, "anchor_id": anchor,
                                      "source_snapshot_sha256": SNAPSHOT}
    chunk = bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    return source, candidate, locator, artifacts, manifest, chunk


def test_pptx_locator_survives_temporal_hybrid_and_app_contract(monkeypatch):
    import research.pptx_ocr_hybrid_bridge_synthetic_20261030 as bridge

    source, _, _, artifacts, _, chunk = fixture()
    assert chunk["available_at"] == EMBED_AT.isoformat()
    assert chunk["source_available_at"] == SOURCE_AT.isoformat()
    assert "[기계 OCR 미검토]" in chunk["text"]
    vectors = {chunk["chunk_id"]: [1.0, 0.0]}
    validator_items = []
    app_validator = bridge.validate_hybrid_response
    def capture_validator(response, **kwargs):
        validator_items.extend(deepcopy(response["items"]))
        return app_validator(response, **kwargs)
    monkeypatch.setattr(bridge, "validate_hybrid_response", capture_validator)
    validated = search_bound_pptx(chunk=chunk, vectors=vectors, artifacts=artifacts,
        query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
        historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
        authorize=lambda _: True, authorize_document=lambda _: True)
    assert validated["status"] == "OK"
    item = validated["items"][0]
    assert validator_items[0]["available_at"] == SOURCE_AT.isoformat()
    assert validator_items[0]["source_available_at"] == SOURCE_AT.isoformat()
    assert validator_items[0]["content_kind"] == "image_ocr"
    assert validator_items[0]["derivative_available_at"] == OCR_AT.isoformat()
    assert validator_items[0]["source_available_at"] != validator_items[0]["derivative_available_at"]
    assert item["content_kind"] == "image_ocr"
    assert item["available_at"] == SOURCE_AT.isoformat()
    assert item["derivative_available_at"] == OCR_AT.isoformat()
    loc = json.loads(item["locator"])
    assert item["document_id"] == source["document_id"]
    assert loc["originating_chunk_id"] == source["chunk_id"]
    assert (loc["slide_ordinal"], loc["slide_file_number"], loc["picture_shape_id"]) == (2, 4, "9")
    assert loc["anchor_id"] == "ppt/slides/slide4.xml#shape-9"
    assert "page" not in loc
    assert loc["time_lineage_provenance"] == "caller_asserted_unverified"
    assert loc["ocr_confidence"] == [0.93]
    assert validated["retrieval_completeness"] == "unknown"
    assert validated["source_reported_candidate_count"] is None
    assert validated["source_reported_truncated"] is None
    assert validated["synthetic_only"] is True
    assert "site_acl_index_model_and_lineage_unverified" in validated["limitations"]


@pytest.mark.parametrize("mutation", [
    lambda c, s, l, a, m: c.update(chunk_link_status="unlinked"),
    lambda c, s, l, a, m: c.update(existing_chunk_id="other"),
    lambda c, s, l, a, m: c.update(source_version="wrong"),
    lambda c, s, l, a, m: c.update(slide_ordinal=88),
    lambda c, s, l, a, m: c.update(picture_shape_id="77"),
    lambda c, s, l, a, m: l.update(anchor_id="ppt/slides/slide4.xml#shape-77"),
    lambda c, s, l, a, m: l.update(source_snapshot_sha256="c" * 64),
    lambda c, s, l, a, m: m["ocr_output"]["binding"].update(image_sha256="c" * 64),
    lambda c, s, l, a, m: l.update(page=3),
    lambda c, s, l, a, m: c.update(picture_shape_id="０９"),
    lambda c, s, l, a, m: c.update(region_coords=[2, 3, 129, 80]),
    lambda c, s, l, a, m: c["ordered_text_confidence"][0].update(confidence=float("nan")),
    lambda c, s, l, a, m: c.update(source_available_at="2026-10-11T09:00:00+00:00"),
])
def test_bad_binding_candidate_or_manifest_fails_closed(mutation):
    _, candidate, locator, artifacts, manifest, _ = fixture()
    candidate, locator, artifacts, manifest = map(deepcopy, (candidate, locator, artifacts, manifest))
    mutation(candidate, None, locator, artifacts, manifest)
    with pytest.raises(PPTXBridgeError):
        bind_pptx_candidate(candidate, fixture()[0], locator=locator, artifacts=artifacts, manifest=manifest)


def test_missing_derivative_time_and_non_synthetic_source_fail_closed():
    source, candidate, locator, artifacts, manifest, _ = fixture()
    artifacts = deepcopy(artifacts); manifest = deepcopy(manifest)
    artifacts["ocr_output"]["available_at"] = None
    manifest["ocr_output"]["available_at"] = None
    with pytest.raises(PPTXBridgeError):
        bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    source["synthetic_fixture"] = False
    with pytest.raises(PPTXBridgeError):
        bind_pptx_candidate(candidate, source, locator=locator, artifacts=fixture()[3], manifest=fixture()[4])


def test_candidate_time_is_manifested_and_included_in_ready_time():
    source, candidate, locator, artifacts, manifest, _ = fixture()
    candidate["available_at"] = datetime(2026, 3, 18, tzinfo=UTC).isoformat()
    manifest["candidate_available_at"] = candidate["available_at"]
    chunk = bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    assert chunk["available_at"] == candidate["available_at"]
    candidate["available_at"] = datetime(2026, 3, 19, tzinfo=UTC).isoformat()
    with pytest.raises(PPTXBridgeError, match="manifest must explicitly assert"):
        bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    candidate["available_at"] = None
    manifest.pop("candidate_available_at")
    with pytest.raises(PPTXBridgeError, match="manifest must explicitly assert"):
        bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)


def test_source_availability_compares_exact_instants_without_float_rounding():
    source, candidate, locator, artifacts, manifest, _ = fixture()
    candidate["source_available_at"] = "2026-03-01T18:00:00+09:00"
    chunk = bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    assert chunk["source_available_at"] == SOURCE_AT.isoformat()
    distant = datetime(9000, 1, 1, tzinfo=UTC)
    source["available_at"] = distant
    candidate["source_available_at"] = distant.isoformat()
    bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    candidate["source_available_at"] = (distant + timedelta(microseconds=1)).isoformat()
    with pytest.raises(PPTXBridgeError, match="does not match the bound source"):
        bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)


def test_locator_must_be_mapping_and_cannot_claim_pdf_page():
    source, candidate, locator, artifacts, manifest, _ = fixture()
    with pytest.raises(PPTXBridgeError, match="locator must be a mapping"):
        bind_pptx_candidate(candidate, source, locator=None, artifacts=artifacts, manifest=manifest)
    locator["page"] = 1
    with pytest.raises(PPTXBridgeError, match="unsupported fields"):
        bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)


def test_temporal_policy_rejects_missing_or_post_cutoff_embedding_artifact():
    _, _, _, artifacts, _, chunk = fixture()
    not_ready = deepcopy(chunk)
    not_ready["available_at"] = OCR_AT.isoformat()
    gated = search_bound_pptx(chunk=not_ready, vectors={not_ready["chunk_id"]: [1.0, 0.0]}, artifacts=artifacts,
        query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
        historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
        authorize=lambda _: True, authorize_document=lambda _: True)
    assert gated["status"] == "NO_MATCH"

    invalid = deepcopy(artifacts)
    invalid["embedding_output"]["available_at"] = None
    with pytest.raises(PPTXBridgeError, match="temporal artifact lineage is ineligible"):
        search_bound_pptx(chunk=chunk, vectors={chunk["chunk_id"]: [1.0, 0.0]}, artifacts=invalid,
            query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
            historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
            authorize=lambda _: True, authorize_document=lambda _: True)
    late = deepcopy(artifacts)
    late_at = datetime(2026, 3, 21, tzinfo=UTC)
    late["embedding_output"].update(available_at=late_at, generated_at=late_at)
    late["index_snapshot"].update(available_at=late_at, generated_at=late_at)
    with pytest.raises(PPTXBridgeError, match="temporal artifact lineage is ineligible"):
        search_bound_pptx(chunk=chunk, vectors={chunk["chunk_id"]: [1.0, 0.0]}, artifacts=late,
            query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
            historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
            authorize=lambda _: True, authorize_document=lambda _: True)


def test_scope_or_document_authorization_denial_has_no_result():
    _, _, _, artifacts, _, chunk = fixture()
    result = search_bound_pptx(chunk=chunk, vectors={chunk["chunk_id"]: [1.0, 0.0]}, artifacts=artifacts,
        query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
        historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
        authorize=lambda _: True, authorize_document=lambda _: False)
    assert result["status"] == "NO_MATCH" and result["items"] == []
    assert result["retrieval_completeness"] == "unknown"
    assert result["source_reported_candidate_count"] is None
    with pytest.raises(ScopedTemporalError, match="authorization denied"):
        search_bound_pptx(chunk=chunk, vectors={chunk["chunk_id"]: [1.0, 0.0]}, artifacts=artifacts,
            query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
            historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
            authorize=lambda _: False, authorize_document=lambda _: True)


def test_extracted_synthetic_pptx_candidate_flows_through_binding_and_search(tmp_path):
    pptx = pytest.importorskip("pptx")
    Image = pytest.importorskip("PIL.Image")
    from io import BytesIO

    image_stream = BytesIO()
    Image.new("RGB", (32, 24), (220, 40, 20)).save(image_stream, format="PNG")
    image_stream.seek(0)
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    picture = slide.shapes.add_picture(image_stream, 0, 0)
    pptx_path = tmp_path / "fixture.pptx"
    deck.save(pptx_path)
    anchor = f"ppt/slides/slide1.xml#shape-{picture.shape_id}"
    source = {"document_id": "doc-extracted", "chunk_id": "chunk-extracted", "version": "v1",
              "source_ref": "synthetic://pptx-extracted", "incident_ids": ["INC-SYN-1"],
              "available_at": SOURCE_AT.isoformat(), "status": "active", "relation": "direct",
              "synthetic_fixture": True}
    metadata = {"synthetic_fixture": True, "source_ref": source["source_ref"],
                "source_document_id": source["document_id"], "source_version": source["version"],
                "available_at": SOURCE_AT, "anchor_chunk_ids": {anchor: source["chunk_id"]}}
    fake_engine = lambda _payload: SimpleNamespace(boxes=[[[0, 0], [20, 0], [20, 10], [0, 10]]],
                                                   txts=["synthetic bearing temperature"], scores=[0.9])
    extracted = extract_pptx_embedded_image_ocr_candidates(pptx_path=pptx_path, source_root=tmp_path,
        metadata=metadata, as_of=ANALYSIS_AT, authorize_source=lambda _: True, engine=fake_engine)
    candidate = extracted["candidates"][0]
    candidate["chunk_link_status"] = "caller_asserted_unverified"
    locator = {"locator_type": "pptx_embedded_picture", "slide_ordinal": candidate["slide_ordinal"],
               "slide_file_number": candidate["slide_file_number"], "picture_shape_id": candidate["picture_shape_id"],
               "anchor_id": candidate["anchor_id"], "image_sha256": candidate["image_sha256"],
               "source_snapshot_sha256": candidate["original_sha256"], "image_bbox": candidate["region_coords"],
               "coordinate_frame": "image_pixels", "image_size": candidate["image_size"],
               "originating_chunk_id": source["chunk_id"],
               "ocr_confidence": [r["confidence"] for r in candidate["ordered_text_confidence"]]}
    artifacts = fixture()[3]
    artifacts["source_version"].update(id=source["document_id"], version=source["version"], available_at=SOURCE_AT)
    artifacts["ocr_output"]["dependencies"]["source_version"] = {"id": source["document_id"], "version": source["version"]}
    manifest = {"provenance": "caller_asserted_unverified_synthetic_manifest", "image_sha256": candidate["image_sha256"],
                "anchor_id": candidate["anchor_id"], "source_snapshot_sha256": candidate["original_sha256"],
                "candidate_available_at": None}
    for name in ("ocr_output", "embedding_output"):
        manifest[name] = {k: artifacts[name][k] for k in ("id", "version", "available_at", "generated_at")}
        manifest[name]["binding"] = {"image_sha256": candidate["image_sha256"], "anchor_id": candidate["anchor_id"],
                                      "source_snapshot_sha256": candidate["original_sha256"]}
    chunk = bind_pptx_candidate(candidate, source, locator=locator, artifacts=artifacts, manifest=manifest)
    validated = search_bound_pptx(chunk=chunk, vectors={chunk["chunk_id"]: [1.0, 0.0]}, artifacts=artifacts,
        query="bearing temperature", query_vector=[1.0, 0.0], incident_ids=["INC-SYN-1"], as_of=AS_OF,
        historical_cutoff_exclusive=CUTOFF, analysis_at=ANALYSIS_AT,
        authorize=lambda _: True, authorize_document=lambda _: True)
    assert validated["status"] == "OK"
    hit_locator = json.loads(validated["items"][0]["locator"])
    assert hit_locator["anchor_id"] == anchor
    assert hit_locator["originating_chunk_id"] == source["chunk_id"]
