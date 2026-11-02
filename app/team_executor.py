"""Experimental in-process executor for compiled, caller-supplied callbacks.

This is not a sandbox or service runtime. Callbacks are trusted Python functions;
they receive only task-scoped evidence and committed data-parent outputs.
Thread callbacks cannot be forcibly preempted: deadline_seconds is cooperative,
late output is discarded, and run_team waits for finite callbacks to finish.
Scope/release checks are local consistency guards, not production ACL checks.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.team_graph import ScopeContext, Task, compile_team
from app.team_ledger import EvidenceLedger, LedgerError, RevisionConflict

MAX_PARALLEL_TASKS = 8
MAX_DEADLINE_SECONDS = 300.0


@dataclass(frozen=True)
class TaskInput:
    task_id: str
    scope_refs: tuple[str, ...]
    as_of: str
    evidence: Mapping[str, Any]
    data_parents: Mapping[str, Any]


@dataclass(frozen=True)
class TaskOutcome:
    task_id: str
    status: str
    provider: str | None
    failure_code: str | None = None


@dataclass(frozen=True)
class TeamRunResult:
    outcomes: tuple[TaskOutcome, ...]
    attempted: int
    cached: int
    failed: int
    stale: int
    blocked: int
    elapsed_seconds: float
    provider_usage: None = None


Callback = Callable[[TaskInput], Any]


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strict_json(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_strict_json(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _strict_json(item) for key, item in value.items())
    return False


def _ledger_setup(tasks: Sequence[Task], ledger: EvidenceLedger,
                  context: ScopeContext, release: str) -> None:
    snapshot = ledger.snapshot()
    _check_scope(snapshot, context, release)
    by_id = {task.task_id: task for task in tasks}
    expected_edges = {(source, task.task_id, kind)
                      for task in tasks
                      for kind, deps in (("data", task.data_dependencies),
                                         ("control", task.control_dependencies))
                      for source in deps}
    if set(snapshot.tasks) - set(by_id):
        raise LedgerError("ledger contains tasks outside this compiled graph")
    revision = snapshot.revision
    for task in tasks:
        if task.task_id not in snapshot.tasks:
            revision = ledger.add_task(task.task_id, scope_refs=tuple(sorted(task.scope_refs)),
                                       expected_revision=revision)
        elif tuple(snapshot.tasks[task.task_id]["scope_refs"]) != tuple(sorted(task.scope_refs)):
            raise LedgerError("ledger task scope differs from compiled task")
    snapshot = ledger.snapshot()
    actual_edges = set(snapshot.edges)
    if actual_edges - expected_edges:
        raise LedgerError("ledger contains edges outside this compiled graph")
    revision = snapshot.revision
    for source, target, kind in sorted(expected_edges - actual_edges):
        revision = ledger.add_edge(source, target, kind=kind, expected_revision=revision)


def _check_scope(snapshot: Any, context: ScopeContext, release: str) -> None:
    scope = snapshot.scope
    expected_refs = list(sorted(context.refs))
    if (scope.get("as_of") != context.as_of or scope.get("release") != release or
            scope.get("refs") != expected_refs):
        raise LedgerError("ledger scope/as_of/release does not match caller context")


def _task_inputs(task: Task, snapshot: Any, context: ScopeContext,
                 provider: str, provider_version: str, release: str) -> tuple[TaskInput, str, tuple[str, ...]]:
    evidence: dict[str, Any] = {}
    evidence_refs = tuple(sorted(pin.ref for pin in task.evidence))
    evidence_identity: dict[str, Any] = {}
    for pin in task.evidence:
        versions = snapshot.evidence.get(pin.ref)
        if not versions:
            raise LedgerError("required evidence is absent from ledger")
        latest = versions[-1]
        if latest["source_version"] != pin.version:
            raise LedgerError("ledger latest evidence source version differs from task pin")
        trusted_available = context.evidence_available_at.get(pin.ref)
        if trusted_available is None:
            raise LedgerError("caller context has no evidence availability attestation")
        record = {"version": latest["version"], "source_version": latest["source_version"],
                  "available_at": trusted_available,
                  "scope_refs": tuple(sorted(context.evidence_scope_refs[pin.ref])),
                  "payload": latest["payload"]}
        evidence[pin.ref] = record
        evidence_identity[pin.ref] = record
    parents: dict[str, Any] = {}
    parent_identity: dict[str, Any] = {}
    for parent_id in sorted(task.data_dependencies):
        record = snapshot.tasks[parent_id]
        if record["state"] != "ledger_committed":
            raise LedgerError("data prerequisite is not committed")
        parents[parent_id] = record["output"]
        parent_identity[parent_id] = {"output": record["output"],
                                      "attempt": len(record["attempts"])}
    task_identity = {"task_id": task.task_id,
                     "required_capabilities": sorted(task.required_capabilities),
                     "scope_refs": sorted(task.scope_refs), "action": task.action,
                     "evidence_refs": evidence_refs,
                     "data_dependencies": sorted(task.data_dependencies),
                     "control_dependencies": sorted(task.control_dependencies)}
    fingerprint = _fingerprint({"task": task_identity, "as_of": context.as_of,
                                "evidence": evidence_identity, "data_parents": parent_identity,
                                "provider": provider, "provider_version": provider_version,
                                "release": release})
    return (TaskInput(task.task_id, tuple(sorted(task.scope_refs)), context.as_of,
                      evidence, parents), fingerprint, evidence_refs)


def _validate_pins(task: Task, snapshot: Any, context: ScopeContext) -> None:
    for pin in task.evidence:
        versions = snapshot.evidence.get(pin.ref)
        if not versions or versions[-1]["source_version"] != pin.version:
            raise LedgerError("ledger latest evidence source version differs from task pin")


def run_team(tasks: Sequence[Task], capabilities: Mapping[str, Sequence[str]],
             context: ScopeContext, budgets: Mapping[str, Any],
             ledger: EvidenceLedger, callbacks: Mapping[str, Callback], *,
             release: str, provider_versions: Mapping[str, str]) -> TeamRunResult:
    """Preflight and execute trusted callbacks with caller-pinned profile versions.

    provider_versions must change whenever the caller changes a callback/profile;
    callable identity or source is deliberately not inferred here.
    """
    started = time.monotonic()
    if (not isinstance(ledger, EvidenceLedger) or not isinstance(callbacks, Mapping) or
            not isinstance(provider_versions, Mapping)):
        raise LedgerError("ledger, callback registry, and trusted provider versions are required")
    if not isinstance(release, str) or not release:
        raise LedgerError("trusted release identifier is required")
    parallel = budgets.get("max_parallel_tasks") if isinstance(budgets, Mapping) else None
    deadline_s = budgets.get("deadline_seconds") if isinstance(budgets, Mapping) else None
    if type(parallel) is not int or not 1 <= parallel <= MAX_PARALLEL_TASKS:
        raise LedgerError("max_parallel_tasks must be an integer from 1 through 8")
    if (type(deadline_s) not in (int, float) or not math.isfinite(deadline_s) or
            not 0 < deadline_s <= MAX_DEADLINE_SECONDS):
        raise LedgerError("deadline_seconds must be finite and in (0, 300]")
    plan = compile_team(tasks, capabilities, context, budgets)
    node_by_id = {node.task_id: node for node in plan.nodes}
    by_id = {task.task_id: task for task in tasks}
    if any(node.provider is None for node in plan.nodes):
        raise LedgerError("every executable task must have a registered provider")
    if any(node.provider not in callbacks or not callable(callbacks[node.provider])
           for node in plan.nodes):
        raise LedgerError("selected provider callback is missing")
    selected_providers = {node.provider for node in plan.nodes}
    if any(not isinstance(provider_versions.get(provider), str) or not provider_versions[provider]
           for provider in selected_providers):
        raise LedgerError("trusted version is required for every selected provider")
    # Check scope and every evidence source before changing the ledger DAG or dispatching.
    snapshot = ledger.snapshot()
    _check_scope(snapshot, context, release)
    if snapshot.dispatch_limit is not None and snapshot.dispatch_limit != budgets["max_shared_calls"]:
        raise LedgerError("shared call budget differs from the fixed ledger limit")
    for task in tasks:
        _validate_pins(task, snapshot, context)
    _ledger_setup(tasks, ledger, context, release)

    statuses: dict[str, str] = {}
    outcomes: dict[str, TaskOutcome] = {}
    attempted = cached = failed = stale = blocked = 0
    deadline = started + float(deadline_s)
    running: dict[Future[Any], tuple[str, TaskInput, str, tuple[str, ...], int]] = {}
    provider_busy: set[str] = set()

    def mark_failure(task_id: str, provider: str, code: str, status: str = "failed") -> None:
        nonlocal failed, stale
        current = ledger.snapshot()
        task_rec = current.tasks[task_id]
        if task_rec["state"] == "structurally_validated":
            try:
                ledger.abandon_task(task_id, code, expected_revision=current.revision)
            except (LedgerError, RevisionConflict):
                status = "stale"
        if status == "stale":
            stale += 1
        else:
            failed += 1
        statuses[task_id] = status
        outcomes[task_id] = TaskOutcome(task_id, status, provider, code)

    with ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="team-worker") as pool:
        while len(statuses) < len(tasks):
            progressed = False
            snapshot = ledger.snapshot()
            for task_id in (node.task_id for node in plan.nodes):
                if task_id in statuses or any(task_id == item[0] for item in running.values()):
                    continue
                task, node = by_id[task_id], node_by_id[task_id]
                deps = (*task.data_dependencies, *task.control_dependencies)
                if any(statuses.get(dep) in {"failed", "stale", "blocked"} for dep in deps):
                    statuses[task_id] = "blocked"
                    outcomes[task_id] = TaskOutcome(task_id, "blocked", node.provider, "prerequisite_failed")
                    blocked += 1
                    progressed = True
                    continue
                if not all(statuses.get(dep) in {"committed", "cached"} for dep in deps):
                    continue
                provider = node.provider
                if provider in provider_busy or len(running) >= parallel or time.monotonic() >= deadline:
                    continue
                try:
                    current = ledger.snapshot()
                    _check_scope(current, context, release)
                    _validate_pins(task, current, context)
                    task_input, fingerprint, refs = _task_inputs(
                        task, current, context, provider, provider_versions[provider], release)
                    rec = current.tasks[task_id]
                    if (rec["state"] == "ledger_committed" and rec["attempts"] and
                            rec["attempts"][-1]["input_fingerprint"] == fingerprint):
                        statuses[task_id] = "cached"
                        outcomes[task_id] = TaskOutcome(task_id, "cached", provider)
                        cached += 1
                        progressed = True
                        continue
                    validation_revision = ledger.validate_task(
                        task_id, evidence_refs=refs, expected_revision=current.revision)
                    reservation_snapshot = ledger.snapshot()
                    ledger.reserve_dispatch(budgets["max_shared_calls"],
                                            expected_revision=reservation_snapshot.revision)
                    input_fp = fingerprint
                    future = pool.submit(callbacks[provider], task_input)
                    running[future] = (task_id, task_input, input_fp, refs, validation_revision)
                    provider_busy.add(provider)
                    attempted += 1
                    progressed = True
                except Exception:
                    mark_failure(task_id, provider, "preflight_or_validation_error", "stale")
                    progressed = True

            if not running and time.monotonic() >= deadline:
                for task_id, node in node_by_id.items():
                    if task_id not in statuses:
                        mark_failure(task_id, node.provider or "", "deadline_exceeded", "failed")
                break
            if not running and not progressed:
                # Unresolved dependencies indicate ledger inconsistency or a blocked graph.
                for task_id, node in node_by_id.items():
                    if task_id not in statuses:
                        statuses[task_id] = "blocked"
                        outcomes[task_id] = TaskOutcome(task_id, "blocked", node.provider, "prerequisite_unavailable")
                        blocked += 1
                break
            if running:
                timeout = max(0.0, deadline - time.monotonic())
                done, _ = wait(tuple(running), timeout=timeout, return_when=FIRST_COMPLETED)
                if not done and time.monotonic() >= deadline:
                    # Thread callbacks cannot be preempted. Wait for completion but discard late results.
                    done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                    expired = True
                else:
                    expired = False
                for future in done:
                    task_id, _inputs, fingerprint, refs, validation_revision = running.pop(future)
                    provider = node_by_id[task_id].provider or ""
                    provider_busy.discard(provider)
                    try:
                        output = future.result()
                    except Exception:
                        mark_failure(task_id, provider, "callback_error")
                        continue
                    if expired or time.monotonic() > deadline:
                        mark_failure(task_id, provider, "deadline_exceeded")
                        continue
                    if type(output) is not dict or not _strict_json(output):
                        mark_failure(task_id, provider, "malformed_result")
                        continue
                    try:
                        current = ledger.snapshot()
                        ledger.complete_task(task_id, uuid.uuid4().hex, fingerprint,
                                             output, refs, expected_revision=current.revision,
                                             validation_revision=validation_revision)
                    except (LedgerError, RevisionConflict):
                        mark_failure(task_id, provider, "stale_result", "stale")
                        continue
                    statuses[task_id] = "committed"
                    outcomes[task_id] = TaskOutcome(task_id, "committed", provider)

    ordered_outcomes = tuple(outcomes[node.task_id] for node in plan.nodes)
    return TeamRunResult(ordered_outcomes, attempted, cached, failed, stale, blocked,
                         time.monotonic() - started)
