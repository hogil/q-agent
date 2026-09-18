"""Offline golden-set checks for retrieval contracts and reviewed prompt proposals.

This module deliberately does not train models, edit Skills, or write reports.
It measures deterministic retrieval separately from live Router/Judge/Answer runs.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from meeting_tools import MeetingTools
from incident_tools import IncidentTools
from runtime_factory import open_incident_tools
from skill_loader import compile_prompt


_SPLITS = {"train", "dev", "test"}
_STATUSES = {"answered", "partial", "unavailable", "needs_clarification", "needs_selection"}
_REQUIRED_EXPECTED = {
    "status", "incident_ids", "required_chunk_ids", "forbidden_chunk_ids",
    "required_tools", "forbidden_tools", "answer_facts", "reference_answer",
}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_TOKENIZER = "unicode_word_v1"


def _fail(message):
    raise ValueError(message)


def _date(value, label):
    if not isinstance(value, str) or not _ISO.fullmatch(value):
        _fail(f"{label}: ISO date required")
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(f"{label}: invalid ISO date")
    return value


def _strings(value, label, allow_empty=True):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        _fail(f"{label}: nonempty string list required")
    if not allow_empty and not value:
        _fail(f"{label}: must not be empty")
    return value


def _load(path):
    if not isinstance(path, str) or not path:
        _fail("paths.golden_file: path required")
    target = Path(path)
    if not target.is_file():
        _fail("GOLDEN_FILE_MISSING")
    records = []
    try:
        raw = target.read_bytes()
        for line_no, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if line.strip():
                records.append(json.loads(line))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"GOLDEN_FILE_INVALID:{type(exc).__name__}")
    return records, hashlib.sha256(raw).hexdigest()


def _validate(records):
    if not records:
        _fail("GOLDEN_FILE_EMPTY")
    seen, groups, incident_splits, incident_groups, chunk_splits = set(), {}, {}, {}, {}
    for index, record in enumerate(records):
        label = f"golden[{index}]"
        if not isinstance(record, dict):
            _fail(f"{label}: object required")
        for key in ("id", "group_id", "question"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                _fail(f"{label}.{key}: nonempty string required")
        if record["id"] in seen:
            _fail(f"{label}.id: duplicate")
        seen.add(record["id"])
        if record.get("synthetic") is not True and record.get("synthetic") is not False:
            _fail(f"{label}.synthetic: boolean required")
        if record.get("split") not in _SPLITS:
            _fail(f"{label}.split: train/dev/test required")
        if record.get("request_scope") not in ("incident", "independent"):
            _fail(f"{label}.request_scope: incident/independent required")
        _date(record.get("as_of"), f"{label}.as_of")
        if len(record["question"]) > 12000:
            _fail(f"{label}.question: too long")
        retrieval = record.get("retrieval")
        if not isinstance(retrieval, dict) or not isinstance(retrieval.get("query"), str) or not retrieval["query"].strip():
            _fail(f"{label}.retrieval.query: nonempty string required")
        if len(retrieval["query"]) > 12000:
            _fail(f"{label}.retrieval.query: too long")
        number = retrieval.get("incident_number")
        if number is not None and (not isinstance(number, str) or not number.strip()):
            _fail(f"{label}.retrieval.incident_number: string or null required")
        lookup = retrieval.get("lookup")
        if lookup is not None:
            if not isinstance(lookup, dict) or not lookup or number is not None:
                _fail(f"{label}.retrieval.lookup: nonempty object, mutually exclusive with incident_number")
            try:
                inspect.signature(IncidentTools.find_incidents).bind(None, "golden", **lookup)
            except TypeError:
                _fail(f"{label}.retrieval.lookup: unsupported Tool arguments")
        if record["request_scope"] == "incident" and not number and lookup is None:
            _fail(f"{label}.retrieval: incident_number or lookup required for incident scope")
        if record["request_scope"] == "independent" and (number is not None or lookup is not None):
            _fail(f"{label}.retrieval: independent scope cannot have an incident lookup")
        if "category" in record and (not isinstance(record["category"], str) or not record["category"].strip()):
            _fail(f"{label}.category: nonempty string required")
        selected = _strings(record.get("selected_incident_ids"), f"{label}.selected_incident_ids")
        expected = record.get("expected")
        if not isinstance(expected, dict) or not _REQUIRED_EXPECTED.issubset(expected):
            _fail(f"{label}.expected: required fields missing")
        if expected["status"] not in _STATUSES:
            _fail(f"{label}.expected.status: unsupported")
        for key in ("incident_ids", "required_chunk_ids", "forbidden_chunk_ids", "required_tools", "forbidden_tools"):
            _strings(expected[key], f"{label}.expected.{key}")
        for left, right, name in (("required_chunk_ids", "forbidden_chunk_ids", "chunks"),
                                  ("required_tools", "forbidden_tools", "tools")):
            if set(expected[left]).intersection(expected[right]):
                _fail(f"{label}.expected: contradictory {name}")
        if not isinstance(expected["answer_facts"], list) or any(not isinstance(x, str) or not x.strip() for x in expected["answer_facts"]):
            _fail(f"{label}.expected.answer_facts: string list required")
        if not isinstance(expected["reference_answer"], str):
            _fail(f"{label}.expected.reference_answer: string required")
        if record["request_scope"] == "independent" and (selected or expected["incident_ids"]):
            _fail(f"{label}: independent records cannot contain incident IDs")
        if expected["status"] == "needs_selection" and (record["request_scope"] != "incident" or selected
                or len(set(expected["incident_ids"])) < 2 or expected["required_chunk_ids"]):
            _fail(f"{label}: needs_selection requires unselected incident candidates and no required chunks")
        for incident_id in set(selected) | set(expected["incident_ids"]):
            previous = incident_splits.setdefault(incident_id, record["split"])
            if previous != record["split"]:
                _fail(f"{label}: incident ID crosses splits: {incident_id}")
            previous_group = incident_groups.setdefault(incident_id, record["group_id"])
            if previous_group != record["group_id"]:
                _fail(f"{label}: incident ID crosses groups: {incident_id}")
        for chunk_id in expected["required_chunk_ids"]:
            previous = chunk_splits.setdefault(chunk_id, record["split"])
            if previous != record["split"]:
                _fail(f"{label}: required chunk crosses splits: {chunk_id}")
        groups.setdefault(record["group_id"], set()).add(record["split"])
    # A group is the leakage boundary. Every group must have one split only.
    leaked = [group for group, splits in groups.items() if len(splits) != 1]
    if leaked:
        _fail("GROUP_CROSSES_SPLITS:" + ",".join(sorted(leaked)))


def _config_meta(settings):
    data = getattr(settings, "data", {})
    paths = data.get("paths", {})
    lock = Path(paths["skill_lock_file"])
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None
    roles = {}
    for role in ("router", "judge", "answer"):
        try:
            roles[role] = settings.model_profile(role)["deployment"]["served_model"]
        except (AttributeError, KeyError, TypeError):
            roles[role] = None
    environment = data.get("environment")
    corpus = {"captured": False, "reason": "only local demo/test SQLite sources are fingerprinted"}
    if (environment in ("demo", "test") and data.get("database", {}).get("dialect") == "sqlite"
            and data.get("meetings", {}).get("backend") == "sqlite"):
        files = {}
        for key in ("database", "meetings"):
            value = data.get(key, {}).get("sqlite_file")
            target = Path(value) if isinstance(value, str) else None
            if target and target.is_file():
                files[key] = hashlib.sha256(target.read_bytes()).hexdigest()
        corpus = {"captured": True, "files": files}
    return {
        "config_hash": getattr(settings, "config_hash", None),
        "release": json.loads(lock.read_text(encoding="utf-8"))["release"] if lock.is_file() else None,
        "skill_lock_sha256": lock_hash,
        "models": roles,
        "prompt_examples": bool(data.get("runtime", {}).get("prompt_examples", False)),
        "corpus_fingerprint": corpus,
    }


def _case_base(record):
    return {"id": record["id"], "group_id": record["group_id"], "passed": False,
            "category": record.get("category", "unspecified"),
            "failures": [], "llm_calls": 0, "tool_calls": 0, "seconds": 0.0}


def token_recall(reference, answer):
    """Clipped unigram recall; additional answer tokens never reduce the score."""
    if not isinstance(reference, str) or (answer is not None and not isinstance(answer, str)):
        _fail("token_recall requires a string reference and string/null answer")
    def counts(text):
        return Counter(_WORD.findall(unicodedata.normalize("NFC", text).casefold()))
    expected = counts(reference)
    total = sum(expected.values())
    score = {"value": None, "matched_tokens": None, "reference_tokens": total,
             "tokenizer": _TOKENIZER, "unscored_reason": None}
    if not total:
        score["unscored_reason"] = "empty_reference"
    elif answer is None:
        score["unscored_reason"] = "answer_unavailable"
    else:
        overlap = sum((expected & counts(answer)).values())
        score.update(value=overlap / total, matched_tokens=overlap)
    return score


def _answer_metrics(cases):
    values = [case["token_recall"]["value"] for case in cases if case["token_recall"]["value"] is not None]
    mean = sum(values) / len(values) if values else None
    return {"token_recall": mean if len(values) == len(cases) else None,
            "scored_case_token_recall": mean, "token_recall_scored_cases": len(values),
            "token_recall_unscored_cases": len(cases) - len(values)}


def _compare_retrieval(record, db_result, meeting_result, case):
    expected = record["expected"]
    actual_incidents = {row.get("incident_id") for row in db_result.get("data", []) if isinstance(row, dict)}
    expected_incidents = set(expected["incident_ids"])
    if record["request_scope"] == "incident" and actual_incidents != expected_incidents:
        case["failures"].append("INCIDENT_ID_MISMATCH")
    chunks = {item.get("chunk_id") for item in meeting_result.get("items", []) if isinstance(item, dict)}
    if not set(expected["required_chunk_ids"]).issubset(chunks):
        case["failures"].append("REQUIRED_CHUNK_MISSING")
    if chunks.intersection(expected["forbidden_chunk_ids"]):
        case["failures"].append("FORBIDDEN_CHUNK_PRESENT")
    case["retrieved_incident_ids"] = sorted(actual_incidents)
    case["retrieved_chunk_ids"] = sorted(chunks)
    required = set(expected["required_chunk_ids"])
    case["required_chunk_count"] = len(required)
    case["required_chunk_hits"] = len(required.intersection(chunks))
    case["forbidden_chunk_hits"] = len(chunks.intersection(expected["forbidden_chunk_ids"]))
    case["unmeasured"] = ["expected.status", "expected.answer_facts", "Router/Answer accuracy"]


def _retrieval_case(settings, record, query_source="annotated"):
    case = _case_base(record)
    case.update(required_chunk_count=len(set(record["expected"]["required_chunk_ids"])),
                required_chunk_hits=0, forbidden_chunk_hits=0)
    started = time.monotonic()
    db_result = {"data": []}
    actual_ids = None
    trace = []
    try:
        if record["request_scope"] == "incident":
            with open_incident_tools(settings) as db:
                trace.append("find_incidents")
                arguments = record["retrieval"].get("lookup") or {"incident_number": record["retrieval"].get("incident_number")}
                lookup = db.find_incidents("golden", **arguments)
                needs_selection = len(lookup.get("data", [])) > 1 and not record["selected_incident_ids"]
                if needs_selection or record["expected"]["status"] == "needs_selection":
                    _compare_retrieval(record, lookup, {"items": []}, case)
                    case["status"] = "needs_selection" if needs_selection else "selection_not_required"
                    if not needs_selection or record["expected"]["status"] != "needs_selection":
                        case["failures"].append("NEEDS_SELECTION" if needs_selection else "STATUS_MISMATCH")
                    case["tool_trace"] = trace
                    case["tool_calls"] = len(trace)
                    case["unmeasured"] = ["expected.required_tools",
                                          "expected.forbidden_tools", "expected.answer_facts",
                                          "Router/Judge/Answer accuracy"]
                    case["passed"] = not case["failures"]
                    case["seconds"] = round(time.monotonic() - started, 6)
                    return case
                if record["selected_incident_ids"]:
                    selected = db.select_incidents("golden", lookup["scope_id"], record["selected_incident_ids"])
                    actual_ids = list(db._scope("golden", selected["scope_id"])["ids"])
                    db_result = {**lookup, "data": [row for row in lookup.get("data", []) if row.get("incident_id") in actual_ids]}
                else:
                    db_result = lookup
                    actual_ids = [row.get("incident_id") for row in lookup.get("data", [])]
        meeting = MeetingTools(settings)
        trace.append("search_meeting_minutes")
        query = record["question"] if query_source == "question" else record["retrieval"]["query"]
        meeting_result = meeting.search("golden", query,
                                        incident_ids=actual_ids if record["request_scope"] == "incident" else None,
                                        as_of=record["as_of"])
        _compare_retrieval(record, db_result, meeting_result, case)
        case["query_match"] = meeting_result.get("query_match")
        case["tool_trace"] = trace
        case["unmeasured"] = ["expected.status", "expected.required_tools",
                              "expected.forbidden_tools", "expected.answer_facts",
                              "Router/Judge/Answer accuracy"]
    except Exception as exc:
        case["failures"].append(type(exc).__name__)
    case["tool_trace"] = trace
    case["tool_calls"] = len(trace)
    case["passed"] = not case["failures"]
    case["seconds"] = round(time.monotonic() - started, 6)
    return case


def _live_case(settings, record):
    case = _case_base(record)
    case["token_recall"] = token_recall(record["expected"]["reference_answer"], None)
    started = time.monotonic()
    events = []
    result = None
    try:
        from agent import run
        result = run(settings, record["question"], "golden", request_scope="auto",
                     selected=record["selected_incident_ids"], as_of=record["as_of"], emit=events.append)
        case["token_recall"] = token_recall(record["expected"]["reference_answer"], result.get("answer"))
        case["answer"] = result.get("answer")
        evidence = result.get("evidence", [])
        chunk_ids = [item.get("chunk_id") for e in evidence
                     if isinstance(e.get("result"), dict)
                     for item in e["result"].get("items", [])
                     if isinstance(item, dict) and item.get("chunk_id")]
        incident_ids = [row.get("incident_id") for e in evidence
                        if isinstance(e.get("result"), dict)
                        for row in e["result"].get("data", [])
                        if isinstance(row, dict) and row.get("incident_id")]
        case.update({"status": result.get("status"), "request_scope": result.get("request_scope"),
                     "tool_trace": [e.get("source") for e in events if e.get("event") == "tool_result"],
                     "evidence_chunk_ids": sorted(set(chunk_ids)),
                     "evidence_incident_ids": sorted(set(incident_ids))})
        if result.get("request_scope") != record["request_scope"]:
            case["failures"].append("ROUTE_MISMATCH")
        expected = record["expected"]
        if result.get("status") != expected["status"]:
            case["failures"].append("STATUS_MISMATCH")
        trace = set(case["tool_trace"])
        if not set(expected["required_tools"]).issubset(trace):
            case["failures"].append("REQUIRED_TOOL_MISSING")
        if trace.intersection(expected["forbidden_tools"]):
            case["failures"].append("FORBIDDEN_TOOL_USED")
        if record["request_scope"] == "incident" and set(case["evidence_incident_ids"]) != set(expected["incident_ids"]):
            case["failures"].append("INCIDENT_ID_MISMATCH")
        chunks = set(case["evidence_chunk_ids"])
        if not set(expected["required_chunk_ids"]).issubset(chunks):
            case["failures"].append("REQUIRED_CHUNK_MISSING")
        if chunks.intersection(expected["forbidden_chunk_ids"]):
            case["failures"].append("FORBIDDEN_CHUNK_PRESENT")
        case["answer_fact_diagnostics"] = [fact for fact in expected["answer_facts"]
                                             if fact not in str(result.get("answer", ""))]
        # Literal overlap cannot establish semantic correctness, even when complete.
        case["needs_semantic_review"] = True
    except Exception as exc:
        case["failures"].append(type(exc).__name__)
    case["llm_calls"] = sum(1 for event in events if event.get("event") == "llm_start")
    reported_calls = result.get("tool_calls") if isinstance(result, dict) else None
    case["tool_calls"] = reported_calls if type(reported_calls) is int and reported_calls >= 0 else sum(
        1 for event in events if event.get("event") == "tool_result")
    case["passed"] = not case["failures"]
    case["seconds"] = round(time.monotonic() - started, 6)
    return case


def evaluate(settings, split="dev", mode="retrieval", limit=None, query_source="annotated"):
    """Return a JSON-serializable report; this function never writes files."""
    if split not in _SPLITS:
        _fail("split must be train, dev, or test")
    if mode not in ("retrieval", "live"):
        _fail("mode must be retrieval or live")
    if query_source not in ("annotated", "question") or (mode == "live" and query_source != "annotated"):
        _fail("query_source is annotated/question for retrieval only; live always uses the question")
    if limit is not None and (type(limit) is not int or limit <= 0):
        _fail("limit must be a positive integer")
    records, dataset_hash = _load(settings.data["paths"]["golden_file"])
    _validate(records)
    # Compile against the locked Skill release before opening any data source.
    compile_prompt("router", [], settings=settings)
    selected = [item for item in records if item["split"] == split]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        _fail("NO_CASES_SELECTED")
    meta = _config_meta(settings)
    cases = [(_retrieval_case(settings, item, query_source) if mode == "retrieval" else _live_case(settings, item))
             for item in selected]
    return {"schema_version": 2, "split": split, "mode": mode,
            "query_source": query_source if mode == "retrieval" else "question",
            "synthetic": all(item["synthetic"] for item in selected),
            "dataset_sha256": dataset_hash, **meta,
            **({"primary_metric": {"name": "token_recall", "aggregation": "macro",
                                   "higher_is_better": True, "tokenizer": _TOKENIZER}} if mode == "live" else {}),
            "cases": cases,
            "aggregate": {"total": len(cases), "passed": sum(x["passed"] for x in cases),
                           "failed": sum(not x["passed"] for x in cases),
                           "llm_calls": sum(x["llm_calls"] for x in cases),
                           "tool_calls": sum(x["tool_calls"] for x in cases),
                           "seconds": round(sum(x["seconds"] for x in cases), 6),
                           **(_retrieval_metrics(cases) if mode == "retrieval" else _answer_metrics(cases))},
            "limitations": ["Retrieval mode verifies fixture contracts, not LLM quality.",
                            "Incident scope is supplied by annotations; question mode only stress-tests meeting retrieval.",
                            "Required chunks are not exhaustive relevance labels; precision is not measured.",
                            "Token Recall is the primary answer score; extra tokens are not penalized. It is not factual accuracy.",
                            "Tokenizer unicode_word_v1 preserves Korean but does not match morphology or synonyms.",
                            "Literal answer-fact checks are diagnostics, not semantic correctness.",
                            "Synthetic records are preliminary and not expert-validated."]}


def _retrieval_metrics(cases):
    positives = [case for case in cases if case["required_chunk_count"]]
    required = sum(case["required_chunk_count"] for case in cases)
    hits = sum(case["required_chunk_hits"] for case in cases)
    return {"positive_cases": len(positives),
            "positive_cases_complete": sum(case["required_chunk_hits"] == case["required_chunk_count"] for case in positives),
            "required_chunks": required, "required_chunk_hits": hits,
            "required_chunk_recall": hits / required if required else None,
            "forbidden_chunk_hits": sum(case["forbidden_chunk_hits"] for case in cases)}


def compare(baseline, candidate):
    """Pair identical retrieval cases; never approve a deployment from this score."""
    keys = ("schema_version", "split", "mode", "query_source", "dataset_sha256", "config_hash",
            "synthetic", "corpus_fingerprint")
    if any(not isinstance(report, dict) or report.get("schema_version") != 2
           or report.get("mode") != "retrieval" or report.get("synthetic") is not True
           for report in (baseline, candidate)):
        _fail("compare requires version-2 synthetic retrieval reports")
    for key in keys:
        if key not in baseline or baseline[key] != candidate.get(key):
            _fail("REPORTS_NOT_COMPARABLE:" + key)
    corpus = baseline["corpus_fingerprint"]
    if not isinstance(corpus, dict) or not corpus.get("captured") or set(corpus.get("files", {})) != {"database", "meetings"}:
        _fail("compare requires captured synthetic database and meeting fingerprints")
    def indexed(report):
        cases = report.get("cases", [])
        if not cases or len({case["id"] for case in cases}) != len(cases):
            _fail("compare requires nonempty unique cases")
        return {case["id"]: case for case in cases}
    before, after = indexed(baseline), indexed(candidate)
    if before.keys() != after.keys():
        _fail("REPORTS_NOT_COMPARABLE:case_ids")
    improved, regressed = [], []
    for key, old in before.items():
        new = after[key]
        if (old["group_id"], old["required_chunk_count"]) != (new["group_id"], new["required_chunk_count"]):
            _fail("REPORTS_NOT_COMPARABLE:case_contract")
        if ((old["passed"] and not new["passed"]) or new["required_chunk_hits"] < old["required_chunk_hits"]
                or set(new["failures"]) - set(old["failures"]) or new["forbidden_chunk_hits"]):
            regressed.append(key)
        elif (new["passed"] and not old["passed"]) or new["required_chunk_hits"] > old["required_chunk_hits"]:
            improved.append(key)
    return {"schema_version": 1, "split": baseline["split"], "query_source": baseline["query_source"],
            "dataset_sha256": baseline["dataset_sha256"],
            "baseline_release": baseline.get("release"), "candidate_release": candidate.get("release"),
            "status": "regression" if regressed else "review_required" if improved else "no_measured_gain",
            "improved_cases": improved, "regressed_cases": regressed,
            "baseline": _retrieval_metrics(list(before.values())),
            "candidate": _retrieval_metrics(list(after.values())),
            "limitations": ["Synthetic retrieval comparison only; no LLM quality or precision claim.",
                            "Review remaining failures, safety tests and live answers before deployment."]}


def propose(report):
    """Group observed dev failures into human-reviewed, non-mutating proposals."""
    if (not isinstance(report, dict) or report.get("split") != "dev"
            or report.get("mode") not in ("retrieval", "live")
            or not isinstance(report.get("cases"), list) or not report["cases"]):
        _fail("propose requires a nonempty dev retrieval/live report")
    groups = {}
    retrieval = report.get("mode") == "retrieval"
    mapping = {
        "INCIDENT_ID_MISMATCH": (("retrieval/config", "Inspect incident lookup, scope selection, and fixture mapping.") if retrieval else ("router skill", "Inspect scope selection and incident-number disambiguation.")),
        "REQUIRED_TOOL_MISSING": (("retrieval/config", "Inspect the deterministic retrieval trace and configured tool contract.") if retrieval else ("router skill", "Inspect retrieval plan and tool availability contract.")),
        "REQUIRED_CHUNK_MISSING": ("retrieval/config", "Inspect meeting chunk metadata, query terms, and retrieval filters."),
        "FORBIDDEN_CHUNK_PRESENT": ("retrieval/config", "Inspect as_of/status/incident-scope filtering before prompt edits."),
        "STATUS_MISMATCH": ("judge/answer", "Inspect evidence sufficiency and status contract."),
        "ANSWER_FACT_LITERAL_MISSING_DIAGNOSTIC": ("judge/answer", "Review claim grounding; literal matching is only a diagnostic."),
        "FORBIDDEN_TOOL_USED": (("retrieval/config", "Inspect the deterministic retrieval trace and configured tool contract.") if retrieval else ("router skill", "Inspect tool allowlists and request-scope routing.")),
        "ROUTE_MISMATCH": ("router skill", "Inspect Router scope classification and route contract."),
        "TOKEN_RECALL_INCOMPLETE": ("answer/retrieval", "Inspect omitted reference tokens and evidence coverage; preserve useful additions and never copy dev/test answers into Skills."),
    }
    for case in report.get("cases", []):
        failures = list(case.get("failures", []))
        recall = case.get("token_recall", {}).get("value")
        if not retrieval and type(recall) in (int, float) and 0 <= recall < 1:
            failures.append("TOKEN_RECALL_INCOMPLETE")
        for failure in failures:
            target, action = mapping.get(failure, ("code", "Inspect the reported runtime or validation failure."))
            item = groups.setdefault(target, {"target": target, "failure_codes": [], "cases": [], "actions": []})
            if failure not in item["failure_codes"]:
                item["failure_codes"].append(failure)
            if case.get("id") not in item["cases"]:
                item["cases"].append(case["id"])
            if action not in item["actions"]:
                item["actions"].append(action)
    return {"schema_version": 1, "source": {"split": "dev", "mode": report.get("mode"),
                                               "dataset_sha256": report.get("dataset_sha256"),
                                               "config_hash": report.get("config_hash")},
            "status": "no_evidenced_change" if not groups else "review_required",
            "proposals": list(groups.values()),
            "guardrails": ["Inspect retrieval/config before editing prompts.",
                            "Do not copy raw answers or test cases into Skills.",
                            "No source writes or freeze occur here.",
                            "This is prompt/example review, not weight fine-tuning."]}
