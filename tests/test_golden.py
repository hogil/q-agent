"""Repeatable contract tests for the offline golden evaluator."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import demo_data
import golden
from config_loader import DEFAULT_CONFIG, load_config


def _case(**changes):
    value = {
        "id": "case-1", "synthetic": True, "split": "dev", "group_id": "group-1",
        "question": "질문", "request_scope": "independent", "as_of": "2026-03-31",
        "selected_incident_ids": [],
        "expected": {"status": "answered", "incident_ids": [], "required_chunk_ids": ["chunk-1"],
                     "forbidden_chunk_ids": [], "required_tools": ["search_meeting_minutes"],
                     "forbidden_tools": [], "answer_facts": ["fact"], "reference_answer": "답"},
        "retrieval": {"incident_number": None, "query": "검색"},
    }
    value.update(changes)
    return value


class GoldenFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        overlay = Path(self.temp.name) / "demo-test.yaml"
        root = self.temp.name.replace("\\", "/")
        overlay.write_text("environment: demo\npaths:\n  data_root: " + root + "\nmeetings:\n  enabled: true\n", encoding="utf-8")
        self.settings = load_config(DEFAULT_CONFIG, overlay)
        self.generated = demo_data.generate(self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def test_generated_full_dataset_and_fingerprint(self):
        self.assertGreaterEqual(self.generated["counts"]["golden_cases"], 12)
        with patch.object(golden, "compile_prompt", return_value=None):
            report = golden.evaluate(self.settings, split="dev", mode="retrieval")
        golden_path = Path(self.generated["paths"]["golden"])
        dev_count = sum(1 for line in golden_path.read_text(encoding="utf-8").splitlines()
                        if line.strip() and json.loads(line)["split"] == "dev")
        self.assertEqual(report["aggregate"]["total"], dev_count)
        self.assertEqual(report["aggregate"]["failed"], 0)
        self.assertTrue(report["corpus_fingerprint"]["captured"])
        self.assertEqual(len(report["corpus_fingerprint"]["files"]), 2)

    def test_same_incident_cannot_use_multiple_groups(self):
        first = _case(request_scope="incident", group_id="g1", retrieval={"incident_number": "I-1", "query": "q"},
                      expected={"status": "answered", "incident_ids": ["i1"], "required_chunk_ids": [],
                                "forbidden_chunk_ids": [], "required_tools": [], "forbidden_tools": [],
                                "answer_facts": [], "reference_answer": ""})
        second = json.loads(json.dumps(first))
        second.update(id="case-2", group_id="g2")
        with self.assertRaisesRegex(ValueError, "crosses groups"):
            golden._validate([first, second])

    def test_missing_positive_retrieval_proposes_search_fix_not_answer_memorization(self):
        records, _ = golden._load(self.settings.data['paths']['golden_file'])
        record = next(r for r in records if r['split'] == 'dev' and r['expected']['required_chunk_ids'])
        record['retrieval']['query'] = 'SYNTHETIC_NO_MATCH_TOKEN'
        case = golden._retrieval_case(self.settings, record)
        self.assertFalse(case['passed'])
        self.assertIn('REQUIRED_CHUNK_MISSING', case['failures'])
        proposal = golden.propose({'split': 'dev', 'mode': 'retrieval', 'cases': [case]})
        self.assertEqual(proposal['status'], 'review_required')
        self.assertEqual(proposal['proposals'][0]['target'], 'retrieval/config')

    def test_required_chunk_cannot_cross_splits_without_incident_id(self):
        first = _case()
        second = json.loads(json.dumps(first))
        second.update(id="case-2", split="test", group_id="group-2")
        with self.assertRaisesRegex(ValueError, "required chunk crosses splits"):
            golden._validate([first, second])

    def test_contradictory_constraints_are_rejected(self):
        value = _case(expected={"status": "answered", "incident_ids": [], "required_chunk_ids": ["c"],
                               "forbidden_chunk_ids": ["c"], "required_tools": [], "forbidden_tools": [],
                               "answer_facts": [], "reference_answer": ""})
        with self.assertRaisesRegex(ValueError, "contradictory chunks"):
            golden._validate([value])

    def test_live_nested_chunks_route_and_semantic_review(self):
        module = types.ModuleType("agent")

        def fake_run(*args, emit=None, **kwargs):
            emit({"event": "llm_start", "role": "router"})
            emit({"event": "tool_result", "source": "search_meeting_minutes",
                  "result": {"items": [{"chunk_id": "chunk-1"}]}})
            return {"status": "answered", "request_scope": "independent", "answer": "a synonymous statement",
                    "evidence": [{"result": {"items": [{"chunk_id": "chunk-1"}]}}], "tool_calls": 3}

        module.run = fake_run
        value = _case()
        with patch.dict(sys.modules, {"agent": module}), patch.object(golden, "compile_prompt", return_value=None):
            result = golden._live_case(self.settings, value)
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence_chunk_ids"], ["chunk-1"])
        self.assertEqual(result["tool_calls"], 3)
        self.assertTrue(result["needs_semantic_review"])
        self.assertEqual(result["answer_fact_diagnostics"], ["fact"])

        wrong = _case(request_scope="incident", selected_incident_ids=["i1"],
                      retrieval={"incident_number": "I-1", "query": "q"},
                      expected={"status": "answered", "incident_ids": ["i1"], "required_chunk_ids": [],
                                "forbidden_chunk_ids": [], "required_tools": [], "forbidden_tools": [],
                                "answer_facts": [], "reference_answer": ""})
        with patch.dict(sys.modules, {"agent": module}), patch.object(golden, "compile_prompt", return_value=None):
            wrong_result = golden._live_case(self.settings, wrong)
        self.assertIn("ROUTE_MISMATCH", wrong_result["failures"])

    def test_proposal_is_dev_only_and_retrieval_never_targets_router(self):
        report = {"split": "dev", "mode": "retrieval", "dataset_sha256": "d", "config_hash": "c",
                  "cases": [{"id": "case-1", "passed": False, "failures": ["INCIDENT_ID_MISMATCH"]}]}
        proposal = golden.propose(report)
        self.assertEqual(proposal["status"], "review_required")
        self.assertEqual(proposal["proposals"][0]["target"], "retrieval/config")
        with self.assertRaisesRegex(ValueError, "nonempty dev"):
            golden.propose({**report, "split": "test"})
        with self.assertRaisesRegex(ValueError, "nonempty dev"):
            golden.propose({"split": "dev", "mode": "retrieval", "cases": []})
        with self.assertRaisesRegex(ValueError, "nonempty dev"):
            golden.propose({"split": "dev", "mode": "unknown", "cases": [{"id": "x"}]})

        live = {**report, "mode": "live", "cases": [{"id": "case-1", "passed": False,
                "failures": ["ROUTE_MISMATCH"]}]}
        live_proposal = golden.propose(live)
        self.assertEqual(live_proposal["proposals"][0]["target"], "router skill")

    def test_lock_verification_happens_before_db_open(self):
        opened = []
        with patch.object(golden, "compile_prompt", side_effect=ValueError("STALE_LOCK")), \
                patch.object(golden, "open_incident_tools", side_effect=lambda settings: opened.append(True)):
            with self.assertRaisesRegex(ValueError, "STALE_LOCK"):
                golden.evaluate(self.settings, split="dev", mode="retrieval", limit=1)
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
