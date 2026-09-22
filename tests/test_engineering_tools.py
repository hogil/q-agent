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
        self.assertEqual(reference["historical_eds"], {
            "edsAt": "2025-11-11T06:00:00Z", "yieldPct": 89.8,
            "bin3Pct": 8.4, "bin4Pct": 1.8,
            "historical_record_id": "SYN-HIST-MET-001",
            "lotId": "SYN-HIST-MET-LOT-001", "waferId": "SYN-HIST-MET-W01",
        })
        self.assertEqual(reference["metadata_match_basis"]["scope_match_fields"],
                         ["step", "item", "equipment"])
        self.assertEqual(reference["metadata_match_basis"]["reference_join_fields"],
                         ["historical_record_id", "lotId", "waferId"])
        self.assertIn("historical_record_id", reference["metadata_match_basis"]["links"])
        self.assertFalse(reference["metadata_match_basis"]["image_similarity_verified"])
        unfiltered = self.tool(("maps",), equipment="").query(
            "actor", [self.incident_id], "2026-03-31")
        self.assertEqual(unfiltered["sections"]["maps"]["records"][0]["metadata_match_basis"]["scope_match_fields"],
                         ["step", "item"])
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

    def test_maps_reject_historical_pair_that_does_not_match_reference(self):
        raw = copy.deepcopy(self.raw)
        raw[self.number]["historical_records"][0]["waferId"] = "different-wafer"
        with self.assertRaisesRegex(ToolError, "INVALID_ENGINEERING_MAP_REFERENCE"):
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
        result = self.tool(("production",), equipment="", recipe="").query(
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

    def test_production_reports_selected_fab_and_explicit_current_eds_absence(self):
        result = self.tool(("production",), equipment="", recipe="").query(
            "actor", [self.incident_id], "2026-03-31")
        production = result["sections"]["production"]
        self.assertEqual(production["fab"]["count"], 2)
        self.assertEqual(production["fab"]["rows"], self.record["engineering"]["fab"][:2])
        self.assertEqual(production["current_eds"]["status"], "not_available_in_snapshot")
        self.assertEqual(production["current_eds"]["verification"], "pending_verification")
        self.assertEqual(production["current_eds"]["rows"]["count"], 0)
        self.assertEqual(production["current_eds"]["selected_fab_count"], 2)
        self.assertEqual(production["current_eds"]["interpretation"], "not_proven_failure_or_normal")
        self.assertIsNone(production["current_eds"]["source"])
        self.assertEqual(result["observations"]["current_fab"], production["fab"])
        self.assertEqual(result["observations"]["current_eds"], production["current_eds"])

    def test_future_yield_shaped_row_does_not_claim_current_eds_available(self):
        raw = copy.deepcopy(self.raw)
        raw[self.number]["engineering"]["yields"] = [{
            "lotId": "SYN-LOT-09-01", "waferId": "W02",
            "measuredAt": "2026-04-01T00:00:00Z", "yieldPct": 91.0,
        }]
        result = EngineeringTools(raw, self.map, self.context(equipment=""), ["production"]).query(
            "actor", [self.incident_id], "2026-03-31")
        current_eds = result["sections"]["production"]["current_eds"]
        self.assertEqual(current_eds["status"], "not_available_in_snapshot")
        self.assertEqual(current_eds["rows"]["rows"], [])
        self.assertIn("CURRENT_EDS_SOURCE_NOT_IMPLEMENTED", current_eds["limitations"])

    def test_production_empty_fab_scope_has_no_current_eds_rows(self):
        result = self.tool(("production",), **{
            "from": "2027-01-01", "to": "2027-01-02", "equipment": "",
        }).query("actor", [self.incident_id], "2027-01-02")
        production = result["sections"]["production"]
        self.assertEqual(production["fab"]["count"], 0)
        self.assertEqual(production["current_eds"]["status"], "no_current_fab")
        self.assertEqual(production["current_eds"]["selected_fab_count"], 0)
        self.assertEqual(production["current_eds"]["verification"], "not_applicable_no_current_fab")
        self.assertEqual(production["current_eds"]["rows"]["rows"], [])

    def test_production_source_is_required_for_current_fab_eds_observations(self):
        result = self.tool(("trend",)).query("actor", [self.incident_id], "2026-03-31")
        self.assertNotIn("production", result["sections"])
        self.assertNotIn("current_eds", result["observations"])

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
