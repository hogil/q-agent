"""Synthetic E2E for owned SQLite lease -> incident bridge -> real planner.

Run with this repository and the q-agent-models src directory on PYTHONPATH.
The provider/manifest reader is a same-process trusted test fixture; this does
not implement production ACL or grant action execution authority.
"""
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

try:
    from qmodels.action_evidence_planner_v1 import CandidateTest, Hypothesis, TrustedContext, plan
except ImportError as exc:
    PLANNER_IMPORT_ERROR = str(exc)
else:
    PLANNER_IMPORT_ERROR = None

from incident_tools import IncidentTools
from app.action_scope_bridge import ActionScopeBridgeError, build_scoped_action_input
from app.synthetic_sqlite_action_lease import sqlite_action_snapshot_lease_provider


MAPPING = {
    "dialect": "sqlite", "mapping_version": "synthetic-e2e-v1",
    "entities": {
        "incident": {"table": "incidents", "columns": {
            "incident_id": "id", "incident_number": "number", "title": "title",
            "city": "city", "line": "line", "expected_lot_count": "expected_lots",
            "affected_wafer_count": "expected_wafers"}},
        "lot_list": {"table": "lots", "columns": {
            "incident_ref": "incident_ref", "lot_id": "lot_id",
            "product_code": "product", "status": "status"}},
        "wafer_list": {"table": "wafers", "columns": {
            "incident_ref": "incident_ref", "lot_id": "wafer_lot_id",
            "wafer_id": "wafer_id", "status": "status"}},
    },
    "relationships": {
        "incident_lots": {"parent_entity": "incident", "child_entity": "lot_list",
                           "parent_key": "incident_id", "child_key": "incident_ref",
                           "duplicate_policy": "exact_rows_deduplicate_conflicts_error",
                           "source_completeness": "declared_complete"},
        "incident_wafers": {"scope": "incident_affected", "parent_key": "incident_id",
                             "child_key": "incident_ref", "lot_key": "lot_id",
                             "source_completeness": "declared_complete"},
    },
    "limits": {"default_page_size": 1, "max_page_size": 20},
}


@unittest.skipIf(PLANNER_IMPORT_ERROR, f"q-agent-models planner unavailable: {PLANNER_IMPORT_ERROR}")
class OwnedLeasePlannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(
            "CREATE TABLE incidents(id TEXT, number TEXT, title TEXT, city TEXT, line TEXT, expected_lots INT, expected_wafers INT);"
            "CREATE TABLE lots(incident_ref TEXT, lot_id TEXT, product TEXT, status TEXT);"
            "CREATE TABLE wafers(incident_ref TEXT, wafer_lot_id TEXT, wafer_id TEXT, status TEXT);"
            "CREATE TABLE manifest(revision TEXT, as_of TEXT);"
            "INSERT INTO incidents VALUES ('syn-inc-1','SYN-1','fixture','x','L1',1,2);"
            "INSERT INTO lots VALUES ('syn-inc-1','lot-a','p','OK');"
            "INSERT INTO wafers VALUES ('syn-inc-1','lot-a','wafer-1','OK'),('syn-inc-1','lot-a','wafer-2','OK');"
            "INSERT INTO manifest VALUES ('synthetic-rev-1','2026-10-29T00:00:00Z');"
        )
        db.commit()
        db.close()
        self.source = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        self.source.execute("PRAGMA query_only=ON")
        self.tools = IncidentTools(self.source, MAPPING)
        self.scope_id = "selected-synthetic-incident"
        self.tools.scopes[self.scope_id] = {
            "actor": "synthetic-actor", "ids": ("syn-inc-1",),
            "expires_at": time.monotonic() + 300, "requires_selection": False,
            "summary_only": False,
        }

    def tearDown(self):
        self.source.close()
        self.temp.cleanup()

    def _reader(self, *, mutate_after_pin=False, bad_revision=False):
        mutated = False

        def read_manifest(con):
            nonlocal mutated
            row = con.execute("SELECT revision, as_of FROM manifest").fetchone()
            manifest = {"revision": row["revision"], "as_of": row["as_of"]}
            if mutate_after_pin and not mutated:
                writer = sqlite3.connect(self.path)
                writer.execute("UPDATE incidents SET expected_lots=2, expected_wafers=3 WHERE id='syn-inc-1'")
                writer.execute("INSERT INTO lots VALUES ('syn-inc-1','lot-b','p','OK')")
                writer.execute("INSERT INTO wafers VALUES ('syn-inc-1','lot-b','wafer-3','OK')")
                writer.execute("UPDATE manifest SET revision='synthetic-rev-2', as_of='2026-10-30T00:00:00Z'")
                writer.commit()
                writer.close()
                mutated = True
            if bad_revision:
                manifest["revision"] = ""
            return manifest

        return read_manifest

    def _bridge(self, reader):
        return build_scoped_action_input(
            self.tools, "synthetic-actor", self.scope_id,
            snapshot_lease_provider=sqlite_action_snapshot_lease_provider(reader), page_size=1)

    def test_pinned_rows_and_manifest_flow_through_bridge_into_real_planner(self):
        bridge = self._bridge(self._reader(mutate_after_pin=True))
        self.assertEqual(bridge["scope"], (("wafer-1", "lot-a"), ("wafer-2", "lot-a")))
        self.assertEqual(bridge["revision"], "synthetic-rev-1")
        self.assertEqual(bridge["as_of"].isoformat(), "2026-10-29T00:00:00+00:00")
        self.assertTrue(bridge["synthetic_planner_input_eligible"])
        self.assertFalse(bridge["execution_granted"])

        context = TrustedContext(bridge["scope"], bridge["as_of"], bridge["revision"])
        hypotheses = (Hypothesis("safe", ("RELEASE",)),
                      Hypothesis("risk", ("HOLD",), risk=True))
        candidate = CandidateTest("synthetic-check", 1.0,
                                  {"safe-result": ("safe",), "risk-result": ("risk",)})
        result = plan(context, hypotheses, tests=(candidate,), requested_action="RELEASE",
                      spent_cost=0.0, cost_budget=1.0)
        self.assertEqual(result["scope"], [list(pair) for pair in bridge["scope"]])
        self.assertEqual(result["as_of"], bridge["as_of"].isoformat())
        self.assertEqual(result["revision"], bridge["revision"])
        self.assertEqual(result["next_test"]["id"], "synthetic-check")
        self.assertFalse(result["next_test"]["execution_granted"])

    def test_bad_manifest_and_incomplete_scope_are_rejected(self):
        with self.assertRaisesRegex(Exception, "MANIFEST_REVISION_REQUIRED"):
            self._bridge(self._reader(bad_revision=True))

        writer = sqlite3.connect(self.path)
        writer.execute("UPDATE incidents SET expected_wafers=99 WHERE id='syn-inc-1'")
        writer.commit()
        writer.close()
        with self.assertRaisesRegex(ActionScopeBridgeError, "WAFER_INCOMPLETE"):
            self._bridge(self._reader())


if __name__ == "__main__":
    unittest.main()
