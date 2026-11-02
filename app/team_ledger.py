"""In-memory immutable version ledger for structural workflow state only.

ledger_committed means version-recorded, not factually verified, authorized, or causal.
No persistence, execution, LLM, network, or database capability is provided.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, Mapping


class LedgerError(ValueError):
    pass


class RevisionConflict(LedgerError):
    pass


class CompletionConflict(LedgerError):
    pass


class ScopeWideningError(LedgerError):
    pass


STATES = ("proposed", "structurally_validated", "ledger_committed", "stale")


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{label} must be a nonempty string")
    return value


def _revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise LedgerError("expected_revision must be a nonnegative int")
    return value


def _canonical(value: Any) -> str:
    """Validate strict finite JSON data and return deterministic canonical text."""
    def check(item: Any) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise LedgerError("non-finite JSON numbers are not supported")
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise LedgerError("JSON object keys must be strings")
                check(child)
            return
        raise LedgerError(f"unsupported JSON value: {type(item).__name__}")
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class Snapshot:
    revision: int
    evidence: Mapping[str, Any]
    tasks: Mapping[str, Any]
    edges: tuple[tuple[str, str, str], ...]
    scope_revision: int
    scope: Mapping[str, Any]
    dispatch_count: int
    dispatch_limit: int | None


class EvidenceLedger:
    """Thread-safe append-only evidence versions and optimistic task DAG."""

    def __init__(self, *, scope: Mapping[str, Any] | None = None,
                 allowed_scope_refs: tuple[str, ...] = ()) -> None:
        if scope is not None and type(scope) is not dict:
            raise LedgerError("scope must be a JSON object")
        if type(allowed_scope_refs) is not tuple or any(type(v) is not str or not v for v in allowed_scope_refs):
            raise LedgerError("allowed_scope_refs must be a tuple of nonempty strings")
        _canonical(scope or {})
        self._lock = RLock()
        self._revision = 0
        self._scope_revision = 0
        self._scope = deepcopy(scope or {})
        self._allowed_scope_refs = frozenset(allowed_scope_refs)
        self._evidence: dict[str, list[dict[str, Any]]] = {}
        self._tasks: dict[str, dict[str, Any]] = {}
        self._edges: set[tuple[str, str, str]] = set()
        self._attempts: dict[tuple[str, str], dict[str, Any]] = {}
        self._dispatch_count = 0
        self._dispatch_limit: int | None = None

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(self._revision, deepcopy(self._evidence),
                            deepcopy(self._tasks), tuple(sorted(self._edges)),
                            self._scope_revision, deepcopy(self._scope),
                            self._dispatch_count, self._dispatch_limit)

    def _check_revision(self, expected_revision: int) -> None:
        expected_revision = _revision(expected_revision)
        if expected_revision != self._revision:
            raise RevisionConflict(f"expected revision {expected_revision}, current {self._revision}")

    def reserve_dispatch(self, max_calls: int, *, expected_revision: int) -> int:
        """Reserve one callback slot against a run-wide cumulative dispatch limit."""
        if type(max_calls) is not int or max_calls <= 0:
            raise LedgerError("max_calls must be a positive finite int")
        with self._lock:
            self._check_revision(expected_revision)
            if self._dispatch_limit is None:
                self._dispatch_limit = max_calls
            elif max_calls != self._dispatch_limit:
                raise LedgerError("dispatch limit is fixed for the lifetime of this ledger")
            if self._dispatch_count >= self._dispatch_limit:
                raise LedgerError("dispatch budget exhausted")
            self._dispatch_count += 1
            self._revision += 1
            return self._revision

    def add_evidence(self, evidence_id: str, payload: Mapping[str, Any], *,
                     source_version: str, expected_revision: int) -> int:
        evidence_id = _required_string(evidence_id, "evidence_id")
        source_version = _required_string(source_version, "source_version")
        if type(payload) is not dict:
            raise LedgerError("evidence payload must be a JSON object")
        canonical_payload = _canonical(payload)
        with self._lock:
            self._check_revision(expected_revision)
            versions = self._evidence.setdefault(evidence_id, [])
            for record in versions:
                if record["source_version"] == source_version:
                    if record["canonical_payload"] != canonical_payload:
                        raise CompletionConflict("same evidence source_version has different payload")
                    return self._revision
            versions.append({"version": len(versions) + 1,
                             "source_version": source_version,
                             "canonical_payload": canonical_payload,
                             "payload": deepcopy(payload)})
            self._revision += 1
            self._invalidate_evidence_consumers(evidence_id)
            return self._revision

    def add_task(self, task_id: str, *, scope_refs: tuple[str, ...] = (),
                 expected_revision: int) -> int:
        task_id = _required_string(task_id, "task_id")
        if type(scope_refs) is not tuple or any(type(ref) is not str or not ref for ref in scope_refs):
            raise LedgerError("scope_refs must be a tuple of nonempty strings")
        with self._lock:
            self._check_revision(expected_revision)
            if task_id in self._tasks:
                raise LedgerError(f"duplicate task_id: {task_id}")
            if not set(scope_refs).issubset(self._allowed_scope_refs):
                raise ScopeWideningError("task scope_refs exceed issued scope")
            self._tasks[task_id] = {"state": "proposed", "scope_refs": scope_refs,
                                    "attempts": [], "output": None,
                                    "evidence_refs": (), "evidence_pins": {},
                                    "parent_pins": {}, "validated_scope_revision": None,
                                    "validation_revision": None,
                                    "invalidated_by": ()}
            self._revision += 1
            return self._revision

    def add_edge(self, upstream: str, downstream: str, *, kind: str,
                 expected_revision: int) -> int:
        upstream = _required_string(upstream, "upstream")
        downstream = _required_string(downstream, "downstream")
        if type(kind) is not str or kind not in ("data", "control"):
            raise LedgerError("edge kind must be data or control")
        with self._lock:
            self._check_revision(expected_revision)
            if upstream not in self._tasks or downstream not in self._tasks:
                raise LedgerError("edge endpoints must be known task IDs")
            pair = {(source, target) for source, target, _ in self._edges}
            if (upstream, downstream) in pair:
                existing = next(edge[2] for edge in self._edges if edge[:2] == (upstream, downstream))
                if existing != kind:
                    raise LedgerError("a task pair cannot have both data and control edges")
                return self._revision
            edge = (upstream, downstream, kind)
            self._edges.add(edge)
            try:
                self._assert_acyclic()
            except Exception:
                self._edges.remove(edge)
                raise
            self._revision += 1
            if kind == "data":
                self._invalidate_task_descendants(downstream, ("data_dependency_added",))
            return self._revision

    def _assert_acyclic(self) -> None:
        graph: dict[str, list[str]] = {key: [] for key in self._tasks}
        for source, target, _ in self._edges:
            graph[source].append(target)
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                raise LedgerError("task graph cycle")
            if node in visited:
                return
            visiting.add(node)
            for child in graph[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)
        for node in graph:
            visit(node)

    def validate_task(self, task_id: str, *, expected_revision: int,
                      evidence_refs: tuple[str, ...] | None = None) -> int:
        task_id = _required_string(task_id, "task_id")
        if evidence_refs is not None and (type(evidence_refs) is not tuple or
                any(type(ref) is not str or not ref for ref in evidence_refs)):
            raise LedgerError("evidence_refs must be a tuple of nonempty strings")
        with self._lock:
            self._check_revision(expected_revision)
            task = self._task(task_id)
            if task["state"] not in ("proposed", "stale", "ledger_committed"):
                raise LedgerError("task cannot be validated from its current state")
            refs = task["evidence_refs"] if evidence_refs is None else evidence_refs
            pins: dict[str, int] = {}
            for ref in refs:
                versions = self._evidence.get(ref)
                if not versions:
                    raise LedgerError(f"unknown evidence ref: {ref}")
                pins[ref] = versions[-1]["version"]
            parents: dict[str, int | None] = {}
            for source, target, kind in self._edges:
                if target == task_id and kind == "data":
                    parent = self._tasks[source]
                    if parent["state"] != "ledger_committed":
                        raise LedgerError(f"data parent {source} is not committed")
                    parents[source] = self._current_attempt_index(parent)
            task["evidence_refs"] = tuple(refs)
            task["evidence_pins"] = pins
            task["parent_pins"] = parents
            task["validated_scope_revision"] = self._scope_revision
            task["state"] = "structurally_validated"
            task["invalidated_by"] = ()
            self._revision += 1
            task["validation_revision"] = self._revision
            had_attempts = bool(task["attempts"])
            if had_attempts:
                task["state"] = "ledger_committed"
                self._invalidate_task_descendants(task_id, ("parent_revalidation",))
                task["state"] = "structurally_validated"
            return self._revision

    def complete_task(self, task_id: str, attempt_id: str, input_fingerprint: str,
                      output: Any, evidence_refs: tuple[str, ...] | None = None, *,
                      expected_revision: int, validation_revision: int) -> int:
        task_id = _required_string(task_id, "task_id")
        attempt_id = _required_string(attempt_id, "attempt_id")
        input_fingerprint = _required_string(input_fingerprint, "input_fingerprint")
        validation_revision = _revision(validation_revision)
        if evidence_refs is not None and (type(evidence_refs) is not tuple or
                any(type(ref) is not str or not ref for ref in evidence_refs)):
            raise LedgerError("evidence_refs must be a tuple of nonempty strings")
        output_json = _canonical(output)
        frozen_output = json.loads(output_json)
        with self._lock:
            self._check_revision(expected_revision)
            task = self._task(task_id)
            key = (task_id, attempt_id)
            if key in self._attempts:
                prior = self._attempts[key]
                requested_refs = task["evidence_refs"] if evidence_refs is None else evidence_refs
                requested_pins = self._pin_current(requested_refs)
                requested = {"input_fingerprint": input_fingerprint,
                             "output_json": output_json,
                             "evidence_refs": tuple(requested_refs),
                             "evidence_pins": requested_pins,
                             "scope_revision": self._scope_revision,
                             "validation_revision": validation_revision,
                             "parent_pins": self._current_parent_pins(task_id)}
                if prior["identity"] != requested:
                    raise CompletionConflict("attempt replay has different inputs or output")
                if task["state"] != "ledger_committed" or prior["task_commit_index"] != self._current_attempt_index(task):
                    raise CompletionConflict("stale attempt cannot be replayed as a fresh completion")
                if prior["identity"]["validation_revision"] != validation_revision:
                    raise CompletionConflict("attempt replay has a different validation token")
                return self._revision
            if task["state"] != "structurally_validated":
                raise LedgerError("task must be freshly structurally_validated before completion")
            if task["validation_revision"] != validation_revision:
                raise RevisionConflict("completion validation token is stale")
            requested_refs = task["evidence_refs"] if evidence_refs is None else evidence_refs
            requested_pins = self._pin_current(requested_refs)
            if (tuple(requested_refs) != task["evidence_refs"] or
                    requested_pins != task["evidence_pins"] or
                    task["validated_scope_revision"] != self._scope_revision or
                    task["parent_pins"] != self._current_parent_pins(task_id)):
                task["state"] = "stale"
                task["invalidated_by"] = ("validation_pins_changed",)
                self._revision += 1
                raise RevisionConflict("task validation pins changed before completion")
            identity = {"input_fingerprint": input_fingerprint,
                        "output_json": output_json,
                        "evidence_refs": tuple(requested_refs),
                        "evidence_pins": deepcopy(task["evidence_pins"]),
                        "scope_revision": self._scope_revision,
                        "validation_revision": validation_revision,
                        "parent_pins": deepcopy(task["parent_pins"])}
            attempt = {"attempt_id": attempt_id,
                       "input_fingerprint": input_fingerprint,
                       "output": deepcopy(frozen_output),
                       "evidence_refs": tuple(requested_refs),
                       "evidence_pins": deepcopy(task["evidence_pins"]),
                       "scope_revision": self._scope_revision,
                       "validation_revision": validation_revision,
                       "parent_pins": deepcopy(task["parent_pins"])}
            task["attempts"].append(attempt)
            task["output"] = deepcopy(frozen_output)
            task["evidence_refs"] = tuple(requested_refs)
            task["state"] = "ledger_committed"
            task["invalidated_by"] = ()
            self._revision += 1
            self._attempts[key] = {"identity": identity,
                                   "task_commit_index": self._current_attempt_index(task)}
            return self._revision

    def abandon_task(self, task_id: str, reason_code: str, *,
                     expected_revision: int) -> int:
        task_id = _required_string(task_id, "task_id")
        reason_code = _required_string(reason_code, "reason_code")
        if not reason_code.replace("_", "").isalnum():
            raise LedgerError("reason_code must contain only letters, digits, and underscores")
        with self._lock:
            self._check_revision(expected_revision)
            task = self._task(task_id)
            if task["state"] != "structurally_validated":
                raise LedgerError("only an in-flight validated task can be abandoned")
            task["state"] = "ledger_committed"
            self._invalidate_task_descendants(task_id, ("abandoned", reason_code))
            task["state"] = "stale"
            task["invalidated_by"] = ("abandoned", reason_code)
            self._revision += 1
            return self._revision

    def change_scope(self, scope: Mapping[str, Any], *, expected_revision: int) -> int:
        if type(scope) is not dict:
            raise LedgerError("scope must be a JSON object")
        _canonical(scope)
        with self._lock:
            self._check_revision(expected_revision)
            updated = deepcopy(scope)
            if updated == self._scope:
                return self._revision
            self._scope = updated
            self._scope_revision += 1
            for task in self._tasks.values():
                if task["state"] in ("structurally_validated", "ledger_committed"):
                    task["state"] = "stale"
                    task["invalidated_by"] = ("scope_revision",)
            self._revision += 1
            return self._revision

    def _pin_current(self, refs: tuple[str, ...]) -> dict[str, int]:
        pins: dict[str, int] = {}
        for ref in refs:
            versions = self._evidence.get(ref)
            if not versions:
                raise LedgerError(f"unknown evidence ref: {ref}")
            pins[ref] = versions[-1]["version"]
        return pins

    def _current_parent_pins(self, task_id: str) -> dict[str, int]:
        parents: dict[str, int] = {}
        for source, target, kind in self._edges:
            if target == task_id and kind == "data":
                parent = self._tasks[source]
                if parent["state"] != "ledger_committed":
                    raise RevisionConflict(f"data parent {source} is not currently committed")
                parents[source] = self._current_attempt_index(parent)
        return parents

    @staticmethod
    def _current_attempt_index(task: dict[str, Any]) -> int:
        return len(task["attempts"])

    def _invalidate_evidence_consumers(self, evidence_id: str) -> None:
        consumers = {task_id for task_id, task in self._tasks.items()
                     if evidence_id in task["evidence_pins"]}
        self._invalidate_from(consumers, (evidence_id,))

    def _invalidate_task_descendants(self, root: str, reason: tuple[str, ...]) -> None:
        self._invalidate_from({root}, reason)

    def _invalidate_from(self, roots: set[str], reason: tuple[str, ...]) -> None:
        graph: dict[str, list[str]] = {key: [] for key in self._tasks}
        for source, target, kind in self._edges:
            if kind == "data":
                graph[source].append(target)
        affected = set(roots)
        stack = list(roots)
        while stack:
            current = stack.pop()
            for child in graph[current]:
                if child not in affected:
                    affected.add(child)
                    stack.append(child)
        for task_id in affected:
            task = self._tasks[task_id]
            if task["state"] in ("proposed", "structurally_validated", "ledger_committed"):
                task["state"] = "stale"
                task["invalidated_by"] = tuple(reason)

    def _task(self, task_id: str) -> dict[str, Any]:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise LedgerError(f"unknown task_id: {task_id}") from exc
