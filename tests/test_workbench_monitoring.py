import json
import hashlib
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock

from app.workbench import WorkbenchError, create_server


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchMonitoringHTTPTests(unittest.TestCase):
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
        cls.server.app.monitor.stop()
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def setUp(self):
        monitor = self.server.app.monitor
        monitor.stop()
        while monitor.process_next():
            pass

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

    def db_count(self, query, params=()):
        with closing(sqlite3.connect(self.chat)) as db:
            return db.execute(query, params).fetchone()[0]

    def valid_body(self, item="monitor-item"):
        status, workspace = self.request("GET", "/api/workspace?incident=SYN-2026-01")
        self.assertEqual(status, 200)
        wafers = workspace["wafers"][:2]
        self.assertEqual(len(wafers), 2)
        context = {
            "incident_number": "SYN-2026-01", "item": item, "step": "step-b",
            "equipment": "EQ-01", "from": "2026-01-07T18:00:00.000Z",
            "to": "2026-03-31T09:00:00.000+09:00", "wafers": [],
        }
        pair = [{"lot_id": wafer["lot_id"], "wafer_id": wafer["wafer_id"]} for wafer in wafers]
        return {"context": context, "comparison": {
            "item": item, "a": pair[0], "b": pair[1],
        }}

    def replay(self, item="monitor-item"):
        body = self.valid_body(item)
        status, event = self.request("POST", "/api/monitoring/replay", body)
        self.assertEqual(status, 200)
        return body, event

    def process(self, event_id):
        self.assertTrue(self.server.app.monitor.process_next())
        status, snapshot = self.request("GET", "/api/monitoring")
        self.assertEqual(status, 200)
        event = next(item for item in snapshot["events"] if item["event_id"] == event_id)
        return event

    def test_00_monitoring_status_is_synthetic_and_unconnected(self):
        self.server.app.monitor.start()
        try:
            status, value = self.request("GET", "/api/monitoring")
            self.assertEqual(status, 200)
            self.assertEqual(value["source"], "synthetic_replay")
            self.assertTrue(value["worker_running"])
            self.assertFalse(value["model_connected"])
            self.assertFalse(value["llm_connected"])
            self.assertFalse(value["production_connected"])
            self.assertFalse(value["image_tools"]["sem"]["connection_verified"])
            self.assertFalse(value["image_tools"]["overlay"]["connection_verified"])
        finally:
            self.server.app.monitor.stop()

    def test_replay_transitions_to_review_and_persists_room(self):
        before = self.db_count("SELECT COUNT(*) FROM detection_events")
        body, submitted = self.replay("transition-item")
        self.assertEqual(submitted["state"], "queued")
        self.assertEqual(submitted["action_status"], "not_requested")
        event = self.process(submitted["event_id"])
        self.assertEqual(event["state"], "review_required")
        self.assertEqual(event["action_status"], "requested")
        self.assertEqual(event["result"]["analysis_mode"], "demo")
        self.assertFalse(event["result"]["production_executed"])
        self.assertEqual(event["comparison"], body["comparison"])
        status, room = self.request("GET", f"/api/rooms/{event['result']['room_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(room["id"], event["result"]["room_id"])
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM detection_events"), before + 1)

    def test_duplicate_replay_is_idempotent_without_second_analysis(self):
        before = self.db_count("SELECT COUNT(*) FROM detection_events")
        body, submitted = self.replay("duplicate-item")
        monitor = self.server.app.monitor
        original = monitor.analyze
        spy = Mock(side_effect=original)
        monitor.analyze = spy
        try:
            self.assertTrue(monitor.process_next())
            status, snapshot = self.request("GET", "/api/monitoring")
            self.assertEqual(status, 200)
            completed = next(item for item in snapshot["events"] if item["event_id"] == submitted["event_id"])
            room_id = completed["result"]["room_id"]
            status, duplicate = self.request("POST", "/api/monitoring/replay", body)
            self.assertEqual(status, 200)
            self.assertEqual(duplicate["event_id"], submitted["event_id"])
            self.assertEqual(duplicate["state"], "review_required")
            self.assertFalse(monitor.process_next())
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(self.db_count("SELECT COUNT(*) FROM messages WHERE room_id=?", (room_id,)), 2)
        finally:
            monitor.analyze = original
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM detection_events"), before + 1)

    def test_reversed_context_wafer_order_reuses_same_event(self):
        first_body = self.valid_body("ordered-item")
        first_body["context"]["wafers"] = [first_body["comparison"]["a"], first_body["comparison"]["b"]]
        second_body = json.loads(json.dumps(first_body))
        second_body["context"]["wafers"].reverse()
        status, first = self.request("POST", "/api/monitoring/replay", first_body)
        self.assertEqual(status, 200)
        status, second = self.request("POST", "/api/monitoring/replay", second_body)
        self.assertEqual(status, 200)
        self.assertEqual(second["event_id"], first["event_id"])
        self.assertEqual(self.db_count("SELECT COUNT(*) FROM detection_events WHERE event_id=?", (first["event_id"],)), 1)

    def test_malformed_item_and_outscope_pair_are_rejected(self):
        malformed = self.valid_body("valid-item")
        malformed["context"]["item"] = ""
        malformed["comparison"]["item"] = ""
        status, value = self.request("POST", "/api/monitoring/replay", malformed)
        self.assertEqual(status, 400)
        self.assertIn("context item", value["error"])

        outscope = self.valid_body("outscope-item")
        outscope["comparison"]["a"] = {"lot_id": "SYN-LOT-99-99", "wafer_id": "W99"}
        status, value = self.request("POST", "/api/monitoring/replay", outscope)
        self.assertEqual(status, 400)
        self.assertIn("outside", value["error"])

    def test_acknowledge_and_reject_never_execute_production_action(self):
        _, acknowledged = self.replay("ack-item")
        self.process(acknowledged["event_id"])
        status, result = self.request("POST", f"/api/monitoring/{acknowledged['event_id']}/decision",
                                      {"decision": "acknowledge"})
        self.assertEqual(status, 200)
        self.assertEqual(result["state"], "acknowledged")
        self.assertFalse(result["result"]["production_executed"])

        _, rejected = self.replay("reject-item")
        self.process(rejected["event_id"])
        status, result = self.request("POST", f"/api/monitoring/{rejected['event_id']}/decision",
                                      {"decision": "reject"})
        self.assertEqual(status, 200)
        self.assertEqual(result["state"], "rejected")
        self.assertFalse(result["result"]["production_executed"])

    def test_execute_action_is_rejected(self):
        _, submitted = self.replay("execute-item")
        self.process(submitted["event_id"])
        status, value = self.request("POST", f"/api/monitoring/{submitted['event_id']}/decision",
                                     {"decision": "execute"})
        self.assertEqual(status, 400)
        self.assertIn("acknowledge or reject", value["error"])

        status, value = self.request("POST", f"/api/monitoring/{submitted['event_id']}/decision", [])
        self.assertEqual(status, 400)
        self.assertIn("invalid monitoring action", value["error"])

    def test_analyze_detection_rejects_stale_room_scope(self):
        _, submitted = self.replay("stale-scope-item")
        room_id = "detection-" + hashlib.sha256(submitted["event_id"].encode()).hexdigest()[:32]
        timestamp = "2026-01-01T00:00:00+00:00"
        with closing(sqlite3.connect(self.chat)) as db:
            db.execute("INSERT INTO rooms VALUES (?,?,?,?)",
                       (room_id, "stale", "SYN-2026-01", timestamp))
            db.execute("INSERT INTO analysis_scopes (room_id,incident_number,sources,context,steps,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                       (room_id, "SYN-2026-02", '["incident"]', '{}', '[]', timestamp, timestamp))
            db.commit()
        with self.assertRaisesRegex(WorkbenchError, "detection analysis room scope changed"):
            self.server.app._analyze_detection(submitted)


if __name__ == "__main__":
    unittest.main()
