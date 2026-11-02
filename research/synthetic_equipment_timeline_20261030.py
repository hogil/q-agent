"""Research-only synthetic equipment timeline filtering contract.

This module consumes only caller-provided records. It has no database, MES,
network, Router, Skill, or production ACL integration. Approval callbacks are
explicit synthetic caller assertions, not evidence of real incident scope.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_INPUT_RECORDS = 10_000
MAX_TOP_K = 500
MAX_ID_LENGTH = 128
MAX_TEXT_LENGTH = 4_000
RECORD_TYPES = frozenset({"event", "process", "maintenance"})


@dataclass(frozen=True)
class TimelineScope:
    incident_id: str
    equipment_ids: tuple[str, ...]
    lot_ids: tuple[str, ...]
    as_of: datetime
    window_start: datetime
    window_end: datetime


class TimelineInputError(ValueError):
    """Invalid synthetic scope or record input."""


def _identifier(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH or value.strip() != value:
        raise TimelineInputError(f"invalid {field}")
    return value


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TimelineInputError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _make_scope(incident_id: Any, equipment_ids: Any, lot_ids: Any, as_of: Any,
                window_start: Any, window_end: Any) -> TimelineScope:
    incident = _identifier(incident_id, "incident_id")
    if isinstance(equipment_ids, (str, bytes)) or not isinstance(equipment_ids, (list, tuple, set, frozenset)):
        raise TimelineInputError("equipment_ids must be a collection")
    if isinstance(lot_ids, (str, bytes)) or not isinstance(lot_ids, (list, tuple, set, frozenset)):
        raise TimelineInputError("lot_ids must be a collection")
    equipment = tuple(sorted({_identifier(v, "equipment_id") for v in equipment_ids}))
    lots = tuple(sorted({_identifier(v, "lot_id") for v in lot_ids}))
    if not equipment:
        raise TimelineInputError("equipment_ids cannot be empty")
    cutoff, start, end = (_utc(as_of, "as_of"), _utc(window_start, "window_start"), _utc(window_end, "window_end"))
    if start > end or end > cutoff:
        raise TimelineInputError("expected window_start <= window_end <= as_of")
    return TimelineScope(incident, equipment, lots, cutoff, start, end)


def search_synthetic_equipment_timeline(
    *, incident_id: str, equipment_ids: list[str] | tuple[str, ...], lot_ids: list[str] | tuple[str, ...],
    as_of: datetime, window_start: datetime, window_end: datetime,
    records: Iterable[Mapping[str, Any]],
    validate_incident_scope: Callable[[TimelineScope], bool] | None,
    authorize_record: Callable[[TimelineScope, Mapping[str, Any]], bool] | None,
    synthetic_fixture_asserted: bool,
    top_k: int = 100,
) -> dict[str, Any]:
    """Return authorized synthetic candidates; never assert causality or lot impact.

    Caller must assert the fixture is synthetic; this is not independently
    verified. The input is capped at 10,000 rows. At most 10,000 are consumed;
    the next iterator item is not fetched. Duplicate IDs are first-seen among
    authorized in-scope rows, and duplicates mark the scan incomplete.
    Unknown-lot records may appear only as equipment-time candidates.
    """
    scope = _make_scope(incident_id, equipment_ids, lot_ids, as_of, window_start, window_end)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise TimelineInputError("top_k must be a positive integer")
    requested_top_k = top_k
    top_k = min(top_k, MAX_TOP_K)
    if synthetic_fixture_asserted is not True:
        raise TimelineInputError("synthetic_fixture_asserted=True is required")
    scope_ok = False
    if callable(validate_incident_scope):
        try:
            scope_ok = validate_incident_scope(scope) is True
        except Exception:
            scope_ok = False
    empty = {
        "synthetic_assertion": "caller_asserted_unverified", "incident_id": scope.incident_id, "records": [],
        "real_source_coverage": "unknown",
        "authorized_input_scan_complete": False, "truncated": False,
        "candidate_limitation": "Caller-asserted synthetic candidates only; real source coverage, incident impact, and causality are unknown.",
    }
    if not scope_ok or not callable(authorize_record):
        empty["candidate_limitation"] = "No records shown: explicit incident-scope approval and callable per-record authorization are required."
        return empty
    if isinstance(records, (str, bytes, Mapping)):
        raise TimelineInputError("records must be an iterable of mappings")
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    scan_complete = True
    truncated = requested_top_k > MAX_TOP_K
    try:
        iterator = iter(records)
    except Exception:
        empty["authorized_input_scan_complete"] = False
        empty["candidate_limitation"] = "No records shown: caller-provided iterable could not be scanned; real source coverage remains unknown."
        return empty
    for _ in range(MAX_INPUT_RECORDS):
        try:
            raw = next(iterator)
        except StopIteration:
            break
        except Exception:
            scan_complete = False
            break
        if not isinstance(raw, Mapping):
            scan_complete = False
            continue
        try:
            rid = _identifier(raw.get("record_id"), "record_id")
            kind = raw.get("type")
            if kind not in RECORD_TYPES:
                scan_complete = False
                continue
            rec_incident = _identifier(raw.get("incident_id"), "record incident_id")
            equipment = _identifier(raw.get("equipment_id"), "record equipment_id")
            lot = _identifier(raw.get("lot_id"), "record lot_id", nullable=True)
            event_time, available_at = _utc(raw.get("event_time"), "event_time"), _utc(raw.get("available_at"), "available_at")
            text = raw.get("text", "")
            if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
                scan_complete = False
                continue
        except (TimelineInputError, TypeError, ValueError):
            scan_complete = False
            continue
        if (rec_incident != scope.incident_id or equipment not in scope.equipment_ids or
                (lot is not None and lot not in scope.lot_ids) or
                not scope.window_start <= event_time <= scope.window_end or available_at > scope.as_of):
            continue
        try:
            if authorize_record(scope, raw) is not True:
                continue
        except Exception:
            scan_complete = False
            continue
        if rid in seen_ids:
            scan_complete = False
            continue
        seen_ids.add(rid)
        kept.append({
            "record_id": rid, "type": kind, "incident_id": rec_incident,
            "equipment_id": equipment, "lot_id": lot,
            "event_time": event_time.isoformat(), "available_at": available_at.isoformat(),
            "text": text, "lot_scope_status": "exact_lot_filter_match_not_impact" if lot is not None else "unknown_equipment_time_candidate_only",
            "causality": "not_assessed",
        })
    else:
        # No lookahead: the caller's iterable tail remains unconsumed and unknown.
        truncated = True
    kept.sort(key=lambda x: (-datetime.fromisoformat(x["event_time"]).timestamp(), x["record_id"]))
    if len(kept) > top_k:
        truncated = True
    returned = kept[:top_k]
    empty.update({
        "records": returned,
        "authorized_input_scan_complete": scan_complete and not truncated,
        "truncated": truncated,
    })
    return empty
