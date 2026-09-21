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
        self.assertEqual({"status", "synthetic", "sections", "limitations", "scope"}, set(result))
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
        result = self.tool(("trend", "maps", "sem", "meetings")).query(
            "actor", [self.incident_id], "2026-03-31")
        self.assertEqual(set(result["sections"]), {"trend"})

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
        self.assertAlmostEqual(summary["mean"], (first[1] + second[1]) / 2)
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
