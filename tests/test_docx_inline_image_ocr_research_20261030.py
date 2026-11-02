"""Synthetic-only tests for unpaged DOCX inline image OCR candidates."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile
import warnings

from PIL import Image
from io import BytesIO

from research.document_image_ocr_adapter_20261030 import OCRModelConfig, OCRAdapterError
from research.docx_inline_image_ocr_research_20261030 import extract_docx_inline_image_ocr_candidates


class Result:
    boxes = [[[1, 1], [10, 1], [10, 8], [1, 8]]]
    txts = ("합성 OCR",)
    scores = (0.9,)


class Engine:
    def __call__(self, payload):
        assert isinstance(payload, bytes)
        return Result()


class DocxOCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"; self.src.mkdir()
        self.models = self.root / "models"; self.models.mkdir()
        d, r = self.models / "d", self.models / "r"
        d.write_bytes(b"det"); r.write_bytes(b"rec")
        self.model = OCRModelConfig("synthetic-v1", d, hashlib.sha256(d.read_bytes()).hexdigest(), r, hashlib.sha256(r.read_bytes()).hexdigest())
        self.when = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.as_of = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.meta = {"source_document_id": "synthetic-doc", "source_version": "v1", "available_at": self.when}
        image = BytesIO(); Image.new("RGB", (20, 16), "white").save(image, format="PNG")
        self.png = image.getvalue()
        self.write_docx()

    def tearDown(self): self.tmp.cleanup()

    def write_docx(self, entries=None):
        if entries is None:
            doc = ('<w:document xmlns:w="w" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body><a:blip r:embed="r1"/><a:blip r:embed="r1"/></w:body></w:document>').encode()
            rel = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="style" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>').encode()
            entries = {"word/document.xml": doc, "word/_rels/document.xml.rels": rel, "word/media/image1.png": self.png}
        self.docx = self.src / "test.docx"
        with ZipFile(self.docx, "w", ZIP_DEFLATED) as z:
            for name, data in entries.items(): z.writestr(name, data)

    def run_extract(self, **changes):
        args = dict(docx_path=self.docx, source_root=self.src, metadata=self.meta, as_of=self.as_of,
                    authorize_source=lambda _m: True, model=self.model, model_root=self.models, engine=Engine())
        args.update(changes)
        return extract_docx_inline_image_ocr_candidates(**args)

    def test_repeated_embedded_placements_are_unpaged_and_hashed(self):
        result = self.run_extract()
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["original_sha256"], hashlib.sha256(self.docx.read_bytes()).hexdigest())
        a, b = result["candidates"]
        self.assertNotEqual(a["anchor_id"], b["anchor_id"])
        self.assertEqual(a["page"], None)
        self.assertEqual(a["page_status"], "unknown_requires_layout_rendering")
        self.assertEqual(a["existing_chunk_id"], None)
        self.assertEqual(a["chunk_link_status"], "unlinked")
        self.assertEqual(a["ordered_text_confidence"][0]["text"], "합성 OCR")
        self.assertEqual(a["image_sha256"], hashlib.sha256(self.png).hexdigest())

    def test_mapping_and_anchor_auth_are_checked(self):
        key = "word/document.xml#drawing-1"
        self.meta["anchor_chunk_ids"] = {key: "chunk-1"}
        seen = []
        out = self.run_extract(authorize_source=lambda m: seen.append(m.get("anchor_id")) or True)
        self.assertEqual(out["candidates"][0]["existing_chunk_id"], "chunk-1")
        self.assertEqual(out["candidates"][0]["chunk_link_status"], "caller_asserted_unverified")
        self.assertEqual(seen, [None, key, "word/document.xml#drawing-2"])

    def test_anchor_denial_precedes_engine_and_bad_box_fails(self):
        called = []
        with self.assertRaisesRegex(OCRAdapterError, "denied"):
            self.run_extract(authorize_source=lambda m: m.get("anchor_id") is None,
                             engine=lambda b: called.append(b))
        self.assertEqual(called, [])
        class Bad:
            boxes = [[[1000, 1], [10, 1], [10, 8], [1, 8]]]
            txts = ("bad",); scores = (0.9,)
        with self.assertRaisesRegex(OCRAdapterError, "outside"):
            self.run_extract(engine=lambda _b: Bad())

    def test_anchor_denial_happens_before_zip_media_read(self):
        import research.docx_inline_image_ocr_research_20261030 as module
        original = module.ZipFile.read
        original_close = module.ZipFile.close
        media_reads, engine_calls, closes = [], [], []
        def tracked_read(archive, member, *args, **kwargs):
            name = member.filename if hasattr(member, "filename") else member
            if isinstance(name, str) and name.startswith("word/media/"):
                media_reads.append(name)
            return original(archive, member, *args, **kwargs)
        def tracked_close(archive):
            if archive.fp is not None: closes.append(True)
            return original_close(archive)
        with mock.patch.object(module.ZipFile, "read", tracked_read), mock.patch.object(module.ZipFile, "close", tracked_close):
            with self.assertRaisesRegex(OCRAdapterError, "denied"):
                self.run_extract(authorize_source=lambda m: m.get("anchor_id") is None,
                                 engine=lambda b: engine_calls.append(b))
        self.assertEqual(media_reads, [])
        self.assertEqual(engine_calls, [])
        self.assertEqual(len(closes), 1)

    def test_duplicate_relationship_mode_and_image_traversal_fail(self):
        doc = b'<w:document xmlns:w="w" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><a:blip r:embed="r1"/></w:document>'
        base = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>'
        for relxml, message in [
            (base.format('<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'), "duplicate"),
            ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png" TargetMode="Internalish"/></Relationships>', "TargetMode"),
            ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../evil.png"/></Relationships>', "unsafe"),
        ]:
            self.write_docx({"word/document.xml": doc, "word/_rels/document.xml.rels": relxml.encode(), "word/media/image1.png": self.png})
            with self.assertRaisesRegex(OCRAdapterError, message): self.run_extract()

    def test_total_ocr_byte_and_pixel_budgets_count_repeated_placements(self):
        doc = b'<w:document xmlns:w="w" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' + b'<a:blip r:embed="r1"/>' * 3 + b'</w:document>'
        rel = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>'
        self.write_docx({"word/document.xml": doc, "word/_rels/document.xml.rels": rel, "word/media/image1.png": self.png})
        import research.docx_inline_image_ocr_research_20261030 as module
        original_close = module.ZipFile.close
        closes, engine_calls = [], []
        def tracked_close(archive):
            if archive.fp is not None: closes.append(True)
            return original_close(archive)
        with mock.patch.object(module, "MAX_OCR_IMAGE_BYTES", len(self.png) * 2 - 1):
            with mock.patch.object(module.ZipFile, "close", tracked_close):
                with self.assertRaisesRegex(OCRAdapterError, "byte budget"):
                    self.run_extract(engine=lambda b: engine_calls.append(b))
        self.assertEqual(len(closes), 1)
        self.assertEqual(engine_calls, [])
        with mock.patch.object(module, "MAX_OCR_IMAGE_PIXELS", 20 * 16 * 2 - 1):
            with mock.patch.object(module.ZipFile, "close", tracked_close):
                with self.assertRaisesRegex(OCRAdapterError, "pixel budget"):
                    self.run_extract(engine=lambda b: engine_calls.append(b))
        self.assertEqual(len(closes), 2)
        self.assertEqual(engine_calls, [])

    def test_auth_denial_and_future_availability_precede_file_read(self):
        with self.assertRaisesRegex(OCRAdapterError, "denied"):
            self.run_extract(docx_path=self.src / "missing.docx", authorize_source=lambda _m: False)
        self.meta["available_at"] = datetime(2026, 10, 31, tzinfo=timezone.utc)
        with self.assertRaisesRegex(OCRAdapterError, "unavailable"):
            self.run_extract(docx_path=self.src / "missing.docx")

    def test_unsafe_duplicate_corrupt_xxe_and_external_relationships(self):
        for filename in ("../evil", "word\\bad"):
            with self.subTest(filename=filename):
                self.write_docx({filename: b"x", "word/document.xml": b"x", "word/_rels/document.xml.rels": b"x"})
                with self.assertRaises(OCRAdapterError): self.run_extract()
        self.write_docx()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(self.docx, "a", ZIP_DEFLATED) as z: z.writestr("word/media/image1.png", self.png)
        with self.assertRaisesRegex(OCRAdapterError, "duplicate"): self.run_extract()
        self.docx.write_bytes(b"not a zip")
        with self.assertRaises(OCRAdapterError): self.run_extract()
        xxe = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///secret">]><x>&e;</x>'
        self.write_docx({"word/document.xml": xxe, "word/_rels/document.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'})
        with self.assertRaisesRegex(OCRAdapterError, "DTD"): self.run_extract()
        self.write_docx({"word/document.xml": b'<w:document xmlns:w="w" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><a:blip r:link="r1"/></w:document>', "word/_rels/document.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="https://example.invalid/x" TargetMode="External"/></Relationships>'})
        result = self.run_extract()
        self.assertEqual(result["candidates"], [])
        self.assertTrue(any("external" in x for x in result["limitations"]))

    def test_zip_metadata_validation_error_closes_archive(self):
        import research.docx_inline_image_ocr_research_20261030 as module
        original_close = module.ZipFile.close
        closes = []
        def tracked_close(archive):
            if archive.fp is not None: closes.append(True)
            return original_close(archive)
        self.write_docx()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(self.docx, "a", ZIP_DEFLATED) as z:
                z.writestr("word/media/image1.png", self.png)
        with mock.patch.object(module.ZipFile, "close", tracked_close):
            with self.assertRaisesRegex(OCRAdapterError, "duplicate"):
                self.run_extract()
        self.assertEqual(closes, [True])

    def test_oversized_decompression_and_engine_failure_fail_closed(self):
        self.write_docx({"word/document.xml": b"x" * (128 * 1024 * 1024 + 1), "word/_rels/document.xml.rels": b"x"})
        with self.assertRaisesRegex(OCRAdapterError, "decompressed"):
            self.run_extract()
        self.write_docx()
        with self.assertRaisesRegex(OCRAdapterError, "inference failed"):
            self.run_extract(engine=lambda _b: (_ for _ in ()).throw(RuntimeError("failure")))


if __name__ == "__main__": unittest.main()
