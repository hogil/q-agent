"""Synthetic end-to-end coverage for configured MES reference filters."""
import json
import tempfile
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from runtime_factory import open_synthetic_mes_reference
from skill_loader import freeze


def _plan(tool=None, arguments=None, ready=False):
    return {
        "intents": ["search"], "filters": {},
        "plan": [] if ready else [{"tool": tool, "arguments": arguments or {},
                                   "depends_on": [], "reason": "synthetic MES regression"}],
        "needs_skills": [], "clarification": None,
        "decision": "ready_for_judge" if ready else "execute",
        "stage": "tools" if ready or tool != "find_incidents" else "incident",
        "search_mode": "sql_exact" if tool == "find_incidents" else "none",
        "limitations": [],
    }


class ScriptedClient:
    def __init__(self):
        self.calls = []
        self.steps = iter([
            ("router", _plan("find_incidents", {"incident_number": "SYN-2026-01"})),
            ("router", _plan("search_mes_reference", {
                "kind": "product", "query": "Alpha",
                "filters": {"product": "SYN-PROD", "process": "ETCH", "equipment": "SYN-EQP"},
            })),
            ("router", _plan(ready=True)),
            ("judge", lambda p: {"verdict": "pass", "return_to": "answer",
                "coverage": [{"requirement": p["question"], "status": "satisfied",
                              "evidence_ids": p["evidence_ids"]}], "issues": []}),
            ("answer", lambda p: {"status": "answered", "answer": "synthetic reference found",
                "claims": [{"claim_id": "c1", "text": "Reference evidence", "evidence_ids": p["evidence_ids"]}],
                "limitations": [], "inspection_plan": None}),
        ])

    def call(self, role, system_prompt, payload, history):
        expected, output = next(self.steps)
        if role != expected:
            raise AssertionError((role, expected))
        self.calls.append((role, payload))
        result = output(payload) if callable(output) else output
        call_id = "synthetic-plan" if role == "router" else None
        if role == "router":
            history.append({"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
                "function": {"name": "submit_plan", "arguments": json.dumps(result)}}]})
        return result, call_id


class MESReferenceFiltersE2E(unittest.TestCase):
    def test_incident_selected_then_configured_filters_and_temporal_scope_are_applied(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / "demo.yaml").data
            data["paths"].update(data_root=str(root), golden_file=str(root / "golden.jsonl"),
                                 skill_lock_file=str(root / "temporary-skill-lock.json"))
            data["database"]["sqlite_file"] = str(root / "incidents.sqlite")
            data["meetings"]["sqlite_file"] = str(root / "meetings.sqlite")
            settings = Settings(data, ())
            freeze(settings=settings)
            generate(settings, profile="basic", include_goldens=False)

            mes_path = root / "mes.sqlite"
            with closing(sqlite3.connect(mes_path)) as db:
                db.execute("CREATE TABLE refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids, product, process, equipment)")
                base = ("product", "SYN-MATCH", "v1", "Alpha product", "synthetic://mes/match",
                        "2026-03-01T00:00:00Z", "2026-01-01T00:00:00Z", None, "candidate",
                        json.dumps(["synthetic-pk-2026-01"]), "SYN-PROD", "ETCH", "SYN-EQP")
                db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", base)
                db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    *base[:1], "SYN-FUTURE", *base[2:5], "2026-04-01T00:00:00Z", *base[6:]))
                db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    *base[:1], "SYN-CATALOG", *base[2:9], json.dumps(["SYN-OUT-OF-SCOPE"]), *base[10:]))
                db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    *base[:1], "SYN-WRONG-PRODUCT", *base[2:10], "OTHER-PROD", *base[11:]))
                db.commit()

            mes = data["mes_reference"]
            mes.update(enabled=True, top_k=5, allowed_kinds=["product"])
            mes["synthetic_sqlite"] = {
                "enabled": True, "database_file": str(mes_path), "table": "refs", "timezone": "UTC",
                "columns": {key: key for key in ("kind", "record_id", "version", "name", "source_ref",
                    "available_at", "effective_from", "effective_to", "applicability", "incident_ids")},
                "filter_columns": {key: key for key in ("product", "process", "equipment")},
            }
            settings = Settings(data, ())
            reader = open_synthetic_mes_reference(settings)
            self.assertEqual(reader(actor="synthetic-test", incident_ids=["synthetic-pk-2026-01"],
                as_of="2026-03-31", kind="product", query="Alpha", top_k=5,
                filters={"product": "SYN-PROD", "process": "ETCH", "equipment": "SYN-EQP"})["status"], "OK")
            client = ScriptedClient()
            with patch.object(agent, "RoleClient", return_value=client):
                result = agent.run(settings, "SYN-2026-01 사고 Alpha 기준정보 조회", "synthetic-test",
                                   as_of="2026-03-31", mes_reference_query=open_synthetic_mes_reference(settings))

        self.assertEqual(result["status"], "answered", result)
        self.assertEqual([role for role, _ in client.calls][-2:], ["judge", "answer"])
        mes_evidence = [row for row in result["evidence"] if row["source"] == "search_mes_reference"]
        self.assertEqual(len(mes_evidence), 1)
        retrieved = mes_evidence[0]["result"]
        self.assertEqual(retrieved["as_of"], "2026-03-31")
        items = {item["record_id"]: item for item in retrieved["items"]}
        self.assertEqual(set(items), {"SYN-MATCH", "SYN-CATALOG"})
        self.assertEqual(items["SYN-MATCH"]["scope_relation"], "current_scope")
        self.assertEqual(items["SYN-MATCH"]["incident_ids"], ["synthetic-pk-2026-01"])
        self.assertEqual(items["SYN-CATALOG"]["scope_relation"], "catalog_candidate")
        self.assertEqual(items["SYN-CATALOG"]["incident_ids"], [])
