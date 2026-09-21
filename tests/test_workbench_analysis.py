import json
import sqlite3
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from app.workbench import create_server
from app.meeting_tools import MeetingTools


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchAnalysisHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.chat = cls.root / "chat.sqlite"
        config = cls.root / "workbench.yaml"
        config.write_text(
            "config_version: 1\n"
            "demo:\n  base_config: " + str(ROOT / "config/config.yaml").replace("\\", "/") + "\n"
            "  overlay: " + str(ROOT / "config/demo.yaml").replace("\\", "/") + "\n"
            "chat:\n  sqlite_file: " + str(cls.chat).replace("\\", "/") + "\n  history_limit: 40\n"
            "cutoff: 2026-03-31\nstatic_root: " + str(cls.root / "static").replace("\\", "/") + "\n",
            encoding="utf-8",
        )
        (cls.root / "static").mkdir()
        (cls.root / "static/index.html").write_text("<main>workbench</main>", encoding="utf-8")
        cls.server = create_server(config, 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def request(self, method, path, body=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        raw = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw))
        connection.request(method, path, raw, headers)
        response = connection.getresponse()
        value = response.read()
        connection.close()
        return response.status, json.loads(value)

    def room(self):
        status, room = self.request("POST", "/api/rooms", {"incident_number": "SYN-2026-01"})
        self.assertEqual(status, 200)
        return room["id"]

    def db_count(self, query, params):
        connection = sqlite3.connect(self.chat)
        try:
            return connection.execute(query, params).fetchone()[0]
        finally:
            connection.close()

    def context(self, wafers=None, **values):
        return {
            "incident_number": "SYN-2026-01",
            "item": values.get("item", "item-a"),
            "step": values.get("step", "step-b"),
            "equipment": values.get("equipment", "EQ-01"),
            "from": values.get("from", "2026-01-07T18:00:00.000Z"),
            "to": values.get("to", "2026-03-31T09:00:00.000+09:00"),
            "wafers": wafers or [],
        }

    def test_analysis_contract_selected_sources_and_no_real_llm(self):
        room_id = self.room()
        workspace = self.request("GET", "/api/workspace?incident=SYN-2026-01")[1]
        wafer = workspace["wafers"][0]
        status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "선택된 사고와 회의 근거를 분석해줘",
            "sources": ["meetings", "trend"],
            "context": self.context(wafers=[{"lot_id": wafer["lot_id"], "wafer_id": wafer["wafer_id"]}]),
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["mode"], "demo")
        self.assertFalse(result["analysis"]["llm_connected"])
        self.assertEqual(result["analysis"]["sources"], ["incident", "meetings", "trend"])
        self.assertIn("등록 Lot", result["messages"][1]["content"])
        self.assertIn("등록 Wafer", result["messages"][1]["content"])
        self.assertIn("회의", result["messages"][1]["content"])
        self.assertIn("실제 LLM에 연결되지 않았습니다", result["messages"][1]["content"])
        self.assertEqual(result["messages"][1]["content"].count("scope:"), 1)
        steps = {step["source"]: step for step in result["analysis"]["steps"]}
        self.assertEqual(steps["incident"]["status"], "completed")
        self.assertEqual(steps["meetings"]["status"], "completed")
        self.assertEqual(steps["trend"]["status"], "unavailable")
        self.assertEqual(result["messages"][0]["attachments"][0]["kind"], "data")
        self.assertEqual(set(result["messages"][0]["attachments"][0]), {"kind", "label", "id", "incident_number"})
        status, saved = self.request("GET", f"/api/rooms/{room_id}/analysis")
        self.assertEqual(status, 200)
        self.assertEqual(saved["analysis"]["sources"], result["analysis"]["sources"])
        self.assertEqual(saved["analysis"]["context"], result["analysis"]["context"])
        self.assertEqual(saved["analysis"]["steps"], result["analysis"]["steps"])

    def test_unselected_meetings_are_not_retrieved_and_incident_is_forced(self):
        room_id = self.room()
        with patch.object(MeetingTools, "search", side_effect=AssertionError("unexpected meeting query")):
            status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {
                "content": "trend만 확인",
                "sources": ["trend"],
                "context": self.context(),
            })
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["sources"], ["incident", "trend"])
        self.assertNotIn("meetings", {step["source"] for step in result["analysis"]["steps"]})
        self.assertNotIn("회의 excerpts", result["messages"][1]["content"])

    def test_analysis_input_validation(self):
        room_id = self.room()
        cases = [
            ({"content": "x", "sources": ["incident", "incident"], "context": self.context()}, "duplicate"),
            ({"content": "x", "sources": ["incident"], "context": self.context(**{"from": "2026-03-31", "to": "2026-01-01"})}, "on or before"),
            ({"content": "x", "sources": ["incident"], "context": {**self.context(), "incident_number": "SYN-2026-02"}}, "match"),
            ({"content": "x", "sources": ["incident"], "context": {**self.context(), "wafers": [{"lot_id": "missing", "wafer_id": "W1"}]}}, "outside"),
            ({"content": "x", "sources": ["incident"], "context": {**self.context(), "item": None}}, "item must be"),
        ]
        for body, marker in cases:
            with self.subTest(marker=marker):
                status, response = self.request("POST", f"/api/rooms/{room_id}/analysis", body)
                self.assertEqual(status, 400)
                self.assertIn(marker, response["error"])

    def test_exact_trend_scope_roundtrips_into_followup_and_progress(self):
        room_id = self.room()
        trend = {"range_selected": True, "value_range": [65, 69],
                 "regions": [[[1767830400000, 1767834000000], [65, 66]],
                             [[1767852000000, 1767855600000], [68, 69]]]}
        context = {**self.context(), "recipe": "SYN-RCP-B", "trend_selection": trend}
        status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "compare selected regions", "sources": ["trend"], "context": context,
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["context"], context)
        self.assertIn("recipe=SYN-RCP-B", result["messages"][0]["content"])
        self.assertIn("UI condition only", result["messages"][0]["content"])
        self.assertEqual(self.request("GET", f"/api/rooms/{room_id}/analysis/progress")[1]["run"]["context"], context)
        status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {"content": "continue"})
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["context"], context)
        self.assertEqual(result["analysis"]["steps"][1]["status"], "unavailable")

    def test_invalid_trend_scope_is_rejected_before_running(self):
        room_id = self.room()
        base = {"range_selected": True, "value_range": [1, 2], "regions": []}
        cases = [None, {**base, "extra": 1}, {**base, "range_selected": 1},
                 {**base, "value_range": [2, 1]}, {**base, "value_range": [True, 2]},
                 {**base, "value_range": [1, float("inf")]},
                 {**base, "regions": [[[1, 2], [1, 2]]] * 17},
                 {**base, "regions": [[[2, 1], [1, 2]]]},
                 {**base, "range_selected": False}, {**base, "regions": [[1, 2]]}]
        for trend in cases:
            with self.subTest(trend=trend):
                status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {
                    "content": "invalid", "sources": ["trend"],
                    "context": {**self.context(), "trend_selection": trend},
                })
                self.assertEqual(status, 400)
                self.assertIn("trend_selection", result["error"])
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM messages WHERE room_id=?", (room_id,)), 0)

    def test_comparison_scope_rejects_unregistered_pairs_and_unknown_views(self):
        room_id = self.room()
        for patch_values in (
            {"sem_wafers": [{"lot_id": "missing", "wafer_id": "W1"}]},
            {"sem_wafers": [{"lot_id": [], "wafer_id": "W1"}]},
            {"map_view": {"kind": "overlay", "overlay": "invented"}},
            {"map_comparison": {"a": [], "b": [{"lot_id": "missing", "wafer_id": "W1"}]}},
            {"map_comparison": {"a": [], "b": [{"lot_id": [], "wafer_id": "W1"}]}},
            {"map_comparison": {"a": []}},
            {"map_comparison": {"a": [], "b": [], "extra": []}},
            {"map_comparison": {"a": None, "b": []}},
            {"recipe": 123},
        ):
            with self.subTest(patch=patch_values):
                status, _ = self.request("POST", f"/api/rooms/{room_id}/analysis", {
                    "content": "invalid", "sources": ["sem"], "context": {**self.context(), **patch_values},
                })
                self.assertEqual(status, 400)

    def test_map_comparison_roundtrip_independent_groups_and_empty_selection(self):
        room_id = self.room()
        workspace = self.request("GET", "/api/workspace?incident=SYN-2026-01")[1]
        pair = {key: workspace["wafers"][0][key] for key in ("lot_id", "wafer_id")}
        groups = {"a": [pair], "b": []}
        status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "map groups", "sources": ["maps"],
            "context": {**self.context(), "map_comparison": groups},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["context"]["map_comparison"], groups)
        self.assertIn("map_comparison=", result["messages"][0]["content"])
        status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {"content": "continue"})
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["context"]["map_comparison"], groups)
        for groups in ({"a": [pair, pair], "b": []}, {"a": [], "b": [pair, pair]}):
            status, _ = self.request("POST", f"/api/rooms/{room_id}/analysis", {
                "content": "duplicate", "sources": ["maps"],
                "context": {**self.context(), "map_comparison": groups},
            })
            self.assertEqual(status, 400)

    def test_followup_reuses_scope_and_stale_scope_is_rejected(self):
        room_id = self.room()
        initial = {"content": "첫 분석", "sources": ["meetings", "maps"], "context": self.context()}
        status, first = self.request("POST", f"/api/rooms/{room_id}/analysis", initial)
        self.assertEqual(status, 200)
        status, followup = self.request("POST", f"/api/rooms/{room_id}/analysis", {"content": "같은 범위로 이어서"})
        self.assertEqual(status, 200)
        self.assertEqual(followup["analysis"]["sources"], first["analysis"]["sources"])
        self.assertEqual(followup["analysis"]["context"], first["analysis"]["context"])
        status, _ = self.request("PATCH", f"/api/rooms/{room_id}", {"incident_number": "SYN-2026-02"})
        self.assertEqual(status, 200)
        status, response = self.request("POST", f"/api/rooms/{room_id}/analysis", {"content": "stale followup"})
        self.assertEqual(status, 400)
        self.assertIn("stale", response["error"])
        status, saved = self.request("GET", f"/api/rooms/{room_id}/analysis")
        self.assertEqual(status, 200)
        self.assertIsNone(saved["analysis"])

    def test_followup_different_incident_is_rejected_without_answering_current_scope(self):
        room_id = self.room()
        status, _ = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "첫 분석", "sources": ["incident"], "context": self.context(),
        })
        self.assertEqual(status, 200)
        status, response = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "SYN-2026-02의 원인을 이어서 설명해줘",
        })
        self.assertEqual(status, 400)
        self.assertIn("match the room scope", response["error"])
        status, room = self.request("GET", f"/api/rooms/{room_id}")
        self.assertEqual(status, 200)
        self.assertEqual(len(room["messages"]), 2)

    def test_empty_equipment_means_all(self):
        room_id = self.room()
        status, saved = self.request("GET", f"/api/rooms/{room_id}/analysis")
        self.assertEqual(status, 200)
        self.assertIsNone(saved["analysis"])
        status, result = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "선택 자료 분석", "sources": ["incident"],
            "context": self.context(equipment=""),
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["analysis"]["context"]["equipment"], "")

    def test_offset_ordering_uses_instants_and_preserves_context_strings(self):
        room_id = self.room()
        context = self.context(
            **{"from": "2026-01-07T18:00:00.000+09:00", "to": "2026-01-07T10:00:00.000Z"}
        )
        status, first = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "선택 자료 분석", "sources": ["incident"], "context": context,
        })
        self.assertEqual(status, 200)
        self.assertEqual(first["analysis"]["context"]["from"], context["from"])
        self.assertEqual(first["analysis"]["context"]["to"], context["to"])
        status, followup = self.request("POST", f"/api/rooms/{room_id}/analysis", {"content": "같은 범위 후속"})
        self.assertEqual(status, 200)
        self.assertEqual(followup["analysis"]["context"], context)

    def test_reversed_offset_instants_are_rejected(self):
        room_id = self.room()
        context = self.context(
            **{"from": "2026-01-07T18:00:00.000Z", "to": "2026-01-07T18:00:00.000+09:00"}
        )
        status, response = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "선택 자료 분석", "sources": ["incident"], "context": context,
        })
        self.assertEqual(status, 400)
        self.assertIn("on or before", response["error"])

    def test_room_delete_cascades_analysis_scope(self):
        room_id = self.room()
        status, _ = self.request("POST", f"/api/rooms/{room_id}/analysis", {
            "content": "저장 확인", "sources": ["incident"], "context": self.context(),
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM analysis_scopes WHERE room_id=?", (room_id,)), 1)
        status, result = self.request("DELETE", f"/api/rooms/{room_id}")
        self.assertEqual(status, 200)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM analysis_scopes WHERE room_id=?", (room_id,)), 0)
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM messages WHERE room_id=?", (room_id,)), 0)


if __name__ == "__main__":
    unittest.main()
