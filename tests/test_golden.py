"""Repeatable contract tests for the offline golden evaluator."""
import copy
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

    def test_query_source_changes_query_input_but_not_dataset(self):
        with patch.object(golden, "compile_prompt", return_value=None):
            annotated = golden.evaluate(self.settings, split="dev", mode="retrieval",
                                        query_source="annotated")
            question = golden.evaluate(self.settings, split="dev", mode="retrieval",
                                       query_source="question")

        self.assertEqual(annotated["query_source"], "annotated")
        self.assertEqual(question["query_source"], "question")
        self.assertEqual(annotated["dataset_sha256"], question["dataset_sha256"])
        self.assertEqual(annotated["corpus_fingerprint"], question["corpus_fingerprint"])
        self.assertEqual([case["id"] for case in annotated["cases"]],
                         [case["id"] for case in question["cases"]])
        records, _ = golden._load(self.settings.data["paths"]["golden_file"])
        positive = next(record for record in records
                        if record["split"] == "dev" and record["expected"]["required_chunk_ids"])
        self.assertNotEqual(positive["question"], positive["retrieval"]["query"])

    def test_live_question_query_source_is_rejected(self):
        with patch.object(golden, "compile_prompt", return_value=None):
            with self.assertRaisesRegex(ValueError, "retrieval only"):
                golden.evaluate(self.settings, split="dev", mode="live", query_source="question")

    def test_no_positive_cases_report_null_recall(self):
        records, _ = golden._load(self.settings.data["paths"]["golden_file"])
        no_positive = []
        for record in records:
            if record["split"] != "dev":
                continue
            value = copy.deepcopy(record)
            value["expected"]["required_chunk_ids"] = []
            no_positive.append(value)
        golden_file = Path(self.temp.name) / "no-positive.jsonl"
        golden_file.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n"
                                         for record in no_positive), encoding="utf-8")
        overlay = Path(self.temp.name) / "no-positive.yaml"
        overlay.write_text(
            "environment: demo\npaths:\n  data_root: "
            + self.temp.name.replace("\\", "/")
            + "\n  golden_file: " + golden_file.as_posix()
            + "\nmeetings:\n  enabled: true\n",
            encoding="utf-8",
        )
        settings = load_config(DEFAULT_CONFIG, overlay)
        with patch.object(golden, "compile_prompt", return_value=None):
            report = golden.evaluate(settings, split="dev", mode="retrieval")
        self.assertEqual(report["aggregate"]["positive_cases"], 0)
        self.assertIsNone(report["aggregate"]["required_chunk_recall"])

    def test_compare_detects_gain_and_regression_when_both_cases_fail(self):
        with patch.object(golden, "compile_prompt", return_value=None):
            baseline = golden.evaluate(self.settings, split="dev", mode="retrieval")
        positive = next(case for case in baseline["cases"] if case["required_chunk_count"])
        baseline["cases"] = [copy.deepcopy(positive)]
        baseline["cases"][0].update(passed=False, failures=["REQUIRED_CHUNK_MISSING"],
                                     required_chunk_hits=0, forbidden_chunk_hits=0)

        gain = copy.deepcopy(baseline)
        gain["cases"][0]["required_chunk_hits"] = 1
        gain_result = golden.compare(baseline, gain)
        self.assertEqual(gain_result["status"], "review_required")
        self.assertEqual(gain_result["improved_cases"], [positive["id"]])
        self.assertEqual(gain_result["regressed_cases"], [])

        regression = copy.deepcopy(baseline)
        regression["cases"][0]["forbidden_chunk_hits"] = 1
        regression_result = golden.compare(baseline, regression)
        self.assertEqual(regression_result["status"], "regression")
        self.assertEqual(regression_result["improved_cases"], [])
        self.assertEqual(regression_result["regressed_cases"], [positive["id"]])

    def test_compare_rejects_report_identity_mismatches(self):
        with patch.object(golden, "compile_prompt", return_value=None):
            baseline = golden.evaluate(self.settings, split="dev", mode="retrieval")
        mismatches = {
            "corpus_fingerprint": {"captured": True, "files": {"database": "x", "meetings": "y"}},
            "dataset_sha256": "different-dataset",
            "config_hash": "different-config",
            "query_source": "question",
        }
        for field, value in mismatches.items():
            with self.subTest(field=field):
                candidate = copy.deepcopy(baseline)
                candidate[field] = value
                with self.assertRaisesRegex(ValueError, "REPORTS_NOT_COMPARABLE:" + field):
                    golden.compare(baseline, candidate)

        candidate = copy.deepcopy(baseline)
        candidate["cases"][0]["id"] = "different-case"
        with self.assertRaisesRegex(ValueError, "REPORTS_NOT_COMPARABLE:case_ids"):
            golden.compare(baseline, candidate)

    def test_remote_sources_and_non_synthetic_reports_cannot_claim_corpus_identity(self):
        self.settings.data["meetings"]["backend"] = "http"
        self.assertFalse(golden._config_meta(self.settings)["corpus_fingerprint"]["captured"])
        self.settings.data["meetings"]["backend"] = "sqlite"
        with patch.object(golden, "compile_prompt", return_value=None):
            report = golden.evaluate(self.settings, split="dev")
        report["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "synthetic retrieval reports"):
            golden.compare(report, report)

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

    def test_live_run_exception_is_reported_without_unbound_result_error(self):
        module = types.ModuleType("agent")

        def failing_run(*args, **kwargs):
            raise RuntimeError("synthetic agent failure")

        module.run = failing_run
        with patch.dict(sys.modules, {"agent": module}):
            result = golden._live_case(self.settings, _case())

        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"], ["RuntimeError"])
        self.assertEqual(result["llm_calls"], 0)
        self.assertEqual(result["tool_calls"], 0)

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
