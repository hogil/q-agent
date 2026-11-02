"""Strict synthetic contract for a callback-backed FBM similarity search."""

from datetime import date, datetime, time, timedelta
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_QUERY_FIELDS = ("incident_id", "lot_id", "wafer_id", "asset_id", "revision", "available_at")
_ITEM_FIELDS = (*_QUERY_FIELDS, "rank", "similarity", "relation")
_MODEL_FIELDS = ("model_id", "model_version", "preprocess_version", "checkpoint_sha256")
_REPRESENTATIONS = {"raw_fbm", "object_id_yield_fbm"}
_LIMITATIONS = [
    "source_query_assertion_unverified", "source_model_assertion_unverified",
    "historical_wafer_scope_unverified", "site_acl_unverified", "coordinate_lineage_unverified",
    "query_exact_self_match_rejected", "source_ranking_unverified",
]


def _incident_coverage(rows, incident_id, expected_field, returned_field):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("source coverage must be a list of dicts")
    matches = [row for row in rows if row.get("incident_id") == incident_id]
    if len(matches) > 1:
        raise ValueError("duplicate incident source coverage")
    if not matches:
        return {"state": "missing", expected_field: None, returned_field: None}
    row = matches[0]
    state = row.get("state")
    expected, returned = row.get(expected_field), row.get(returned_field)
    if not isinstance(state, str) or not state.strip():
        raise ValueError("source coverage state is invalid")
    if ((expected is not None and (type(expected) is not int or expected < 0))
            or type(returned) is not int or returned < 0):
        raise ValueError("source coverage counts are invalid")
    return {"state": state, expected_field: expected, returned_field: returned}


def project_source_coverage(query_incident_id, lot_rows, wafer_rows):
    """Keep only the selected incident's incident-grain source coverage."""
    incident_id = _string(query_incident_id, "query incident_id")
    return {
        "grain": "incident",
        "lot": _incident_coverage(lot_rows, incident_id, "expected_lots", "returned_total_lots"),
        "wafer": _incident_coverage(wafer_rows, incident_id, "expected_wafers", "returned_total_wafers"),
    }


