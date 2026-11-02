"""Agent boundary checks for per-source OCR marker enforcement."""

from pathlib import Path
from unittest.mock import patch

import test_document_retrieval_completeness_e2e as helper
import demo_data


class OCRMarkerAgentScopeTests(helper.DocumentRetrievalCompletenessE2ETests):
    def setUp(self):
        with patch.object(
            helper,
            "generate",
            side_effect=lambda settings: demo_data.generate(settings, include_goldens=False),
        ):
            super().setUp()
        golden_file = Path(self.settings.data["paths"]["golden_file"])
        self.assertFalse(golden_file.exists(), "synthetic setup must not generate goldens")

    @staticmethod
    def _marked_item(content_kind, derivative_available_at=None):
        item = {
            "document_id": "SYN-DOC-MARKED",
            "chunk_id": "SYN-CHUNK-MARKED",
            "version": "v1",
            "text": "Synthetic evidence with explicit content marker.",
            "source_ref": "synthetic://document/marked",
            "locator": "page:1",
            "status": "active",
            "available_at": "2026-03-01T00:00:00+09:00",
            "incident_ids": ["SYN-INCIDENT-ID", "synthetic-pk-2026-01"],
            "relation": "direct",
            "score": 1.0,
            "observed_at": None,
            "effective_from": None,
            "effective_to": None,
            "applicability": None,
            "content_kind": content_kind,
        }
        if derivative_available_at is not None:
            item["derivative_available_at"] = derivative_available_at
        return item

    def test_strict_source_without_marker_fails_closed(self):
        self.settings.data["retrieval"]["internal_documents"]["require_content_kind"] = True

        result, _, calls, _ = self._run_case("internal_documents", {})

        self.assertEqual(len(calls), 1)
        self.assertNotEqual(result["status"], "answered")
        self.assertIn(
            "DOCUMENT_RETRIEVAL_FAILED",
            [event.get("error") for event in result.get("events", [])],
        )

    def test_strict_setting_is_bound_to_selected_source_only(self):
        self.settings.data["retrieval"]["engineer_notes"]["require_content_kind"] = True
        self.settings.data["retrieval"]["internal_documents"]["require_content_kind"] = False

        result, _, calls, _ = self._run_case("internal_documents", {})

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "answered")

    def test_strict_source_accepts_explicit_text_through_agent_callback(self):
        self.settings.data["retrieval"]["internal_documents"]["require_content_kind"] = True

        result, _, calls, _ = self._run_case(
            "internal_documents", {"items": [self._marked_item("text")]},
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["evidence"][-1]["result"]["items"][0]["content_kind"], "text")

    def test_strict_source_rejects_future_image_ocr_derivative_through_agent(self):
        self.settings.data["retrieval"]["internal_documents"]["require_content_kind"] = True

        result, _, calls, _ = self._run_case(
            "internal_documents",
            {"items": [self._marked_item("image_ocr", "2026-04-01T00:00:00+09:00")]},
        )

        self.assertEqual(len(calls), 1)
        self.assertNotEqual(result["status"], "answered")
        self.assertTrue(any(
            "DOCUMENT_RETRIEVAL_FAILED" in str(event.get("error", ""))
            for event in result.get("events", [])
        ))

    def test_no_match_remains_valid_for_strict_source(self):
        self.settings.data["retrieval"]["internal_documents"]["require_content_kind"] = True

        result, _, calls, _ = self._run_case("internal_documents", {}, no_match=True)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "answered")

