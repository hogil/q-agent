import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
import golden
from runtime_factory import open_incident_tools


class HardDemoDataTests(unittest.TestCase):
    def settings(self, root):
        root = Path(root)
        data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / "demo.yaml").data
        data["paths"].update(data_root=str(root), golden_file=str(root / "golden.jsonl"))
        data["database"]["sqlite_file"] = str(root / "incidents.sqlite")
        data["meetings"]["sqlite_file"] = str(root / "meetings.sqlite")
        return Settings(data, ())

    def test_hard_profile_is_repeatable_varied_and_has_truth_metadata(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            result_a = generate(self.settings(first), profile="hard")
            result_b = generate(self.settings(second), profile="hard")
            self.assertEqual(result_a["profile"], "hard")
            self.assertGreaterEqual(result_a["counts"]["incidents"], 180)
            self.assertGreaterEqual(result_a["counts"]["meeting_chunks"], 300)
            self.assertEqual(result_a["counts"], result_b["counts"])
            for key in ("database", "meetings", "golden"):
                self.assertEqual(hashlib.sha256(Path(result_a["paths"][key]).read_bytes()).digest(),
                                 hashlib.sha256(Path(result_b["paths"][key]).read_bytes()).digest())

            con = sqlite3.connect(result_a["paths"]["database"])
            try:
                tables = self.settings(first).data["tables"]
                incident_cols = tables["incident"]["columns"]
                lot_cols = tables["lot_list"]["columns"]
                wafer_cols = tables["wafer_list"]["columns"]
                incidents = con.execute("SELECT " + ",".join(incident_cols[field] for field in ("incident_id", "title", "city", "department", "occurred_at", "product_generations", "confirmed_cause")) + f" FROM {tables['incident']['name']}").fetchall()
                lots = con.execute("SELECT " + ",".join(lot_cols[field] for field in ("incident_ref", "lot_id")) + f" FROM {tables['lot_list']['name']}").fetchall()
                wafers = con.execute("SELECT " + ",".join(wafer_cols[field] for field in ("incident_ref", "lot_id", "wafer_id")) + f" FROM {tables['wafer_list']['name']}").fetchall()
            finally:
                con.close()
            self.assertGreater(len({row[1] for row in incidents}), 6)
            self.assertGreater(len({row[2] for row in incidents}), 3)
            self.assertGreater(len({row[3] for row in incidents}), 3)
            self.assertGreater(len({row[4][-6:] for row in incidents}), 2)
            self.assertGreater(len({row[5] for row in incidents}), 3)
            self.assertGreater(len({row[6] for row in incidents if row[6]}), 5)
            self.assertGreater(len(lots) - len(set(lots)), 0)  # exact duplicate source rows are present
            self.assertLess(len(lots) - len(set(lots)), 60)
            self.assertTrue(any(lot_id.startswith("H-LOT-") for _, lot_id in lots))
            self.assertTrue(any(wafer_id == "HW01" for _, _, wafer_id in wafers))

            records = [json.loads(line) for line in Path(result_a["paths"]["golden"]).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 30)
            self.assertEqual({record["split"] for record in records}, {"train", "dev", "test"})
            self.assertTrue({record["category"] for record in records}.issuperset({
                "ambiguous_candidates", "array_exact", "array_all", "array_any", "split_evidence",
                "asof_guard", "compound_filter", "no_match", "independent_paraphrase"}))
            self.assertTrue(all(record["retrieval"]["incident_number"] is None for record in records))
            self.assertTrue(all((record["request_scope"] == "independent") == ("lookup" not in record["retrieval"])
                                for record in records))
            ambiguous = [record for record in records if record["category"] == "ambiguous_candidates"]
            self.assertTrue(ambiguous)
            self.assertTrue(all(record["expected"]["status"] == "needs_selection" and not record["selected_incident_ids"]
                                and not record["expected"]["required_chunk_ids"]
                                and "search_meeting_minutes" in record["expected"]["forbidden_tools"] for record in ambiguous))

            golden._validate(records)

            with open_incident_tools(self.settings(first)) as tool:
                for record in records:
                    if record["request_scope"] != "incident":
                        continue
                    lookup = record["retrieval"]["lookup"]
                    found = tool.find_incidents("golden-contract", **lookup)
                    actual = [row["incident_id"] for row in found["data"]]
                    self.assertEqual(actual, record["expected"]["incident_ids"], record["id"])
                    if len(actual) > 1:
                        self.assertEqual(found["status"], "NEEDS_SELECTION")
                    else:
                        self.assertIn(found["status"], {"OK", "NO_MATCH"})

            meeting_con = sqlite3.connect(result_a["paths"]["meetings"])
            try:
                table = self.settings(first).data["meetings"]["table"]
                for record in records:
                    expected_ids = set(record["expected"]["incident_ids"])
                    for chunk_id in record["expected"]["required_chunk_ids"]:
                        row = meeting_con.execute(f"SELECT status,meeting_date,incident_ids FROM {table} WHERE chunk_id=?", (chunk_id,)).fetchone()
                        self.assertIsNotNone(row, chunk_id)
                        self.assertEqual(row[0], "approved")
                        self.assertLessEqual(row[1], record["as_of"])
                        self.assertTrue(expected_ids.intersection(json.loads(row[2])) if expected_ids else not json.loads(row[2]))
            finally:
                meeting_con.close()

    def test_hard_join_dedup_count_mismatch_and_pagination(self):
        with tempfile.TemporaryDirectory() as root:
            settings = self.settings(root)
            result = generate(settings, profile="hard")
            with closing(sqlite3.connect(result["paths"]["database"])) as con:
                spec = settings.data["tables"]["wafer_list"]
                cols = spec["columns"]
                source = con.execute("SELECT " + ",".join(cols[key] for key in ("incident_ref", "lot_id", "wafer_id", "status"))
                                     + f" FROM {spec['name']}").fetchall()
            with open_incident_tools(settings) as tool:
                seen_shared_lots = set()
                for number in range(1, 193):
                    lookup = tool.find_incidents("join-contract", incident_number=f"H-2026-{number:03d}")
                    self.assertEqual(lookup["status"], "OK")
                    page = tool.list_incident_lots("join-contract", lookup["scope_id"], page_size=1)
                    self.assertEqual(page["page_size"], 1)
                    all_lots = tool.list_incident_lots("join-contract", lookup["scope_id"], page_size=100)
                    self.assertIn(all_lots["status"], {"OK", "PARTIAL"})
                    self.assertEqual(all_lots["unique_lots"], len({item["lot_id"] for item in all_lots["items"]}))
                    wafers = tool.list_incident_wafers("join-contract", lookup["scope_id"], page_size=100)
                    self.assertIn(wafers["status"], {"OK", "PARTIAL"})
                    pairs = [(item["lot_id"], item["wafer_id"]) for item in wafers["items"]]
                    self.assertEqual(len(pairs), len(set(pairs)))
                    incident_id = lookup["data"][0]["incident_id"]
                    self.assertEqual({(item["incident_id"], item["lot_id"], item["wafer_id"], item["status"])
                                      for item in wafers["items"]},
                                     {row for row in source if row[0] == incident_id})
                    self.assertTrue(wafers["lots_without_wafer_rows"] or any(item["state"] != "complete_by_declared_source_and_count" for item in wafers["coverage"]))
                    seen_shared_lots.update(item["lot_id"] for item in all_lots["items"])
                self.assertGreater(len(seen_shared_lots), 0)
            self.assertTrue(Path(result["paths"]["database"]).is_file())

    def test_time_bounds_use_instants_and_exclude_upper_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            settings = self.settings(root)
            generate(settings, profile="hard")
            instant = datetime.fromisoformat("2026-01-01T08:10:00+09:00").astimezone(timezone.utc)
            with open_incident_tools(settings) as tool:
                for lower, upper, expected in ((instant, instant + timedelta(seconds=1), ["synthetic-hard-pk-2026-001"]),
                                               (instant - timedelta(seconds=1), instant, [])):
                    result = tool.find_incidents("boundary", filters={"occurred_at": {
                        "gte": lower.isoformat(), "lt": upper.isoformat()}})
                    self.assertEqual([row["incident_id"] for row in result["data"]], expected)

    def test_profile_validation_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            settings = self.settings(root)
            with self.assertRaisesRegex(ValueError, "unknown demo data profile"):
                generate(settings, profile="not-a-profile")
            generate(settings, profile="hard")
            with self.assertRaises(FileExistsError):
                generate(settings, profile="hard")


if __name__ == "__main__":
    unittest.main()
