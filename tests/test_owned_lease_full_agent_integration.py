"""Full synthetic Agent path through an owned SQLite lease and real planner."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

try:
    from qmodels.action_evidence_planner_v1 import CandidateTest, Hypothesis, TrustedContext, plan
except ImportError as exc:
    if exc.name == "qmodels":
        PLANNER_IMPORT_ERROR = str(exc)
    else:
        raise
else:
    PLANNER_IMPORT_ERROR = None

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from synthetic_sqlite_action_lease import sqlite_action_snapshot_lease_provider
from test_agent import ScriptedClient, answer, judge, plan as router_plan
from workbench import Workbench, load_workbench


MAPPING = {
    "dialect": "sqlite", "mapping_version": "synthetic-full-agent-v1",
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
    "limits": {"default_page_size": 1, "max_page_size": 100, "max_scope_incidents": 20},
}


@unittest.skipIf(PLANNER_IMPORT_ERROR, f"q-agent-models planner unavailable: {PLANNER_IMPORT_ERROR}")
class OwnedLeaseFullAgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        db = sqlite3.connect(self.path)
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

        data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / "demo.yaml").data
        data["database"]["sqlite_file"] = str(self.path)
        data["synthetic_action_planner"] = {"enabled": True}
        data["value_matching"]["fuzzy_enabled"] = False
        data["relations"].update(source_completeness="declared_complete",
                                 wafer_source_completeness="declared_complete",
                                 wafer_scope="incident_affected")
        self.settings = Settings(data, ())
        def lease_provider(tools, actor, scope_id):
            self.assertEqual(actor, "synthetic-actor")
            self.assertIn(scope_id, tools.scopes)
            self.assertEqual(Path(tools.db.execute("PRAGMA database_list").fetchone()[2]).resolve(),
                             self.path.resolve())
            return sqlite_action_snapshot_lease_provider(lambda conn: {
                "revision": conn.execute("SELECT revision FROM manifest").fetchone()[0],
                "as_of": conn.execute("SELECT as_of FROM manifest").fetchone()[0],
            })(tools, actor, scope_id)

        self.lease_provider = lease_provider

    def tearDown(self):
        self.temp.cleanup()

    def test_agent_incident_first_lease_real_planner_judge_answer_is_proposal_only(self):
        steps = [
            ("router", router_plan(tool="find_incidents", arguments={"incident_number": "SYN-1"},
                                    search_mode="sql_exact")),
            ("router", router_plan(stage="tools", tool="list_incident_lots",
                                    arguments={"page_size": 20, "offset": 0})),
            ("router", router_plan(stage="tools", tool="list_incident_wafers",
                                    arguments={"page_size": 20, "offset": 0})),
            ("router", router_plan(stage="tools", tool="plan_synthetic_action_evidence")),
            ("judge", judge), ("answer", answer),
        ]
        client = ScriptedClient(steps)
        planner_inputs = []

        def real_planner(scoped):
            planner_inputs.append(scoped)
            context = TrustedContext(scoped["scope"], scoped["as_of"], scoped["revision"])
            hypotheses = (Hypothesis("safe", ("RELEASE",)),
                          Hypothesis("risk", ("HOLD",), risk=True))
            candidate = CandidateTest("synthetic-check", 1.0,
                                      {"safe-result": ("safe",), "risk-result": ("risk",)})
            return plan(context, hypotheses, tests=(candidate,), requested_action="RELEASE",
                        spent_cost=0.0, cost_budget=1.0)

        with patch.object(agent, "RoleClient", return_value=client), \
             patch.object(Settings, "mapping", return_value=MAPPING):
            result = agent.run(self.settings, "합성 사고의 조치 evidence를 검토", "synthetic-actor",
                               as_of="2026-10-29", incident_number="SYN-1",
                               requested_tools=["find_incidents", "plan_synthetic_action_evidence"],
                               synthetic_action_planner=real_planner,
                               snapshot_lease_provider=self.lease_provider)

        self.assertEqual(result["status"], "answered", result)
        self.assertEqual([entry["source"] for entry in result["evidence"]], [
            "find_incidents", "list_incident_lots", "list_incident_wafers",
            "plan_synthetic_action_evidence"])
        self.assertEqual(len(planner_inputs), 1)
        self.assertEqual(planner_inputs[0]["scope"], (("wafer-1", "lot-a"), ("wafer-2", "lot-a")))
        self.assertEqual(planner_inputs[0]["revision"], "synthetic-rev-1")
        planner_result = result["evidence"][-1]["result"]
        self.assertEqual(planner_result["scope"], [["wafer-1", "lot-a"], ["wafer-2", "lot-a"]])
        self.assertEqual(planner_result["revision"], "synthetic-rev-1")
        self.assertFalse(planner_result["execution_granted"])
        self.assertFalse(planner_result["next_test"]["execution_granted"])
        self.assertEqual([role for role, _, _ in client.calls][-2:], ["judge", "answer"])
        self.assertTrue(client.calls[-2][2]["synthetic_action_provenance_and_assumptions"])
        self.assertTrue(client.calls[-1][2]["synthetic_action_provenance_and_assumptions"])

    def test_workbench_explicit_action_evidence_runs_real_agent_and_planner(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        overlay_path = root / "demo.yaml"
        overlay = yaml.safe_load((ROOT / "config/demo.yaml").read_text(encoding="utf-8"))
        overlay["paths"]["data_root"] = str(root / "data")
        overlay.setdefault("relations", {}).update(source_completeness="declared_complete",
                                                   wafer_source_completeness="declared_complete",
                                                   wafer_scope="incident_affected")
        overlay["synthetic_action_planner"] = {"enabled": True}
        overlay_path.write_text(yaml.safe_dump(overlay, allow_unicode=True, sort_keys=False), encoding="utf-8")
        static_root = root / "static"
        static_root.mkdir()
        (static_root / "index.html").write_text("<main>synthetic workbench</main>", encoding="utf-8")
        config_path = root / "workbench.yaml"
        config_path.write_text(
            "config_version: 1\n"
            "demo:\n  base_config: " + str(ROOT / "config/config.yaml").replace("\\", "/") + "\n"
            "  overlay: " + str(overlay_path).replace("\\", "/") + "\n"
            "chat:\n  sqlite_file: " + str(root / "chat.sqlite").replace("\\", "/") + "\n"
            "  history_limit: 40\ncutoff: 2026-03-31\nstatic_root: "
            + str(static_root).replace("\\", "/") + "\n",
            encoding="utf-8",
        )
        config = load_workbench(config_path)
        database_path = Path(config["settings"].data["database"]["sqlite_file"])
        writer = sqlite3.connect(database_path)
        writer.execute(
            "UPDATE demo_incident SET affected_wafer_count = "
            "(SELECT COUNT(*) FROM demo_wafer_list w WHERE w.accident_ref = demo_incident.accident_pk)"
        )
        writer.execute("CREATE TABLE synthetic_action_manifest (revision TEXT, as_of TEXT)")
        writer.execute("INSERT INTO synthetic_action_manifest VALUES (?, ?)",
                       ("workbench-synthetic-rev-1", "2026-03-31T00:00:00Z"))
        writer.commit()
        writer.close()
        data = dict(config["settings"].data)
        data["models"] = {**data["models"], "text": {
            **data["models"]["text"], "enabled": True, "mode": "api",
            "base_url": "http://llm.invalid/v1", "api_key_env": "UNUSED_SCRIPTED_KEY",
            "served_model": "scripted-workbench-model"}}
        config["settings"] = Settings(data, config["settings"].source_files)

        planner_inputs = []

        def real_planner(scoped):
            planner_inputs.append(scoped)
            context = TrustedContext(scoped["scope"], scoped["as_of"], scoped["revision"])
            hypotheses = (Hypothesis("safe", ("RELEASE",)),
                          Hypothesis("risk", ("HOLD",), risk=True))
            candidate = CandidateTest("workbench-synthetic-check", 1.0,
                                      {"safe-result": ("safe",), "risk-result": ("risk",)})
            return plan(context, hypotheses, tests=(candidate,), requested_action="RELEASE",
                        spent_cost=0.0, cost_budget=1.0)

        def workbench_answer(payload):
            result = answer(payload)
            evidence_ids = payload["evidence_ids"]
            result["inspection_plan"] = {
                "historical_matches": [],
                "checks": [{"target": "synthetic process logs", "basis": "synthetic incident scope",
                            "comparison": "compare the recorded conditions with the reference",
                            "evidence_ids": evidence_ids}],
                "eds_followup": {"target": "synthetic EDS result", "basis": "follow-up result not supplied",
                                 "comparison": "compare after the result arrives", "evidence_ids": evidence_ids},
            }
            return result

        def lease_provider(tools, actor, scope_id):
            self.assertEqual(actor, "local-workbench")
            self.assertIn(scope_id, tools.scopes)
            self.assertEqual(Path(tools.db.execute("PRAGMA database_list").fetchone()[2]).resolve(),
                             database_path.resolve())
            return sqlite_action_snapshot_lease_provider(lambda conn: {
                "revision": conn.execute("SELECT revision FROM synthetic_action_manifest").fetchone()[0],
                "as_of": conn.execute("SELECT as_of FROM synthetic_action_manifest").fetchone()[0],
            })(tools, actor, scope_id)

        app = Workbench(config, synthetic_action_planner=real_planner,
                        snapshot_lease_provider=lease_provider)
        room_id = app.create_room("Synthetic action evidence", "SYN-2026-01")["id"]
        context = {"incident_number": "SYN-2026-01", "item": "SYN-ITEM", "step": "ETCH",
                   "equipment": "EQ-SYN-01", "from": "2026-01-01T00:00:00Z",
                   "to": "2026-03-31T00:00:00Z", "wafers": []}
        steps = [
            ("router", router_plan(tool="find_incidents", arguments={"incident_number": "SYN-2026-01"},
                                    search_mode="sql_exact")),
            ("router", router_plan(stage="tools", tool="list_incident_lots",
                                    arguments={"page_size": 100, "offset": 0})),
            ("router", router_plan(stage="tools", tool="list_incident_wafers",
                                    arguments={"page_size": 100, "offset": 0})),
            ("router", router_plan(stage="tools", tool="plan_synthetic_action_evidence")),
            ("judge", judge), ("answer", workbench_answer),
        ]
        client = ScriptedClient(steps)
        with patch.object(agent, "RoleClient", return_value=client):
            result = app.analysis(room_id, {"content": "선택한 사고의 합성 조치 제안 근거를 검토해줘",
                                            "sources": ["action_evidence"], "context": context})

        analysis = result["analysis"]
        report = analysis["report"]
        self.assertEqual(analysis["mode"], "llm")
        self.assertTrue(analysis["llm_connected"])
        self.assertEqual(analysis["sources"], ["incident", "action_evidence"])
        self.assertEqual(next(step for step in analysis["steps"] if step["source"] == "action_evidence")["status"],
                         "completed")
        self.assertEqual(len(planner_inputs), 1)
        self.assertEqual(planner_inputs[0]["revision"], "workbench-synthetic-rev-1")
        self.assertGreater(len(planner_inputs[0]["scope"]), 0)
        proposal = report["synthetic_action_evidence"][0]["result"]
        self.assertFalse(proposal["execution_granted"])
        self.assertFalse(proposal["next_test"]["execution_granted"])
        self.assertIn("proposal-only", result["messages"][-1]["content"])
        self.assertEqual([role for role, _, _ in client.calls][-2:], ["judge", "answer"])


if __name__ == "__main__":
    unittest.main()
