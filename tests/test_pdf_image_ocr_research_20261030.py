"""Synthetic-only tests for embedded PDF image OCR candidate extraction."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from research.document_image_ocr_adapter_20261030 import OCRModelConfig
from research.pdf_image_ocr_research_20261030 import (
    MAX_PDF_BYTES,
    extract_pdf_image_ocr_candidates,
)


class FakeResult:
    boxes = [[[1, 2], [20, 2], [20, 10], [1, 10]]]
    txts = ("synthetic OCR",)
    scores = (0.91,)


class FakeEngine:
    def __call__(self, data):
        assert isinstance(data, bytes)
        return FakeResult()


class PdfImageOCRResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.output = self.root / "out"
        self.output.mkdir()
        self.models = self.root / "models"
        self.models.mkdir()
        det, rec = self.models / "det", self.models / "rec"
        det.write_bytes(b"synthetic detection model")
        rec.write_bytes(b"synthetic recognition model")
        self.model = OCRModelConfig("synthetic-v1", det, hashlib.sha256(det.read_bytes()).hexdigest(),
                                    rec, hashlib.sha256(rec.read_bytes()).hexdigest())
        self.available = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.as_of = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.metadata = {"source_document_id": "synthetic-doc", "source_version": "v1",
                         "page_chunk_ids": {1: "existing-chunk"}, "available_at": self.available}
        self.png = self.root / "fixed.png"
        Image.new("RGB", (32, 24), (255, 255, 255)).save(self.png)
        self.pdf = self.sources / "repeated.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        image_rect = fitz.Rect(10, 20, 74, 68)
        page.insert_image(image_rect, filename=str(self.png))
        page.insert_image(fitz.Rect(120, 80, 184, 128), filename=str(self.png))
        doc.save(self.pdf)
        doc.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_extract(self, **overrides):
        args = dict(pdf_path=self.pdf, source_root=self.sources, metadata=self.metadata,
                    authorize_source=lambda _m: True, as_of=self.as_of, output_root=self.output,
                    model=self.model, model_root=self.models, engine=FakeEngine())
        args.update(overrides)
        return extract_pdf_image_ocr_candidates(**args)

    def test_repeated_xref_yields_two_independent_placements_and_provenance(self):
        result = self.run_extract()
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["coverage_status"], "incomplete_not_verified")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["original_sha256"], hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertEqual(len({x["region_id"] for x in result["candidates"]}), 2)
        self.assertEqual([x["page_bbox"] for x in result["candidates"]],
                         [[10.0, 20.0, 74.0, 68.0], [120.0, 80.0, 184.0, 128.0]])
        for candidate in result["candidates"]:
            self.assertEqual(candidate["region_coords"], [0.0, 0.0, 32.0, 24.0])
            self.assertEqual(candidate["coordinate_frame"], "image_pixels")
            self.assertEqual(candidate["page_bbox_coordinate_frame"],
                             "PyMuPDF unrotated page coordinates (points; origin top-left; axis-aligned bbox)")
            self.assertEqual(candidate["ordered_text_confidence"][0]["text"], "synthetic OCR")
            self.assertEqual(candidate["existing_chunk_id"], "existing-chunk")
            self.assertEqual(candidate["original_sha256_provenance"], "caller_asserted_unverified")
            self.assertEqual(candidate["visibility_status"], "coverage_incomplete_not_verified")
            self.assertEqual(candidate["page_chunk_id_provenance"], "caller_asserted_mapping_unverified_against_index")

    def test_denial_happens_before_pdf_open_or_output_creation(self):
        missing = self.sources / "does-not-exist.pdf"
        with self.assertRaisesRegex(ValueError, "denied"):
            self.run_extract(pdf_path=missing, authorize_source=lambda _m: False)
        self.assertTrue(self.output.is_dir())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_future_as_of_rejected_before_pdf_open(self):
        self.metadata["available_at"] = datetime(2026, 10, 31, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.run_extract(pdf_path=self.sources / "missing.pdf")

    def test_missing_page_chunk_mapping_fails_before_engine(self):
        self.metadata["page_chunk_ids"] = {}
        calls = []
        with self.assertRaisesRegex(ValueError, "page_chunk_ids"):
            self.run_extract(engine=lambda _data: calls.append(True))
        self.assertEqual(calls, [])

    def test_mult_page_chunk_mapping_is_required_for_each_image_page(self):
        two_pages = self.sources / "two-pages.pdf"
        doc = fitz.open()
        first = doc.new_page(width=300, height=200)
        first.insert_image(fitz.Rect(10, 20, 74, 68), filename=str(self.png))
        second = doc.new_page(width=300, height=200)
        second.insert_image(fitz.Rect(10, 20, 74, 68), filename=str(self.png))
        doc.save(two_pages)
        doc.close()
        calls = []
        with self.assertRaisesRegex(ValueError, "page 2"):
            self.run_extract(pdf_path=two_pages, engine=lambda _data: calls.append(True))
        self.assertEqual(calls, [])

    def test_outside_pdf_and_nonexistent_output_directory_rejected(self):
        outside = self.root / "outside.pdf"
        outside.write_bytes(self.pdf.read_bytes())
        with self.assertRaisesRegex(ValueError, "outside"):
            self.run_extract(pdf_path=outside)
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.run_extract(output_root=self.root / "new-output")

    def test_rotated_page_records_rotation_and_unrotated_bbox_frame(self):
        rotated = self.sources / "rotated.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_image(fitz.Rect(10, 20, 74, 68), filename=str(self.png))
        page.set_rotation(90)
        doc.save(rotated)
        doc.close()
        candidate = self.run_extract(pdf_path=rotated)["candidates"][0]
        self.assertEqual(candidate["page_rotation_degrees"], 90)
        self.assertIn("unrotated page coordinates", candidate["page_bbox_coordinate_frame"])

    def test_empty_corrupt_encrypted_and_oversized_pdfs_fail_explicitly(self):
        empty = self.sources / "empty.pdf"
        empty.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "parse PDF"):
            self.run_extract(pdf_path=empty)
        corrupt = self.sources / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.7\nnot a valid xref")
        with self.assertRaises(ValueError):
            self.run_extract(pdf_path=corrupt)
        encrypted = self.sources / "encrypted.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
        doc.close()
        with self.assertRaisesRegex(ValueError, "encrypted"):
            self.run_extract(pdf_path=encrypted)
        oversized = self.sources / "oversized.pdf"
        with oversized.open("wb") as stream:
            stream.truncate(MAX_PDF_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            self.run_extract(pdf_path=oversized)

    def test_page_limit_is_enforced(self):
        many = self.sources / "many.pdf"
        doc = fitz.open()
        for _ in range(129):
            doc.new_page()
        doc.save(many)
        doc.close()
        with self.assertRaisesRegex(ValueError, "page limit"):
            self.run_extract(pdf_path=many)


if __name__ == "__main__":
    unittest.main()
