"""One-shot, local-only smoke runner for one synthetic agent run.

This is a research harness, not production functionality or an ACL boundary.
It creates a disposable demo configuration, incident DB, MES DB and frozen Skill
lock under a fresh temporary directory. It sends synthetic prompts only to the
explicit loopback Ollama endpoint. Running it is opt-in; use --run after review.
This means at most six LLM calls with a 20-second per-call timeout; there is no
strict whole-run wall-clock deadline.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

ENDPOINT = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"
MIN_COMMIT_HEADROOM_GIB = 13.5
MIN_D_FREE_GIB = 20.0
MAX_STEPS = 6
TIMEOUT_SECONDS = 20
AS_OF = "2026-03-31"
INCIDENT_NUMBER = "SYN-2026-01"
EXPECTED_INCIDENT_ID = "synthetic-pk-2026-01"
EXPECTED_FILTERS = {"product": "SYN-PROD-01"}
QUESTION = "SYN-2026-01 사고의 Product 코드 SYN-PROD-01 기준정보를 조회해줘."


def _gib(value: int) -> float:
    return value / (1024 ** 3)


def _classify_busy_processes(samples: dict, current: dict) -> list[dict]:
    """Compare only the same still-running process instance, excluding Windows idle PID 0."""
    busy = []
    for pid, before in samples.items():
        after = current.get(pid)
        if not after or not after.get("is_running"):
            continue
        if pid == 0 or before.get("name", "").casefold() == "system idle process" \
                or after.get("name", "").casefold() == "system idle process":
            continue
        if before.get("create_time") is None or after.get("create_time") is None \
                or before.get("create_time") != after.get("create_time"):
            continue
        delta = after["cpu_seconds"] - before["cpu_seconds"]
        rss = before["rss_bytes"]
        if delta >= 0.5 or (rss >= 2 * 1024 ** 3 and delta >= 0.1):
            busy.append({"pid": pid, "name": before.get("name", ""),
                         "cpu_seconds_delta": round(delta, 3), "rss_gib": round(_gib(rss), 2)})
    return busy


def _process_activity_self_check() -> dict:
    """Synthetic-only checks for idle exclusion, PID reuse and real busy processes."""
    samples = {
        0: {"name": "System Idle Process", "cpu_seconds": 1.0, "rss_bytes": 0, "create_time": 1.0},
        4: {"name": "System", "cpu_seconds": 1.0, "rss_bytes": 0, "create_time": 1.0},
        77: {"name": "Reused PID", "cpu_seconds": 1.0, "rss_bytes": 0, "create_time": 1.0},
        88: {"name": "Exited process", "cpu_seconds": 1.0, "rss_bytes": 0, "create_time": 1.0},
    }
    current = {
        0: {"name": "System Idle Process", "cpu_seconds": 9.0, "rss_bytes": 0, "create_time": 1.0,
            "is_running": True},
        4: {"name": "System", "cpu_seconds": 1.7, "rss_bytes": 0, "create_time": 1.0,
            "is_running": True},
        77: {"name": "Different process", "cpu_seconds": 9.0, "rss_bytes": 0, "create_time": 2.0,
             "is_running": True},
        88: {"name": "Exited process", "cpu_seconds": 9.0, "rss_bytes": 0, "create_time": 1.0,
             "is_running": False},
    }
    busy = _classify_busy_processes(samples, current)
    detected = [row["pid"] for row in busy]
    checks = {
        "idle_pid_zero_excluded": "PASS" if 0 not in detected else "FAIL",
        "system_pid_four_not_ignored_when_busy": "PASS" if 4 in detected else "FAIL",
        "reused_pid_delta_ignored": "PASS" if 77 not in detected else "FAIL",
        "stopped_process_delta_ignored": "PASS" if 88 not in detected else "FAIL",
    }
    return {"checks": checks, "detected_busy_pids": detected}


def _resource_snapshot() -> dict:
    """Read current commit, D: free space, process activity and Ollama model state."""
    import ctypes
    from ctypes import wintypes

    class PERFORMANCE_INFORMATION(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t),
                    ("CommitLimit", ctypes.c_size_t), ("CommitPeak", ctypes.c_size_t),
                    ("PhysicalTotal", ctypes.c_size_t), ("PhysicalAvailable", ctypes.c_size_t),
                    ("SystemCache", ctypes.c_size_t), ("KernelTotal", ctypes.c_size_t),
                    ("KernelPaged", ctypes.c_size_t), ("KernelNonpaged", ctypes.c_size_t),
                    ("PageSize", ctypes.c_size_t), ("HandleCount", wintypes.DWORD),
                    ("ProcessCount", wintypes.DWORD), ("ThreadCount", wintypes.DWORD)]

    perf = PERFORMANCE_INFORMATION()
    perf.cb = ctypes.sizeof(perf)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb):
        raise RuntimeError("PSAPI_COMMIT_QUERY_FAILED")
    headroom = _gib((perf.CommitLimit - perf.CommitTotal) * perf.PageSize)
    d_free = _gib(shutil.disk_usage("D:\\").free)
    # Compare CPU deltas over a bounded observation; do not stop or alter processes.
    import psutil
    samples = {}
    for proc in psutil.process_iter(["pid", "name", "cpu_times", "memory_info", "create_time"]):
        try:
            info = proc.info
            cpu = info.get("cpu_times")
            samples[info["pid"]] = {"name": info.get("name") or "",
                "cpu_seconds": (cpu.user + cpu.system) if cpu else 0.0,
                "rss_bytes": info["memory_info"].rss if info.get("memory_info") else 0,
                "create_time": info.get("create_time")}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(2.0)
    current = {}
    for pid in samples:
        try:
            proc = psutil.Process(pid)
            is_running = proc.is_running()
            create_time = proc.create_time()
            now = proc.cpu_times()
            current[pid] = {"name": proc.name(), "cpu_seconds": now.user + now.system,
                            "create_time": create_time, "is_running": is_running}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    busy = _classify_busy_processes(samples, current)
    # Inspection requests bypass ambient proxies; they never alter Ollama state.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(ENDPOINT + "/api/ps", timeout=3) as response:
            ollama_ps = json.loads(response.read().decode("utf-8"))
        with opener.open(ENDPOINT + "/api/tags", timeout=3) as response:
            tags = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("OLLAMA_LOCAL_INSPECTION_FAILED: " + type(exc).__name__) from None
    models = ollama_ps.get("models", [])
    loaded_conflicts = [m.get("name", "") for m in models]
    matching = [m for m in tags.get("models", []) if m.get("name") == MODEL or m.get("name", "").startswith(MODEL + ":")]
    return {"commit_headroom_gib": round(headroom, 2), "d_free_gib": round(d_free, 2),
            "busy_processes": busy, "ollama_loaded_models": loaded_conflicts,
            "requested_model_present": bool(matching), "requested_model_loaded": any(
                n == MODEL or n.startswith(MODEL + ":") for n in loaded_conflicts)}


def _resource_gate(snapshot: dict) -> list[str]:
    failures = []
    if snapshot["commit_headroom_gib"] < MIN_COMMIT_HEADROOM_GIB:
        failures.append("COMMIT_HEADROOM_BELOW_13_5_GIB")
    if snapshot["d_free_gib"] < MIN_D_FREE_GIB:
        failures.append("D_FREE_BELOW_20_GIB")
    if snapshot["busy_processes"]:
        failures.append("HEAVY_PROCESS_ACTIVITY")
    if snapshot["ollama_loaded_models"]:
        failures.append("OLLAMA_MODEL_ALREADY_LOADED")
    if not snapshot["requested_model_present"]:
        failures.append("REQUESTED_MODEL_NOT_ALREADY_INSTALLED")
    return failures


def _build_fixture(root: Path):
    import agent
    from config_loader import DEFAULT_CONFIG, Settings, load_config
    from demo_data import generate
    from llm_client import RoleClient
    from runtime_factory import open_synthetic_mes_reference
    from skill_loader import freeze
    from unittest.mock import patch

    data_root = root / "data"
    data_root.mkdir(parents=True)
    base = load_config(DEFAULT_CONFIG).data
    base["paths"].update(data_root=str(data_root), output_root=str(root / "output"),
                         model_root=str(root / "models"), image_root=str(data_root / "images"),
                         document_root=str(data_root / "documents"), trend_root=str(data_root / "trends"),
                         cache_root=str(root / "cache"), log_root=str(root / "logs"),
                         skills_root=str(ROOT / "app" / "skills"),
                         dictionary_root=str(ROOT / "app" / "domain-data"),
                         registry_file=str(ROOT / "app" / "skill_registry.json"),
                         skill_lock_file=str(root / "release.lock.json"),
                         terminology_file=str(ROOT / "app" / "domain-data" / "terminology.json"),
                         golden_file=str(root / "golden.jsonl"))
    base["database"].update(dialect="sqlite", sqlite_file=str(data_root / "incidents.sqlite"), read_only=True)
    base["meetings"]["sqlite_file"] = str(data_root / "meetings.sqlite")
    base["models"]["text"].update(enabled=True, mode="api", structured_outputs=False,
        base_url=ENDPOINT + "/v1", api_key_env="QAGENT_LOCAL_OLLAMA_SMOKE_KEY", served_model=MODEL,
        timeout_seconds=TIMEOUT_SECONDS)
    base["runtime"].update(max_agent_steps=MAX_STEPS, max_retries=1, max_tool_calls=4)
    base["mes_reference"] = {"enabled": True, "top_k": 5, "allowed_kinds": ["product"],
        "synthetic_sqlite": {"enabled": True, "database_file": "mes.sqlite", "table": "refs",
            "timezone": "UTC", "columns": {key: key for key in (
                "kind", "record_id", "version", "name", "source_ref", "available_at",
                "effective_from", "effective_to", "applicability", "incident_ids")},
            "filter_columns": {"product": "product_code"}}}
    settings = Settings(base, (str(DEFAULT_CONFIG), "isolated-smoke-overlay"))
    _assert_local_role_endpoints(settings)
    freeze(settings=settings)
    generated = generate(settings, profile="basic", include_goldens=False)
    mes_path = data_root / "mes.sqlite"
    with closing(sqlite3.connect(mes_path)) as db:
        db.execute("CREATE TABLE refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids, product_code)")
        db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            "product", "SYN-MES-01", "v1", "Synthetic Alpha", "synthetic://mes/01",
            "2026-03-01T00:00:00Z", "2026-01-01T00:00:00Z", None, "candidate",
            json.dumps(["synthetic-pk-2026-01"]), "SYN-PROD-01"))
        db.commit()
    settings = Settings(base, (str(DEFAULT_CONFIG), "isolated-smoke-overlay"))
    # Capture only catalog metadata immediately before RoleClient builds/sends
    # its request. No raw payload, question or system prompt is retained here.
    catalog_receipts = []
    original_call = RoleClient.call

    def capture_catalog(self, role, system_prompt, payload, history):
        if role == "router":
            catalog_receipts.append({
                "mes_reference_catalog": payload.get("mes_reference_catalog"),
                "mes_tool_enabled": payload.get("available_tools", {}).get("search_mes_reference", {}).get("enabled"),
                "scope_valid": payload.get("scope_valid"),
            })
        return original_call(self, role, system_prompt, payload, history)

    with patch.object(RoleClient, "call", capture_catalog):
        result = agent.run(settings, QUESTION, "synthetic-smoke-actor", incident_number=INCIDENT_NUMBER, as_of=AS_OF,
                           mes_reference_query=open_synthetic_mes_reference(settings))
    return result, generated, catalog_receipts


def _assert_local_role_endpoints(settings):
    expected = ENDPOINT + "/v1"
    actual = {role: settings.model_profile(role)["deployment"]["base_url"]
              for role in ("router", "judge", "answer")}
    if any(value != expected for value in actual.values()):
        raise RuntimeError("ROLE_ENDPOINT_NOT_EXACT_LOOPBACK")
    return actual


def _checks(result: dict, catalog_receipts: list) -> dict:
    evidence = result.get("evidence", [])
    incidents = [item for item in evidence if item.get("source") == "find_incidents"]
    mes_rows = [item for item in evidence if item.get("source") == "search_mes_reference"]
    confirmed = result.get("final_scope", {}).get("confirmed", {})
    incident_ids = confirmed.get("incident_ids", [])
    mes_result = mes_rows[-1].get("result", {}) if mes_rows else {}
    mes_items = mes_result.get("items", [])
    router_outputs = [item.get("output", {}) for item in result.get("events", [])
                      if item.get("event") == "llm_output" and item.get("role") == "router"]
    planned_mes = [step.get("arguments", {}) for output in router_outputs
                   for step in output.get("plan", []) if step.get("tool") == "search_mes_reference"]
    planned_filters = [args.get("filters") for args in planned_mes if "filters" in args]
    plan_filter_status = ("NOT_OBSERVED" if not planned_filters else
                          "PASS" if planned_filters[-1] == EXPECTED_FILTERS else "FAIL")
    expected_catalog = {"allowed_kinds": ["product"], "allowed_filter_keys": ["product"]}
    enabled_receipts = [receipt for receipt in catalog_receipts if receipt.get("mes_tool_enabled") is True]
    disabled_receipts = [receipt for receipt in catalog_receipts if receipt.get("mes_tool_enabled") is False]
    catalog_status = ("NOT_OBSERVED" if not enabled_receipts else
                      "PASS" if all(receipt.get("mes_reference_catalog") == expected_catalog
                                    for receipt in enabled_receipts) else "FAIL")
    gating_status = ("NOT_OBSERVED" if not catalog_receipts else
                     "PASS" if all(receipt.get("mes_reference_catalog") is None for receipt in disabled_receipts)
                     and all(receipt.get("mes_reference_catalog") == expected_catalog for receipt in enabled_receipts)
                     else "FAIL")
    event_rows = result.get("events", [])
    def first_index(predicate):
        return next((index for index, row in enumerate(event_rows) if predicate(row)), None)
    flow_indices = [
        first_index(lambda row: row.get("event") == "llm_output" and row.get("role") == "router"
                    and any(step.get("tool") == "find_incidents" for step in row.get("output", {}).get("plan", []))),
        first_index(lambda row: row.get("event") == "tool_result" and row.get("source") == "find_incidents"),
        first_index(lambda row: row.get("event") == "llm_output" and row.get("role") == "router"
                    and any(step.get("tool") == "search_mes_reference" for step in row.get("output", {}).get("plan", []))),
        first_index(lambda row: row.get("event") == "tool_result" and row.get("source") == "search_mes_reference"),
        first_index(lambda row: row.get("event") == "llm_output" and row.get("role") == "judge"),
        first_index(lambda row: row.get("event") == "llm_output" and row.get("role") == "answer"),
    ]
    flow_status = ("NOT_OBSERVED" if any(index is None for index in flow_indices) else
                   "PASS" if flow_indices == sorted(flow_indices) and len(set(flow_indices)) == len(flow_indices)
                   else "FAIL")
    incident_row = incidents[-1].get("result", {}) if incidents else {}
    incident_records = [row for row in incident_row.get("data", []) if isinstance(row, dict)]
    checks = {
        "router_incident_mes_judge_answer_order": flow_status,
        "router_pre_transport_catalog_payload": catalog_status,
        "router_catalog_scope_gating": gating_status,
        "router_mes_plan_expected_filter": plan_filter_status,
        "incident_lookup_expected_record": ("NOT_OBSERVED" if not incidents else
            "PASS" if incident_row.get("status") == "OK" and any(
                row.get("incident_id") == EXPECTED_INCIDENT_ID and
                row.get("incident_number") == INCIDENT_NUMBER for row in incident_records) else "FAIL"),
        "selected_incident_scope": ("NOT_OBSERVED" if not confirmed else
            "PASS" if confirmed.get("selected") is True and incident_ids == [EXPECTED_INCIDENT_ID] else "FAIL"),
        "mes_filter_execution_and_evidence": ("NOT_OBSERVED" if not mes_rows else
            "PASS" if mes_result.get("status") == "OK" and mes_result.get("as_of") == AS_OF
            and mes_result.get("incident_ids") == [EXPECTED_INCIDENT_ID]
            and any(row.get("record_id") == "SYN-MES-01" for row in mes_items) else "FAIL"),
        "judge_pass": ("NOT_OBSERVED" if not result.get("judge") else
                       "PASS" if result["judge"].get("verdict") == "pass" else "FAIL"),
        "answer_status": ("PASS" if result.get("status") == "answered" else "FAIL"),
        "as_of_consistent": ("PASS" if result.get("as_of") == AS_OF and
                             (not mes_rows or mes_result.get("as_of") == AS_OF) else "FAIL"),
    }
    return {"checks": checks, "planned_mes_arguments": planned_mes,
            "router_catalog_payload_receipts": catalog_receipts,
            "selected_incident_ids": incident_ids,
            "mes_evidence_incident_ids": mes_result.get("incident_ids"),
            "mes_evidence_as_of": mes_result.get("as_of"),
            "matched_mes_record_ids": [row.get("record_id") for row in mes_items]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="after resource guard, call the local model once")
    args = parser.parse_args()
    if not args.run:
        activity_check = _process_activity_self_check()
        print(json.dumps({"status": "SELF_CHECK_ONLY", "run_required": "--run",
                          "endpoint": ENDPOINT, "model": MODEL, "max_agent_steps": MAX_STEPS,
                          "timeout_seconds": TIMEOUT_SECONDS,
                          "process_activity_self_check": activity_check,
                          "note": "No model call or background task was started."}, ensure_ascii=False))
        return 0 if all(value == "PASS" for value in activity_check["checks"].values()) else 1
    activity_check = _process_activity_self_check()
    if not all(value == "PASS" for value in activity_check["checks"].values()):
        print(json.dumps({"status": "NO_RUN", "process_activity_self_check": activity_check}, ensure_ascii=False))
        return 2
    try:
        snapshot = _resource_snapshot()
    except Exception as exc:
        print(json.dumps({"status": "NO_RUN", "reason": str(exc)}, ensure_ascii=False))
        return 2
    failures = _resource_gate(snapshot)
    if failures:
        print(json.dumps({"status": "NO_RUN", "resource_snapshot": snapshot,
                          "gate_failures": failures,
                          "note": "No process was stopped and no model was unloaded."}, ensure_ascii=False))
        return 2
    # Request direct HTTP client routing. Endpoint checks below still cannot
    # attest server-side forwarding/redirect handling by Ollama or the client.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["QAGENT_LOCAL_OLLAMA_SMOKE_KEY"] = "local-only-placeholder"
    root = Path(tempfile.mkdtemp(prefix="qagent_local_mes_smoke_"))
    try:
        result, generated, catalog_receipts = _build_fixture(root)
        checks = _checks(result, catalog_receipts)
        all_checks_pass = all(value == "PASS" for value in checks["checks"].values())
        print(json.dumps({"status": "PASS" if all_checks_pass else "FAIL",
            "agent_status": result.get("status"), "actor": "synthetic-smoke-actor",
            "incident_number": INCIDENT_NUMBER, "as_of": AS_OF,
            "mes_reference_catalog": {"logical_filter": "product", "synthetic_sqlite_column": "product_code",
                                      "expected_filter": EXPECTED_FILTERS},
            "synthetic_question": QUESTION,
            "synthetic_fixture_and_question_text_audit": {"status": "PASS", "basis": [
                "question is authored from synthetic incident/product identifiers",
                "incident rows come from demo_data.generate(profile=basic)",
                "MES row is inserted by this runner with synthetic:// source_ref"],
                "application_skill_prompt_content": "existing app Skills are compiled and sent to local loopback; their text was not independently audited as synthetic",
                "model_generated_answer_text": "semantic synthetic-only content is not mechanically verified; Judge evidence checks are reported separately"},
            **checks,
            "synthetic_fixture_counts": generated, "events": result.get("events", []),
            "evidence": result.get("evidence", []),
            "answer": result.get("answer"), "limitations": result.get("limitations", []),
            "execution_metrics": result.get("execution_metrics", {}),
            "resource_snapshot": snapshot,
            "scope_note": "One synthetic demo agent run; not production behavior or ACL validation. Resource values are a pre-run snapshot and may change concurrently; the guard cannot stop external work or prevent resource races. HTTP model endpoint is asserted for all roles as exact loopback; server-side forwarding/redirect behavior is not verified."},
            ensure_ascii=False, default=str))
        return 0 if all_checks_pass else 1
    except Exception as exc:
        print(json.dumps({"status": "RUN_ERROR", "error_type": type(exc).__name__,
                          "synthetic_temp_root": str(root)}, ensure_ascii=False))
        return 1
    finally:
        # Preserve the disposable fixture and result trace for review; no app config was changed.
        print(json.dumps({"synthetic_temp_root": str(root)}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
