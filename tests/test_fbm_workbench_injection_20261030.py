"""Synthetic Workbench contract tests for the FBM retrieval callback."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app.workbench as workbench_module
from test_workbench_llm import WorkbenchLLMTests

_SyntheticWorkbenchFixture = WorkbenchLLMTests
del WorkbenchLLMTests


class FBMWorkbenchInjectionTests(unittest.TestCase):
    setUp = _SyntheticWorkbenchFixture.setUp
    tearDown = _SyntheticWorkbenchFixture.tearDown
    _agent_result = staticmethod(_SyntheticWorkbenchFixture._agent_result)

    def _enable_llm(self, app):
        app.settings.data["models"]["text"]["enabled"] = True

    def test_create_server_forwards_same_callback_to_workbench_and_run_agent(self):
        callback = lambda **kwargs: {"status": "NO_MATCH", "records": []}
        server = workbench_module.create_server(self.config_path, port=0, fbm_search_query=callback)
        try:
            self._enable_llm(server.app)
            self.assertIs(server.app.fbm_search_query, callback)
            captured = {}

            def fake_run(*args, **kwargs):
                captured.update(kwargs)
                return self._agent_result("합성 FBM 근거 없음")

            with patch.object(workbench_module, "run_agent", side_effect=fake_run):
                response = server.app.analysis(self.room_id, {
                    "content": "합성 사고의 유사 FBM 사례를 확인",
                    "sources": ["incident"], "context": self.context,
                })

            self.assertIs(captured["fbm_search_query"], callback)
            self.assertTrue(response["messages"][-1]["content"].startswith("합성 FBM 근거 없음"))
        finally:
            server.server_close()

    def test_missing_callback_stays_none_through_analysis(self):
        self._enable_llm(self.app)
        self.assertIsNone(self.app.fbm_search_query)
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return self._agent_result("합성 기본 동작")

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            response = self.app.analysis(self.room_id, {
                "content": "합성 사고 확인", "sources": ["incident"], "context": self.context,
            })

        self.assertIsNone(captured["fbm_search_query"])
        self.assertTrue(response["messages"][-1]["content"].startswith("합성 기본 동작"))

    def test_callback_and_raw_usage_fields_are_not_exposed_in_response(self):
        class SecretCallback:
            def __repr__(self):
                return "SYNTHETIC_CALLBACK_SECRET_OBJECT"

            def __call__(self, **kwargs):
                return {"status": "NO_MATCH", "records": []}

        callback = SecretCallback()
        self._enable_llm(self.app)
        self.app.fbm_search_query = callback
        result_data = self._agent_result("합성 결과")
        result_data["execution_metrics"] = {
            "provider_usage": {
                "input_tokens": {"total": 4, "observed_subtotal": 4, "coverage": "complete",
                                 "reported_calls": 1, "attempted_calls": 1, "raw": "SYNTHETIC_USAGE_SECRET"},
                "output_tokens": {"total": 2, "observed_subtotal": 2, "coverage": "complete",
                                  "reported_calls": 1, "attempted_calls": 1},
                "callback": callback,
            },
            "raw_events": ["SYNTHETIC_EVENT_SECRET"],
        }
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return result_data

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            response = self.app.analysis(self.room_id, {
                "content": "합성 사고 사용량 확인", "sources": ["incident"], "context": self.context,
            })

        self.assertIs(captured["fbm_search_query"], callback)
        serialized = json.dumps(response, ensure_ascii=False, default=str)
        for secret in ("SYNTHETIC_CALLBACK_SECRET_OBJECT", "SYNTHETIC_USAGE_SECRET",
                       "SYNTHETIC_EVENT_SECRET"):
            self.assertNotIn(secret, serialized)
        usage = response["analysis"]["provider_usage"]
        self.assertEqual(usage["input_tokens"]["total"], 4)
        self.assertNotIn("callback", usage)


del _SyntheticWorkbenchFixture


if __name__ == "__main__":
    unittest.main()
