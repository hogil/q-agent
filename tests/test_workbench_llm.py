import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app.workbench as workbench_module
from app.config_loader import Settings, merge
from app.workbench import Workbench, WorkbenchError, load_workbench
from app.workbench_data import load_workbench_data


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
        self.assertTrue(captured["kwargs"]["inspection_requested"])
        self.assertEqual(captured["question"], "선택 사고번호: SYN-2026-01\n선택 사고의 원인을 확인해줘")
        self.assertEqual(captured["kwargs"]["context_data"]["selected_incident"], "SYN-2026-01")
        self.assertEqual(captured["kwargs"]["context_data"]["requested_sources"], ["incident", "trend"])
        self.assertFalse(captured["settings"].data["meetings"]["enabled"])
        self.assertTrue(all(not item["enabled"] for item in captured["settings"].data["image_tools"].values()))

    def test_default_room_has_saved_analysis_not_only_chat(self):
        self.assertIsNone(self.app.bootstrap()["default_room_id"])
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result("Saved analysis")):
            result = self.app.analysis(self.room_id, {
                "content": "분석", "sources": ["incident"], "context": self.context,
            })
        self.app._append_messages(self.room_id, "follow up", [], "Later chat", [])
        self.assertEqual(self.app.bootstrap()["default_room_id"], self.room_id)
        report = self.app.analysis_metadata(self.room_id)["analysis"]["report"]
        self.assertEqual(report["summary"], "Saved analysis")
        self.assertEqual(report["images"], [])
        self.assertEqual(result["analysis"]["answer_message_id"], result["messages"][-1]["id"])
        self.assertEqual(report["version"], 2)
        self.assertEqual(result["analysis"]["release"], self.app.release)

    def test_default_room_requires_original_message_and_matching_incident(self):
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result()):
            result = self.app.analysis(self.room_id, {
                "content": "분석", "sources": ["incident"], "context": self.context,
            })
        self.app.update_room(self.room_id, {"incident_number": "SYN-2026-02"})
        self.assertIsNone(self.app.bootstrap()["default_room_id"])
        self.app.update_room(self.room_id, {"incident_number": "SYN-2026-01"})
        with self.app._db() as db:
            db.execute("DELETE FROM messages WHERE id=?", (result["messages"][-1]["id"],))
        self.assertIsNone(self.app.bootstrap()["default_room_id"])

    def test_failed_analysis_does_not_become_default_room(self):
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result(status="unavailable")):
            with self.assertRaises(WorkbenchError):
                self.app.analysis(self.room_id, {"content": "분석", "sources": ["incident"], "context": self.context})
        self.assertIsNone(self.app.bootstrap()["default_room_id"])

    def test_report_images_are_bound_to_queried_assets_and_historical_references(self):
        self.app.raw_data = {"SYN-2026-01": {"sem_assets": [
            {"id": "SEM-A", "lotId": "LOT-A", "waferId": "W01", "src": "/assets/a.png",
             "description": "Synthetic image", "provenance": "synthetic"},
            {"id": "SEM-B", "lotId": "LOT-B", "waferId": "W02", "src": "/assets/b.png",
             "description": "Other image", "provenance": "synthetic"},
        ]}}
        events = [
            {"event": "tool_result", "source": "get_engineering_snapshot", "result": {"sections": {
                "trend": {"stats": {"signal": {"unit": "degC", "onset_summary": {"delta": {"value": 0.2}}}}},
                "maps": {"records": [{"incident_number": "HIST-1", "sem": {"id": "HIST-SEM-1",
                    "src": "/assets/history.png", "occurred_at": "2025-01-01", "description": "Historical synthetic"}}]},
            }}},
            {"event": "tool_result", "source": "compare_sem_images", "result": {
                "status": "INCOMPARABLE", "findings": ["Alignment not verified"],
                "provenance": {"validated_asset_metadata": [
                    {"asset_id": "SEM-A", "lot_id": "LOT-A", "wafer_id": "W01",
                     "item": self.context["item"], "step": self.context["step"]},
                    {"asset_id": "SEM-B", "lot_id": "WRONG-LOT", "wafer_id": "W02",
                     "item": self.context["item"], "step": self.context["step"]},
                ]},
            }},
        ]
        report = self.app._analysis_report(self._agent_result(events=events), self.context)
        self.assertEqual([row["id"] for row in report["images"]], ["SEM-A", "HIST-SEM-1"])
        self.assertEqual(report["images"][1]["kind"], "historical")
        self.assertEqual(report["trend"][0]["onset_summary"]["delta"]["value"], 0.2)
        self.assertEqual(report["image_findings"][0]["status"], "INCOMPARABLE")
        empty = self.app._analysis_report(self._agent_result(), self.context)
        self.assertEqual(empty["images"], [])

    def test_historical_overlay_uses_only_queried_reference_and_matching_scope(self):
        vector = {"x": 1, "y": 2, "dx": 0.2, "dy": 0.3}
        overlay = {"id": "OVL-1", "modality": "overlay", "incident_number": "HIST-1",
                   "step": self.context["step"], "item": self.context["item"], "vectors": [vector]}
        self.app.raw_data = {"SYN-2026-01": {
            "image_history": [overlay, {**overlay, "id": "NOT-QUERIED"}],
            "inform_notes": [{"id": "INFORM-1", "title": "Historical bridge review"}],
        }}
        events = [{"event": "tool_result", "source": "get_engineering_snapshot", "result": {
            "sections": {"maps": {"records": [{"id": "REF-1", "incident_number": "HIST-1",
                "inform_id": "INFORM-1", "overlay": {"id": "OVL-1"}}]}}}}]
        report = self.app._analysis_report(self._agent_result(events=events), self.context)
        self.assertEqual(len(report["historical_cases"]), 1)
        case = report["historical_cases"][0]
        self.assertEqual(case["title"], "Historical bridge review")
        self.assertEqual(case["overlay"]["vectors"], [vector])
        self.assertNotIn("vectors", events[0]["result"]["sections"]["maps"]["records"][0]["overlay"])
        for field in ("step", "item", "incident_number", "modality"):
            with self.subTest(field=field):
                self.app.raw_data["SYN-2026-01"]["image_history"] = [{**overlay, field: "wrong"}]
                invalid = self.app._analysis_report(self._agent_result(events=events), self.context)
                self.assertNotIn("vectors", invalid["historical_cases"][0]["overlay"])
        self.assertEqual(self.app._analysis_report(self._agent_result(), self.context)["historical_cases"], [])

    def test_validated_inspection_plan_is_displayed_with_synthetic_disclaimer(self):
        plan = [
            {"kind": "historical_match", "target": "SYN-2025-09 사고", "basis": "동일 Etch 단계와 장비군", "comparison": "원인 코드와 재발 패턴 대조", "evidence_ids": ["evidence-1"]},
            {"kind": "check", "target": "ETCH chamber 온도 로그", "basis": "현재 사고의 공정 조건 확인", "comparison": "사고 전후 평균과 허용 범위 비교", "evidence_ids": ["evidence-2"]},
            {"kind": "eds_followup", "target": "EDS 전기 특성 결과", "basis": "후속 EDS 수신 필요", "comparison": "Fail bit 분포와 과거 매칭 사고 비교", "evidence_ids": ["evidence-3"]},
        ]

        with patch.object(workbench_module, "run_agent", return_value={
            **self._agent_result(answer="근거 기반 분석 결과"),
            "inspection_plan": plan,
        }):
            result = self.app.analysis(self.room_id, {
                "content": "과거 사고와 점검 및 EDS 후속을 확인해줘",
                "sources": ["incident"],
                "context": self.context,
            })

        answer = result["messages"][-1]["content"]
        self.assertIn("과거 사고 매칭", answer)
        self.assertIn("대상: SYN-2025-09 사고", answer)
        self.assertIn("근거: 동일 Etch 단계와 장비군", answer)
        self.assertIn("비교·확인: 원인 코드와 재발 패턴 대조", answer)
        self.assertIn("점검 권고", answer)
        self.assertIn("대상: ETCH chamber 온도 로그", answer)
        self.assertIn("근거: 현재 사고의 공정 조건 확인", answer)
        self.assertIn("비교·확인: 사고 전후 평균과 허용 범위 비교", answer)
        self.assertIn("EDS 후속 확인", answer)
        self.assertIn("대상: EDS 전기 특성 결과", answer)
        self.assertIn("근거: 후속 EDS 수신 필요", answer)
        self.assertIn("비교·확인: Fail bit 분포와 과거 매칭 사고 비교", answer)
        self.assertIn("synthetic fixture", answer)
        self.assertIn("[합성 데이터 · LLM 생성 답변]", answer)

    def test_engineering_sources_are_read_by_tool_not_promoted_ui_context(self):
        self.app.raw_data = load_workbench_data({"raw_file": str(ROOT / "data/workbench/raw.example.json")}, ROOT)
        context = {**self.context, "step": "SYN-ETCH-10", "equipment": "SYN-EQP-01",
                   "map_comparison": {"a": self.context["wafers"], "b": []}}

        def fake_run(settings, question, **kwargs):
            query = kwargs["engineering_query"]
            result = query(actor=self.app.actor, incident_ids=[self.incident_id], as_of="2026-03-31")
            self.assertIn("production", result["sections"])
            self.assertNotIn("sem", result["sections"])
            self.assertNotIn("production", kwargs["context_data"]["unavailable_sources"])
            self.assertEqual(kwargs["context_data"]["ui_context_unverified"]["map_comparison"],
                             context["map_comparison"])
            events = self._agent_result()["events"] + [
                {"event": "tool_result", "source": "get_engineering_snapshot", "result": result}]
            return self._agent_result(events=events)

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            response = self.app.analysis(self.room_id, {
                "content": "합성 재공과 상태 확인", "sources": ["incident", "production"], "context": context})
        self.assertEqual(response["analysis"]["steps"][1]["status"], "completed")

    def test_enterprise_source_is_gated_and_failed_query_is_not_completed(self):
        from unittest.mock import Mock
        self.app.settings.data['enterprise']['enabled'] = True
        enterprise_result = {'status': 'UNAVAILABLE', 'systems': [
            {'id': 'mes', 'system': 'Synthetic MES', 'view': 'approved_events', 'status': 'UNAVAILABLE', 'row_count': 0}],
            'limitations': ['ENTERPRISE_QUERY_FAILED']}
        connector = Mock()
        connector.query.return_value = enterprise_result

        def fake_run(settings, question, **kwargs):
            result = kwargs['engineering_query'](self.app.actor, [self.incident_id], '2026-03-31')
            self.assertEqual(result['sections']['enterprise'], enterprise_result)
            self.assertNotIn('synthetic', result)
            self.assertIn('get_engineering_snapshot', kwargs['requested_tools'])
            events = self._agent_result()['events'] + [
                {'event': 'tool_result', 'source': 'get_engineering_snapshot', 'result': result}]
            return self._agent_result(events=events, status='partial')

        with patch.object(workbench_module, 'EnterpriseTools', return_value=connector), \
                patch.object(workbench_module, 'run_agent', side_effect=fake_run):
            result = self.app.analysis(self.room_id, {'content': 'Query system', 'sources': ['incident', 'enterprise'], 'context': self.context})
        self.assertEqual(result['analysis']['steps'][1]['status'], 'unavailable')
        self.assertEqual(result['analysis']['enterprise']['status'], 'UNAVAILABLE')
        connector.query.assert_called_once_with(self.app.actor, [self.incident_id], '2026-03-31')

    def test_enterprise_overlay_loads_but_cannot_target_chat_database(self):
        import yaml
        overlay = Path(self.temp.name) / 'sql.local.yaml'
        cfg = yaml.safe_load((ROOT / 'config/enterprise.example.yaml').read_text(encoding='utf-8'))
        overlay.write_text(yaml.safe_dump(cfg), encoding='utf-8')
        loaded = load_workbench(self.config_path, agent_overlay=overlay)
        self.assertEqual(loaded['settings'].data['enterprise']['sources'][0]['id'], 'equipment_events')
        source = cfg['enterprise']['sources'][0]
        source.update(dialect='sqlite', schema='', sqlite_file=str(self.chat_path))
        overlay.write_text(yaml.safe_dump(cfg), encoding='utf-8')
        with self.assertRaisesRegex(WorkbenchError, 'must differ from chat DB'):
            load_workbench(self.config_path, agent_overlay=overlay)

    def test_unconfigured_enterprise_does_not_create_connector(self):
        with patch.object(workbench_module, 'EnterpriseTools') as connector, \
                patch.object(workbench_module, 'run_agent', return_value=self._agent_result()):
            result = self.app.analysis(self.room_id, {'content': 'Query system', 'sources': ['incident', 'enterprise'], 'context': self.context})
        connector.assert_not_called()
        self.assertIn('DB', result['analysis']['steps'][1]['detail'])

    def test_map_question_requests_related_search_without_claiming_cd_model(self):
        self.app.settings.data['image_tools']['overlay']['enabled'] = True
        def fake_run(settings, question, **kwargs):
            self.assertIn('search_related_incidents', kwargs['requested_tools'])
            self.assertTrue(kwargs['related_search'])
            self.assertEqual(kwargs['context_data']['map_model_capabilities']['cd'], 'not_connected')
            self.assertFalse(settings.data['image_tools']['overlay']['enabled'])
            self.assertNotIn('compare_overlay_maps', kwargs['requested_tools'])
            return self._agent_result()
        with patch.object(workbench_module, 'run_agent', side_effect=fake_run):
            self.app.analysis(self.room_id, {'content': 'CD 이상 관련 사고와 Trend 비교',
                                           'sources': ['incident', 'related', 'maps'],
                                           'context': {**self.context, 'map_view': {'kind': 'cd', 'overlay': 'raw'}}})

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
        self.assertNotIn("current answer", history_text)
        self.assertNotIn("other incident note", history_text)
        self.assertEqual(captured["context"]["selected_incident"], "SYN-2026-01")
        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            self.app.analysis(self.room_id, {"content": "continue with the previous answer"})
        self.assertTrue(any(row['role'] == 'assistant'
                            for row in captured['context']['previous_messages_unverified']))

    def test_checked_image_tools_remain_enabled_and_results_are_reported(self):
        self.app.settings = Settings(merge(self.app.settings.data, {
            "image_tools": {name: {"enabled": True, "endpoint": "http://localhost:9876",
                                   "served_model": "synthetic-baseline"} for name in ("sem", "overlay")},
        }), self.app.settings.source_files)
        captured = []

        def fake_run(settings, question, **kwargs):
            captured.append((settings, kwargs["context_data"]))
            return self._agent_result(events=[
                {"event": "tool_result", "source": "find_incidents"},
                {"event": "tool_result", "source": "compare_sem_images"},
                {"event": "tool_result", "source": "compare_overlay_maps"},
            ])

        context = {**self.context, "recipe": "SYN-RCP-B", "sem_wafers": self.context["wafers"],
                   "map_view": {"kind": "overlay", "overlay": "residual"},
                   "trend_selection": {"range_selected": False, "value_range": None, "regions": []}}
        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            result = self.app.analysis(self.room_id, {
                "content": "compare", "sources": ["incident", "sem", "maps"], "context": context,
            })
            self.app.analysis(self.room_id, {
                "content": "database only", "sources": ["incident"], "context": context,
            })
        settings, payload = captured[0]
        self.assertTrue(all(row["enabled"] for row in settings.data["image_tools"].values()))
        self.assertEqual(payload["unavailable_sources"], [])
        self.assertEqual(payload["ui_context_unverified"], context)
        self.assertTrue(all(row["status"] == "completed" for row in result["analysis"]["steps"]))
        self.assertFalse(any(row["enabled"] for row in captured[1][0].data["image_tools"].values()))

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
