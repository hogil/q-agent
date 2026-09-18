"""Read-only meeting RAG adapter for SQLite FTS5 or an existing HTTP service."""
import json
import math
import os
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from incident_tools import ToolError


_IDENT = re.compile(r"[^\W\d]\w*\Z", re.UNICODE)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_MAX_RESPONSE = 1024 * 1024
_MAX_METADATA = 2048
_MAX_QUERY_TERMS = 64


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolError("MEETING_REDIRECT_REFUSED")


def _ident(value):
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ToolError("INVALID_IDENTIFIER")
    return '"' + value + '"'


def _valid_date(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ToolError("INVALID_AS_OF")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError("INVALID_AS_OF") from exc
    return value


class MeetingTools:
    def __init__(self, settings):
        try:
            self.cfg = settings.data["meetings"]
        except (AttributeError, KeyError, TypeError) as exc:
            raise ToolError("MEETINGS_CONFIG_REQUIRED") from exc
        c = self.cfg
        if type(c.get("enabled")) is not bool or type(c.get("top_k")) is not int or type(c.get("max_top_k")) is not int:
            raise ToolError("INVALID_MEETINGS_CONFIG")
        if c["top_k"] < 1 or c["max_top_k"] < c["top_k"]:
            raise ToolError("INVALID_MEETINGS_LIMITS")
        if c.get("backend") not in ("sqlite", "http"):
            raise ToolError("INVALID_MEETINGS_BACKEND")
        if type(c.get("timeout_seconds")) is not int or c["timeout_seconds"] <= 0:
            raise ToolError("INVALID_MEETINGS_TIMEOUT")
        self.table = _ident(c.get("table"))
        self.fts_table = _ident(c.get("fts_table"))
        if c["backend"] == "sqlite":
            if not isinstance(c.get("sqlite_file"), str) or not Path(c["sqlite_file"]).is_absolute():
                raise ToolError("INVALID_SQLITE_FILE")
        else:
            endpoint = c.get("endpoint")
            if not isinstance(endpoint, str) or urlparse(endpoint).scheme not in ("http", "https"):
                raise ToolError("INVALID_MEETING_ENDPOINT")
            if not isinstance(c.get("api_key_env"), str):
                raise ToolError("INVALID_API_KEY_ENV")
        runtime = getattr(settings, "data", {}).get("runtime", {})
        configured_limit = runtime.get("max_scope_incidents", 10000)
        self.max_incident_ids = min(configured_limit, 10000) if type(configured_limit) is int and configured_limit > 0 else 10000

    def search(self, actor, query, incident_ids=None, as_of=None, top_k=None):
        if not self.cfg["enabled"]:
            raise ToolError("MEETINGS_DISABLED")
        if not isinstance(actor, str) or not actor.strip():
            raise ToolError("INVALID_ACTOR")
        if not isinstance(query, str) or not query.strip() or len(query) > 12000:
            raise ToolError("INVALID_QUERY")
        as_of = _valid_date(as_of)
        ids = self._ids(incident_ids)
        if incident_ids is not None and not ids:
            return self._result("NO_MATCH", [], as_of, [], self._method())
        limit = self.cfg["top_k"] if top_k is None else top_k
        if type(limit) is not int or not 1 <= limit <= self.cfg["max_top_k"]:
            raise ToolError("INVALID_TOP_K")
        if self.cfg["backend"] == "sqlite":
            items, match = self._sqlite(query, ids, as_of, limit)
            return {**self._result("OK" if items else "NO_MATCH", items, as_of, ids, "sqlite_fts5_bm25"),
                    "query_match": match}
        items = self._http(actor, query, ids, as_of, limit)
        return self._result("OK" if items else "NO_MATCH", items, as_of, ids, "remote_hybrid")

    def _ids(self, values):
        if values is None:
            return None
        if not isinstance(values, list) or len(values) > self.max_incident_ids or any(not isinstance(x, str) or not x.strip() for x in values):
            raise ToolError("INVALID_INCIDENT_IDS")
        return list(dict.fromkeys(values))

    def _method(self):
        return "sqlite_fts5_bm25" if self.cfg["backend"] == "sqlite" else "remote_hybrid"

    def _result(self, status, items, as_of, ids, method):
        return {"status": status, "items": items, "retrieval_method": method,
                "as_of": as_of, "incident_ids": ids}

    def _sqlite(self, query, ids, as_of, limit):
        tokens = list(dict.fromkeys(_TOKEN.findall(query)))
        if len(tokens) > _MAX_QUERY_TERMS:
            raise ToolError("MEETING_QUERY_TOO_MANY_TERMS")
        if not tokens:
            return [], {"strategy": "no_terms", "term_count": 0}
        terms = ['"' + token.replace('"', '""') + '"' for token in tokens]
        match = {"strategy": "all_terms", "term_count": len(terms)}
        deadline = time.monotonic() + self.cfg["timeout_seconds"]
        uri = Path(self.cfg["sqlite_file"]).as_uri() + "?mode=ro"
        db = None
        try:
            db = sqlite3.connect(uri, uri=True, timeout=self.cfg["timeout_seconds"])
            db.row_factory = sqlite3.Row
            db.set_progress_handler(lambda: 1 if time.monotonic() >= deadline else 0, 1000)
            fields = "c.chunk_id,c.meeting_id,c.title,c.meeting_date,c.version,c.status,c.incident_ids,c.text,c.source_ref"
            sql = (f"SELECT {fields},bm25({self.fts_table}) AS score FROM {self.fts_table} f "
                   f"JOIN {self.table} c ON c.chunk_id=f.chunk_id WHERE {self.fts_table} MATCH ? "
                   "AND c.status='approved' AND c.meeting_date<=?")
            params = [" AND ".join(terms), as_of]
            if ids is not None:
                sql += " AND EXISTS (SELECT 1 FROM json_each(c.incident_ids) x WHERE x.value IN (" + ",".join("?" for _ in ids) + "))"
                params.extend(ids)
            order = " ORDER BY score,c.chunk_id LIMIT ?"
            rows = db.execute(sql + order, [*params, limit]).fetchall()
            # Preserve strict hits; complementary passages share the same scope and deadline.
            if len(rows) < limit and ids and len(terms) > 1:
                extra_sql = sql
                extra_params = [" OR ".join(terms), *params[1:]]
                if rows:
                    extra_sql += " AND c.chunk_id NOT IN (" + ",".join("?" for _ in rows) + ")"
                    extra_params.extend(row["chunk_id"] for row in rows)
                extra = db.execute(extra_sql + order, [*extra_params, limit - len(rows)]).fetchall()
                if extra or not rows:
                    match["strategy"] = "scoped_mixed_terms" if rows else "scoped_any_terms"
                rows.extend(extra)
            items, seen = [], set()
            for row in rows:
                try:
                    parsed = json.loads(row["incident_ids"])
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ToolError("INVALID_MEETING_ROW") from exc
                item = {"chunk_id": row["chunk_id"], "meeting_id": row["meeting_id"], "title": row["title"],
                        "meeting_date": row["meeting_date"], "version": row["version"], "status": row["status"],
                        "incident_ids": parsed, "text": row["text"], "source_ref": row["source_ref"], "score": row["score"]}
                items.append(self._validate_item(item, as_of, ids, seen))
            return items, match
        except sqlite3.Error as exc:
            raise ToolError("MEETING_SQLITE_QUERY_FAILED") from exc
        finally:
            if db is not None:
                db.close()

    def _http(self, actor, query, ids, as_of, limit):
        key = os.environ.get(self.cfg["api_key_env"]) if self.cfg["api_key_env"] else None
        if self.cfg["api_key_env"] and not key:
            raise ToolError("MEETING_API_KEY_UNAVAILABLE")
        payload = {"actor": actor, "query": query, "incident_ids": ids, "as_of": as_of,
                   "top_k": limit, "methods": ["bm25", "vector_similarity"]}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        request = Request(self.cfg["endpoint"], data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with build_opener(_NoRedirect).open(request, timeout=self.cfg["timeout_seconds"]) as response:
                raw = response.read(_MAX_RESPONSE + 1)
            if len(raw) > _MAX_RESPONSE:
                raise ToolError("MEETING_RESPONSE_TOO_LARGE")
            body = json.loads(raw.decode("utf-8"))
        except ToolError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError("MEETING_REMOTE_QUERY_FAILED") from exc
        if not isinstance(body, dict) or body.get("retrieval_method") != "remote_hybrid" or not isinstance(body.get("items"), list) or len(body["items"]) > limit:
            raise ToolError("INVALID_MEETING_RESPONSE")
        items, seen = [], set()
        for item in body["items"]:
            items.append(self._validate_item(item, as_of, ids, seen))
        return items

    def _validate_item(self, item, as_of, ids, seen):
        fields = ("chunk_id", "meeting_id", "title", "version", "text", "source_ref")
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in fields):
            raise ToolError("INVALID_MEETING_ROW")
        if any(len(item[k]) > (_MAX_METADATA if k != "text" else 8000) for k in fields):
            raise ToolError("INVALID_MEETING_ROW")
        if item["chunk_id"] in seen or item.get("status") != "approved":
            raise ToolError("INVALID_MEETING_ROW")
        meeting_date = _valid_date(item.get("meeting_date"))
        if (meeting_date > as_of or not isinstance(item.get("incident_ids"), list)
                or len(item["incident_ids"]) > self.max_incident_ids
                or any(not isinstance(x, str) or not x.strip() or len(x) > _MAX_METADATA for x in item["incident_ids"])):
            raise ToolError("INVALID_MEETING_ROW")
        if ids is not None and not set(item["incident_ids"]).intersection(ids):
            raise ToolError("INVALID_MEETING_ROW")
        try:
            score = float(item.get("score"))
        except (OverflowError, TypeError, ValueError) as exc:
            raise ToolError("INVALID_MEETING_ROW") from exc
        if type(item.get("score")) not in (int, float) or not math.isfinite(score):
            raise ToolError("INVALID_MEETING_ROW")
        seen.add(item["chunk_id"])
        return {"chunk_id": item["chunk_id"], "meeting_id": item["meeting_id"], "title": item["title"],
                "meeting_date": meeting_date, "version": item["version"], "status": "approved",
                "incident_ids": list(item["incident_ids"]), "text": item["text"],
                "source_ref": item["source_ref"], "score": score}
