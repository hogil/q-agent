"""Pure, fail-closed compiler for proposed Team task DAGs.

This module plans only; it never dispatches tools or workers. Scope authority
must arrive as an in-process ScopeContext created by trusted orchestration code.
Serialized task fields and hashes are not evidence of scope rights or truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from types import MappingProxyType
from typing import Mapping, Sequence

MAX_TASKS = 128
MAX_PROVIDERS = 24
MAX_WORKERS = 8
MAX_PROVIDER_SUBSETS = 100_000


class PlanError(ValueError):
    """The proposed graph cannot be safely compiled."""


@dataclass(frozen=True)
class ScopeContext:
    """Caller-attested scope refs; do not construct from model supplied data."""
    refs: frozenset[str]
    evidence_versions: Mapping[str, str]
    evidence_available_at: Mapping[str, str]
    evidence_scope_refs: Mapping[str, frozenset[str]]
    as_of: str
    _issuer: object


_TRUSTED_ISSUER = object()


def trusted_scope_context(refs: Sequence[str],
                          as_of: str,
                          evidence_versions: Mapping[str, str] | None = None,
                          evidence_available_at: Mapping[str, str] | None = None,
                          evidence_scope_refs: Mapping[str, Sequence[str]] | None = None) -> ScopeContext:
    """Create context at a trusted Orchestrator/Adapter boundary only.

    This is an application trust boundary, not production authentication/ACL.
    A Python caller can call this function; untrusted model JSON cannot supply
    this object through the compile_team task packet.
    """
    if isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence) or not refs:
        raise PlanError("trusted scope refs must be a sequence")
    if any(not isinstance(ref, str) or not ref for ref in refs):
        raise PlanError("trusted scope refs must be non-empty strings")
    if evidence_versions is not None and not isinstance(evidence_versions, Mapping):
        raise PlanError("trusted evidence versions must be a mapping")
    if evidence_available_at is not None and not isinstance(evidence_available_at, Mapping):
        raise PlanError("trusted evidence metadata must be mappings")
    versions = dict(evidence_versions or {})
    availability = dict(evidence_available_at or {})
    if evidence_scope_refs is not None and not isinstance(evidence_scope_refs, Mapping):
        raise PlanError("trusted evidence ownership must be a mapping")
    ownership_input = dict(evidence_scope_refs or {})
    if any(not isinstance(values, (list, tuple, set, frozenset)) or not values
           for values in ownership_input.values()):
        raise PlanError("evidence ownership values must be non-empty scope collections")
    if any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
           for mapping in (versions, availability) for k, v in mapping.items()):
        raise PlanError("trusted evidence metadata must contain non-empty strings")
    normalized_as_of = _time(as_of, "caller as_of").isoformat()
    normalized_availability = {key: _time(value, "server evidence availability").isoformat()
                               for key, value in availability.items()}
    normalized_refs = frozenset(refs)
    if len(normalized_refs) == 1:
        sole_ref = next(iter(normalized_refs))
        ownership = {key: frozenset(values) for key, values in ownership_input.items()}
        for evidence_ref in set(versions) | set(availability):
            ownership.setdefault(evidence_ref, frozenset((sole_ref,)))
    else:
        ownership = {key: frozenset(values) for key, values in ownership_input.items()}
        missing = (set(versions) | set(availability)) - set(ownership)
        if missing:
            raise PlanError("multi-scope context requires explicit ownership for every evidence ref")
    if any(not isinstance(key, str) or not key or not refs_for_evidence or
           any(not isinstance(ref, str) or not ref for ref in refs_for_evidence) or
           not refs_for_evidence <= normalized_refs
           for key, refs_for_evidence in ownership.items()):
        raise PlanError("evidence ownership must be non-empty and within trusted scope refs")
    return ScopeContext(frozenset(refs), MappingProxyType(versions),
                        MappingProxyType(normalized_availability), MappingProxyType(ownership), normalized_as_of,
                        _TRUSTED_ISSUER)


@dataclass(frozen=True)
class EvidencePin:
    ref: str
    version: str
    available_at: str
    cutoff: str


@dataclass(frozen=True)
class Task:
    task_id: str
    required_capabilities: frozenset[str]
    scope_refs: frozenset[str]
    evidence: tuple[EvidencePin, ...] = ()
    data_dependencies: tuple[str, ...] = ()
    control_dependencies: tuple[str, ...] = ()
    action: str = "read"


@dataclass(frozen=True)
class PlanNode:
    task_id: str
    provider: str | None
    data_dependencies: tuple[str, ...]
    control_dependencies: tuple[str, ...]


@dataclass(frozen=True)
class TeamPlan:
    nodes: tuple[PlanNode, ...]
    providers: tuple[str, ...]
    reserved_calls: int
    quality_estimate: None = None


def _time(value: str, label: str) -> datetime:
    if not isinstance(value, str):
        raise PlanError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise PlanError(f"{label} must include timezone")
    return parsed.astimezone(timezone.utc)


def _validate_task(task: Task, context: ScopeContext, ids: set[str]) -> None:
    if not isinstance(task, Task) or not isinstance(task.task_id, str) or not task.task_id or task.task_id in ids:
        raise PlanError("tasks must have unique non-empty IDs and use Task records")
    ids.add(task.task_id)
    if not isinstance(task.action, str) or task.action not in {"read", "analyze", "propose"}:
        raise PlanError("write or unknown actions are unsupported")
    if not isinstance(task.scope_refs, (set, frozenset)) or any(not isinstance(ref, str) or not ref for ref in task.scope_refs):
        raise PlanError("scope refs must be a set of non-empty strings")
    if not task.scope_refs or not task.scope_refs <= context.refs:
        raise PlanError("task scope refs are not contained in trusted caller scope")
    if not isinstance(task.required_capabilities, (set, frozenset)) or any(not isinstance(cap, str) or not cap for cap in task.required_capabilities):
        raise PlanError("invalid required capability")
    if not isinstance(task.evidence, tuple) or not isinstance(task.data_dependencies, tuple) or not isinstance(task.control_dependencies, tuple):
        raise PlanError("evidence and dependency collections must be tuples")
    for dep in (*task.data_dependencies, *task.control_dependencies):
        if not isinstance(dep, str) or not dep:
            raise PlanError("dependency IDs must be non-empty strings")
    for pin in task.evidence:
        if not isinstance(pin, EvidencePin) or not isinstance(pin.ref, str) or not pin.ref or not isinstance(pin.version, str) or not pin.version:
            raise PlanError("evidence requires exact ref and version pins")
        available, cutoff = _time(pin.available_at, "evidence availability"), _time(pin.cutoff, "cutoff")
        if cutoff != _time(context.as_of, "caller as_of"):
            raise PlanError("evidence cutoff differs from caller-attested as_of")
        server_available = context.evidence_available_at.get(pin.ref)
        if server_available is None or available != _time(server_available, "server evidence availability"):
            raise PlanError("evidence availability differs from caller-attested metadata")
        if available > cutoff:
            raise PlanError("evidence is unavailable at its retrieval cutoff")
        if context.evidence_versions.get(pin.ref) != pin.version:
            raise PlanError("evidence version is not the caller-pinned current version")
        owners = context.evidence_scope_refs.get(pin.ref)
        if not owners or not owners <= task.scope_refs:
            raise PlanError("task scope does not own every pinned evidence ref")


def compile_team(tasks: Sequence[Task], capabilities: Mapping[str, Sequence[str]],
                 context: ScopeContext, budgets: Mapping[str, int]) -> TeamPlan:
    """Validate and deterministically compile a bounded task graph, without execution."""
    if not isinstance(context, ScopeContext) or context._issuer is not _TRUSTED_ISSUER:
        raise PlanError("scope context must be caller-attested")
    if (not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)) or not tasks
            or len(tasks) > MAX_TASKS or not isinstance(capabilities, Mapping) or not isinstance(budgets, Mapping)):
        raise PlanError("tasks, capability map, and budgets are required")
    max_workers, max_calls = budgets.get("max_workers"), budgets.get("max_shared_calls")
    if type(max_workers) is not int or max_workers < 0 or max_workers > MAX_WORKERS or type(max_calls) is not int or max_calls < 0:
        raise PlanError("non-negative integer max_workers and max_shared_calls required")
    ids: set[str] = set()
    for task in tasks:
        _validate_task(task, context, ids)
    by_id = {task.task_id: task for task in tasks}
    for task in tasks:
        if set(task.data_dependencies) & set(task.control_dependencies):
            raise PlanError("data and control edges must be distinct")
        if any(dep not in by_id for dep in (*task.data_dependencies, *task.control_dependencies)):
            raise PlanError("unknown dependency")
        for parent_id in task.data_dependencies:
            if not by_id[parent_id].scope_refs <= task.scope_refs:
                raise PlanError("data parent scope exceeds child task scope")

    # Stable Kahn topological order; cycle check is independent of input order.
    remaining = {t.task_id: set(t.data_dependencies) | set(t.control_dependencies) for t in tasks}
    ordered: list[str] = []
    while remaining:
        ready = sorted(node for node, deps in remaining.items() if not deps)
        if not ready:
            raise PlanError("dependency cycle")
        for node in ready:
            ordered.append(node)
            del remaining[node]
        for deps in remaining.values():
            deps.difference_update(ready)

    normalized: dict[str, frozenset[str]] = {}
    for provider, caps in capabilities.items():
        if not isinstance(provider, str) or not provider or not isinstance(caps, Sequence) or isinstance(caps, (str, bytes)):
            raise PlanError("invalid capability provider")
        if any(not isinstance(cap, str) or not cap for cap in caps):
            raise PlanError("provider capabilities must be non-empty strings")
        normalized[provider] = frozenset(caps)
    if len(normalized) > MAX_PROVIDERS:
        raise PlanError("provider registry exceeds finite search limit")
    requirements = {cap for task in tasks for cap in task.required_capabilities}
    if any(not any(cap in caps for caps in normalized.values()) for cap in requirements):
        raise PlanError("required capability unavailable")

    # Find the smallest provider subset that can assign every whole task to
    # one provider. Search is lazy, budget-bounded, and stops at an explicit cap.
    providers = sorted(normalized)
    chosen: tuple[str, ...] = ()
    examined = 0
    found = False
    for size in range(min(max_workers, len(providers)) + 1):
        for combo in combinations(providers, size):
            examined += 1
            if examined > MAX_PROVIDER_SUBSETS:
                raise PlanError("provider assignment search limit exceeded")
            if all(not task.required_capabilities or any(
                    task.required_capabilities <= normalized[p] for p in combo) for task in tasks):
                chosen, found = combo, True
                break
        if found:
            break
    if not found:
        raise PlanError("no feasible provider assignment within worker budget")
    calls = len(tasks)
    if calls > max_calls:
        raise PlanError("shared call reservation exceeds budget")

    nodes: list[PlanNode] = []
    for task_id in ordered:
        task = by_id[task_id]
        provider = None
        if task.required_capabilities:
            eligible = [p for p in chosen if task.required_capabilities <= normalized[p]]
            if not eligible:
                raise PlanError("capabilities lack a single eligible provider for task")
            provider = eligible[0]
        nodes.append(PlanNode(task_id, provider, tuple(sorted(task.data_dependencies)),
                              tuple(sorted(task.control_dependencies))))
    return TeamPlan(tuple(nodes), chosen, calls)
