import json
import tempfile
import unittest
from pathlib import Path

from app.workbench_data import MAX_RAW_FILE_BYTES, load_workbench_data


ROOT = Path(__file__).resolve().parents[1]


def valid_payload():
    timestamp = "2026-01-01T00:00:00+00:00"
    engineering = {
        "signals": [{
            "id": "signal-1", "title": "Temperature", "severity": "high",
            "metric": "temperature", "device": "DEV-1", "equipment": "EQP-1",
            "step": "STEP-1", "item": "ITEM-1", "legendAxis": "eqp_id",
            "recipe": "RCP-1", "detectedAt": timestamp, "startIndex": 0,
            "endIndex": 1, "description": "synthetic", "onsetIndex": 0,
            "pattern": "drift",
        }],
        "trend": [
            {"timestamp": timestamp, "temperature": 1.0, "queue": 2.0, "availability": 99.0},
            {"timestamp": "2026-01-01T01:00:00+00:00", "temperature": 1.1, "queue": 2.1, "availability": 98.9},
        ],
        "fab": [{"lotId": "LOT-1", "waferId": "W01", "timestamp": timestamp,
                 "equipment": "EQP-1", "step": "STEP-1", "recipe": "RCP-1", "value": 1.0}],
        "yields": [{"lotId": "LOT-1", "waferId": "W01", "measuredAt": timestamp, "yieldPct": None}],
        "wip": [{"lotId": "LOT-1", "productCode": "PROD-1", "layer": 1.0, "endLayer": 2.0,
                 "step": "STEP-1", "equipment": "EQP-1", "recipe": "RCP-1", "status": "RUN",
                 "wafers": 1, "queueHours": 0.5, "holdCode": "SYN-NONE"}],
        "downtime": [{"id": "down-1", "equipment": "EQP-1", "start": timestamp,
                       "end": "2026-01-01T00:10:00+00:00", "code": "D-1", "category": "check",
                       "description": "synthetic"}],
        "changes": [{"id": "change-1", "equipment": "EQP-1", "recipe": "RCP-1", "kind": "recipe",
                     "timestamp": timestamp, "before": "v1", "after": "v2", "sourceRef": "synthetic://change"}],
    }
    return {"version": 1, "synthetic": True, "incidents": {"SYN-1": {
        "engineering": engineering,
        "trend_fleets": {"signal-1": [{"member": "EQP-1", "highlighted": True,
                                         "points": [[0.0, 1.0], [1.0, 1.1]]}]},
        "comparison_traces": {"signal-1": {"EQP-1": [
            {"timestamp": timestamp, "value": 1.0},
            {"timestamp": "2026-01-01T01:00:00+00:00", "value": 1.1},
        ]}},
        "inform_notes": [{"id": "note-1", "title": "Check", "step": "STEP-1", "equipment": "EQP-1",
                           "date": timestamp, "version": "v1", "body": "synthetic"}],
        "sem_assets": [{"id": "sem-1", "lotId": "LOT-1", "waferId": "W01", "src": "/assets/sem.png",
                         "provenance": "synthetic", "description": "synthetic"}],
    }}}


class WorkbenchDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, payload, name="raw.json"):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_missing_source_is_unconfigured(self):
        self.assertIsNone(load_workbench_data(None, self.root))
        self.assertIsNone(load_workbench_data({}, self.root))

    def test_loads_valid_incident_map(self):
        path = self.write(valid_payload())
        result = load_workbench_data({"raw_file": path.name}, self.root)
        self.assertEqual(set(result), {"SYN-1"})
        self.assertEqual(result["SYN-1"]["engineering"]["signals"][0]["id"], "signal-1")

    def test_missing_or_invalid_source_fails_before_generation(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            load_workbench_data({"raw_file": "missing.json"}, self.root)
        payload = valid_payload()
        payload["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "synthetic must be true"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)

    @unittest.skipUnless(Path("D:/raw.json").is_absolute(), "Windows drive-path semantics required")
    def test_windows_absolute_drive_path_is_local(self):
        path = self.root / "raw.json"
        path.write_text(json.dumps(valid_payload()), encoding="utf-8")
        windows_path = str(path).replace("\\", "/")
        self.assertTrue(windows_path[1:3] == ":/")
        self.assertIsNotNone(load_workbench_data({"raw_file": windows_path}, self.root))

    def test_cross_references_and_media_paths_are_checked(self):
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["engineering"]["signals"] = []
        with self.assertRaisesRegex(ValueError, "signals must not be empty"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["trend_fleets"] = {}
        with self.assertRaisesRegex(ValueError, "trend_fleets keys"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["comparison_traces"]["unknown"] = {}
        with self.assertRaisesRegex(ValueError, "comparison_traces keys"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["sem_assets"][0]["src"] = "https://example.invalid/sem.png"
        with self.assertRaisesRegex(ValueError, "/assets/"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)

    def test_axes_require_matching_highlighted_fleet_and_no_non_equipment_peers(self):
        payload = valid_payload()
        signal = payload["incidents"]["SYN-1"]["engineering"]["signals"][0]
        signal["legendAxis"] = "recipe"
        signal["highlightedMember"] = "RCP-1"
        payload["incidents"]["SYN-1"]["trend_fleets"]["signal-1"][0]["member"] = "RCP-1"
        payload["incidents"]["SYN-1"]["comparison_traces"]["signal-1"] = {}
        loaded = load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        self.assertEqual(loaded["SYN-1"]["engineering"]["signals"][0]["legendAxis"], "recipe")

        invalid = valid_payload()
        invalid_signal = invalid["incidents"]["SYN-1"]["engineering"]["signals"][0]
        invalid_signal["legendAxis"] = "chamber"
        invalid_signal["highlightedMember"] = "CH-A"
        invalid["incidents"]["SYN-1"]["trend_fleets"]["signal-1"][0]["member"] = "EQP-1"
        with self.assertRaisesRegex(ValueError, "highlighted member"):
            load_workbench_data({"raw_file": self.write(invalid, "invalid-fleet.json").name}, self.root)

        invalid = valid_payload()
        invalid_signal = invalid["incidents"]["SYN-1"]["engineering"]["signals"][0]
        invalid_signal["legendAxis"] = "recipe"
        invalid_signal["highlightedMember"] = "RCP-1"
        invalid["incidents"]["SYN-1"]["trend_fleets"]["signal-1"][0]["member"] = "RCP-1"
        invalid["incidents"]["SYN-1"]["comparison_traces"]["signal-1"] = {"EQP-1": []}
        with self.assertRaisesRegex(ValueError, "only supported for eqp_id"):
            load_workbench_data({"raw_file": self.write(invalid, "invalid-peer.json").name}, self.root)

    def test_duplicate_timestamps_and_nonfinite_values_are_rejected(self):
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["engineering"]["trend"][1]["timestamp"] = payload["incidents"]["SYN-1"]["engineering"]["trend"][0]["timestamp"]
        with self.assertRaisesRegex(ValueError, "timestamps must be unique"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["engineering"]["trend"][0]["temperature"] = float("nan")
        with self.assertRaisesRegex(ValueError, "must be finite"):
            load_workbench_data({"raw_file": self.write(payload).name}, self.root)

    def test_file_size_limit_is_enforced(self):
        path = self.root / "large.json"
        with path.open("wb") as handle:
            handle.write(b"{" + b" " * MAX_RAW_FILE_BYTES + b"}")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            load_workbench_data({"raw_file": path.name}, self.root)


if __name__ == "__main__":
    unittest.main()
