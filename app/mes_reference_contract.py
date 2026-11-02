"""Synthetic validation contract for read-only MES reference responses.

This module validates only a response already returned by an existing adapter.
The accepted field meanings and effective-date rules are a synthetic contract;
they do not establish company schema, source semantics, or ACL correctness.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_ITEM_FIELDS = (
    "kind",
    "record_id",
    "version",
    "name",
    "source_ref",
    "available_at",
    "effective_from",
    "effective_to",
    "applicability",
    "scope_relation",
    "incident_ids",
)
_APPLICABILITY = {"confirmed", "candidate", "unknown"}
_SCOPE_RELATIONS = {"current_scope", "catalog_candidate"}
_LIMITATIONS = (
    "active is time validity only, not applicability",
    "scope_relation is an adapter assertion, not source authentication or ACL evidence",
    "source field and effective-date semantics are unverified synthetic contract",
)


def _instant(value):
    """Compare aware datetimes by instant, including across DST folds."""
    return value.astimezone(timezone.utc)


def _text(value, field, *, limit=512):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or any(ord(c) < 32 for c in normalized):
        raise ValueError(f"{field} must be nonempty normalized text of at most {limit} characters")
    return normalized


def _parse_datetime(value, field, zone, *, required=False):
    if value is None and not required:
        return None
    raw = _text(value, field, limit=128)
    try:
        day = date.fromisoformat(raw)
        return datetime.combine(day, time.min, tzinfo=zone)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(zone)


def _parse_as_of(value, zone):
    raw = _text(value, "as_of", limit=128)
    try:
        day = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("as_of must be an ISO date (YYYY-MM-DD)") from exc
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)


def validate_mes_reference_response(
    response, *, incident_ids, as_of, timezone_name, allowed_kinds, top_k
):
    """Validate and project a synthetic MES reference response.

    Effective intervals are [effective_from, effective_to). ``time_status``
    describes time validity only; it does not establish product applicability.
    A catalog candidate is preserved without claiming incident applicability.
    """
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
        raise ValueError("top_k must be an integer from 1 to 100")
    try:
        zone = ZoneInfo(_text(timezone_name, "timezone_name", limit=128))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone_name must identify a known timezone") from exc

    if not isinstance(incident_ids, (list, tuple)) or not incident_ids:
        raise ValueError("incident_ids must be a nonempty list or tuple")
    scoped_ids = [_text(v, "incident_ids[]", limit=128) for v in incident_ids]
    if len(set(scoped_ids)) != len(scoped_ids):
        raise ValueError("incident_ids must not contain duplicates")
    normalized_as_of = _parse_as_of(as_of, zone)

    if not isinstance(allowed_kinds, (set, frozenset, list, tuple)) or not allowed_kinds:
        raise ValueError("allowed_kinds must be a nonempty collection")
    kinds = {_text(v, "allowed_kinds[]", limit=64) for v in allowed_kinds}

    if not isinstance(response, dict):
        raise ValueError("response must be a dict")
    status = response.get("status")
    if status not in ("OK", "NO_MATCH"):
        raise ValueError("status must be OK or NO_MATCH")
    if response.get("as_of") != as_of or response.get("incident_ids") != scoped_ids:
        raise ValueError("response as_of and incident_ids must exactly match the request scope")
    items = response.get("items")
    if not isinstance(items, list) or len(items) > top_k:
        raise ValueError("items must be a list with no more than top_k entries")
    truncated = response.get("truncated")
    candidate_count = response.get("candidate_count")
    if type(truncated) is not bool:
        raise ValueError("truncated must be a boolean")
    if (isinstance(candidate_count, bool) or not isinstance(candidate_count, int)
            or candidate_count < len(items) or (candidate_count > len(items)) != truncated
            or (status == "NO_MATCH") != (candidate_count == 0)):
        raise ValueError("candidate_count does not match the response truncation state")
    if (status == "OK" and not items) or (status == "NO_MATCH" and items):
        raise ValueError("status must be consistent with items")

    output_items = []
    seen = set()
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} must be a dict")
        projected = {}
        for field in _ITEM_FIELDS:
            if field not in item:
                raise ValueError(f"{prefix}.{field} is required")
        kind = _text(item["kind"], f"{prefix}.kind", limit=64)
        if kind not in kinds:
            raise ValueError(f"{prefix}.kind is outside allowed_kinds")
        projected["kind"] = kind
        for field, limit in (("record_id", 128), ("version", 128), ("name", 256), ("source_ref", 512)):
            projected[field] = _text(item[field], f"{prefix}.{field}", limit=limit)
        scope_relation = _text(item["scope_relation"], f"{prefix}.scope_relation", limit=32)
        if scope_relation not in _SCOPE_RELATIONS:
            raise ValueError(f"{prefix}.scope_relation must be current_scope or catalog_candidate")
        item_ids = item["incident_ids"]
        if not isinstance(item_ids, (list, tuple)):
            raise ValueError(f"{prefix}.incident_ids must be a list or tuple")
        normalized_item_ids = [_text(v, f"{prefix}.incident_ids[]", limit=128) for v in item_ids]
        if len(set(normalized_item_ids)) != len(normalized_item_ids):
            raise ValueError(f"{prefix}.incident_ids must not contain duplicates")
        if not set(normalized_item_ids).issubset(scoped_ids):
            raise ValueError(f"{prefix} incident_ids must be a subset of request scope")
        if scope_relation == "current_scope" and not normalized_item_ids:
            raise ValueError(f"{prefix} current_scope incident_ids must be a nonempty subset of request scope")
        if scope_relation == "catalog_candidate" and normalized_item_ids:
            raise ValueError(f"{prefix} catalog_candidate incident_ids must be empty")
        projected["scope_relation"] = scope_relation
        projected["incident_ids"] = normalized_item_ids
        identity = (kind, projected["record_id"], projected["version"])
        if identity in seen:
            raise ValueError(f"duplicate item identity: {identity}")
        seen.add(identity)

        available = _parse_datetime(item["available_at"], f"{prefix}.available_at", zone, required=True)
        if _instant(available) >= _instant(normalized_as_of):
            raise ValueError(f"{prefix}.available_at must be before the exclusive as_of boundary")
        projected["available_at"] = item["available_at"]

        start = _parse_datetime(item["effective_from"], f"{prefix}.effective_from", zone)
        end = _parse_datetime(item["effective_to"], f"{prefix}.effective_to", zone)
        # Keep explicit nulls in the projection so validating this output again
        # preserves the original "unknown/open interval boundary" meaning.
        projected["effective_from"] = item["effective_from"]
        projected["effective_to"] = item["effective_to"]
        if start is not None and end is not None and _instant(start) >= _instant(end):
            raise ValueError(f"{prefix}.effective_from must be before effective_to")

        applicability = _text(item["applicability"], f"{prefix}.applicability", limit=32)
        if applicability not in _APPLICABILITY:
            raise ValueError(f"{prefix}.applicability must be confirmed, candidate, or unknown")
        projected["applicability"] = applicability

        if start is None and end is None:
            time_status = "unknown"
        elif start is not None and _instant(start) >= _instant(normalized_as_of):
            time_status = "future"
        elif end is not None and _instant(end) < _instant(normalized_as_of):
            time_status = "expired"
        elif (start is None or _instant(start) < _instant(normalized_as_of)) and (
            end is None or _instant(end) >= _instant(normalized_as_of)
        ):
            time_status = "active"
        else:
            time_status = "unknown"
        projected["time_status"] = time_status
        output_items.append(projected)

    return {
        "status": status,
        "as_of": as_of,
        "incident_ids": list(scoped_ids),
        "items": output_items,
        "truncated": truncated,
        "candidate_count": candidate_count,
        "limitations": list(_LIMITATIONS),
    }
