"""Validation contract for existing BM25+vector document chunks."""

from datetime import date, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_METHOD = "bm25_vector_hybrid"
_LIMITATIONS = ["source_acl_not_verified", "historical_candidate_not_current_scope"]
_FIELDS = (
    "document_id", "chunk_id", "version", "text", "source_ref", "locator",
    "status", "available_at", "incident_ids", "relation", "score",
    "observed_at", "effective_from", "effective_to", "applicability",
)


def _string(value, name, maximum=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def _aware_datetime(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timezone-aware ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a timezone-aware ISO datetime") from exc
    if parsed.tzinfo is None or offset is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _id_set(values, name, *, required=False):
    if not isinstance(values, (list, tuple)) or (required and not values) or len(values) > 100:
        raise ValueError(f"{name} must be a bounded list" + (" and cannot be empty" if required else ""))
    result = {_string(value, name, 256) for value in values}
    if len(result) != len(values):
        raise ValueError(f"{name} must be unique")
    return result


def validate_hybrid_response(
    response, *, source_kind, incident_ids, as_of, timezone_name, top_k,
    historical_incident_ids=(), allowed_statuses, require_content_kind=False,
):
    """Validate and normalize a hybrid retrieval response against its bound scope."""
    if source_kind not in ("engineer_notes", "internal_documents"):
        raise ValueError("unsupported source_kind")
    if type(require_content_kind) is not bool:
        raise ValueError("require_content_kind must be a boolean")
    scope = _id_set(incident_ids, "incident_ids", required=True)
    historical_scope = _id_set(historical_incident_ids, "historical_incident_ids")
    if not isinstance(allowed_statuses, (list, tuple)) or not allowed_statuses or len(allowed_statuses) > 100:
        raise ValueError("allowed_statuses must be a non-empty bounded allowlist")
    trusted_statuses = {_string(value, "allowed status", 256) for value in allowed_statuses}
    if len(trusted_statuses) != len(allowed_statuses):
        raise ValueError("allowed_statuses must be unique")
    if not isinstance(as_of, str):
        raise ValueError("as_of must be an ISO date")
    try:
        target_date = date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError("as_of must be an ISO date") from exc
    if target_date.isoformat() != as_of:
        raise ValueError("as_of must be an ISO date")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("timezone_name must identify a ZoneInfo timezone")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone_name must identify a ZoneInfo timezone") from exc
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
        raise ValueError("top_k must be an integer from 1 to 100")
    if not isinstance(response, dict):
        raise ValueError("response must be a dict")
    status = response.get("status")
    if status not in ("OK", "NO_MATCH"):
        raise ValueError("status must be OK or NO_MATCH")
    if response.get("retrieval_method") != _METHOD:
        raise ValueError("retrieval_method must be bm25_vector_hybrid")
    if response.get("as_of") != as_of:
        raise ValueError("response as_of must match the requested date")
    raw_truncated = response.get("truncated")
    normalized_truncated = response.get("source_reported_truncated")
    if raw_truncated is not None and type(raw_truncated) is not bool:
        raise ValueError("truncated must be a boolean or null")
    if normalized_truncated is not None and type(normalized_truncated) is not bool:
        raise ValueError("source_reported_truncated must be a boolean or null")
    if "truncated" in response and "source_reported_truncated" in response and raw_truncated != normalized_truncated:
        raise ValueError("truncated conflicts with source_reported_truncated")
    source_truncated = normalized_truncated if "source_reported_truncated" in response else raw_truncated

    raw_candidate_count = response.get("candidate_count")
    normalized_candidate_count = response.get("source_reported_candidate_count")
    for name, value in (("candidate_count", raw_candidate_count),
                         ("source_reported_candidate_count", normalized_candidate_count)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"{name} must be a nonnegative integer or null")
    if ("candidate_count" in response and "source_reported_candidate_count" in response
            and raw_candidate_count != normalized_candidate_count):
        raise ValueError("candidate_count conflicts with source_reported_candidate_count")
    source_candidate_count = (normalized_candidate_count
                              if "source_reported_candidate_count" in response else raw_candidate_count)

    completeness = (
        "source_reported_truncated" if source_truncated is True
        else "source_reported_not_truncated" if source_truncated is False
        else "unknown"
    )
    if "retrieval_completeness" in response and response["retrieval_completeness"] != completeness:
        raise ValueError("retrieval_completeness conflicts with source-reported truncation")
    count_basis = "source_reported_unverified"
    if "candidate_count_basis" in response and response["candidate_count_basis"] != count_basis:
        raise ValueError("candidate_count_basis is unsupported")
    items = response.get("items")
    if not isinstance(items, list) or len(items) > top_k:
        raise ValueError("items must be a list no longer than top_k")
    if (status == "OK") != bool(items):
        raise ValueError("status and items do not agree")

    try:
        cutoff = datetime.combine(target_date + timedelta(days=1), time.min, zone)
    except (ValueError, OverflowError) as exc:
        raise ValueError("as_of cutoff is out of range") from exc
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item must be a dict")
        record = {key: item.get(key) for key in _FIELDS}
        content_kind = item.get("content_kind")
        has_content_kind = "content_kind" in item
        has_derivative_time = "derivative_available_at" in item
        if has_content_kind and content_kind not in ("image_ocr", "text"):
            raise ValueError("content_kind is unsupported")
        if require_content_kind and not has_content_kind:
            raise ValueError("content_kind is required")
        if content_kind == "image_ocr":
            if not has_derivative_time:
                raise ValueError("image_ocr requires derivative_available_at")
            record["content_kind"] = content_kind
        elif content_kind == "text":
            record["content_kind"] = content_kind
            if has_derivative_time:
                raise ValueError("derivative_available_at requires image_ocr content_kind")
        elif has_derivative_time:
            raise ValueError("derivative_available_at requires image_ocr content_kind")
        for key in ("document_id", "chunk_id", "version", "source_ref", "locator", "status"):
            record[key] = _string(record[key], key)
        if record["status"] not in trusted_statuses:
            raise ValueError("item status is not in the caller-provided allowlist")
        record["text"] = _string(record["text"], "text", 20000)
        key = (record["document_id"], record["version"], record["chunk_id"])
        if key in seen:
            raise ValueError("duplicate document/version/chunk")
        seen.add(key)
        item_scope = _id_set(record["incident_ids"], "item incident_ids", required=True)
        if record["relation"] not in ("direct", "historical_candidate"):
            raise ValueError("relation must be direct or historical_candidate")
        if record["relation"] == "direct":
            permitted_ids = item_scope & scope
            if not permitted_ids:
                raise ValueError("direct evidence must intersect the bound incident scope")
        else:
            permitted_ids = item_scope & historical_scope
            if not permitted_ids:
                raise ValueError("historical evidence must intersect caller-registered historical incident IDs")
        record["incident_ids"] = sorted(permitted_ids)
        score = record["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("score must be a finite number")
        parsed = _aware_datetime(record["available_at"], "available_at")
        try:
            after_cutoff = parsed.astimezone(zone) >= cutoff
        except (ValueError, OverflowError) as exc:
            raise ValueError("available_at cannot be converted to the configured timezone") from exc
        if after_cutoff:
            raise ValueError("available_at must be on or before the as_of date in the configured timezone")
        if content_kind == "image_ocr":
            derivative = _aware_datetime(item["derivative_available_at"], "derivative_available_at")
            try:
                derivative_after_cutoff = derivative.astimezone(zone) >= cutoff
            except (ValueError, OverflowError) as exc:
                raise ValueError("derivative_available_at cannot be converted to the configured timezone") from exc
            if derivative_after_cutoff:
                raise ValueError("derivative_available_at must be on or before the as_of date in the configured timezone")
            record["derivative_available_at"] = item["derivative_available_at"]
        if record["observed_at"] is not None:
            _aware_datetime(record["observed_at"], "observed_at")
        start = record["effective_from"]
        end = record["effective_to"]
        parsed_start = _aware_datetime(start, "effective_from") if start is not None else None
        parsed_end = _aware_datetime(end, "effective_to") if end is not None else None
        if parsed_start is not None and parsed_end is not None:
            try:
                invalid_interval = parsed_start >= parsed_end
            except (ValueError, OverflowError) as exc:
                raise ValueError("effective period timestamps cannot be compared") from exc
            if invalid_interval:
                raise ValueError("effective period must be a non-empty half-open interval [effective_from, effective_to)")
        applicability = record["applicability"]
        if applicability is not None:
            if not isinstance(applicability, dict) or len(applicability) > 32:
                raise ValueError("applicability must be a bounded metadata dict or null")
            for meta_key, meta_value in applicability.items():
                _string(meta_key, "applicability key", 128)
                if isinstance(meta_value, str):
                    _string(meta_value, "applicability value", 1024)
                elif isinstance(meta_value, list):
                    if len(meta_value) > 100:
                        raise ValueError("applicability list is too long")
                    for value in meta_value:
                        _string(value, "applicability list value", 256)
                elif meta_value is not None and not isinstance(meta_value, bool):
                    raise ValueError("applicability values must be strings, string lists, booleans, or null")
        record["applicability_status"] = "unverified"
        normalized.append(record)

    return {
        "status": status,
        "retrieval_method": _METHOD,
        "as_of": as_of,
        "source_kind": source_kind,
        "incident_ids": sorted(scope),
        "historical_incident_ids": sorted(historical_scope),
        "items": normalized,
        "source_reported_truncated": source_truncated,
        "source_reported_candidate_count": source_candidate_count,
        "retrieval_completeness": completeness,
        "candidate_count_basis": count_basis,
        "limitations": list(_LIMITATIONS),
    }
