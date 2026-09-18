import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from app.workbench import WorkbenchError, create_server, load_workbench


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.config = cls.root / "workbench.yaml"
        cls.chat = cls.root / "chat.sqlite"
        cls.config.write_text(
            "config_version: 1\n"
            "demo:\n  base_config: " + str(ROOT / "config/config.yaml").replace("\\", "/") + "\n"
            "  overlay: " + str(ROOT / "config/demo.yaml").replace("\\", "/") + "\n"
            "chat:\n  sqlite_file: " + str(cls.chat).replace("\\", "/") + "\n  history_limit: 40\n"
            "cutoff: 2026-03-31\nstatic_root: " + str(cls.root / "static").replace("\\", "/") + "\n",
            encoding="utf-8",
        )
        (cls.root / "static").mkdir()
        (cls.root / "static/index.html").write_text("<main>workbench</main>", encoding="utf-8")
        cls.server = create_server(cls.config, 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def request(self, method, path, body=None, host=None, origin=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if origin is not None: headers["Origin"] = origin
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw))
        else: raw = None
        conn.request(method, path, raw, headers)
        response = conn.getresponse()
        value = response.read()
        conn.close()
        return response.status, json.loads(value) if response.getheader("Content-Type", "").startswith("application/json") else value

    def test_bootstrap_workspace_and_scope(self):
        status, body = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue(body["synthetic"])
        self.assertFalse(body["llm_connected"])
        self.assertEqual(body["mode"], "demo")
        self.assertIn("incident_number", body["incidents"][0])
        self.assertEqual(body["rooms"][0]["title"], "외곽 패턴 원인 분석")
        self.assertEqual(body["rooms"][0]["incident_number"], "SYN-2026-01")
        status, seeded = self.request("GET", f"/api/rooms/{body['rooms'][0]['id']}")
        self.assertEqual(status, 200)
        self.assertIn("회의 원문", seeded["messages"][1]["content"])
        self.assertEqual(seeded["messages"][1]["attachments"][0]["kind"], "data")
        self.assertTrue(all(item["kind"] == "inform" for item in seeded["messages"][1]["attachments"][1:]))
        status, workspace = self.request("GET", "/api/workspace?incident=SYN-2026-01")
        self.assertEqual(status, 200)
        self.assertEqual(workspace["incident"]["incident_number"], "SYN-2026-01")
        self.assertEqual(len(workspace["lots"]), 3)
        self.assertTrue(workspace["meetings"])
        self.assertTrue(all(item["status"] == "approved" for item in workspace["meetings"]))
        self.assertTrue(all(item["meeting_date"] <= "2026-03-31" for item in workspace["meetings"]))

    def test_room_persistence_rename_delete_and_targeted_message(self):
        status, room = self.request("POST", "/api/rooms", {"title": "검증 방", "incident_number": "SYN-2026-03"})
        self.assertEqual(status, 200)
        room_id = room["id"]
        status, sent = self.request("POST", f"/api/rooms/{room_id}/messages", {
            "content": "Lot과 회의 근거를 보여줘",
            "attachments": [
                {"kind": "data", "label": "client ref", "id": "client-1", "incident_number": "SYN-2026-01"},
                {"kind": "data", "label": "current ref", "id": "client-2"},
            ],
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(sent["messages"]), 2)
        self.assertIn("합성 DB 조회 결과", sent["messages"][1]["content"])
        self.assertIn("Lot", sent["messages"][1]["content"])
        self.assertEqual(sent["messages"][1]["attachments"][0]["kind"], "data")
        self.assertEqual(sent["messages"][0]["attachments"][0]["incident_number"], "SYN-2026-01")
        self.assertEqual(sent["messages"][0]["attachments"][1]["incident_number"], "SYN-2026-03")
        self.assertTrue(all(item["incident_number"] == "SYN-2026-03" for item in sent["messages"][1]["attachments"]))
        self.assertTrue(all(item["kind"] == "inform" for item in sent["messages"][1]["attachments"][1:]))
        self.assertTrue(all(item["id"].startswith("syn-chunk-") for item in sent["messages"][1]["attachments"][1:]))
        status, unknown = self.request("POST", f"/api/rooms/{room_id}/messages", {"content": "오늘 날씨를 알려줘"})
        self.assertEqual(status, 200)
        self.assertIn("LLM이 연결되지 않은", unknown["messages"][1]["content"])
        self.assertNotIn("합성 DB 조회 결과", unknown["messages"][1]["content"])
        status, production = self.request("POST", f"/api/rooms/{room_id}/messages", {"content": "production system 기록을 보여줘"})
        self.assertEqual(status, 200)
        self.assertIn("연결되지 않은", production["messages"][1]["content"])
        self.assertIn("회사 생산계 기록", production["messages"][1]["content"])
        self.assertEqual(production["messages"][1]["attachments"], [])
        status, sem = self.request("POST", f"/api/rooms/{room_id}/messages", {"content": "SEM image overlay map을 보여줘"})
        self.assertEqual(status, 200)
        self.assertIn("SEM/image/overlay map", sem["messages"][1]["content"])
        self.assertIn("실제 이미지·map 값", sem["messages"][1]["content"])
        self.assertEqual(sem["messages"][1]["attachments"], [])
        status, renamed = self.request("PATCH", f"/api/rooms/{room_id}", {"title": "이름 변경"})
        self.assertEqual(status, 200)
        self.assertEqual(renamed["title"], "이름 변경")
        status, loaded = self.request("GET", f"/api/rooms/{room_id}")
        self.assertEqual(status, 200)
        self.assertEqual(len(loaded["messages"]), 8)
        self.assertEqual(loaded["messages"][0]["attachments"][0]["incident_number"], "SYN-2026-01")
        status, switched = self.request("PATCH", f"/api/rooms/{room_id}", {"incident_number": "SYN-2026-06"})
        self.assertEqual(status, 200)
        self.assertEqual(switched["incident_number"], "SYN-2026-06")
        self.assertEqual(self.request("PATCH", f"/api/rooms/{room_id}", {"incident_number": None})[0], 404)
        status, retained = self.request("GET", f"/api/rooms/{room_id}")
        self.assertEqual(status, 200)
        self.assertEqual(retained["incident_number"], "SYN-2026-06")
        self.assertEqual(retained["messages"][0]["attachments"][0]["incident_number"], "SYN-2026-01")
        status, deleted = self.request("DELETE", f"/api/rooms/{room_id}")
        self.assertEqual(status, 200)
        self.assertEqual(deleted, {"ok": True})
        self.assertEqual(self.request("GET", f"/api/rooms/{room_id}")[0], 404)

    def test_room_cursor_pagination_is_latest_bounded_and_room_scoped(self):
        status, room = self.request("POST", "/api/rooms", {"title": "페이지 방"})
        self.assertEqual(status, 200)
        self.assertIsNotNone(room["incident_number"])
        room_id = room["id"]
        for index in range(25):
            status, _ = self.request("POST", f"/api/rooms/{room_id}/messages", {"content": f"오늘 날씨 {index}"})
            self.assertEqual(status, 200)
        status, latest = self.request("GET", f"/api/rooms/{room_id}")
        self.assertEqual(status, 200)
        self.assertEqual(len(latest["messages"]), 40)
        self.assertTrue(latest["has_more"])
        self.assertEqual(latest["oldest_id"], latest["messages"][0]["id"])
        self.assertIsNotNone(latest["updated_at"])
        status, older = self.request("GET", f"/api/rooms/{room_id}?before={latest['oldest_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(len(older["messages"]), 10)
        self.assertFalse(older["has_more"])
        self.assertEqual(older["messages"][-1]["created_at"] < latest["messages"][0]["created_at"], True)
        status, other = self.request("POST", "/api/rooms", {"title": "다른 방", "incident_number": "SYN-2026-02"})
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", f"/api/rooms/{other['id']}?before={latest['oldest_id']}")[0], 400)

    def test_explicit_invalid_incident_does_not_reuse_room_data(self):
        status, room = self.request("POST", "/api/rooms", {"incident_number": "SYN-2026-01"})
        self.assertEqual(status, 200)
        status, sent = self.request("POST", f"/api/rooms/{room['id']}/messages", {"content": "SYN-2026-99의 원인을 알려줘"})
        self.assertEqual(status, 200)
        self.assertIn("재사용하지 않았습니다", sent["messages"][1]["content"])
        self.assertEqual(sent["room"]["incident_number"], "SYN-2026-01")
        self.assertEqual(sent["messages"][1]["attachments"], [])

    def test_invalid_attachment_incident_is_rejected_without_room_mutation(self):
        status, room = self.request("POST", "/api/rooms", {"incident_number": "SYN-2026-01"})
        self.assertEqual(status, 200)
        status, response = self.request("POST", f"/api/rooms/{room['id']}/messages", {
            "content": "회의 근거를 보여줘",
            "attachments": [{"kind": "data", "label": "bad", "id": "x", "incident_number": "SYN-2026-99"}],
        })
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "invalid attachment incident_number")
        status, loaded = self.request("GET", f"/api/rooms/{room['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(loaded["incident_number"], "SYN-2026-01")
        self.assertEqual(loaded["messages"], [])

    def test_equal_timestamps_preserve_insert_order_across_pages(self):
        app = self.server.app
        room = app.create_room("same-time test", "SYN-2026-01")
        with app.lock, app._db() as db:
            for index in range(42):
                db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (
                    f"equal-{41-index:03d}", room["id"],
                    "user" if index % 2 == 0 else "assistant", str(index),
                    "2026-09-18T00:00:00+00:00", "[]",
                ))
        latest = app.room(room["id"])
        self.assertEqual([m["content"] for m in latest["messages"]], [str(i) for i in range(2, 42)])
        self.assertTrue(latest["has_more"])
        earlier = app.room(room["id"], before=latest["oldest_id"])
        self.assertEqual([m["content"] for m in earlier["messages"]], ["0", "1"])
        self.assertFalse(earlier["has_more"])
        app.delete_room(room["id"])

    def test_safe_origin_and_static_path(self):
        self.assertEqual(self.request("GET", "/api/bootstrap", origin="http://evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/bootstrap", host="evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/../config/config.yaml")[0], 400)
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"workbench", body)

    def test_partial_demo_outputs_and_onprem_are_rejected(self):
        partial_root = self.root / "partial-data"
        partial_root.mkdir()
        (partial_root / "quality_demo.sqlite").write_bytes(b"fixture")
        overlay = self.root / "demo.yaml"
        overlay.write_text("environment: demo\npaths:\n  data_root: " + str(partial_root).replace("\\", "/") + "\n", encoding="utf-8")
        partial_config = self.root / "partial-workbench.yaml"
        partial_config.write_text(
            "config_version: 1\ndemo:\n  base_config: " + str(ROOT / "config/config.yaml").replace("\\", "/") + "\n"
            "  overlay: " + str(overlay).replace("\\", "/") + "\nchat:\n  sqlite_file: " + str(self.root / "partial-chat.sqlite").replace("\\", "/") + "\n  history_limit: 40\n"
            "cutoff: 2026-03-31\nstatic_root: " + str(self.root / "static").replace("\\", "/") + "\n", encoding="utf-8")
        with self.assertRaises(WorkbenchError):
            load_workbench(partial_config)

        onprem_overlay = self.root / "onprem-demo.yaml"
        onprem_overlay.write_text("environment: onprem\n", encoding="utf-8")
        onprem_config = self.root / "onprem-workbench.yaml"
        onprem_config.write_text(partial_config.read_text(encoding="utf-8").replace(str(overlay).replace("\\", "/"), str(onprem_overlay).replace("\\", "/")), encoding="utf-8")
        with self.assertRaises(WorkbenchError):
            load_workbench(onprem_config)

    def test_chat_db_cannot_be_business_output_or_static_content(self):
        settings = load_workbench(self.config)["settings"].data
        business_db = Path(settings["database"]["sqlite_file"])
        conflict = self.root / "conflict-workbench.yaml"
        conflict.write_text(self.config.read_text(encoding="utf-8").replace(str(self.chat).replace("\\", "/"), str(business_db).replace("\\", "/")), encoding="utf-8")
        with self.assertRaises(WorkbenchError):
            load_workbench(conflict)
        static_chat = self.root / "static" / "chat.sqlite"
        static_conflict = self.root / "static-chat-workbench.yaml"
        static_conflict.write_text(self.config.read_text(encoding="utf-8").replace(str(self.chat).replace("\\", "/"), str(static_chat).replace("\\", "/")), encoding="utf-8")
        with self.assertRaises(WorkbenchError):
            load_workbench(static_conflict)


if __name__ == "__main__":
    unittest.main()
