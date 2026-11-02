"""Read-only synthetic SQLite callback for the MES reference contract.

This is an executable adapter example for a synthetic database only. It does
not define a company MES schema, production connection, or access-control rule.
"""

from datetime import date, datetime, time, timedelta
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from incident_tools import ident
from mes_reference_contract import validate_mes_reference_response


_LOGICAL_COLUMNS = (
    "kind",
    "record_id",
    "version",
    "name",
    "source_ref",
    "available_at",
    "effective_from",
    "effective_to",
    "applicability",
    "incident_ids",
)
_MAX_QUERY_LENGTH = 256
_MAX_SCAN_ROWS = 1000
_MAX_FILTER_COLUMNS = 32
_FILTER_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _bounded_text(value, field, limit):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError(f"{field} must be nonempty text of at most {limit} characters")
    return value


def _availability(value, zone):
    """Parse a DB value strictly; availability may never silently become unknown."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("available_at is missing or is not text")
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=zone)
        except ValueError as exc:
            raise ValueError("available_at must be an ISO date or timezone-aware datetime") from exc
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(raw), time.min, tzinfo=zone)
        except ValueError as exc:
            raise ValueError("available_at must be an ISO date or timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("available_at must include a timezone")
    return parsed.astimezone(zone)


class SyntheticMESReferenceReader:
    """Read mapped synthetic reference rows using a per-call SQLite ro handle.

    ``mapping`` is administrator-provided and has ``table`` and ``columns``
    keys. ``columns`` maps the logical names above to physical SQLite columns.
    Physical identifiers are checked with the same strict ``ident`` helper as
    the incident SQLite adapter; request values are never SQL identifiers.
    """

    def __init__(self, database_path, mapping, *, timezone_name, allowed_kinds, filter_columns=None, timeout=5.0):
        path = Path(database_path)
        if not path.is_absolute():
            raise ValueError("database_path must be an absolute path")
        try:
            self.database_path = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("database_path must identify an existing SQLite file") from exc
        if not self.database_path.is_file():
            raise ValueError("database_path must identify a file")

        if not isinstance(mapping, dict) or set(mapping) != {"table", "columns"}:
            raise ValueError("mapping must contain exactly table and columns")
        self.table = ident(mapping["table"])
        columns = mapping["columns"]
        if not isinstance(columns, dict) or not set(_LOGICAL_COLUMNS).issubset(columns):
            raise ValueError("mapping.columns must map every required logical column")
        self.columns = {logical: ident(columns[logical]) for logical in _LOGICAL_COLUMNS}
        if filter_columns is None:
            filter_columns = {}
        if not isinstance(filter_columns, dict) or len(filter_columns) > _MAX_FILTER_COLUMNS:
            raise ValueError(f"filter_columns must be a mapping of at most {_MAX_FILTER_COLUMNS} entries")
        self.filter_columns = {}
        for key, physical in filter_columns.items():
            if not isinstance(key, str) or len(key) > 64 or not _FILTER_KEY.fullmatch(key):
                raise ValueError("filter_columns keys must be ASCII identifiers of at most 64 characters")
            self.filter_columns[key] = ident(physical)

        try:
            self.zone = ZoneInfo(_bounded_text(timezone_name, "timezone_name", 128))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone_name must identify a known timezone") from exc
        if not isinstance(allowed_kinds, (set, frozenset, list, tuple)) or not allowed_kinds:
            raise ValueError("allowed_kinds must be a nonempty collection")
        self.allowed_kinds = frozenset(
            _bounded_text(kind, "allowed_kinds[]", 64) for kind in allowed_kinds
        )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.timeout = float(timeout)

        # Validate mapped objects against the actual synthetic file, without
        # accepting arbitrary SQL fragments from the mapping.
        with closing(self._connect()) as connection:
            columns_sql = ",".join([*self.columns.values(), *self.filter_columns.values()])
            connection.execute(f"SELECT {columns_sql} FROM {self.table} LIMIT 0")

    def _connect(self):
        uri = self.database_path.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        connection.create_function("qagent_casefold", 1, lambda value: value.casefold() if isinstance(value, str) else "", deterministic=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def __call__(self, *, actor, incident_ids, as_of, kind, query, top_k, filters=None):
        # actor is accepted for callback compatibility; this synthetic example
        # has no user-specific ACL and must not be treated as one.
        del actor
        if not isinstance(incident_ids, (list, tuple)) or not incident_ids:
            raise ValueError("incident_ids must be a nonempty list or tuple")
        scoped_ids = [_bounded_text(value, "incident_ids[]", 128) for value in incident_ids]
        if len(set(scoped_ids)) != len(scoped_ids):
            raise ValueError("incident_ids must not contain duplicates")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be an integer from 1 to 100")
        kind = _bounded_text(kind, "kind", 64)
        if kind not in self.allowed_kinds:
            raise ValueError("kind is outside allowed_kinds")
        query = _bounded_text(query, "query", _MAX_QUERY_LENGTH)
        filter_sql = ""
        filter_values = []
        if filters is not None:
            if not isinstance(filters, dict) or not filters or len(filters) > 5:
                raise ValueError("filters must be a nonempty mapping of at most 5 entries")
            for key, value in filters.items():
                if key not in self.filter_columns:
                    raise ValueError("filter key is not enabled in filter_columns")
                if (not isinstance(value, str) or not value.strip() or len(value) > 128 or
                        any(ord(char) < 32 for char in value)):
                    raise ValueError(f"filters.{key} must be nonempty text of at most 128 characters")
                filter_values.append(value)
            filter_sql = "".join(f" AND {self.filter_columns[key]}=?" for key in filters)
        if not isinstance(as_of, str):
            raise ValueError("as_of must be an ISO date")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
            raise ValueError("as_of must be an ISO date (YYYY-MM-DD)")
        try:
            day = date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date (YYYY-MM-DD)") from exc
        cutoff = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self.zone)

        selected = ",".join(f"{column} AS {ident(logical)}" for logical, column in self.columns.items())
        sql = (
            f"SELECT {selected} FROM {self.table} "
            f"WHERE {self.columns['kind']}=? "
            f"AND instr(qagent_casefold({self.columns['name']}),?)>0 "
            f"{filter_sql} "
            f"ORDER BY {self.columns['record_id']},{self.columns['version']} LIMIT ?"
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, (kind, query.casefold(), *filter_values, _MAX_SCAN_ROWS + 1)).fetchall()
        if len(rows) > _MAX_SCAN_ROWS:
            raise ValueError(f"MES reference candidate scan exceeds fixed cap of {_MAX_SCAN_ROWS}")

        items = []
        for row in rows:
            available_raw = row["available_at"]
            available = _availability(available_raw, self.zone)
            if available >= cutoff:
                continue
            try:
                row_incident_ids = json.loads(row["incident_ids"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("incident_ids DB value must be a JSON array") from exc
            if not isinstance(row_incident_ids, list) or any(not isinstance(value, str) for value in row_incident_ids):
                raise ValueError("incident_ids DB value must be a JSON array of strings")
            matched_ids = [value for value in row_incident_ids if value in scoped_ids]
            item = {
                "kind": row["kind"],
                "record_id": row["record_id"],
                "version": row["version"],
                "name": row["name"],
                "source_ref": row["source_ref"],
                "available_at": available_raw,
                "effective_from": row["effective_from"],
                "effective_to": row["effective_to"],
                "applicability": row["applicability"],
                "scope_relation": "current_scope" if matched_ids else "catalog_candidate",
                # Out-of-scope identifiers are discarded and never inferred to
                # be connected to the requested incident scope.
                "incident_ids": matched_ids,
            }
            items.append(item)

        total = len(items)
        truncated = total > top_k
        response = {
            "status": "OK" if items else "NO_MATCH",
            "as_of": as_of,
            "incident_ids": scoped_ids,
            "items": items[:top_k],
            "truncated": truncated,
            "candidate_count": total,
        }
        return validate_mes_reference_response(
            response,
            incident_ids=scoped_ids,
            as_of=as_of,
            timezone_name=self.zone.key,
            allowed_kinds=self.allowed_kinds,
            top_k=top_k,
        ) | {"truncated": truncated, "candidate_count": total}


def _self_test():
    """Small executable smoke test using only temporary synthetic data."""
    import hashlib
    import tempfile

    columns = {name: name for name in _LOGICAL_COLUMNS}
    mapping = {"table": "synthetic_refs", "columns": columns}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "refs.sqlite"
        db = sqlite3.connect(path)
        db.execute(
            "CREATE TABLE synthetic_refs (kind, record_id, version, name, source_ref, "
            "available_at, effective_from, effective_to, applicability, incident_ids)"
        )

        def add(record_id, kind="product", name="Product alpha", available="2026-10-28T10:00:00+09:00", ids='["I-1"]'):
            db.execute(
                "INSERT INTO synthetic_refs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (kind, record_id, "v1", name, "synthetic://" + record_id, available,
                 "2026-01-01", None, "candidate", ids),
            )

        add("product-1")
        add("route-1", "route", "Alpha route")
        add("recipe-1", "recipe", "Alpha recipe")
        add("log-1", "log", "Alpha log", ids='["OTHER"]')
        add("future", available="2026-10-30T00:00:00+09:00")
        db.commit()
        db.close()
        reader = SyntheticMESReferenceReader(
            path, mapping, timezone_name="Asia/Seoul",
            allowed_kinds={"product", "route", "recipe", "log"},
        )
        add_to_db = sqlite3.connect(path)
        add_to_db.execute("INSERT INTO synthetic_refs VALUES (?,?,?,?,?,?,?,?,?,?)", ("product", "product-2", "v1", "Product alpha two", "synthetic://product-2", "2026-10-28T10:00:00+09:00", None, None, "candidate", '["I-1"]'))
        add_to_db.commit()
        add_to_db.close()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = reader(actor="synthetic", incident_ids=["I-1"], as_of="2026-10-29", kind="product", query="ALPHA", top_k=10)
        assert result["status"] == "OK" and [item["record_id"] for item in result["items"]] == ["product-1", "product-2"]
        unrelated = reader(actor="synthetic", incident_ids=["I-1"], as_of="2026-10-29", kind="log", query="alpha", top_k=10)
        assert unrelated["items"][0]["scope_relation"] == "catalog_candidate" and unrelated["items"][0]["incident_ids"] == []
        assert reader(actor="synthetic", incident_ids=["I-1"], as_of="2026-10-29", kind="route", query="alpha", top_k=10)["status"] == "OK"
        assert reader(actor="synthetic", incident_ids=["I-1"], as_of="2026-10-29", kind="recipe", query="alpha", top_k=10)["status"] == "OK"
        assert reader(actor="synthetic", incident_ids=["I-1"], as_of="2026-10-29", kind="product", query="' OR 1=1 --", top_k=10)["status"] == "NO_MATCH"
        try:
            reader(actor="synthetic", incident_ids=["I-1", "I-1"], as_of="2026-10-29", kind="product", query="alpha", top_k=10)
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate request incident IDs were accepted")
        overflow = reader(actor="synthetic", incident_ids=["I-1"], as_of="2026-10-29", kind="product", query="alpha", top_k=1)
        assert len(overflow["items"]) == 1 and overflow["truncated"] is True and overflow["candidate_count"] == 2
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert before == after
        try:
            with closing(reader._connect()) as connection:
                connection.execute("INSERT INTO synthetic_refs VALUES (?,?,?,?,?,?,?,?,?,?)", ("product", "blocked", "v1", "x", "x", "2026-10-28T10:00:00+09:00", None, None, "candidate", "[]"))
        except sqlite3.OperationalError:
            pass
        else:
            raise AssertionError("read-only connection accepted a write")


if __name__ == "__main__":
    _self_test()
