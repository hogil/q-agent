from __future__ import annotations

import math
import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import fitz
from PIL import Image

from research.ocr_hybrid_synthetic_bridge_20261030 import (
    BridgeError, SyntheticOCRHybridIndex, make_ocr_chunk, validate_for_qagent_contract,
)
from research.document_image_ocr_adapter_20261030 import OCRModelConfig
from research.pdf_image_ocr_research_20261030 import extract_pdf_image_ocr_candidates


def unit(x, y):
    n = math.sqrt(x*x + y*y)
    return [x/n, y/n]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "document_id": "synthetic-doc", "chunk_id": "chunk-a", "version": "v1",
            "source_ref": "synthetic://doc/v1", "incident_ids": ["INC-SYN-1"],
            "available_at": "2026-10-29T00:00:00+00:00", "status": "active", "relation": "direct",
            "synthetic_fixture": True,
        }
        self.candidate = {
            "source_document_id": "synthetic-doc", "source_version": "v1", "page": 2,
            "region_id": "r1", "region_coords": [1, 2, 30, 20], "coordinate_frame": "image_pixels",
            "image_sha256": "a" * 64, "available_at": "2026-10-29T00:00:00+00:00",
            "existing_chunk_id": "chunk-a", "status": "candidate_unreviewed",
            "ordered_text_confidence": [{"text": "합성 OCR wafer alarm", "confidence": .73}],
        }

    def test_ocr_gets_separate_chunk_with_provenance_and_contract_shape(self):
        original = dict(self.source)
        ocr = make_ocr_chunk(self.candidate, self.source)
        self.assertEqual(self.source, original)
        self.assertEqual(ocr["originating_chunk_id"], "chunk-a")
        self.assertEqual(ocr["ocr_status"], "candidate_unreviewed")
        self.assertIn('"bbox": [1, 2, 30, 20]', ocr["locator"])
        self.assertEqual(ocr["ocr_confidence"], [.73])
        index = SyntheticOCRHybridIndex([ocr], {ocr["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        response = index.search(
            query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
            as_of="2026-10-30", top_k=3, authorize=lambda scope: scope["incident_ids"] == ["INC-SYN-1"],
            timezone_name="UTC", similarity_threshold=0.5,
        )
        normalized = validate_for_qagent_contract(response, incident_ids=["INC-SYN-1"], as_of="2026-10-30")
        self.assertEqual(normalized["items"][0]["chunk_id"], ocr["chunk_id"])
        self.assertEqual(normalized["items"][0]["status"], "candidate_unreviewed")
        self.assertIn("기계 OCR 미검토", normalized["items"][0]["text"])
        self.assertIn('"originating_chunk_id": "chunk-a"', normalized["items"][0]["locator"])
        index.close()

    def test_explicit_ocr_marker_passes_strict_contract_with_distinct_times(self):
        source = {**self.source, "available_at": "2026-10-29T00:00:00+00:00"}
        candidate = {**self.candidate, "available_at": "2026-10-30T00:00:00+00:00"}
        ocr = make_ocr_chunk(candidate, source)
        self.assertEqual(ocr["available_at"], "2026-10-30T00:00:00+00:00")
        self.assertEqual(ocr["source_available_at"], source["available_at"])
        self.assertEqual(ocr["derivative_available_at"], candidate["available_at"])
        index = SyntheticOCRHybridIndex([ocr], {ocr["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        response = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                                as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                                timezone_name="UTC", similarity_threshold=.5)
        normalized = validate_for_qagent_contract(response, incident_ids=["INC-SYN-1"], as_of="2026-10-30",
                                                  require_content_kind=True)
        self.assertEqual(normalized["items"][0]["content_kind"], "image_ocr")
        self.assertEqual(normalized["items"][0]["available_at"], source["available_at"])
        self.assertEqual(normalized["items"][0]["derivative_available_at"], candidate["available_at"])
        index.close()

    def test_source_and_derivative_cutoffs_are_independently_enforced(self):
        base = make_ocr_chunk(self.candidate, self.source)
        index = SyntheticOCRHybridIndex([base], {base["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        # Derivative exactly at the next UTC date is excluded by retrieval's max timestamp.
        late_derivative = {**base, "chunk_id": "late-derivative", "text": "wafer",
                           "available_at": "2026-10-31T00:00:00+00:00",
                           "derivative_available_at": "2026-10-31T00:00:00+00:00"}
        index.close()
        index = SyntheticOCRHybridIndex([late_derivative], {"late-derivative": unit(1, 0)}, authorize=lambda _: True)
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                              as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                              timezone_name="UTC", similarity_threshold=.5)
        self.assertEqual(result["status"], "NO_MATCH")
        # A source timestamp in the future remains excluded even if OCR is earlier.
        future_source = {**base, "chunk_id": "future-source", "text": "wafer",
                         "available_at": "2026-10-31T00:00:00+00:00",
                         "source_available_at": "2026-10-31T00:00:00+00:00",
                         "derivative_available_at": "2026-10-29T00:00:00+00:00"}
        index.close()
        index = SyntheticOCRHybridIndex([future_source], {"future-source": unit(1, 0)}, authorize=lambda _: True)
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                              as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                              timezone_name="UTC", similarity_threshold=.5)
        self.assertEqual(result["status"], "NO_MATCH")
        index.close()

    def test_contract_adapter_rejects_missing_or_inconsistent_ocr_provenance(self):
        chunk = make_ocr_chunk(self.candidate, self.source)
        index = SyntheticOCRHybridIndex([chunk], {chunk["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        response = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                                as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                                timezone_name="UTC", similarity_threshold=.5)
        index.close()
        item = response["items"][0]
        corruptions = (
            {**item, "locator": json.dumps({"ocr_status": "candidate_unreviewed", "region_id": "r1"})},
            {**item, "originating_chunk_id": ""},
            {**item, "source_available_at": None},
            {**item, "derivative_available_at": None},
            {**item, "available_at": "2026-10-30T00:00:00+00:00"},
        )
        for corrupted in corruptions:
            with self.subTest(corrupted=corrupted):
                bad_response = {**response, "items": [corrupted]}
                with self.assertRaises(BridgeError):
                    validate_for_qagent_contract(bad_response, incident_ids=["INC-SYN-1"],
                                                 as_of="2026-10-30", require_content_kind=True)

    def test_future_derivative_rejected_by_validator_and_future_source_filtered(self):
        source = {**self.source, "available_at": "2026-10-29T00:00:00+00:00"}
        candidate = {**self.candidate, "available_at": "2026-10-31T00:00:00+00:00"}
        chunk = make_ocr_chunk(candidate, source)
        # Retrieval uses max(source, derivative), so it does not return future OCR.
        index = SyntheticOCRHybridIndex([chunk], {chunk["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        response = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                                as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                                timezone_name="UTC", similarity_threshold=.5)
        self.assertEqual(response["status"], "NO_MATCH")
        index.close()

        # If an out-of-contract caller supplies that item anyway, the validator rejects its future derivative.
        response = {"status": "OK", "retrieval_method": "bm25_vector_hybrid", "as_of": "2026-10-30",
                    "truncated": False, "candidate_count": 1, "items": [chunk]}
        with self.assertRaises(ValueError):
            validate_for_qagent_contract(response, incident_ids=["INC-SYN-1"], as_of="2026-10-30",
                                         require_content_kind=True)

    def test_scope_and_authorization_fail_closed_before_search(self):
        ocr = make_ocr_chunk(self.candidate, self.source)
        index = SyntheticOCRHybridIndex([ocr], {ocr["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-OTHER"],
                              as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                              timezone_name="UTC", similarity_threshold=0.5)
        self.assertEqual(result["status"], "NO_MATCH")
        for kwargs in ({"incident_ids": ["INC-SYN-1"], "as_of": "invalid", "authorize": lambda _: True,
                        "timezone_name": "UTC", "similarity_threshold": .5},
                       {"incident_ids": ["INC-SYN-1"], "as_of": "2026-10-30", "authorize": lambda _: False,
                        "timezone_name": "UTC", "similarity_threshold": .5}):
            with self.assertRaises(BridgeError):
                index.search(query="wafer", query_vector=unit(1, 0), top_k=2, **kwargs)
        index.close()

    def test_confidence_does_not_change_retrieval_score_and_scope_filters(self):
        first = make_ocr_chunk(self.candidate, self.source)
        other_source = {**self.source, "chunk_id": "chunk-b", "incident_ids": ["INC-OTHER"]}
        other_candidate = {**self.candidate, "existing_chunk_id": "chunk-b", "region_id": "r2",
                           "ordered_text_confidence": [{"text": "wafer alarm", "confidence": .99}]}
        second = make_ocr_chunk(other_candidate, other_source)
        index = SyntheticOCRHybridIndex([first, second], {first["chunk_id"]: unit(1, 0), second["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                              as_of="2026-10-30", top_k=5, authorize=lambda _: True,
                              timezone_name="UTC", similarity_threshold=.5)
        self.assertEqual([x["chunk_id"] for x in result["items"]], [first["chunk_id"]])
        self.assertNotEqual(result["items"][0]["score"], .73)
        index.close()

    def test_rrf_threshold_truncation_and_vector_candidate_count(self):
        chunks, vectors = [], {}
        for i, (text, vec) in enumerate((("wafer alarm", unit(1, 0)), ("wafer alarm", unit(.8, .6)),
                                         ("unrelated", unit(0, 1)))):
            cid = f"syn-{i}"
            chunks.append({"document_id": "d", "chunk_id": cid, "version": "v1", "text": text,
                           "source_ref": "synthetic://d", "locator": "synthetic", "status": "active",
                           "available_at": "2026-10-29T00:00:00+00:00", "incident_ids": ["INC-SYN-1"],
                           "relation": "direct", "synthetic_fixture": True})
            vectors[cid] = vec
        index = SyntheticOCRHybridIndex(chunks, vectors, authorize=lambda _: True)
        res = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"], as_of="2026-10-30",
                           top_k=1, authorize=lambda _: True, timezone_name="UTC", similarity_threshold=.7)
        self.assertEqual(res["candidate_count"], 2)
        self.assertTrue(res["truncated"])
        self.assertEqual(len(res["items"]), 1)
        index.close()

    def test_local_timezone_cutoff_and_max_source_ocr_time(self):
        source = {**self.source, "available_at": "2026-10-29T14:59:00+00:00"}
        candidate = {**self.candidate, "available_at": "2026-10-29T15:30:00+00:00"}
        ocr = make_ocr_chunk(candidate, source)
        self.assertEqual(ocr["available_at"], "2026-10-29T15:30:00+00:00")
        self.assertEqual(ocr["status"], "candidate_unreviewed")
        index = SyntheticOCRHybridIndex([ocr], {ocr["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        # In Seoul the exclusive end of 2026-10-30 is 2026-10-30T15:00Z.
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                              as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                              timezone_name="Asia/Seoul", similarity_threshold=.5)
        self.assertEqual(result["status"], "OK")
        after_cutoff = {**ocr, "chunk_id": "late", "available_at": "2026-10-30T15:00:00+00:00", "text": "wafer"}
        index.close()
        index = SyntheticOCRHybridIndex([after_cutoff], {"late": unit(1, 0)}, authorize=lambda _: True)
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                              as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                              timezone_name="Asia/Seoul", similarity_threshold=.5)
        self.assertEqual(result["status"], "NO_MATCH")
        index.close()

    def test_index_requires_synthetic_marker_and_authorization(self):
        chunk = make_ocr_chunk(self.candidate, self.source)
        with self.assertRaises(BridgeError):
            SyntheticOCRHybridIndex([chunk], {chunk["chunk_id"]: unit(1, 0)}, authorize=None)
        with self.assertRaises(BridgeError):
            SyntheticOCRHybridIndex([chunk], {chunk["chunk_id"]: unit(1, 0)}, authorize=lambda _: False)
        non_synthetic = {**chunk, "synthetic_fixture": False}
        with self.assertRaises(BridgeError):
            SyntheticOCRHybridIndex([non_synthetic], {chunk["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)

    def test_index_requires_incident_ids_as_non_empty_id_sequence(self):
        base = make_ocr_chunk(self.candidate, self.source)
        for value in ("INC-SYN-1", [], [""], ["INC-SYN-1", None], ["INC-SYN-1", 1]):
            chunk = {**base, "incident_ids": value}
            with self.subTest(incident_ids=value), self.assertRaises(BridgeError):
                SyntheticOCRHybridIndex([chunk], {chunk["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)

        valid = {**base, "incident_ids": ("INC-SYN-1",)}
        index = SyntheticOCRHybridIndex([valid], {valid["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        result = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["INC-SYN-1"],
                              as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                              timezone_name="UTC", similarity_threshold=.5)
        self.assertEqual([item["chunk_id"] for item in result["items"]], [valid["chunk_id"]])
        unauthorized = index.search(query="wafer", query_vector=unit(1, 0), incident_ids=["I"],
                                    as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                                    timezone_name="UTC", similarity_threshold=.5)
        self.assertEqual(unauthorized["status"], "NO_MATCH")
        index.close()

    def test_query_scope_rejects_string_and_malformed_ids(self):
        chunk = make_ocr_chunk(self.candidate, self.source)
        index = SyntheticOCRHybridIndex([chunk], {chunk["chunk_id"]: unit(1, 0)}, authorize=lambda _: True)
        for incident_ids in ("INC-SYN-1", [], [""], ["INC-SYN-1", None], ["INC-SYN-1", 1]):
            with self.subTest(incident_ids=incident_ids), self.assertRaises(BridgeError):
                index.search(query="wafer", query_vector=unit(1, 0), incident_ids=incident_ids,
                             as_of="2026-10-30", top_k=2, authorize=lambda _: True,
                             timezone_name="UTC", similarity_threshold=.5)
        index.close()

    def test_missing_origin_metadata_rejected(self):
        with self.assertRaises(BridgeError):
            make_ocr_chunk(self.candidate, {"document_id": "synthetic-doc"})

    def test_docx_anchors_keep_unknown_page_and_distinct_identity(self):
        candidates = []
        for ordinal in (1, 2):
            anchor = f"word/document.xml#drawing-{ordinal}"
            candidates.append({**self.candidate, "page": None, "page_status": "unknown_requires_layout_rendering",
                "anchor_part": "word/document.xml", "anchor_id": anchor, "anchor_ordinal": ordinal,
                "region_id": anchor, "region_coords": [0, 0, 80, 40], "coordinate_frame": "image_pixels",
                "original_sha256": "d" * 64,
                "original_sha256_provenance": "computed_from_single_docx_byte_snapshot",
                "chunk_link_status": "caller_asserted_unverified", "visibility_status": "unverified"})
        chunks = [make_ocr_chunk(c, self.source) for c in candidates]
        self.assertNotEqual(chunks[0]["chunk_id"], chunks[1]["chunk_id"])
        for candidate, chunk in zip(candidates, chunks):
            locator = json.loads(chunk["locator"])
            self.assertIsNone(locator["page"])
            self.assertEqual(locator["page_status"], "unknown_requires_layout_rendering")
            self.assertEqual(locator["anchor_id"], candidate["anchor_id"])
            self.assertEqual(locator["anchor_ordinal"], candidate["anchor_ordinal"])
            self.assertEqual(locator["bbox"], candidate["region_coords"])
            self.assertEqual(locator["visibility_status"], "unverified")
            self.assertEqual(locator["mapping_verification"], "unverified_against_index_or_acl")

    def test_docx_missing_visibility_field_defaults_only_to_unverified(self):
        anchor = "word/document.xml#drawing-1"
        candidate = {**self.candidate, "page": None, "page_status": "unknown_requires_layout_rendering",
            "anchor_part": "word/document.xml", "anchor_id": anchor, "anchor_ordinal": 1,
            "region_id": anchor, "coordinate_frame": "image_pixels", "region_coords": [0, 0, 80, 40],
            "original_sha256": "f" * 64,
            "original_sha256_provenance": "computed_from_single_docx_byte_snapshot",
            "chunk_link_status": "caller_asserted_unverified"}
        candidate.pop("visibility_status", None)
        locator = json.loads(make_ocr_chunk(candidate, self.source)["locator"])
        self.assertEqual(locator["visibility_status"], "unverified")
        for value in ("verified", "visible", False, None):
            with self.subTest(visibility_status=value), self.assertRaises(BridgeError):
                make_ocr_chunk({**candidate, "visibility_status": value}, self.source)

    def test_docx_requires_exact_caller_chunk_mapping_and_valid_anchor(self):
        anchor = "word/document.xml#drawing-1"
        candidate = {**self.candidate, "page": None, "page_status": "unknown_requires_layout_rendering",
            "anchor_part": "word/document.xml", "anchor_id": anchor, "anchor_ordinal": 1,
            "region_id": anchor, "coordinate_frame": "image_pixels", "region_coords": [0, 0, 80, 40],
            "original_sha256": "e" * 64,
            "original_sha256_provenance": "computed_from_single_docx_byte_snapshot",
            "chunk_link_status": "caller_asserted_unverified", "visibility_status": "unverified"}
        for c, s in (({**candidate, "existing_chunk_id": None}, self.source),
                     (candidate, {**self.source, "version": "v2"}),
                     ({**candidate, "anchor_id": "word/document.xml#drawing-x"}, self.source),
                     ({**candidate, "anchor_ordinal": 0}, self.source),
                     ({**candidate, "region_coords": [0, 0, float("inf"), 40]}, self.source),
                     ({**candidate, "original_sha256": "bad"}, self.source),
                     ({**candidate, "chunk_link_status": "unlinked"}, self.source)):
            with self.subTest(candidate=c, source=s), self.assertRaises(BridgeError):
                make_ocr_chunk(c, s)

    def test_non_docx_null_page_is_rejected(self):
        with self.assertRaises(BridgeError):
            make_ocr_chunk({**self.candidate, "page": None}, self.source)

    def test_pdf_locator_preserves_page_bbox_separately_from_pixel_bbox(self):
        candidate = {**self.candidate, "page_bbox": [12.5, 20, 312, 420],
                     "page_bbox_coordinate_frame": "pdf_points_unrotated",
                     "page_rotation_degrees": 90, "visibility_status": "visible",
                     "original_sha256": "b" * 64,
                     "original_sha256_provenance": "caller_asserted_unverified",
                     "page_chunk_id_provenance": "caller_asserted_mapping_unverified_against_index"}
        locator = json.loads(make_ocr_chunk(candidate, self.source)["locator"])
        self.assertEqual(locator["bbox"], [1, 2, 30, 20])
        self.assertEqual(locator["page_bbox"], [12.5, 20, 312, 420])
        self.assertEqual(locator["page_bbox_coordinate_frame"], "pdf_points_unrotated")
        self.assertEqual(locator["page_rotation_degrees"], 90)
        self.assertEqual(locator["original_sha256_provenance"], "caller_asserted_unverified")
        self.assertEqual(locator["page_chunk_id_provenance"], "caller_asserted_mapping_unverified_against_index")

    def test_invalid_or_incomplete_pdf_locator_bundle_rejected(self):
        base = {**self.candidate, "page_bbox": [0, 0, 100, 200],
                "page_bbox_coordinate_frame": "pdf_points",
                "page_rotation_degrees": 0, "visibility_status": "visible",
                "original_sha256": "c" * 64,
                "original_sha256_provenance": "caller_asserted_unverified",
                "page_chunk_id_provenance": "caller_asserted_mapping_unverified_against_index"}
        for changes in ({"page_bbox": [0, float("nan"), 100, 200]},
                        {"page_bbox": [0, 0, 0, 200]},
                        {"page_bbox_coordinate_frame": None},
                        {"page_bbox_coordinate_frame": ""}):
            with self.subTest(changes=changes), self.assertRaises(BridgeError):
                make_ocr_chunk({**base, **changes}, self.source)

    def test_rendered_page_candidate_preserves_geometry_and_provenance(self):
        source = {**self.source, "chunk_id": "synthetic-existing-page-chunk-1",
                  "document_id": "synthetic-rendered-page-en", "version": "1"}
        candidate = {**self.candidate, "source_document_id": source["document_id"],
                     "source_version": source["version"], "existing_chunk_id": source["chunk_id"],
                     "coordinate_frame": "rendered_page_pixels", "page": 1,
                     "region_id": "rendered-page-1", "region_coords": [0.0, 0.0, 1224.0, 1584.0],
                     "original_sha256": "3fd6f11296261487f7064a4b0067c4956c43b1960d36b79d0287bca2a351dab7",
                     "original_sha256_provenance": "computed_from_single_pdf_byte_snapshot",
                     "page_chunk_id_provenance": "caller_asserted_mapping_unverified_against_index",
                     "rendered_page_pixels": {"width": 1224, "height": 1584},
                     "page_rect_points": [0.0, 0.0, 612.0, 792.0],
                     "page_cropbox_points": [0.0, 0.0, 612.0, 792.0],
                     "page_rotation_degrees": 0, "render_dpi": 144,
                     "pixmap_irect": [0, 0, 1224, 1584],
                     "derotation_matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]}
        locator = json.loads(make_ocr_chunk(candidate, source)["locator"])
        self.assertEqual(locator["bbox"], candidate["region_coords"])
        self.assertEqual(locator["coordinate_frame"], "rendered_page_pixels")
        for key in ("page_rect_points", "page_cropbox_points", "page_rotation_degrees", "render_dpi",
                    "pixmap_irect", "derotation_matrix", "rendered_page_pixels", "original_sha256",
                    "original_sha256_provenance", "page_chunk_id_provenance"):
            self.assertEqual(locator[key], candidate[key])
        self.assertEqual(locator["pixel_to_original_page_transform_accuracy"], "unverified")
        self.assertEqual(locator["annotations"], "excluded")
        self.assertEqual(locator["crop_limitations"], "partial_page_crop_may_omit_context")

        for changes in ({"render_dpi": float("inf")}, {"pixmap_irect": [0, 0, 1224, 1583]},
                        {"derotation_matrix": [1, 0, float("nan"), 1, 0, 0]},
                        {"page_chunk_id_provenance": "verified"},
                        {"rendered_page_pixels": {"width": 1224}},
                        {"page_rect_points": None}):
            with self.subTest(changes=changes), self.assertRaises(BridgeError):
                make_ocr_chunk({**candidate, **changes}, source)
        with self.assertRaises(BridgeError):
            make_ocr_chunk({**candidate, "coordinate_frame": "mystery_pixels"}, source)

    def test_pdf_producer_candidate_integrates_with_bridge_without_translation(self):
        class Result:
            boxes = [[[1, 2], [20, 2], [20, 10], [1, 10]]]
            txts = ("synthetic OCR",)
            scores = (.91,)

        class Engine:
            def __call__(self, data):
                self_data = data
                assert isinstance(self_data, bytes)
                return Result()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources, output, models = root / "sources", root / "out", root / "models"
            sources.mkdir(); output.mkdir(); models.mkdir()
            image_path, pdf_path = root / "image.png", sources / "sample.pdf"
            Image.new("RGB", (32, 24), "white").save(image_path)
            doc = fitz.open(); page = doc.new_page(width=300, height=200)
            page.insert_image(fitz.Rect(10, 20, 74, 68), filename=str(image_path))
            doc.save(pdf_path); doc.close()
            det, rec = models / "det", models / "rec"
            det.write_bytes(b"synthetic detector"); rec.write_bytes(b"synthetic recognizer")
            model = OCRModelConfig("synthetic-v1", det, hashlib.sha256(det.read_bytes()).hexdigest(),
                                   rec, hashlib.sha256(rec.read_bytes()).hexdigest())
            available = datetime(2026, 10, 29, tzinfo=timezone.utc)
            result = extract_pdf_image_ocr_candidates(
                pdf_path=pdf_path, source_root=sources,
                metadata={"source_document_id": "synthetic-doc", "source_version": "v1",
                          "page_chunk_ids": {1: "chunk-a"}, "available_at": available},
                authorize_source=lambda _: True, as_of=datetime(2026, 10, 30, tzinfo=timezone.utc),
                output_root=output, model=model, model_root=models, engine=Engine())
            candidate = result["candidates"][0]
            chunk = make_ocr_chunk(candidate, self.source)
            locator = json.loads(chunk["locator"])
            self.assertEqual(locator["page_bbox"], candidate["page_bbox"])
            self.assertEqual(locator["page_bbox_coordinate_frame"], candidate["page_bbox_coordinate_frame"])
            self.assertEqual(locator["page_rotation_degrees"], candidate["page_rotation_degrees"])
            self.assertEqual(locator["original_sha256"], candidate["original_sha256"])
            self.assertEqual(locator["original_sha256_provenance"], candidate["original_sha256_provenance"])
            self.assertEqual(locator["page_chunk_id_provenance"], candidate["page_chunk_id_provenance"])
            self.assertEqual(locator["visibility_status"], candidate["visibility_status"])


if __name__ == "__main__":
    unittest.main()
