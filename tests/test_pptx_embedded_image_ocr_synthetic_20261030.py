"""Synthetic-only tests for embedded raster PPTX OCR candidates."""
from datetime import datetime, timezone
import hashlib
import traceback
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from research.document_image_ocr_adapter_20261030 import OCRAdapterError
from research.pptx_embedded_image_ocr_synthetic_20261030 import extract_pptx_embedded_image_ocr_candidates


class Result:
    boxes = [[[1, 1], [10, 1], [10, 8], [1, 8]]]
    txts = ("합성 OCR",)
    scores = (0.91,)


class Engine:
    def __call__(self, payload):
        assert isinstance(payload, bytes)
        return Result()


class PptxOCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name); self.src = self.root / "src"; self.src.mkdir()
        self.when = datetime(2026, 10, 29, tzinfo=timezone.utc); self.as_of = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.meta = {"source_document_id":"synthetic-pptx", "source_version":"v1", "available_at":self.when,
                     "synthetic_fixture":True, "source_ref":"synthetic://pptx/fixture-1"}
        b = BytesIO(); Image.new("RGB", (20, 16), "white").save(b, format="PNG"); self.png = b.getvalue()
        self.write_pptx()

    def tearDown(self): self.tmp.cleanup()

    def write_pptx(self, *, slide_xml=None, rel_xml=None, extras=None, presentation_xml=None, pres_rel_xml=None, slide2_xml=None, slide1_id="256"):
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        slide_xml = slide_xml or (f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:pic><p:nvPicPr><p:cNvPr id="7" name="Picture 7"/></p:nvPicPr><p:blipFill><a:blip r:embed="rImg"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>').encode()
        rel_xml = rel_xml or b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/></Relationships>'
        presentation_xml = presentation_xml or f'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="{slide1_id}" r:id="sRel"/></p:sldIdLst></p:presentation>'.encode()
        pres_rel_xml = pres_rel_xml or b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="sRel" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>'
        entries = {"ppt/presentation.xml":presentation_xml, "ppt/_rels/presentation.xml.rels":pres_rel_xml,
            "ppt/slides/slide1.xml":slide_xml, "ppt/slides/_rels/slide1.xml.rels":rel_xml,
            "ppt/media/image1.png":self.png}
        if slide2_xml is not None:
            entries.update({"ppt/slides/slide2.xml":slide2_xml,
                "ppt/slides/_rels/slide2.xml.rels":rel_xml.replace(b'rImg', b'rImg2'),
                "ppt/media/image2.png":self.png})
        if extras: entries.update(extras)
        self.pptx = self.src / "synthetic.pptx"
        with ZipFile(self.pptx, "w", ZIP_DEFLATED) as z:
            for name, data in entries.items(): z.writestr(name, data)

    def run_extract(self, **changes):
        args = dict(pptx_path=self.pptx, source_root=self.src, metadata=self.meta, as_of=self.as_of,
            authorize_source=lambda _m: True, engine=Engine())
        args.update(changes)
        return extract_pptx_embedded_image_ocr_candidates(**args)

    def test_picture_ocr_hash_order_and_existing_chunk_link(self):
        anchor = "ppt/slides/slide1.xml#shape-7"; self.meta["anchor_chunk_ids"] = {anchor:"existing-42"}
        result = self.run_extract()
        c = result["candidates"][0]
        self.assertEqual(c["slide_ordinal"], 1); self.assertEqual(c["slide_file_number"], 1)
        self.assertEqual(c["picture_shape_id"], "7"); self.assertEqual(c["existing_chunk_id"], "existing-42")
        self.assertEqual(c["ordered_text_confidence"][0]["text"], "합성 OCR")
        self.assertEqual(c["image_sha256"], hashlib.sha256(self.png).hexdigest())
        self.assertEqual(c["original_sha256"], hashlib.sha256(self.pptx.read_bytes()).hexdigest())
        self.assertEqual(c["source_available_at"], self.when.isoformat())
        self.assertIsNone(c["available_at"]); self.assertEqual(c["ocr_derivative_time_status"], "unverified")

    def test_unknown_presentation_order_and_unlinked_candidate(self):
        self.write_pptx(pres_rel_xml=b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        with self.assertRaisesRegex(OCRAdapterError, "slide relationship"): self.run_extract()

    def test_synthetic_metadata_required_before_source_read(self):
        self.meta["synthetic_fixture"] = False
        with self.assertRaisesRegex(OCRAdapterError, "synthetic fixture"):
            self.run_extract(pptx_path=self.src / "missing.pptx")

    def test_non_mapping_metadata_rejected_generically(self):
        with self.assertRaisesRegex(OCRAdapterError, "metadata must be a mapping"):
            self.run_extract(metadata=["sensitive metadata"])

    def test_duplicate_or_nonpositive_picture_shape_id_rejected(self):
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        pic = f'<p:pic><p:nvPicPr><p:cNvPr id="7"/></p:nvPicPr><p:blipFill><a:blip r:embed="rImg"/></p:blipFill></p:pic>'
        template = f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree>{{}}</p:spTree></p:cSld></p:sld>'
        self.write_pptx(slide_xml=template.format(pic + pic).encode())
        with self.assertRaisesRegex(OCRAdapterError, "duplicate slide shape id"): self.run_extract()
        pic01 = pic.replace('id="7"','id="01"')
        self.write_pptx(slide_xml=template.format(pic.replace('id="7"','id="1"') + pic01).encode())
        with self.assertRaisesRegex(OCRAdapterError, "duplicate slide shape id"): self.run_extract()
        for shape_id in ("0", "2147483648", "4294967295"):
            self.write_pptx(slide_xml=template.format(pic.replace('id="7"',f'id="{shape_id}"')).encode())
            self.assertEqual(self.run_extract()["candidates"][0]["picture_shape_id"], str(int(shape_id)))
        self.write_pptx(slide_xml=template.format(pic.replace('id="7"','id="4294967296"')).encode())
        with self.assertRaisesRegex(OCRAdapterError, "0 and 4294967295"): self.run_extract()
        text_shape = '<p:sp><p:nvSpPr><p:cNvPr id="7" name="Text"/></p:nvSpPr></p:sp>'
        self.write_pptx(slide_xml=template.format(pic + text_shape).encode())
        with self.assertRaisesRegex(OCRAdapterError, "duplicate slide shape id"): self.run_extract()

    def test_presentation_slide_ids_must_be_valid_and_unique(self):
        for first, second, message in (("256", "256", "duplicate presentation slide id"),
                                       ("invalid", "257", "between 256 and 2147483647"),
                                       ("255", "257", "between 256 and 2147483647")):
            pres = f'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="{first}" r:id="s1"/><p:sldId id="{second}" r:id="s2"/></p:sldIdLst></p:presentation>'.encode()
            rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="s1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/><Relationship Id="s2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/></Relationships>'
            slide2 = b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree/></p:cSld></p:sld>'
            self.write_pptx(presentation_xml=pres, pres_rel_xml=rels, slide2_xml=slide2)
            with self.assertRaisesRegex(OCRAdapterError, message): self.run_extract()
        self.write_pptx(slide1_id="256")
        self.assertEqual(self.run_extract()["candidates"][0]["slide_ordinal"], 1)

    def test_picture_shape_total_limit_stops_later_media_and_all_ocr(self):
        import research.pptx_embedded_image_ocr_synthetic_20261030 as module
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        empty_pics = ''.join('<p:pic><p:nvPicPr><p:cNvPr id="%d"/></p:nvPicPr></p:pic>' % i for i in range(1, 513))
        slide2 = f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree>{empty_pics}<p:pic><p:nvPicPr><p:cNvPr id="900"/></p:nvPicPr><p:blipFill><a:blip r:embed="rImg2"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>'.encode()
        pres = b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="s1"/><p:sldId id="257" r:id="s2"/></p:sldIdLst></p:presentation>'
        rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="s1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/><Relationship Id="s2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/></Relationships>'
        self.write_pptx(presentation_xml=pres, pres_rel_xml=rels, slide2_xml=slide2)
        original_read = module.ZipFile.read; media=[]; engines=[]
        def tracked(archive, member, *a, **kw):
            name = member.filename if hasattr(member,"filename") else member
            if isinstance(name,str) and name.startswith("ppt/media/"): media.append(name)
            return original_read(archive, member, *a, **kw)
        with mock.patch.object(module.ZipFile, "read", tracked):
            with self.assertRaisesRegex(OCRAdapterError, "picture count exceeds"):
                self.run_extract(engine=lambda payload: engines.append(payload))
        self.assertNotIn("ppt/media/image2.png", media); self.assertEqual(engines, [])

    def test_pillow_failure_traceback_is_sanitized(self):
        with mock.patch("PIL.Image.open", side_effect=RuntimeError("PRIVATE_PIL_PATH")):
            try: self.run_extract()
            except OCRAdapterError as exc:
                rendered = "".join(traceback.format_exception(exc))
                self.assertIn("unsupported or corrupt embedded raster", rendered)
                self.assertNotIn("PRIVATE_PIL_PATH", rendered)
            else: self.fail("expected sanitized adapter error")

    def test_callback_exception_secrets_are_absent_from_traceback(self):
        secret = "SECRET_ENGINE_OR_AUTH_PATH"
        for callback, match in ((lambda _m: (_ for _ in ()).throw(RuntimeError(secret)), "authorization denied"),
                                (lambda _payload: (_ for _ in ()).throw(RuntimeError(secret)), "inference failed")):
            try:
                self.run_extract(authorize_source=callback if match.startswith("authorization") else lambda _m: True,
                                 engine=callback if match.startswith("inference") else Engine())
            except OCRAdapterError as exc:
                rendered = "".join(traceback.format_exception(exc))
                self.assertIn(match, rendered)
                self.assertNotIn(secret, rendered)
            else: self.fail("expected sanitized adapter error")

    def test_xml_crc_error_is_sanitized(self):
        import research.pptx_embedded_image_ocr_synthetic_20261030 as module
        with mock.patch.object(module.ZipFile, "read", side_effect=OSError("PRIVATE_CRC_PATH")):
            try: self.run_extract()
            except OCRAdapterError as exc:
                rendered = "".join(traceback.format_exception(exc))
                self.assertIn("cannot read PPTX XML part", rendered)
                self.assertNotIn("PRIVATE_CRC_PATH", rendered)
            else: self.fail("expected sanitized adapter error")

    def test_presentation_order_controls_candidates_and_orphan_is_excluded(self):
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        pic2 = (f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:pic><p:nvPicPr><p:cNvPr id="22"/></p:nvPicPr><p:blipFill><a:blip r:embed="rImg2"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>').encode()
        pres = b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="s2"/><p:sldId id="257" r:id="s1"/></p:sldIdLst></p:presentation>'
        rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="s1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/><Relationship Id="s2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/></Relationships>'
        self.write_pptx(presentation_xml=pres, pres_rel_xml=rels, slide2_xml=pic2,
                        extras={"ppt/slides/slide3.xml":b"<orphan/>"})
        out = self.run_extract(); cs = out["candidates"]
        self.assertEqual([(c["slide_file_number"],c["slide_ordinal"]) for c in cs], [(2,1),(1,2)])
        self.assertEqual(len(cs),2); self.assertTrue(any("orphan slide" in x for x in out["limitations"]))

    def test_source_denial_precedes_file_and_media_read_and_engine(self):
        import research.pptx_embedded_image_ocr_synthetic_20261030 as module
        original = module.ZipFile.read; reads=[]; engine=[]
        def tracked(archive, member, *a, **kw):
            name = member.filename if hasattr(member, "filename") else member
            if isinstance(name, str) and name.startswith("ppt/media/"): reads.append(name)
            return original(archive, member, *a, **kw)
        with mock.patch.object(module.ZipFile, "read", tracked):
            with self.assertRaisesRegex(OCRAdapterError, "denied"):
                self.run_extract(pptx_path=self.src / "missing.pptx", authorize_source=lambda _m: False,
                                 engine=lambda b: engine.append(b))
        self.assertEqual(reads, []); self.assertEqual(engine, [])

    def test_anchor_denial_precedes_media_read_and_engine(self):
        import research.pptx_embedded_image_ocr_synthetic_20261030 as module
        original = module.ZipFile.read; reads=[]; calls=[]
        def tracked(archive, member, *a, **kw):
            name = member.filename if hasattr(member, "filename") else member
            if isinstance(name, str) and name.startswith("ppt/media/"): reads.append(name)
            return original(archive, member, *a, **kw)
        with mock.patch.object(module.ZipFile, "read", tracked):
            with self.assertRaisesRegex(OCRAdapterError, "denied"):
                self.run_extract(authorize_source=lambda m: m.get("anchor_id") is None, engine=lambda b: calls.append(b))
        self.assertEqual(reads, []); self.assertEqual(calls, [])

    def test_external_relationship_and_unsafe_path_rejected(self):
        external = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.invalid/x" TargetMode="External"/></Relationships>'
        self.write_pptx(rel_xml=external)
        with self.assertRaisesRegex(OCRAdapterError, "missing or external"): self.run_extract()
        traversal = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../../../evil.png"/></Relationships>'
        self.write_pptx(rel_xml=traversal)
        with self.assertRaisesRegex(OCRAdapterError, "unsafe"): self.run_extract()

    def test_zip_duplicates_limits_and_malformed_xml_rejected(self):
        with ZipFile(self.pptx, "a", ZIP_DEFLATED) as z: z.writestr("ppt/media/image1.png", self.png)
        with self.assertRaisesRegex(OCRAdapterError, "duplicate"): self.run_extract()
        self.write_pptx(slide_xml=b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///secret">]><x>&e;</x>')
        with self.assertRaisesRegex(OCRAdapterError, "DTD"): self.run_extract()
        self.write_pptx(slide_xml=b"<broken")
        with self.assertRaisesRegex(OCRAdapterError, "invalid"): self.run_extract()
        self.write_pptx(extras={"ppt/extra.bin":b"x" * (128 * 1024 * 1024 + 1)})
        with self.assertRaisesRegex(OCRAdapterError, "decompressed"): self.run_extract()

    def test_normal_zip_directory_entries_are_accepted_but_unsafe_names_rejected(self):
        from io import BytesIO
        import research.pptx_embedded_image_ocr_synthetic_20261030 as module
        original = self.pptx.read_bytes()
        output = BytesIO()
        with ZipFile(BytesIO(original), "r") as source, ZipFile(output, "w", ZIP_DEFLATED) as dest:
            dest.writestr("ppt/", b""); dest.writestr("ppt/media/", b"")
            for info in source.infolist(): dest.writestr(info.filename, source.read(info))
        self.pptx.write_bytes(output.getvalue())
        self.assertEqual(len(self.run_extract()["candidates"]), 1)
        with self.assertRaisesRegex(OCRAdapterError, "unsafe ZIP member"):
            module._zip_member_name("ppt//media/", is_directory=True)
        with self.assertRaisesRegex(OCRAdapterError, "unsafe ZIP member"):
            module._zip_member_name("../", is_directory=True)

    def test_python_pptx_generated_synthetic_deck_integration(self):
        try:
            from pptx import Presentation
            from pptx.dml.color import RGBColor
            from pptx.util import Inches
        except ImportError:
            self.skipTest("python-pptx is not installed; no install attempted")
        from PIL import Image as PILImage
        image_path = self.src / "generated.png"
        PILImage.new("RGB", (24, 18), (255, 255, 255)).save(image_path, format="PNG")
        prs = Presentation()
        blank = prs.slide_layouts[6]
        first = prs.slides.add_slide(blank)
        first.shapes.add_picture(str(image_path), Inches(1), Inches(1))
        second = prs.slides.add_slide(blank)
        second.shapes.add_picture(str(image_path), Inches(2), Inches(2))
        generated = self.src / "python_pptx_synthetic.pptx"
        prs.save(generated)
        self.meta["source_ref"] = "synthetic://python-pptx/two-slide-raster-fixture"
        result = self.run_extract(pptx_path=generated)
        candidates = result["candidates"]
        self.assertEqual([c["slide_ordinal"] for c in candidates], [1, 2])
        self.assertEqual([c["slide_file_number"] for c in candidates], [1, 2])
        self.assertEqual([c["ordered_text_confidence"][0]["text"] for c in candidates], ["합성 OCR", "합성 OCR"])
        self.assertEqual(candidates[0]["image_sha256"], hashlib.sha256(image_path.read_bytes()).hexdigest())
        self.assertTrue(all(c["picture_shape_id"] for c in candidates))

    def test_path_read_error_is_sanitized(self):
        with mock.patch("pathlib.Path.open", side_effect=OSError("private source path")):
            with self.assertRaisesRegex(OCRAdapterError, "cannot read authorized PPTX source") as err:
                self.run_extract()
        self.assertNotIn("private source path", str(err.exception))

    def test_image_budgets_checked_before_accumulating_payloads(self):
        import research.pptx_embedded_image_ocr_synthetic_20261030 as module
        original_read = module.ZipFile.read
        with mock.patch.object(module, "MAX_OCR_IMAGE_BYTES", len(self.png) - 1):
            reads=[]
            def tracked(archive, member, *a, **kw):
                reads.append(member.filename if hasattr(member,"filename") else member)
                return original_read(archive, member, *a, **kw)
            with mock.patch.object(module.ZipFile, "read", tracked):
                with self.assertRaisesRegex(OCRAdapterError, "byte budget"): self.run_extract()
                self.assertNotIn("ppt/media/image1.png", reads)
        with mock.patch.object(module, "MAX_OCR_IMAGE_PIXELS", 20 * 16 - 1):
            with self.assertRaisesRegex(OCRAdapterError, "pixel budget"): self.run_extract()


if __name__ == "__main__": unittest.main()
