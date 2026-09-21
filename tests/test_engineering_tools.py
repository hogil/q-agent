import copy
import json
import math
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from engineering_tools import EngineeringTools
from incident_tools import ToolError
from workbench_data import load_workbench_data


ROOT = Path(__file__).resolve().parents[1]
RAW_FILE = ROOT / "data" / "workbench" / "raw.example.json"


class EngineeringToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_workbench_data({"raw_file": str(RAW_FILE)}, ROOT)
        cls.number = next(iter(cls.raw))
        cls.record = cls.raw[cls.number]
        cls.signal = cls.record["engineering"]["signals"][0]
        cls.incident_id = "synthetic-db-id"
        cls.map = {cls.number: {"incident_id": cls.incident_id}}

    def context(self, **changes):
        context = {
            "incident_number": self.number,
            "item": self.signal["item"],
            "step": self.signal["step"],
            "equipment": self.signal["equipment"],
            "recipe": self.signal["recipe"],
            "from": "2026-03-27",
            "to": "2026-03-31",
            "wafers": [{"lot_id": row["lotId"], "wafer_id": row["waferId"]}
                       for row in self.record["engineering"]["fab"][:2]],
            "trend_selection": {"range_selected": True, "value_range": None, "regions": []},
        }
        context.update(changes)
        return context

    def tool(self, sources=("trend", "correlation", "production", "inform", "changes"), **context):
        return EngineeringTools(self.raw, self.map, self.context(**context), list(sources))

    def test_real_raw_fixture_returns_bounded_engineering_snapshot(self):
        result = self.tool().query("actor", [self.incident_id], "2026-03-31")
        self.assertEqual({"status", "synthetic", "sections", "limitations", "scope",
                          "source_inventory", "interpretation", "observations"}, set(result))
        self.assertTrue(result["synthetic"])
        self.assertEqual(set(result["sections"]), {"trend", "correlation", "production", "inform", "changes"})
        self.assertLessEqual(len(result["sections"]["trend"]["engineering_trend"]["rows"]), 200)
        self.assertGreater(result["sections"]["correlation"]["count"], 0)
        self.assertEqual(result["sections"]["correlation"]["baseline"], "historical_records")

    def test_scope_must_match_single_incident_lookup(self):
        with self.assertRaisesRegex(ToolError, "INCIDENT_SCOPE_MISMATCH"):
            self.tool().query("actor", ["other-id"], "2026-03-31")
        with self.assertRaisesRegex(ToolError, "INCIDENT_SCOPE_MISMATCH"):
            self.tool().query("actor", [self.incident_id, "second-id"], "2026-03-31")

    def test_as_of_excludes_future_inform_and_changes(self):
        result = self.tool().query("actor", [self.incident_id], "2026-03-27")
        for row in result["sections"]["inform"]["rows"]:
            self.assertLessEqual(row["date"], "2026-03-27T23:59:59.999999Z")
        for row in result["sections"]["changes"]["rows"]:
            self.assertLessEqual(row["timestamp"], "2026-03-27T23:59:59.999999Z")

    def test_unchecked_sources_are_not_returned(self):
        result = self.tool(("trend", "unknown", "sem", "meetings")).query(
            "actor", [self.incident_id], "2026-03-31")
        self.assertEqual(set(result["sections"]), {"trend"})

    def test_maps_return_stored_references_and_scope_provenance_only(self):
        result = self.tool(("maps",)).query("actor", [self.incident_id], "2026-03-31")
        maps = result["sections"]["maps"]
        self.assertEqual(maps["count"], 1)
        reference = maps["records"][0]
        self.assertEqual(reference["inform_id"], "SYN-INFORM-HIST-DEFECT-1")
        self.assertEqual(reference["historical_record_id"], "SYN-HIST-MET-001")
        self.assertEqual(reference["sem"]["id"], "SYN-HIST-SEM-BRIDGE")
        self.assertEqual(reference["sem"]["src"], "/assets/synthetic-sem-history.png")
        self.assertEqual(reference["overlay"]["id"], "SYN-HIST-OVL-RADIAL")
        self.assertEqual(reference["cd"]["unit"], "nm")
        self.assertEqual(reference["cd"]["measurements"][0]["value"], 45.2)
        self.assertTrue(reference["synthetic"])
        self.assertIn("STORED_REFERENCES_ONLY", maps["limitations"])
        self.assertIn("NO_IMAGE_MODEL_ANALYSIS", maps["limitations"])
        self.assertEqual(result["source_inventory"]["selected"], ["maps"])
        self.assertEqual(result["interpretation"], "observations_only")

    def test_maps_filter_future_and_cross_scope_records(self):
        future = copy.deepcopy(self.raw)
        future[self.number]["defect_references"][0]["date"] = "2026-04-01T00:00:00Z"
        result = EngineeringTools(future, self.map, self.context(), ["maps"]).query(
            "actor", [self.incident_id], "2026-03-31")
        self.assertEqual(result["sections"]["maps"]["records"], [])
        future[self.number]["defect_references"][0]["date"] = "2026-03-28T00:00:00Z"
        result = EngineeringTools(future, self.map, self.context(), ["maps"]).query(
            "actor", [self.incident_id], "2026-03-31")
        self.assertEqual(result["sections"]["maps"]["records"], [])
        result = self.tool(("maps",), item="SYN-OTHER-ITEM").query(
            "actor", [self.incident_id], "2026-03-31")
        self.assertEqual(result["sections"]["maps"]["records"], [])

    def test_maps_reject_nonfinite_stored_cd_measurement(self):
        raw = copy.deepcopy(self.raw)
        raw[self.number]["defect_references"][0]["cd"]["measurements"][0]["value"] = float("nan")
        with self.assertRaisesRegex(ToolError, "INVALID_ENGINEERING_MAP_MEASUREMENT"):
            EngineeringTools(raw, self.map, self.context(), ["maps"]).query(
                "actor", [self.incident_id], "2026-03-31")

    def test_trend_reports_deterministic_before_after_onset_delta(self):
        result = self.tool(("trend",)).query("actor", [self.incident_id], "2026-03-31")
        stats = result["sections"]["trend"]["stats"][self.signal["id"]]
        onset = stats["onset_summary"]
        self.assertEqual(onset["timestamp"], self.record["engineering"]["trend"][self.signal["onsetIndex"]]["timestamp"])
        highlighted = next(trace for trace in self.record["trend_fleets"][self.signal["id"]] if trace["highlighted"])
        onset_ms = datetime.fromisoformat(onset["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
        selected = [point for point in highlighted["points"]
                    if self.tool(("trend",)).context["_from_time"].timestamp() * 1000 <= point[0]
                    <= self.tool(("trend",)).context["_to_time"].timestamp() * 1000]
        self.assertEqual(onset["basis"], "highlighted_fleet_points")
        self.assertEqual(onset["before"]["count"], sum(point[0] < onset_ms for point in selected))
        self.assertEqual(onset["after"]["count"], sum(point[0] >= onset_ms for point in selected))
        self.assertAlmostEqual(onset["delta"]["value"], onset["after"]["mean"] - onset["before"]["mean"])

    def test_production_prioritizes_onset_state_and_reports_truncation(self):
        result = self.tool(("production",), equipment="").query(
            "actor", [self.incident_id], "2026-03-31")
        states = result["sections"]["production"]["equipmentStates"]
        self.assertEqual(states["count"], 18)
        self.assertEqual(states["returned_count"], 12)
        self.assertEqual(states["truncated_count"], 6)
        self.assertTrue(any(row["state"] == "DOWN" and row["start"] <= "2026-03-28T08:05:00Z" <= row["end"]
                            for row in states["rows"]))

    def test_focus_observations_preserve_actual_state_and_source_values(self):
        result = self.tool(("trend", "production", "maps")).query("actor", [self.incident_id], "2026-03-31")
        focus = result["observations"]
        self.assertEqual(focus["trend_onset"][self.signal["id"]],
                         result["sections"]["trend"]["stats"][self.signal["id"]]["onset_summary"])
        self.assertEqual(focus["historical_references"], result["sections"]["maps"]["records"])
        self.assertEqual({row['state'] for row in focus['equipment_events']}, {'DOWN', 'PM'})
        for row in focus['equipment_events']:
            self.assertIn(row, result['sections']['production']['equipmentStates']['rows'])

    def test_exact_xy_rectangles_exclude_gap_and_compute_stats(self):
        target = next(trace for trace in self.record["trend_fleets"][self.signal["id"]] if trace["highlighted"])
        first, second = target["points"][0], target["points"][2]
        context = self.context(trend_selection={
            "range_selected": True,
            "value_range": None,
            "regions": [
                [[first[0], first[0]], [first[1], first[1]]],
                [[second[0], second[0]], [second[1], second[1]]],
            ],
        })
        result = EngineeringTools(self.raw, self.map, context, ["trend"]).query(
            "actor", [self.incident_id], "2026-03-31")
        selected = result["sections"]["trend"]["trend_fleets"][self.signal["id"]][0]
        self.assertLessEqual(selected["count"], 2)
        summary = result["sections"]["trend"]["stats"][self.signal["id"]]["selected"]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["mean"], round((first[1] + second[1]) / 2, 6))
        self.assertAlmostEqual(summary["min"], min(first[1], second[1]), places=6)
        self.assertAlmostEqual(summary["max"], max(first[1], second[1]), places=6)
        self.assertEqual(summary["unit"], "degC")

    def test_optional_historical_records_provide_explicit_baseline_and_pearson(self):
        raw = copy.deepcopy(self.raw)
        raw[self.number]["historical_records"] = [
            {"id": "h1", "lotId": "hl1", "waferId": "w1", "step": self.signal["step"],
             "item": self.signal["item"], "equipment": self.signal["equipment"], "recipe": self.signal["recipe"],
             "fabAt": "2026-03-20T00:00:00Z", "edsAt": "2026-03-21T00:00:00Z",
             "temperature": 1.0, "queue": 2.0, "availability": 90.0, "yieldPct": 80.0,
             "bin3Pct": 10.0, "bin4Pct": 10.0},
            {"id": "h2", "lotId": "hl2", "waferId": "w2", "step": self.signal["step"],
             "item": self.signal["item"], "equipment": self.signal["equipment"], "recipe": self.signal["recipe"],
             "fabAt": "2026-03-22T00:00:00Z", "edsAt": "2026-03-23T00:00:00Z",
             "temperature": 3.0, "queue": 2.0, "availability": 90.0, "yieldPct": 90.0,
             "bin3Pct": 5.0, "bin4Pct": 5.0},
        ]
        result = EngineeringTools(raw, self.map, self.context(), ["correlation"]).query(
            "actor", [self.incident_id], "2026-03-31")
        correlation = result["sections"]["correlation"]
        self.assertEqual(correlation["baseline"], "historical_records")
        self.assertEqual(correlation["count"], 2)
        self.assertAlmostEqual(correlation["pearson_r"], 1.0)
        self.assertEqual([row["id"] for row in correlation["rows"]], ["h1", "h2"])
        self.assertNotIn("RAW_HISTORICAL_PAIRS_UNAVAILABLE", result["limitations"])


if __name__ == "__main__":
    unittest.main()
