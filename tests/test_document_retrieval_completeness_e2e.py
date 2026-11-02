"""Scoped synthetic document retrieval through Judge and Answer."""

import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from skill_loader import freeze


def plan(tool=None, arguments=None, *, ready=False):
    return {
        "intents": ["search"], "filters": {},
        "plan": [] if ready else [{"tool": tool, "arguments": arguments or {},
                                     "depends_on": [], "reason": "synthetic E2E"}],
        "needs_skills": [], "clarification": None,
        "decision": "ready_for_judge" if ready else "execute",
        "stage": "incident" if tool == "find_incidents" else "tools",
        "search_mode": "sql_exact" if tool == "find_incidents" else "none", "limitations": [],
    }


class DocumentRetrievalCompletenessE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        settings = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / "demo.yaml")
        data = copy.deepcopy(settings.data)
        data["paths"].update(data_root=str(root), golden_file=str(root / "golden.jsonl"))
        data["database"]["sqlite_file"] = str(root / "incidents.sqlite")
        data["meetings"]["sqlite_file"] = str(root / "meetings.sqlite")
        data["mes_reference"]["synthetic_sqlite"]["filter_columns"] = {"__test_disabled": "__test_disabled"}
        data["retrieval"]["engineer_notes"].update(enabled=True, top_k=5)
        data["retrieval"]["internal_documents"].update(enabled=True, top_k=5)
        self.settings = Settings(data, ())
        generate(self.settings)
        lock = root / "release.lock.json"
        self.settings.data["paths"]["skill_lock_file"] = str(lock)
        freeze(settings=self.settings)

        self.documents_db = root / "documents.sqlite"
        with closing(sqlite3.connect(self.documents_db)) as db:
            db.execute("CREATE TABLE synthetic_chunks (source_kind TEXT, document_id TEXT, chunk_id TEXT, version TEXT, text TEXT, source_ref TEXT, locator TEXT, status TEXT, available_at TEXT, incident_ids TEXT, relation TEXT, score REAL, observed_at TEXT, effective_from TEXT, effective_to TEXT, applicability TEXT)")
            for source_kind in ("engineer_notes", "internal_documents"):
                db.execute("INSERT INTO synthetic_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    source_kind, "SYN-DOC-1", "SYN-CHUNK-1", "v1", "Synthetic prior incident note.",
                    "synthetic://document/1", "chunk:1", "active", "2026-03-01T00:00:00+09:00",
                    json.dumps(["SYN-INCIDENT-ID"]), "direct", 1.0, None, None, None, None))
            db.commit()

    def _run_case(self, source_kind, metadata, *, no_match=False):
        tool = "search_engineer_notes" if source_kind == "engineer_notes" else "search_internal_documents"
        callback_calls = []
        callback_validation = []

        def callback(*, source_kind, actor, incident_ids, historical_incident_ids,
                     as_of, query, top_k):
            callback_calls.append({"source_kind": source_kind, "actor": actor,
                                   "incident_ids": list(incident_ids), "as_of": as_of,
                                   "query": query, "top_k": top_k})
            with closing(sqlite3.connect(self.documents_db)) as db:
                rows = db.execute("SELECT document_id, chunk_id, version, text, source_ref, locator, status, available_at, incident_ids, relation, score, observed_at, effective_from, effective_to, applicability FROM synthetic_chunks WHERE source_kind=?",
                                  (source_kind,)).fetchall()
            items = [] if no_match else [{
                "document_id": row[0], "chunk_id": row[1], "version": row[2], "text": row[3],
                "source_ref": row[4], "locator": row[5], "status": row[6], "available_at": row[7],
                "incident_ids": list(incident_ids), "relation": row[9], "score": row[10],
                "observed_at": row[11], "effective_from": row[12], "effective_to": row[13],
                "applicability": row[14],
            } for row in rows]
            response = {"status": "NO_MATCH" if no_match else "OK", "retrieval_method": "bm25_vector_hybrid",
                        "as_of": as_of, "items": items, **metadata}
            from document_evidence_contract import validate_hybrid_response
            try:
                validate_hybrid_response(response, source_kind=source_kind, incident_ids=incident_ids,
                    as_of=as_of, timezone_name="Asia/Seoul", top_k=top_k,
                    historical_incident_ids=historical_incident_ids, allowed_statuses=["active"])
            except Exception as exc:
                callback_validation.append(repr(exc))
            return response

        steps = [
            ("router", plan("find_incidents", {"incident_number": "SYN-2026-01"})),
            ("router", plan(tool, {"query": "synthetic prior incident"})),
            ("router", plan(ready=True)),
            ("judge", lambda payload: {"verdict": "pass", "return_to": "answer",
                "coverage": [{"requirement": payload["question"], "status": "satisfied",
                              "evidence_ids": payload["evidence_ids"]}], "issues": []}),
            ("answer", lambda payload: {"status": "answered", "answer": "Synthetic answer.",
                "claims": [{"claim_id": "c1", "text": "Synthetic evidence reviewed.",
                            "evidence_ids": payload["evidence_ids"]}], "limitations": []}),
        ]
        class Client:
            def __init__(self):
                self.calls = []
                self.steps = list(steps)
                self.index = 0

            def call(self, role, system_prompt, payload, history):
                while role != "router" and self.steps[self.index][0] == "router":
                    self.index += 1
                expected, output = self.steps[self.index]
                if role == "router" and expected != "router":
                    output = plan(ready=True)
                    expected = "router"
                else:
                    self.index += 1
                if role != expected:
                    raise AssertionError((role, expected))
                self.calls.append((role, copy.deepcopy(payload)))
                value = output(payload) if callable(output) else output
                call_id = "synthetic-call" if role == "router" else None
                if role == "router":
                    history.append({"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
                        "function": {"name": "submit_plan", "arguments": json.dumps(value)}}]})
                return value, call_id

        client = Client()
        with patch.object(agent, "RoleClient", return_value=client):
            result = agent.run(self.settings, "선택 사고와 관련된 과거 문서를 찾아줘", "synthetic-user",
                               as_of="2026-03-31", document_query=callback,
                               document_allowed_statuses={source_kind: ["active"]})
        return result, client, callback_calls, callback_validation

    def test_scoped_documents_flow_through_review_judge_answer_and_caveats(self):
        for source_kind in ("engineer_notes", "internal_documents"):
            for metadata, expected_truncated, expected_count, expected_limitations in (
                ({"truncated": True, "candidate_count": 7}, True, 7,
                 [agent.DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED_LIMITATION]),
                ({}, None, None, [agent.DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN_LIMITATION]),
            ):
                with self.subTest(source_kind=source_kind, metadata=metadata):
                    result, client, calls, callback_validation = self._run_case(source_kind, metadata)
                    self.assertEqual(result["status"], "answered", {
                        "status": result["status"], "limitations": result.get("limitations"),
                        "callback_calls": calls,
                        "callback_validation": callback_validation,
                        "tool_errors": [event for event in result.get("events", [])
                                        if event.get("event") == "validation_or_tool_error"],
                    })
                    self.assertEqual(callback_validation, [])
                    roles = [role for role, _ in client.calls]
                    self.assertGreaterEqual(roles.count("router"), 3)
                    self.assertEqual(roles[-2:], ["judge", "answer"])
                    self.assertTrue(calls[0]["incident_ids"])
                    self.assertEqual(calls[0]["as_of"], "2026-03-31")
                    self.assertEqual(calls[0]["source_kind"], source_kind)
                    evidence = result["evidence"][-1]
                    self.assertEqual(evidence["result"]["incident_ids"], calls[0]["incident_ids"])
                    self.assertEqual(evidence["result"]["items"][0]["document_id"], "SYN-DOC-1")
                    self.assertEqual(evidence["result"]["source_reported_truncated"], expected_truncated)
                    self.assertEqual(evidence["result"]["source_reported_candidate_count"], expected_count)
                    self.assertEqual(evidence["review_metadata"]["document_retrieval"][
                        "source_reported_truncated"], expected_truncated)
                    self.assertEqual(evidence["review_metadata"]["document_retrieval"][
                        "source_reported_candidate_count"], expected_count)
                    self.assertIn("historical_candidate_not_current_scope", evidence["result"]["limitations"])
                    answer_payload = client.calls[-1][1]
                    self.assertTrue(answer_payload["evidence_review"]["records"])
                    self.assertEqual(answer_payload["evidence_review"]["records"][-1]["document_id"],
                                     "SYN-DOC-1")
                    self.assertTrue(set(expected_limitations).issubset(result["system_limitations"]))

                    # Revalidating an already-normalized callback result is idempotent.
                    from document_evidence_contract import validate_hybrid_response
                    normalized = evidence["result"]
                    again = validate_hybrid_response(normalized, source_kind=source_kind,
                        incident_ids=calls[0]["incident_ids"], as_of="2026-03-31", timezone_name="Asia/Seoul",
                        top_k=5, allowed_statuses=["active"])
                    self.assertEqual(again["source_reported_truncated"], expected_truncated)
                    self.assertEqual(again["source_reported_candidate_count"], expected_count)

    def test_no_match_keeps_unknown_completeness_and_does_not_claim_exhaustive_absence(self):
        result, client, calls, validation = self._run_case("internal_documents", {}, no_match=True)
        evidence = result["evidence"][-1]
        self.assertEqual(evidence["result"]["status"], "NO_MATCH")
        self.assertEqual(evidence["result"]["items"], [])
        self.assertEqual(evidence["result"]["retrieval_completeness"], "unknown")
        self.assertIn(agent.DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN_LIMITATION,
                      result["system_limitations"])
        self.assertNotIn("자료가 없습니다", result["answer"])
        self.assertTrue(client.calls[-2][1].get("evidence_ids"))
        self.assertTrue(calls[0]["incident_ids"])
        self.assertEqual(validation, [])


if __name__ == "__main__":
    unittest.main()
