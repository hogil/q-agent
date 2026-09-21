import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app.workbench as workbench_module
from app.config_loader import Settings, merge
from app.workbench import Workbench, WorkbenchError, load_workbench


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchLLMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_path = root / "workbench.yaml"
        self.chat_path = root / "chat.sqlite"
        static_root = root / "static"
        static_root.mkdir()
        (static_root / "index.html").write_text("<main>test</main>", encoding="utf-8")
        self.config_path.write_text(
            "config_version: 1\n"
            "demo:\n"
            f"  base_config: {str(ROOT / 'config/config.yaml').replace(chr(92), '/')}\n"
            f"  overlay: {str(ROOT / 'config/demo.yaml').replace(chr(92), '/')}\n"
            "chat:\n"
            f"  sqlite_file: {str(self.chat_path).replace(chr(92), '/')}\n"
            "  history_limit: 40\n"
            "cutoff: 2026-03-31\n"
            f"static_root: {str(static_root).replace(chr(92), '/')}\n",
            encoding="utf-8",
        )
        config = load_workbench(self.config_path)
        data = merge(config["settings"].data, {
            "models": {
                "text": {
                    "enabled": True,
                    "mode": "api",
                    "base_url": "http://llm.test/v1",
                    "api_key_env": "TEST_QAGENT_LLM_KEY",
                    "served_model": "mock-model",
                }
            }
        })
        config["settings"] = Settings(data, config["settings"].source_files)
        self.app = Workbench(config)
        self.room_id = self.app.create_room("LLM test", "SYN-2026-01")["id"]
        workspace = self.app.workspace("SYN-2026-01")
        self.incident_id = workspace["incident"]["incident_id"]
        wafer = workspace["wafers"][0]
        self.context = {
            "incident_number": "SYN-2026-01",
            "item": "SYN-TEMP",
            "step": "ETCH",
            "equipment": "EQP-ETCH-01",
            "from": "2026-01-01T00:00:00+00:00",
            "to": "2026-01-31T23:59:59+00:00",
            "wafers": [{"lot_id": wafer["lot_id"], "wafer_id": wafer["wafer_id"]}],
        }

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _agent_result(answer="mock answer", events=None, status="answered"):
        return {
            "status": status,
            "answer": answer,
            "events": events or [
                {"event": "llm_start", "role": "router", "model": "mock-model", "step": 1},
                {"event": "tool_result", "source": "find_incidents"},
                {"event": "llm_start", "role": "judge", "model": "mock-model", "step": 2},
                {"event": "llm_start", "role": "answer", "model": "mock-model", "step": 3},
                {"event": "llm_output", "role": "answer", "model": "mock-model", "step": 3},
            ],
            "tool_calls": 1,
            "llm_calls": 3,
            "limitations": ["synthetic fixture"],
        }

    def test_llm_bridge_scopes_incident_and_disables_unchecked_sources(self):
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured["settings"] = settings
            captured["question"] = question
            captured["kwargs"] = kwargs
            return self._agent_result()

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            result = self.app.analysis(self.room_id, {
                "content": "선택 사고의 원인을 확인해줘",
                "sources": ["incident", "trend"],
                "context": self.context,
            })

        self.assertEqual(captured["kwargs"]["selected"], [self.incident_id])
        self.assertEqual(captured["kwargs"]["request_scope"], "incident")
        self.assertEqual(captured["kwargs"]["as_of"], "2026-03-31")
        self.assertEqual(captured["question"], "선택 사고번호: SYN-2026-01\n선택 사고의 원인을 확인해줘")
        self.assertEqual(captured["kwargs"]["context_data"]["selected_incident"], "SYN-2026-01")
        self.assertEqual(captured["kwargs"]["context_data"]["requested_sources"], ["incident", "trend"])
        self.assertFalse(captured["settings"].data["meetings"]["enabled"])
        self.assertTrue(all(not item["enabled"] for item in captured["settings"].data["image_tools"].values()))

    def test_prior_history_is_unverified_and_filtered_to_current_incident(self):
        self.app._append_messages(
            self.room_id,
            "current incident note",
            [self.app._ref("data", "current", "current-1", "SYN-2026-01")],
            "current answer",
            [self.app._ref("data", "current", "current-2", "SYN-2026-01")],
        )
        self.app._append_messages(
            self.room_id,
            "other incident note",
            [self.app._ref("data", "other", "other-1", "SYN-2026-02")],
            "other answer",
            [self.app._ref("data", "other", "other-2", "SYN-2026-02")],
        )
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured["context"] = kwargs["context_data"]
            return self._agent_result()

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            self.app.analysis(self.room_id, {
                "content": "현재 사고를 이어서 분석해줘",
                "sources": ["incident"],
                "context": self.context,
            })

        history = captured["context"]["previous_messages_unverified"]
        history_text = " ".join(item["content"] for item in history)
        self.assertIn("current incident note", history_text)
        self.assertNotIn("other incident note", history_text)
        self.assertEqual(captured["context"]["selected_incident"], "SYN-2026-01")

    def test_selected_context_does_not_silently_truncate_long_questions(self):
        with patch.object(workbench_module, "run_agent") as run:
            with self.assertRaisesRegex(workbench_module.WorkbenchError, "content plus selected incident context"):
                self.app.analysis(self.room_id, {
                    "content": "x" * 12000, "sources": ["incident"], "context": self.context,
                })
        run.assert_not_called()

    def test_real_runtime_trace_and_status_are_persisted(self):
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result()):
            result = self.app.analysis(self.room_id, {
                "content": "실제 역할 trace를 저장해줘",
                "sources": ["incident"],
                "context": self.context,
            })

        runtime = result["analysis"]
        self.assertEqual(runtime["mode"], "llm")
        self.assertTrue(runtime["llm_connected"])
        self.assertEqual([item["role"] for item in runtime["trace"]], ["router", "judge", "answer"])
        self.assertEqual(runtime["status"], "answered")
        saved = self.app.analysis_metadata(self.room_id)["analysis"]
        self.assertEqual(saved["mode"], "llm")
        self.assertTrue(saved["llm_connected"])
        self.assertEqual(saved["trace"], runtime["trace"])

    def test_unavailable_or_invalid_llm_does_not_fallback_or_write(self):
        bad_results = (
            self._agent_result(answer="", status="unavailable", events=[]),
            self._agent_result(answer=None, status="answered", events=[]),
        )
        for bad_result in bad_results:
            with self.subTest(status=bad_result["status"], answer=bad_result["answer"]):
                room_id = self.app.create_room("failure", "SYN-2026-01")["id"]
                before = self.app.room(room_id)
                with patch.object(workbench_module, "run_agent", return_value=bad_result):
                    with self.assertRaisesRegex(WorkbenchError, "LLM analysis did not complete"):
                        self.app.analysis(room_id, {
                            "content": "실패하면 demo로 대체하지 마",
                            "sources": ["incident"],
                            "context": self.context,
                        })
                after = self.app.room(room_id)
                self.assertEqual(after["messages"], before["messages"])
                self.assertIsNone(self.app.analysis_metadata(room_id)["analysis"])
                self.assertNotIn(room_id, self.app.running_rooms)

    def test_room_mutations_are_blocked_while_get_remains_available(self):
        started = threading.Event()
        release = threading.Event()
        outcome = []

        def blocking_run(settings, question, **kwargs):
            kwargs['emit']({'event': 'llm_start', 'role': 'router', 'model': 'mock-model', 'step': 1})
            kwargs['emit']({'event': 'llm_output', 'role': 'router', 'output': {'decision': 'execute', 'private': 'not public'}})
            started.set()
            self.assertTrue(release.wait(3))
            return self._agent_result()

        def run_analysis():
            try:
                self.app.analysis(self.room_id, {
                    "content": "긴 분석",
                    "sources": ["incident"],
                    "context": self.context,
                })
            except Exception as exc:  # pragma: no cover - assertion below reports it
                outcome.append(exc)

        with patch.object(workbench_module, "run_agent", side_effect=blocking_run):
            thread = threading.Thread(target=run_analysis)
            thread.start()
            self.assertTrue(started.wait(3))
            self.assertEqual(self.app.room(self.room_id)["id"], self.room_id)
            progress = self.app.analysis_progress(self.room_id)['run']
            self.assertEqual(progress['status'], 'running')
            self.assertEqual(progress['events'][-1]['status'], 'execute')
            self.assertNotIn('private', json.dumps(progress))
            with self.assertRaisesRegex(WorkbenchError, "analysis is already running"):
                self.app.update_room(self.room_id, {"title": "blocked"})
            with self.assertRaisesRegex(WorkbenchError, "analysis is already running"):
                self.app.delete_room(self.room_id)
            release.set()
            thread.join(3)

        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [])
        self.assertEqual(self.app.analysis_progress(self.room_id)['run']['status'], 'completed')

    def test_agent_overlay_rejects_database_changes_before_generation(self):
        root = Path(self.temp.name)
        overlay = root / "invalid-agent.yaml"
        overlay.write_text("database:\n  sqlite_file: altered.sqlite\n", encoding="utf-8")
        untouched_chat = root / "untouched-chat.sqlite"
        invalid_config = root / "invalid-workbench.yaml"
        invalid_config.write_text(
            self.config_path.read_text(encoding="utf-8").replace(
                str(self.chat_path).replace(chr(92), "/"),
                str(untouched_chat).replace(chr(92), "/"),
            )
            + f"agent_overlay: {str(overlay).replace(chr(92), '/')}\n",
            encoding="utf-8",
        )

        with patch.object(workbench_module, "generate") as generate:
            with self.assertRaisesRegex(WorkbenchError, "agent_overlay may only configure"):
                load_workbench(invalid_config)

        generate.assert_not_called()
        self.assertFalse(untouched_chat.exists())


if __name__ == "__main__":
    unittest.main()
