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

    def test_token_recall_uses_clipped_multiset_recall(self):
        cases = [
            ("alpha beta", "alpha beta", 1.0, 2),
            ("alpha beta", "alpha beta extra", 1.0, 2),
            ("alpha beta gamma", "alpha extra", 1 / 3, 1),
            ("alpha alpha beta", "alpha alpha alpha", 2 / 3, 2),
        ]
        for reference, answer, value, matched in cases:
            with self.subTest(reference=reference, answer=answer):
                result = golden.token_recall(reference, answer)
                self.assertEqual(result["value"], value)
                self.assertEqual(result["matched_tokens"], matched)
                self.assertEqual(result["reference_tokens"], len(reference.split()))
                self.assertEqual(result["tokenizer"], "unicode_word_v1")
                self.assertIsNone(result["unscored_reason"])

    def test_token_recall_normalizes_unicode_and_preserves_korean(self):
        result = golden.token_recall("Cafe\u0301 한국", "CAFÉ 한국 추가")
        self.assertEqual(result["value"], 1.0)
        self.assertEqual(result["matched_tokens"], 2)
        self.assertEqual(result["reference_tokens"], 2)

    def test_token_recall_marks_empty_reference_and_unavailable_answer(self):
        empty_reference = golden.token_recall("!!!", "anything")
        self.assertIsNone(empty_reference["value"])
        self.assertIsNone(empty_reference["matched_tokens"])
        self.assertEqual(empty_reference["reference_tokens"], 0)
        self.assertEqual(empty_reference["unscored_reason"], "empty_reference")

        empty_answer = golden.token_recall("alpha", "")
        self.assertEqual(empty_answer["value"], 0.0)
        self.assertEqual(empty_answer["matched_tokens"], 0)
        self.assertIsNone(empty_answer["unscored_reason"])

        unavailable = golden.token_recall("alpha", None)
        self.assertIsNone(unavailable["value"])
        self.assertIsNone(unavailable["matched_tokens"])
        self.assertEqual(unavailable["unscored_reason"], "answer_unavailable")

    def test_live_case_scores_actual_answer_without_gold_in_agent_kwargs(self):
        module = types.ModuleType("agent")
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"status": "answered", "request_scope": "independent", "answer": "답 추가",
                    "evidence": [], "tool_calls": 0}

        module.run = fake_run
        record = _case(expected={"status": "answered", "incident_ids": [], "required_chunk_ids": [],
                                "forbidden_chunk_ids": [], "required_tools": [], "forbidden_tools": [],
                                "answer_facts": [], "reference_answer": "답"})
        with patch.dict(sys.modules, {"agent": module}):
            result = golden._live_case(self.settings, record)

        self.assertEqual(result["token_recall"]["value"], 1.0)
        self.assertEqual(result["token_recall"]["matched_tokens"], 1)
        self.assertNotIn("expected", captured["kwargs"])
        self.assertNotIn("reference_answer", captured["kwargs"])
        self.assertNotIn("답", repr(captured["kwargs"]))

    def test_live_evaluate_reports_complete_only_when_all_cases_are_scorable(self):
        def scored_case(settings, record):
            return {"id": record["id"], "group_id": record["group_id"], "passed": True,
                    "failures": [], "llm_calls": 1, "tool_calls": 1, "seconds": 0.0,
                    "token_recall": {"value": 0.5, "matched_tokens": 1, "reference_tokens": 2,
                                     "tokenizer": "unicode_word_v1", "unscored_reason": None}}

        with patch.object(golden, "compile_prompt", return_value=None), \
                patch.object(golden, "_live_case", side_effect=scored_case):
            report = golden.evaluate(self.settings, split="dev", mode="live", limit=2)

        self.assertEqual(report["primary_metric"], {"name": "token_recall", "aggregation": "macro",
                                                     "higher_is_better": True, "tokenizer": "unicode_word_v1"})
        self.assertEqual(report["aggregate"]["token_recall"], 0.5)
        self.assertEqual(report["aggregate"]["scored_case_token_recall"], 0.5)
        self.assertEqual(report["aggregate"]["token_recall_scored_cases"], 2)
        self.assertEqual(report["aggregate"]["token_recall_unscored_cases"], 0)

        call_count = [0]

        def partial_case(settings, record):
            call_count[0] += 1
            case = scored_case(settings, record)
            if call_count[0] == 1:
                return case
            case["token_recall"] = {"value": None, "matched_tokens": None, "reference_tokens": 0,
                                     "tokenizer": "unicode_word_v1", "unscored_reason": "empty_reference"}
            return case

        with patch.object(golden, "compile_prompt", return_value=None), \
                patch.object(golden, "_live_case", side_effect=partial_case):
            report = golden.evaluate(self.settings, split="dev", mode="live", limit=2)

        self.assertIsNone(report["aggregate"]["token_recall"])
        self.assertEqual(report["aggregate"]["scored_case_token_recall"], 0.5)
        self.assertEqual(report["aggregate"]["token_recall_scored_cases"], 1)
        self.assertEqual(report["aggregate"]["token_recall_unscored_cases"], 1)

    def test_retrieval_report_has_no_answer_score_or_primary_metric(self):
        with patch.object(golden, "compile_prompt", return_value=None):
            report = golden.evaluate(self.settings, split="dev", mode="retrieval", limit=1)
        self.assertNotIn("primary_metric", report)
        self.assertNotIn("token_recall", report["aggregate"])
        self.assertTrue(all("token_recall" not in case for case in report["cases"]))

    def test_live_proposal_reviews_incomplete_recall_without_failing_contract(self):
        case = {"id": "case-1", "passed": True, "failures": [],
                "token_recall": {"value": 0.5, "matched_tokens": 1, "reference_tokens": 2,
                                 "tokenizer": "unicode_word_v1", "unscored_reason": None}}
        proposal = golden.propose({"split": "dev", "mode": "live", "cases": [case]})
        self.assertTrue(case["passed"])
        self.assertEqual(proposal["status"], "review_required")
        self.assertEqual(proposal["proposals"][0]["failure_codes"], ["TOKEN_RECALL_INCOMPLETE"])
        self.assertEqual(proposal["proposals"][0]["target"], "answer/retrieval")

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

    def test_compound_lookup_uses_filters_without_annotated_incident_number(self):
        record = copy.deepcopy(demo_data._goldens()[1])
        record["selected_incident_ids"] = []
        record["retrieval"] = {"incident_number": None, "query": "SYN", "lookup": {
            "filters": {"incident_number": "SYN-2026-01", "city": "SYNTH-CITY",
                        "product_generations": {"mode": "all", "values": ["SYN-GEN-A", "SYN-GEN-B"]}}}}
        golden._validate([record])
        result = golden._retrieval_case(self.settings, record)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["retrieved_incident_ids"], ["synthetic-pk-2026-01"])

        record["retrieval"]["lookup"]["filters"]["department"] = "SYN-NONEXISTENT-DEPARTMENT"
        record["retrieval"]["query"] = "교정"
        record["expected"].update(incident_ids=[], required_chunk_ids=[])
        result = golden._retrieval_case(self.settings, record)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["retrieved_chunk_ids"], [])

    def test_expected_selection_compares_candidates_and_stops_before_meetings(self):
        ids = [row["incident_id"] for row in demo_data._incident_rows()]
        record = _case(request_scope="incident", retrieval={"lookup": {"city": "SYNTH-CITY"}, "query": "SYN"},
                       expected={"status": "needs_selection", "incident_ids": ids, "required_chunk_ids": [],
                                 "forbidden_chunk_ids": [], "required_tools": ["find_incidents"],
                                 "forbidden_tools": ["search_meeting_minutes"], "answer_facts": [],
                                 "reference_answer": "사고 선택 필요"})
        golden._validate([record])
        with patch.object(golden, "MeetingTools", side_effect=AssertionError("must not search")):
            result = golden._retrieval_case(self.settings, record)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["status"], "needs_selection")
        self.assertEqual(result["tool_trace"], ["find_incidents"])
        record["expected"]["incident_ids"] = ids[:-1]
        result = golden._retrieval_case(self.settings, record)
        self.assertIn("INCIDENT_ID_MISMATCH", result["failures"])

    def test_lookup_rejects_caller_overrides_and_ambiguous_sources(self):
        for lookup in ({"actor": "other"}, {"scope_id": "other"}, {"unknown": "value"}, {}):
            with self.subTest(lookup=lookup), self.assertRaises(ValueError):
                golden._validate([_case(request_scope="incident", retrieval={"lookup": lookup, "query": "x"})])
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            golden._validate([_case(request_scope="incident", retrieval={"lookup": {"city": "SYNTH-CITY"},
                                                                         "incident_number": "SYN-1", "query": "x"})])
        with self.assertRaisesRegex(ValueError, "independent scope"):
            golden._validate([_case(retrieval={"lookup": {"city": "SYNTH-CITY"}, "query": "x"})])

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
        self.assertEqual(result["token_recall"]["unscored_reason"], "answer_unavailable")
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
