"""Workbench exposure contract for safe provider usage summaries."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app.workbench as workbench_module
from test_workbench_llm import WorkbenchLLMTests


class WorkbenchProviderUsageTests(unittest.TestCase):
    setUp = WorkbenchLLMTests.setUp
    tearDown = WorkbenchLLMTests.tearDown
    _agent_result = staticmethod(WorkbenchLLMTests._agent_result)
    def test_analysis_response_and_saved_runtime_include_only_usage_summary(self):
        usage = {
            "input_tokens": {"total": None, "observed_subtotal": 12, "coverage": "partial",
                             "reported_calls": 1, "attempted_calls": 2, "raw": "secret"},
            "output_tokens": {"total": 8, "observed_subtotal": 8, "coverage": "complete",
                              "reported_calls": 2, "attempted_calls": 2},
            "unknown_metric": {"total": 99},
        }
        result_data = self._agent_result()
        result_data["execution_metrics"] = {"provider_usage": usage, "raw_events": ["secret"]}
        with patch.object(workbench_module, "run_agent", return_value=result_data):
            result = self.app.analysis(self.room_id, {
                "content": "확인", "sources": ["incident"], "context": self.context,
            })

        expected = {
            "input_tokens": {"total": None, "observed_subtotal": 12, "coverage": "partial",
                             "reported_calls": 1, "attempted_calls": 2},
            "output_tokens": {"total": 8, "observed_subtotal": 8, "coverage": "complete",
                              "reported_calls": 2, "attempted_calls": 2},
        }
        self.assertEqual(result["analysis"]["provider_usage"], expected)
        self.assertNotIn("raw_events", result["analysis"])
        self.assertNotIn("raw", result["analysis"]["provider_usage"]["input_tokens"])
        with self.app._db() as db:
            row = db.execute("SELECT payload FROM item_analyses WHERE room_id=?", (self.room_id,)).fetchone()
        import json
        self.assertEqual(json.loads(row["payload"])["analysis"]["provider_usage"], expected)

    def test_missing_and_invalid_usage_preserve_legacy_shape(self):
        from app.workbench import _safe_provider_usage

        self.assertIsNone(_safe_provider_usage(None))
        self.assertIsNone(_safe_provider_usage({"input_tokens": {"total": 2, "coverage": "complete"}}))
        sanitized = _safe_provider_usage({"input_tokens": {
            "total": 1, "observed_subtotal": 1, "coverage": "complete",
            "reported_calls": 1, "attempted_calls": 1, "prompt": "secret",
        }})
        self.assertEqual(sanitized["input_tokens"]["total"], 1)
        self.assertNotIn("prompt", sanitized["input_tokens"])


if __name__ == "__main__":
    unittest.main()
