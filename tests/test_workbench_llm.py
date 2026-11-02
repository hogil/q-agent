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
from app.conversation_memory import pack_turns


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
        self.config = config
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
            "final_scope": {"incident_lookup_status": "OK",
                            "confirmed": {"incident_ids": ["SYN-2026-01"]}},
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
        self.assertNotIn("plan_synthetic_action_evidence", captured["kwargs"]["requested_tools"])

    def test_llm_bridge_passes_only_explicit_synthetic_action_callbacks(self):
        planner = lambda scoped: scoped
        lease_provider = lambda conn: {"revision": "synthetic-test", "as_of": "2026-03-31T00:00:00Z"}
        config = dict(self.config)
        enabled_data = merge(self.config["settings"].data, {
            "synthetic_action_planner": {"enabled": True},
        })
        config["settings"] = Settings(enabled_data, self.config["settings"].source_files)
        app = Workbench(config, synthetic_action_planner=planner,
                        snapshot_lease_provider=lease_provider)
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured["settings"] = settings
            captured.update(kwargs)
            return self._agent_result(events=[
                {"event": "tool_result", "source": "plan_synthetic_action_evidence",
                 "id": "evidence-1", "result": {"status": "OK", "execution_granted": False}},
                {"event": "llm_output", "role": "answer", "model": "mock-model", "step": 3},
            ])

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            result = app.analysis(self.room_id, {
                "content": "선택 사고 확인", "sources": ["incident", "action_evidence"], "context": self.context,
            })

        self.assertIs(captured["synthetic_action_planner"], planner)
        self.assertIs(captured["snapshot_lease_provider"], lease_provider)
        self.assertTrue(captured["settings"].data["synthetic_action_planner"]["enabled"])
        self.assertIn("plan_synthetic_action_evidence", captured["requested_tools"])
        action_step = next(step for step in result["analysis"]["steps"] if step["source"] == "action_evidence")
        self.assertEqual(action_step["status"], "completed")
        self.assertIn("proposal-only", action_step["detail"])
        self.assertIn("no action was executed", action_step["detail"])
        self.assertEqual(result["analysis"]["report"]["synthetic_action_evidence"], [
            {"evidence_id": "evidence-1", "result": {"status": "OK", "execution_granted": False}},
        ])
        self.assertIn("실제 조치나 HOLD/RELEASE는 실행되지 않았습니다.", result["messages"][-1]["content"])

    def test_action_evidence_is_unavailable_without_enabled_planner_and_callbacks(self):
        with patch.object(workbench_module, "run_agent") as run:
            with self.assertRaisesRegex(WorkbenchError, "action_evidence is unavailable"):
                self.app.analysis(self.room_id, {
                    "content": "합성 조치 evidence 확인",
                    "sources": ["incident", "action_evidence"], "context": self.context,
                })
        run.assert_not_called()
        progress = self.app.analysis_progress(self.room_id)["run"]
        self.assertEqual(progress["status"], "failed")
        self.assertIn("action_evidence is unavailable", progress["error"])

    def test_action_evidence_requires_enabled_setting_and_both_callbacks(self):
        planner = lambda scoped: scoped
        lease_provider = lambda conn: {"revision": "synthetic-test", "as_of": "2026-03-31T00:00:00Z"}
        enabled_config = dict(self.config)
        enabled_data = merge(self.config["settings"].data, {"synthetic_action_planner": {"enabled": True}})
        enabled_config["settings"] = Settings(enabled_data, self.config["settings"].source_files)
        invalid_apps = [
            Workbench(self.config, synthetic_action_planner=planner,
                      snapshot_lease_provider=lease_provider),
            Workbench(enabled_config, synthetic_action_planner=planner),
            Workbench(enabled_config, snapshot_lease_provider=lease_provider),
        ]
        for app in invalid_apps:
            with self.subTest(planner=callable(app.synthetic_action_planner),
                              lease=callable(app.snapshot_lease_provider),
                              enabled=app.settings.data.get("synthetic_action_planner", {}).get("enabled")):
                with patch.object(workbench_module, "run_agent") as run:
                    with self.assertRaisesRegex(WorkbenchError, "action_evidence is unavailable"):
                        app.analysis(self.room_id, {
                            "content": "합성 조치 evidence 확인",
                            "sources": ["incident", "action_evidence"], "context": self.context,
                        })
                run.assert_not_called()

    def test_workbench_callback_injection_defaults_to_none(self):
        self.assertIsNone(self.app.synthetic_action_planner)
        self.assertIsNone(self.app.snapshot_lease_provider)

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

    def test_complete_item_room_precedes_recent_partial_room(self):
        for item in ("A", "B"):
            with patch.object(workbench_module, "run_agent", return_value=self._agent_result(item)):
                self.app.analysis(self.room_id, {"content": "analyze", "sources": ["incident"],
                    "context": {**self.context, "item": item}})
        newer = self.app.create_room("incomplete", "SYN-2026-01")["id"]
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result("A")):
            self.app.analysis(newer, {"content": "analyze", "sources": ["incident"],
                "context": {**self.context, "item": "A"}})
        self.app.raw_data = {"SYN-2026-01": {"engineering": {"signals": [{"item": item} for item in ("A", "B")]}}}
        self.assertEqual(self.app._default_room_id(), self.room_id)

    def test_report_retains_tool_map_arrays_without_regenerating(self):
        maps = [{"id": "map-1", "cd": [{"x": 1, "y": 2, "value": 99}], "sha256": "source-hash"}]
        result = self._agent_result(events=[{"event": "tool_result", "source": "get_engineering_snapshot",
            "result": {"sections": {"maps": {"assets": maps}}}}])
        report = self.app._analysis_report(result, self.context)
        self.assertEqual(report["map_assets"], maps)
        report["map_assets"][0]["cd"][0]["value"] = 0
        self.assertEqual(maps[0]["cd"][0]["value"], 99)

    def test_item_results_survive_switch_restart_and_failure(self):
        contexts = [self.context, {**self.context, "item": "SYN-QUEUE"}]
        for context in contexts:
            with patch.object(workbench_module, "run_agent", return_value=self._agent_result(context["item"])):
                self.app.analysis(self.room_id, {"content": "analyze", "sources": ["incident"], "context": context})
        restarted = Workbench({"settings": self.app.settings, "cutoff": self.app.cutoff,
            "static_root": self.app.static_root, "chat_db": self.app.chat_db,
            "history_limit": 1, "release": self.app.release})
        with patch.object(workbench_module, "run_agent", side_effect=AssertionError("GET must not run LLM")):
            for context in contexts:
                saved = restarted.analysis_metadata(self.room_id, context["item"])
                self.assertEqual(saved["analysis"]["report"]["summary"], context["item"])
                self.assertIn(context["item"], saved["messages"][-1]["content"])
                self.assertEqual(saved["run"]["status"], "completed")
                self.assertTrue(saved["analysis"]["saved_at"])
            self.assertIsNone(restarted.analysis_metadata(self.room_id, "MISSING")["analysis"])
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result(status="unavailable")):
            with self.assertRaises(WorkbenchError):
                restarted.analysis(self.room_id, {"content": "retry", "sources": ["incident"], "context": self.context})
        self.assertEqual(restarted.analysis_metadata(self.room_id, "SYN-TEMP")["analysis"]["report"]["summary"], "SYN-TEMP")
        restarted.update_room(self.room_id, {"incident_number": "SYN-2026-02"})
        self.assertIsNone(restarted.analysis_metadata(self.room_id, "SYN-TEMP")["analysis"])

    def test_item_followup_uses_selected_saved_scope_not_last_item(self):
        for item in ("SYN-TEMP", "SYN-QUEUE"):
            with patch.object(workbench_module, "run_agent", return_value=self._agent_result(item)):
                self.app.analysis(self.room_id, {"content": "analyze", "sources": ["incident"],
                    "context": {**self.context, "item": item}})
        with patch.object(workbench_module, "run_agent", return_value=self._agent_result("follow-up")) as run:
            result = self.app.analysis(self.room_id, {"content": "check again", "item": "SYN-TEMP"})
        self.assertEqual(result["analysis"]["context"]["item"], "SYN-TEMP")
        self.assertEqual(run.call_args.kwargs["context_data"]["ui_context_unverified"]["item"], "SYN-TEMP")
        self.assertEqual(self.app.analysis_metadata(self.room_id, "SYN-QUEUE")["analysis"]["report"]["summary"], "SYN-QUEUE")
        with self.assertRaises(WorkbenchError):
            self.app.analysis(self.room_id, {"content": "check", "item": "MISSING"})

    def test_explicit_preparation_binds_equipment_and_continues_after_failure(self):
        self.app.raw_data = {"SYN-2026-01": {"engineering": {
            "signals": [{"item": item, "title": item, "step": "ETCH", "equipment": "EQP-1"}
                        for item in ("A", "B")],
            "trend": [{"timestamp": self.context["from"]}, {"timestamp": self.context["to"]}],
            "fab": [{"lotId": "LOT-1", "waferId": "W01", "step": "ETCH"}],
        }}}
        with patch.object(self.app, "analysis", side_effect=[WorkbenchError("failed"),
                {"analysis": {"status": "answered"}}]) as analyze, patch("builtins.print"):
            results = self.app.prepare_analyses(self.room_id)
        self.assertEqual([row["status"] for row in results], ["failed", "answered"])
        self.assertEqual(analyze.call_count, 2)
        for call in analyze.call_args_list:
            self.assertEqual(call.args[1]["context"]["equipment"], "EQP-1")
            self.assertIn("enterprise", call.args[1]["sources"])
            self.assertFalse(call.kwargs["use_history"])
        with self.assertRaises(WorkbenchError):
            self.app.prepare_analyses(self.room_id, ["UNKNOWN"])

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

    def test_explicit_retrieval_sources_inject_trusted_callbacks_and_return_evidence(self):
        self.app.settings.data['retrieval']['engineer_notes']['enabled'] = True
        self.app.settings.data['retrieval']['internal_documents']['enabled'] = True
        self.app.settings.data['mes_reference']['enabled'] = True
        self.app.settings.data['mes_reference']['allowed_kinds'] = ['recipe']
        document_query = lambda **kwargs: None
        mes_query = lambda **kwargs: None
        statuses = {'engineer_notes': ['released'], 'internal_documents': ['released']}
        app = Workbench(self.config, document_query=document_query,
                        document_allowed_statuses=statuses, mes_reference_query=mes_query)
        room_id = app.create_room('retrieval', 'SYN-2026-01')['id']
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured.update(kwargs)
            results = [
                {'event': 'tool_result', 'source': 'search_engineer_notes',
                 'result': {'status': 'OK', 'items': [{'title': 'note'}]}},
                {'event': 'tool_result', 'source': 'search_internal_documents',
                 'result': {'status': 'NO_MATCH', 'items': []}},
                {'event': 'tool_result', 'source': 'search_mes_reference',
                 'result': {'status': 'OK', 'items': [{'id': 'ref'}]}},
            ]
            return self._agent_result(events=self._agent_result()['events'] + results)

        with patch.object(workbench_module, 'run_agent', side_effect=fake_run):
            response = app.analysis(room_id, {
                'content': '문서와 MES 기준 확인',
                'sources': ['incident', 'engineer_note_search', 'internal_document_search', 'mes_reference_search'],
                'context': self.context})
        self.assertEqual(captured['requested_tools'], [
            'find_incidents', 'search_engineer_notes', 'search_internal_documents', 'search_mes_reference'])
        self.assertIs(captured['document_query'], document_query)
        self.assertIs(captured['mes_reference_query'], mes_query)
        self.assertEqual(captured['document_allowed_statuses'], statuses)
        steps = {step['source']: step for step in response['analysis']['steps']}
        self.assertEqual([steps[source]['status'] for source in (
            'engineer_note_search', 'internal_document_search', 'mes_reference_search')],
            ['completed', 'completed', 'completed'])
        evidence = response['analysis']['report']['retrieval_evidence']
        self.assertEqual([item['source'] for item in evidence], [
            'search_engineer_notes', 'search_internal_documents', 'search_mes_reference'])

    def test_retrieval_sources_are_not_requested_without_explicit_selection_or_configuration(self):
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured.update(kwargs)
            return self._agent_result()

        with patch.object(workbench_module, 'run_agent', side_effect=fake_run):
            self.app.analysis(self.room_id, {'content': '사고만 확인', 'sources': ['incident'],
                                             'context': self.context})
            self.assertNotIn('search_engineer_notes', captured['requested_tools'])
            self.assertNotIn('search_internal_documents', captured['requested_tools'])
            self.assertNotIn('search_mes_reference', captured['requested_tools'])
            self.assertIsNone(captured['document_query'])
            self.assertIsNone(captured['mes_reference_query'])

            response = self.app.analysis(self.room_id, {
                'content': '문서 검색', 'sources': ['incident', 'engineer_note_search'],
                'context': self.context})
        self.assertNotIn('search_engineer_notes', captured['requested_tools'])
        self.assertEqual(response['analysis']['steps'][1]['status'], 'unavailable')
        self.assertIn('trusted callback', response['analysis']['steps'][1]['detail'])

    def test_create_server_forwards_retrieval_callbacks_as_trusted_runtime_dependencies(self):
        document_query = lambda **kwargs: None
        mes_query = lambda **kwargs: None
        statuses = {'engineer_notes': ['released']}
        server = workbench_module.create_server(
            self.config_path, port=0, document_query=document_query,
            document_allowed_statuses=statuses, mes_reference_query=mes_query)
        try:
            self.assertIs(server.app.document_query, document_query)
            self.assertIs(server.app.mes_reference_query, mes_query)
            self.assertEqual(server.app.document_allowed_statuses, statuses)
        finally:
            server.server_close()

    def test_retrieval_sources_without_llm_are_explicitly_unavailable(self):
        self.app.settings.data['models']['text']['enabled'] = False
        self.app.settings.data['retrieval']['engineer_notes']['enabled'] = True
        self.app.settings.data['retrieval']['internal_documents']['enabled'] = True
        self.app.settings.data['mes_reference']['enabled'] = True
        self.app.settings.data['mes_reference']['allowed_kinds'] = ['recipe']
        self.app.document_query = lambda **kwargs: self.fail('document callback must not run without LLM')
        self.app.document_allowed_statuses = {
            'engineer_notes': ['released'], 'internal_documents': ['released']}
        self.app.mes_reference_query = lambda **kwargs: self.fail('MES callback must not run without LLM')
        response = self.app.analysis(self.room_id, {
            'content': '문서와 MES 기준 확인',
            'sources': ['incident', 'engineer_note_search', 'internal_document_search', 'mes_reference_search'],
            'context': self.context})
        self.assertEqual(response['analysis']['mode'], 'demo')
        steps = {step['source']: step for step in response['analysis']['steps']}
        for source in ('engineer_note_search', 'internal_document_search', 'mes_reference_search'):
            self.assertEqual(steps[source]['status'], 'unavailable')
            self.assertIn('LLM is not configured; retrieval Tool was not called', steps[source]['detail'])

    def test_invalid_retrieval_allowlists_are_not_silently_passed_as_valid(self):
        self.app.settings.data['retrieval']['engineer_notes']['enabled'] = True
        self.app.settings.data['mes_reference']['enabled'] = True
        self.app.settings.data['mes_reference']['allowed_kinds'] = ['recipe', 'recipe']
        document_query = lambda **kwargs: None
        mes_query = lambda **kwargs: None
        app = Workbench(self.config, document_query=document_query,
                        document_allowed_statuses={'engineer_notes': ['released', 'released']},
                        mes_reference_query=mes_query)
        room_id = app.create_room('invalid retrieval config', 'SYN-2026-01')['id']
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured.update(kwargs)
            return self._agent_result()

        with patch.object(workbench_module, 'run_agent', side_effect=fake_run):
            response = app.analysis(room_id, {
                'content': '문서와 MES 기준 확인',
                'sources': ['incident', 'engineer_note_search', 'mes_reference_search'],
                'context': self.context})
        self.assertNotIn('search_engineer_notes', captured['requested_tools'])
        self.assertNotIn('search_mes_reference', captured['requested_tools'])
        self.assertIsNone(captured['document_query'])
        self.assertIsNone(captured['mes_reference_query'])
        steps = {step['source']: step for step in response['analysis']['steps']}
        self.assertIn('allowlist is invalid', steps['engineer_note_search']['detail'])
        self.assertIn('allowed kinds are invalid', steps['mes_reference_search']['detail'])

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
            captured["history"] = pack_turns(kwargs["conversation_turns"], question, 2400)
            return self._agent_result()

        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            self.app.analysis(self.room_id, {
                "content": "현재 사고를 이어서 분석해줘",
                "sources": ["incident"],
                "context": self.context,
            })

        history = captured["history"]
        history_text = " ".join(item["content"] for item in history)
        self.assertIn("current incident note", history_text)
        self.assertNotIn("current answer", history_text)
        self.assertNotIn("other incident note", history_text)
        self.assertEqual(captured["context"]["selected_incident"], "SYN-2026-01")
        with patch.object(workbench_module, "run_agent", side_effect=fake_run):
            self.app.analysis(self.room_id, {"content": "continue with the previous answer"})
        self.assertTrue(any(row['role'] == 'assistant'
                            for row in captured['history']))

    def test_memory_query_is_room_scoped_independent_of_display_page_and_excludes_generated_scope(self):
        self.app.history_limit = 2
        other_room = self.app.create_room('separate room', 'SYN-2026-01')['id']
        ref = self.app._ref('data', 'current', 'current', 'SYN-2026-01')
        self.app._append_messages(self.room_id, 'SEM point comparison\n분석 scope: DUPLICATE_SCOPE', [ref],
                                  'Compare registered points', [ref])
        self.app._append_messages(other_room, 'SEM PRIVATE_OTHER_ROOM', [ref], 'OTHER_ROOM_ANSWER', [ref])
        for index in range(8):
            self.app._append_messages(self.room_id, f'queue {index}', [ref], 'Production status', [ref])
        captured = {}

        def fake_run(settings, question, **kwargs):
            captured['turns'] = kwargs['conversation_turns']
            return self._agent_result()

        with patch.object(workbench_module, 'run_agent', side_effect=fake_run):
            self.app.analysis(self.room_id, {'content': 'SEM point comparison',
                                            'sources': ['incident'], 'context': self.context})
        text = json.dumps(captured['turns'])
        self.assertIn('SEM point comparison', text)
        self.assertNotIn('DUPLICATE_SCOPE', text)
        self.assertNotIn('PRIVATE_OTHER_ROOM', text)
        self.assertNotIn('OTHER_ROOM_ANSWER', text)

    def test_offline_analysis_does_not_reuse_other_item_questions(self):
        ref = self.app._ref('data', 'previous', 'previous', 'SYN-2026-01')
        self.app._append_messages(self.room_id, 'Analyze another Item', [ref], 'Old conclusion', [ref])
        with patch.object(workbench_module, 'run_agent', return_value=self._agent_result()) as run:
            self.app.analysis(self.room_id, {'content': 'Analyze this Item',
                                            'sources': ['incident'], 'context': self.context}, use_history=False)
        self.assertEqual(run.call_args.kwargs['conversation_turns'], [])

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
        self.assertEqual(runtime["final_scope"]["incident_lookup_status"], "OK")
        self.assertEqual(runtime["final_scope"]["confirmed"]["incident_ids"], ["SYN-2026-01"])
        saved = self.app.analysis_metadata(self.room_id)["analysis"]
        self.assertEqual(saved["mode"], "llm")
        self.assertTrue(saved["llm_connected"])
        self.assertEqual(saved["trace"], runtime["trace"])

    def test_system_limitations_are_persisted_and_displayed_once(self):
        caveat = "인용된 MES 결과에 사고 연관성이 확인되지 않은 기준정보 후보가 포함되어 있습니다."
        model_limitations = [f"model limitation {index}" for index in range(6)]
        result_data = self._agent_result()
        result_data["limitations"] = model_limitations
        result_data["system_limitations"] = [caveat]

        with patch.object(workbench_module, "run_agent", return_value=result_data):
            result = self.app.analysis(self.room_id, {
                "content": "시스템 한계 표시 확인",
                "sources": ["incident"],
                "context": self.context,
            })

        runtime = result["analysis"]
        body = result["messages"][-1]["content"]
        self.assertEqual(runtime["limitations"], model_limitations)
        self.assertEqual(runtime["system_limitations"], [caveat])
        self.assertEqual(body.count(caveat), 1)
        for limitation in model_limitations:
            self.assertIn(limitation, body)

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
