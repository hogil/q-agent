import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from config_loader import load_config
from demo_data import generate
from engineering_demo import load_scenarios
from meeting_tools import MeetingTools
from runtime_factory import open_incident_tools
from workbench_data import load_workbench_data


class LinkedEngineeringDemoTests(unittest.TestCase):
    def test_history_and_time_scoped_meeting_search(self):
        raw = load_workbench_data({"raw_file": str(ROOT / "data/workbench/raw.example.json"),
                                   "scenario_file": str(ROOT / "data/workbench/scenarios.json")}, ROOT)
        scenarios = load_scenarios(ROOT / "data/workbench/scenarios.json")
        with tempfile.TemporaryDirectory() as directory:
            settings = load_config(ROOT / "config/config.yaml", ROOT / "config/engineering-demo.yaml")
            settings.data["paths"]["data_root"] = directory
            settings.data["paths"]["golden_file"] = str(Path(directory) / "empty.jsonl")
            settings.data["database"]["sqlite_file"] = str(Path(directory) / "incidents.sqlite")
            settings.data["meetings"]["sqlite_file"] = str(Path(directory) / "meetings.sqlite")
            report = generate(settings, "engineering", engineering_raw=raw, scenarios=scenarios)
            self.assertEqual(report["counts"]["incidents"], 16)
            self.assertEqual(report["counts"]["golden_cases"], 0)
            with open_incident_tools(settings) as tools:
                result = tools.find_incidents("test", incident_number="SYN-HIST-2025-QUEUE")
                self.assertEqual(len(result["data"]), 1)
                wafers = tools.list_incident_wafers("test", result["scope_id"])
                self.assertEqual(wafers["items"][0]["lot_id"], "SYN-HIST-REF-QUEUE-LOT")
            meetings = MeetingTools(settings)
            before = meetings.search("test", "SYN-QUEUE", ["synthetic-pk-2026-09"], "2026-03-30", 10)
            after = meetings.search("test", "SYN-QUEUE", ["synthetic-pk-2026-09"], "2026-03-31", 10)
            self.assertTrue(before["items"])
            self.assertTrue(all(row["meeting_date"] <= "2026-03-30" for row in before["items"]))
            self.assertTrue(any(row["chunk_id"].endswith("review") for row in after["items"]))
            self.assertTrue(all("과거 결론은 현재 원인" in row["text"] for row in before["items"]))
            with self.assertRaises(FileExistsError):
                generate(settings, "engineering", engineering_raw=raw, scenarios=scenarios)
