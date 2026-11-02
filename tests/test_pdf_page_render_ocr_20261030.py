"""Synthetic-only tests for rendered PDF page OCR candidates."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from research.document_image_ocr_adapter_20261030 import OCRModelConfig
from research.pdf_page_render_ocr_20261030 import extract_pdf_rendered_page_ocr_candidates


class FakeResult:
    boxes = [[[1, 2], [20, 2], [20, 10], [1, 10]]]
    txts = ("synthetic OCR",)
    scores = (0.91,)


class FakeEngine:
    def __init__(self): self.calls = []
    def __call__(self, data):
        self.calls.append(data)
        return FakeResult()


class PdfRenderedPageOCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sources = self.root / "sources"; self.sources.mkdir()
        self.output = self.root / "out"; self.output.mkdir()
        self.models = self.root / "models"; self.models.mkdir()
        det, rec = self.models / "det", self.models / "rec"
        det.write_bytes(b"synthetic detection model"); rec.write_bytes(b"synthetic recognition model")
        self.model = OCRModelConfig("synthetic-v1", det, hashlib.sha256(det.read_bytes()).hexdigest(),
                                    rec, hashlib.sha256(rec.read_bytes()).hexdigest())
        self.available = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.as_of = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.metadata = {"source_document_id": "synthetic-doc", "source_version": "v1",
                         "page_chunk_ids": {1: "synthetic-chunk"}, "available_at": self.available}
        png = self.root / "pixels.png"
        Image.new("RGB", (40, 30), (240, 20, 30)).save(png)
        self.pdf = self.sources / "sample.pdf"
        doc = fitz.open(); page = doc.new_page(width=240, height=180)
        page.insert_text((25, 50), "Vector text")
        page.insert_image(fitz.Rect(90, 75, 150, 120), filename=str(png))
        page.set_cropbox(fitz.Rect(5, 7, 225, 165)); page.set_rotation(90)
        doc.save(self.pdf); doc.close()
        self.engine = FakeEngine()

    def tearDown(self): self.tmp.cleanup()

    def run_extract(self, **overrides):
        args = dict(pdf_path=self.pdf, source_root=self.sources, metadata=self.metadata,
                    authorize_source=lambda _m: True, as_of=self.as_of, output_root=self.output,
                    model=self.model, model_root=self.models, engine=self.engine, dpi=144)
        args.update(overrides)
        return extract_pdf_rendered_page_ocr_candidates(**args)

    def test_render_and_candidate_provenance(self):
        result = self.run_extract()
        self.assertEqual(len(self.engine.calls), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["coordinate_frame"], "rendered_page_pixels")
        self.assertEqual(candidate["region_coords"], [0.0, 0.0, candidate["image_size"]["width"], candidate["image_size"]["height"]])
        self.assertEqual(candidate["rendered_page_pixels"], candidate["image_size"])
        self.assertEqual(candidate["page_rotation_degrees"], 90)
        self.assertNotEqual(candidate["page_cropbox_points"], [0.0, 0.0, 240.0, 180.0])
        self.assertEqual(candidate["original_sha256"], hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertEqual(candidate["existing_chunk_id"], "synthetic-chunk")
        self.assertEqual(candidate["status"], "candidate_unreviewed")
        self.assertTrue(any("annotations" in item for item in result["limitations"]))

    def test_denial_before_pdf_read(self):
        with self.assertRaisesRegex(ValueError, "denied"):
            self.run_extract(pdf_path=self.sources / "missing.pdf", authorize_source=lambda _m: False)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.engine.calls, [])

    def test_missing_page_mapping_fails_before_engine(self):
        self.metadata["page_chunk_ids"] = {}
        with self.assertRaisesRegex(ValueError, "page_chunk_ids"):
            self.run_extract()
        self.assertEqual(self.engine.calls, [])

    def test_bad_dpi_empty_and_encrypted_inputs_fail(self):
        with self.assertRaisesRegex(ValueError, "dpi"):
            self.run_extract(dpi=201)
        empty = self.sources / "empty.pdf"; empty.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "parse PDF"):
            self.run_extract(pdf_path=empty)
        encrypted = self.sources / "encrypted.pdf"
        doc = fitz.open(); doc.new_page(); doc.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u"); doc.close()
        with self.assertRaisesRegex(ValueError, "encrypted"):
            self.run_extract(pdf_path=encrypted)
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.run_extract(output_root=self.root / "not-created")

    def test_page_bound_rejected_before_engine(self):
        huge = self.sources / "huge.pdf"
        doc = fitz.open(); doc.new_page(width=10000, height=10000); doc.save(huge); doc.close()
        with self.assertRaisesRegex(ValueError, "pixel limit"):
            self.run_extract(pdf_path=huge)
        self.assertEqual(self.engine.calls, [])

    def test_invalid_preflight_inputs_leave_no_output_directory(self):
        malformed = self.sources / "malformed.pdf"; malformed.write_bytes(b"bad pdf")
        before = set(self.output.iterdir())
        with self.assertRaisesRegex(ValueError, "parse PDF"):
            self.run_extract(pdf_path=malformed)
        self.metadata["page_chunk_ids"] = {}
        with self.assertRaisesRegex(ValueError, "page_chunk_ids"):
            self.run_extract()
        self.assertEqual(set(self.output.iterdir()), before)

    def test_invalid_geometry_fails_closed_without_overflow(self):
        real_open = fitz.open

        class BadPage:
            rect = type("Rect", (), {"width": float("nan"), "height": 20.0})()
        class BadDocument:
            needs_pass = False; page_count = 1; is_repaired = False
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def __iter__(self): return iter([BadPage()])
        with patch("fitz.open", return_value=BadDocument()):
            with self.assertRaisesRegex(ValueError, "geometry"):
                self.run_extract()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.engine.calls, [])

    def test_aggregate_pixel_guard_precedes_output_creation(self):
        pages = self.sources / "aggregate.pdf"
        doc = fitz.open()
        for _ in range(4): doc.new_page(width=2000, height=2000)
        doc.save(pages); doc.close()
        self.metadata["page_chunk_ids"] = {i: f"chunk-{i}" for i in range(1, 5)}
        before = set(self.output.iterdir())
        with self.assertRaisesRegex(ValueError, "total render pixel"):
            self.run_extract(pdf_path=pages, dpi=200)
        self.assertEqual(set(self.output.iterdir()), before)
        self.assertEqual(self.engine.calls, [])


if __name__ == "__main__": unittest.main()