def _string(value, name, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def _ids(values, name, *, required=False):
    if not isinstance(values, (list, tuple)) or (required and not values) or len(values) > 100:
        raise ValueError(f"{name} must be a bounded list" + (" and cannot be empty" if required else ""))
    result = [_string(v, name) for v in values]
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must be unique")
    return set(result)


def _date(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{name} must be an ISO date")
    return parsed


def _timestamp(value, name, zone, cutoff):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timezone-aware ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        future = parsed.astimezone(zone) >= cutoff
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a valid timezone-aware ISO datetime") from exc
    if future:
        raise ValueError(f"{name} must be on or before as_of in the configured timezone")


def validate_fbm_response(
    response, *, query_wafer, representation, current_incident_ids,
    historical_incident_ids, registered_wafers, as_of, timezone_name, top_k,
):
    """Validate and project callback output; caller-supplied scope is not source-verified."""
    current = _ids(current_incident_ids, "current_incident_ids", required=True)
    historical = _ids(historical_incident_ids, "historical_incident_ids")
    if current & historical:
        raise ValueError("current and historical incident IDs must be disjoint")
    if representation not in _REPRESENTATIONS:
        raise ValueError("representation must be raw_fbm or object_id_yield_fbm")
    target_date = _date(as_of, "as_of")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("timezone_name must identify a ZoneInfo timezone")
    try:
        zone = ZoneInfo(timezone_name)
        cutoff = datetime.combine(target_date + timedelta(days=1), time.min, zone)
    except (ZoneInfoNotFoundError, ValueError, OverflowError) as exc:
        raise ValueError("timezone_name/as_of must define a valid cutoff") from exc
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
        raise ValueError("top_k must be an integer from 1 to 100")
    if not isinstance(query_wafer, tuple) or len(query_wafer) != 3:
        raise ValueError("query_wafer must be an (incident_id, lot_id, wafer_id) tuple")
    query_tuple = tuple(_string(v, "query_wafer member") for v in query_wafer)
    if query_tuple[0] not in current:
        raise ValueError("query wafer incident must be in current_incident_ids")
    if not isinstance(registered_wafers, (list, tuple, set, frozenset)):
        raise ValueError("registered_wafers must be an iterable of three-string tuples")
    registered = set()
    for value in registered_wafers:
        if not isinstance(value, tuple) or len(value) != 3:
            raise ValueError("each registered wafer must be a three-string tuple")
        registered.add(tuple(_string(v, "registered wafer member") for v in value))
    if query_tuple not in registered:
        raise ValueError("query wafer must be registered")
    if not isinstance(response, dict):
        raise ValueError("response must be a dict")
    status = response.get("status")
    if status not in ("OK", "NO_MATCH"):
        raise ValueError("status must be OK or NO_MATCH")
    if response.get("representation") != representation:
        raise ValueError("response representation must match the requested representation")
    if response.get("as_of") != as_of:
        raise ValueError("response as_of must match the requested date")
    raw_query = response.get("query")
    if not isinstance(raw_query, dict):
        raise ValueError("query must be a dict")
    query = {key: _string(raw_query.get(key), f"query.{key}") for key in _QUERY_FIELDS}
    if tuple(query[k] for k in ("incident_id", "lot_id", "wafer_id")) != query_tuple:
        raise ValueError("query wafer tuple must match the bound query_wafer")
    if query_tuple not in registered:
        raise ValueError("query wafer must be registered")
    _timestamp(query["available_at"], "query.available_at", zone, cutoff)
    items = response.get("items")
    if not isinstance(items, list) or len(items) > top_k:
        raise ValueError("items must be a list no longer than top_k")
    if (status == "OK") != bool(items):
        raise ValueError("status and items do not agree")
    normalized = []
    seen_items = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError("each item must be a dict")
        record = {key: _string(item.get(key), f"item.{key}") for key in _QUERY_FIELDS}
        if all(record[key] == query[key] for key in ("incident_id", "lot_id", "wafer_id", "asset_id", "revision")):
            raise ValueError("exact query self-match is not allowed")
        identity = tuple(record[key] for key in ("incident_id", "lot_id", "wafer_id", "asset_id", "revision"))
        if identity in seen_items:
            raise ValueError("duplicate incident/lot/wafer/asset/revision item")
        seen_items.add(identity)
        if type(item.get("rank")) is not int or item.get("rank") != index:
            raise ValueError("rank must be consecutive starting at 1")
        record["rank"] = index
        score = item.get("similarity")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not -1 <= score <= 1:
            raise ValueError("similarity must be a finite cosine score in [-1, 1]")
        record["similarity"] = score
        relation = item.get("relation")
        if relation not in ("direct", "historical_candidate"):
            raise ValueError("relation must be direct or historical_candidate")
        item_tuple = (record["incident_id"], record["lot_id"], record["wafer_id"])
        if relation == "direct":
            if record["incident_id"] not in current or item_tuple not in registered:
                raise ValueError("direct item must belong to current incident and registered wafer scope")
        elif record["incident_id"] not in historical:
            raise ValueError("historical_candidate must belong to registered historical incident IDs")
        record["relation"] = relation
        _timestamp(record["available_at"], "item.available_at", zone, cutoff)
        normalized.append(record)
    metadata = {}
    for key in _MODEL_FIELDS:
        value = _string(response.get(key), key)
        if key == "checkpoint_sha256" and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("checkpoint_sha256 must be 64 lowercase hexadecimal characters")
        metadata[key] = value
    truncated = response.get("truncated")
    if truncated is not None and type(truncated) is not bool:
        raise ValueError("truncated must be a boolean or null")
    return {
        "status": status, "as_of": as_of, "representation": representation,
        "query": query, "items": normalized, **metadata,
        "source_query_identity": dict(query),
        "source_reported_truncated": truncated,
        "truncation_semantics": "unknown" if truncated is None else "source_assertion_only",
        "limitations": list(_LIMITATIONS),
    }
