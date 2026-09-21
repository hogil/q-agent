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

    def test_shared_historical_records_validate_timestamps_and_values(self):
        payload = valid_payload()
        row = {"id": "hist-1", "lotId": "past-lot", "waferId": "W01",
               "step": "STEP-1", "item": "ITEM-1", "equipment": "EQP-1", "recipe": "RCP-1",
               "fabAt": "2025-12-01T00:00:00Z", "edsAt": "2025-12-03T00:00:00Z",
               "temperature": 65, "queue": 2, "availability": 97, "yieldPct": 90,
               "bin3Pct": 3, "bin4Pct": 2}
        payload["incidents"]["SYN-1"]["historical_records"] = [row]
        path = self.write(payload)
        self.assertEqual(load_workbench_data({"raw_file": path.name}, self.root)["SYN-1"]["historical_records"], [row])
        row["edsAt"] = "2025-11-01T00:00:00Z"
        self.write(payload)
        with self.assertRaisesRegex(ValueError, "EDS must follow Fab"):
            load_workbench_data({"raw_file": path.name}, self.root)

    def test_loads_valid_incident_map(self):
        path = self.write(valid_payload())
        result = load_workbench_data({"raw_file": path.name}, self.root)
        self.assertEqual(set(result), {"SYN-1"})
        self.assertEqual(result["SYN-1"]["engineering"]["signals"][0]["id"], "signal-1")

    def test_image_history_validates_assets_vectors_and_synthetic_provenance(self):
        payload = valid_payload()
        row = {"id": "ref-1", "incident_number": "SYN-PAST", "occurred_at": "2025-12-01T00:00:00Z",
               "item": "ITEM-1", "step": "STEP-1", "modality": "sem", "provenance": "synthetic",
               "description": "reference", "src": "/assets/past.png"}
        payload["incidents"]["SYN-1"]["image_history"] = [row]
        def load():
            return load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        self.assertEqual(load()["SYN-1"]["image_history"], [row])
        row["src"] = "/assets/../secret.png"
        with self.assertRaisesRegex(ValueError, "local /assets/"):
            load()
        row.update(modality="overlay", vectors=[{"x": 0, "y": 0, "dx": 1, "dy": 2}])
        self.assertEqual(len(load()["SYN-1"]["image_history"]), 1)
        row["vectors"][0]["dx"] = float("nan")
        with self.assertRaises(ValueError):
            load()

    def test_defect_references_link_inform_history_and_finite_cd_measurements(self):
        payload = valid_payload()
        incident = payload["incidents"]["SYN-1"]
        incident["image_history"] = [
            {"id": "sem-ref", "incident_number": "SYN-PAST", "occurred_at": "2025-12-01T00:00:00Z",
             "item": "ITEM-1", "step": "STEP-1", "modality": "sem", "provenance": "synthetic",
             "description": "reference", "src": "/assets/past.png"},
            {"id": "overlay-ref", "incident_number": "SYN-PAST", "occurred_at": "2025-12-01T00:00:00Z",
             "item": "ITEM-1", "step": "STEP-1", "modality": "overlay", "provenance": "synthetic",
             "description": "reference", "vectors": [{"x": 0, "y": 0, "dx": 1, "dy": 2}]},
        ]
        incident["historical_records"] = [{
            "id": "hist-1", "lotId": "past-lot", "waferId": "W01", "step": "STEP-1", "item": "ITEM-1",
            "equipment": "EQP-1", "recipe": "RCP-1", "fabAt": "2025-11-30T00:00:00Z",
            "edsAt": "2025-12-01T00:00:00Z", "temperature": 65, "queue": 2, "availability": 97,
            "yieldPct": 90, "bin3Pct": 3, "bin4Pct": 2,
        }]
        incident["defect_references"] = [{
            "id": "defect-ref-1", "date": "2026-01-01T00:00:00Z", "step": "STEP-1", "equipment": "EQP-1",
            "item": "ITEM-1", "lotId": "past-lot", "waferId": "W01", "inform_id": "note-1",
            "historical_record_id": "hist-1", "incident_number": "SYN-PAST", "sem": {"image_history_id": "sem-ref"},
            "cd": {"unit": "nm", "range": [40, 50], "measurements": [{"site": "center", "value": 45}]},
            "overlay": {"image_history_id": "overlay-ref"}, "finding": "stored synthetic reference", "synthetic": True,
        }]
        loaded = load_workbench_data({"raw_file": self.write(payload).name}, self.root)
        self.assertEqual(loaded["SYN-1"]["defect_references"][0]["cd"]["unit"], "nm")

        invalid = json.loads(json.dumps(payload))
        invalid["incidents"]["SYN-1"]["defect_references"][0]["cd"]["measurements"][0]["value"] = float("nan")
        with self.assertRaisesRegex(ValueError, "must be finite"):
            load_workbench_data({"raw_file": self.write(invalid, "invalid-defect.json").name}, self.root)

        invalid = json.loads(json.dumps(payload))
        invalid["incidents"]["SYN-1"]["defect_references"][0]["step"] = "STEP-OTHER"
        with self.assertRaisesRegex(ValueError, "invalid Inform or historical"):
            load_workbench_data({"raw_file": self.write(invalid, "cross-step-defect.json").name}, self.root)

    def test_optional_equipment_state_history_is_validated_and_preserved(self):
        payload = valid_payload()
        payload["incidents"]["SYN-1"]["engineering"]["equipmentStates"] = [
            {"equipment": "EQP-1", "start": "2025-12-31T23:00:00+00:00", "end": "2026-01-01T00:00:00+00:00", "state": "PM", "code": "PM-1"},
            {"equipment": "EQP-1", "start": "2026-01-01T00:00:00+00:00", "end": "2026-01-01T01:00:00+00:00", "state": "RUN", "code": "RUN-1"},
        ]
        path = self.write(payload)
        loaded = load_workbench_data({"raw_file": path.name}, self.root)
        self.assertEqual(loaded["SYN-1"]["engineering"]["equipmentStates"][0]["state"], "PM")

        invalid = valid_payload()
        invalid["incidents"]["SYN-1"]["engineering"]["equipmentStates"] = [
            {"equipment": "EQP-1", "start": "2026-01-01T00:00:00+00:00", "end": "2026-01-01T02:00:00+00:00", "state": "RUN", "code": "RUN-1"},
            {"equipment": "EQP-1", "start": "2026-01-01T01:00:00+00:00", "end": "2026-01-01T03:00:00+00:00", "state": "DOWN", "code": "DOWN-1"},
        ]
        with self.assertRaisesRegex(ValueError, "overlaps"):
            load_workbench_data({"raw_file": self.write(invalid, "overlap.json").name}, self.root)

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
