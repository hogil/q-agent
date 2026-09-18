import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from incident_tools import ToolError
from meeting_tools import MeetingTools


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _settings(path, table="meeting_chunks", fts_table="meeting_fts", **changes):
    config = {"enabled": True, "backend": "sqlite", "sqlite_file": str(path),
              "table": table, "fts_table": fts_table, "endpoint": "",
              "api_key_env": "", "top_k": 5, "max_top_k": 10,
              "timeout_seconds": 2}
    config.update(changes)
    return SimpleNamespace(data={"meetings": config, "runtime": {"max_scope_incidents": 2}})


def _database(path, table="meeting_chunks", fts_table="meeting_fts", rows=None):
    rows = rows or []
    db = sqlite3.connect(path)
    db.execute(f"CREATE TABLE {_q(table)} (chunk_id TEXT PRIMARY KEY, meeting_id TEXT, title TEXT, meeting_date TEXT, version TEXT, status TEXT, incident_ids TEXT, text TEXT, source_ref TEXT)")
    db.execute(f"CREATE VIRTUAL TABLE {_q(fts_table)} USING fts5(chunk_id UNINDEXED, title, text, tokenize='unicode61')")
    for row in rows:
        db.execute(f"INSERT INTO {_q(table)} VALUES (?,?,?,?,?,?,?,?,?)", row)
        db.execute(f"INSERT INTO {_q(fts_table)} VALUES (?,?,?)", (row[0], row[2], row[7]))
    db.commit()
    db.close()


VALID = ("ok", "meeting-1", "Needle", "2026-01-10", "v1", "approved", '["I1"]', "needle evidence", "ref://meeting-1")


class MeetingTests(unittest.TestCase):
    def test_default_and_unicode_fts_identifiers(self):
        for table, fts in (("meeting_chunks", "meeting_fts"), ("회의테이블", "회의FTS")):
            with self.subTest(table=table, fts=fts), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "meetings.sqlite"
                _database(path, table, fts, [VALID])
                result = MeetingTools(_settings(path, table, fts)).search("actor", "needle", as_of="2026-12-31")
                self.assertEqual(result["status"], "OK")
                self.assertEqual(result["items"][0]["chunk_id"], "ok")

    def test_filters_apply_before_top_k_and_empty_scope_is_not_global(self):
        rows = [
            VALID,
            ("future", "m", "Needle", "2027-01-01", "v1", "approved", '["I1"]', "needle future", "ref://future"),
            ("draft", "m", "Needle", "2026-01-01", "v1", "draft", '["I1"]', "needle draft", "ref://draft"),
            ("other", "m", "Needle", "2026-01-01", "v1", "approved", '["I2"]', "needle other", "ref://other"),
        ]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, rows=rows)
            tool = MeetingTools(_settings(path, top_k=1))
            result = tool.search("actor", "needle", incident_ids=["I1"], as_of="2026-12-31")
            self.assertEqual([x["chunk_id"] for x in result["items"]], ["ok"])
            self.assertEqual(tool.search("actor", "needle", incident_ids=[], as_of="2026-12-31")["status"], "NO_MATCH")

    def test_readonly_database_hash_is_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, rows=[VALID])
            before = hashlib.sha256(path.read_bytes()).digest()
            MeetingTools(_settings(path)).search("actor", "needle", as_of="2026-12-31")
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())

    def test_scoped_fallback_preserves_filters_and_independent_precision(self):
        rows = [VALID,
                ("future", "m", "Needle", "2027-01-01", "v1", "approved", '["I1"]', "needle unknown", "ref://future"),
                ("draft", "m", "Needle", "2026-01-01", "v1", "draft", '["I1"]', "needle unknown", "ref://draft"),
                ("other", "m", "Needle", "2026-01-01", "v1", "approved", '["I2"]', "needle unknown", "ref://other")]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, rows=rows)
            tool = MeetingTools(_settings(path, top_k=1))
            before = hashlib.sha256(path.read_bytes()).digest()
            result = tool.search("actor", "needle absentword", incident_ids=["I1"], as_of="2026-12-31")
            self.assertEqual([item["chunk_id"] for item in result["items"]], ["ok"])
            self.assertEqual(result["query_match"], {"strategy": "scoped_any_terms", "term_count": 2})
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())
            for ids in (None, []):
                self.assertEqual(tool.search("actor", "needle absentword", incident_ids=ids,
                                             as_of="2026-12-31")["items"], [])
            self.assertEqual(tool.search("actor", "entirely absentword", incident_ids=["I1"],
                                         as_of="2026-12-31")["items"], [])

    def test_scoped_exact_results_are_first_and_partial_evidence_fills_remaining_slots(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            partial = ("partial", "m", "Needle", "2026-01-01", "v1", "approved", '["I1"]', "needle unrelated", "ref://partial")
            other = ("other", "m", "Needle", "2026-01-01", "v1", "approved", '["I2"]', "needle", "ref://other")
            draft = ("draft", "m", "Needle", "2026-01-01", "v1", "draft", '["I1"]', "needle", "ref://draft")
            future = ("future", "m", "Needle", "2027-01-01", "v1", "approved", '["I1"]', "needle", "ref://future")
            _database(path, rows=[VALID, partial, other, draft, future])
            tool = MeetingTools(_settings(path))
            before = hashlib.sha256(path.read_bytes()).digest()
            result = tool.search("actor", "needle evidence", incident_ids=["I1"], as_of="2026-12-31")
            self.assertEqual([item["chunk_id"] for item in result["items"]], ["ok", "partial"])
            self.assertEqual(result["query_match"]["strategy"], "scoped_mixed_terms")
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())
            for ids, limit in ((["I1"], 1), (None, 5)):
                result = tool.search("actor", "needle evidence", incident_ids=ids, as_of="2026-12-31", top_k=limit)
                self.assertEqual([item["chunk_id"] for item in result["items"]], ["ok"])
                self.assertEqual(result["query_match"]["strategy"], "all_terms")

    def test_scoped_top_up_excludes_strict_hits_before_applying_limit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            rows = [VALID, ("second", *VALID[1:]),
                    ("partial", "m", "Needle", "2026-01-01", "v1", "approved", '["I1"]', "needle", "ref://partial")]
            _database(path, rows=rows)
            tool = MeetingTools(_settings(path))
            result = tool.search("actor", "needle evidence", incident_ids=["I1"], as_of="2026-12-31", top_k=3)
            self.assertEqual([item["chunk_id"] for item in result["items"]], ["ok", "second", "partial"])
            result = tool.search("actor", "needle", incident_ids=["I1"], as_of="2026-12-31", top_k=3)
            self.assertEqual(result["query_match"]["strategy"], "all_terms")

    def test_query_terms_are_bounded_deduplicated_and_not_executed_as_fts_syntax(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, rows=[VALID])
            tool = MeetingTools(_settings(path))
            with self.assertRaisesRegex(ToolError, "MEETING_QUERY_TOO_MANY_TERMS"):
                tool.search("actor", " ".join(f"word{i}" for i in range(65)), incident_ids=["I1"], as_of="2026-12-31")
            result = tool.search("actor", "needle " * 80, as_of="2026-12-31")
            self.assertEqual(result["query_match"], {"strategy": "all_terms", "term_count": 1})
            self.assertEqual(result["status"], "OK")
            result = tool.search("actor", 'needle OR "missing"*', as_of="2026-12-31")
            self.assertEqual(result["items"], [])
            result = tool.search("actor", "! *", as_of="2026-12-31")
            self.assertEqual(result["query_match"]["strategy"], "no_terms")

    def test_fts_owns_unicode_normalization(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            row = ("unicode", "m", "Straße", "2026-01-01", "v1", "approved", '["I1"]', "Straße", "ref://unicode")
            _database(path, rows=[row])
            result = MeetingTools(_settings(path)).search("actor", "Straße", as_of="2026-12-31")
            self.assertEqual([item["chunk_id"] for item in result["items"]], ["unicode"])

    def test_tied_scores_have_stable_chunk_order(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, rows=[VALID, ("aaa", *VALID[1:])])
            result = MeetingTools(_settings(path, top_k=1)).search("actor", "needle absentword", incident_ids=["I1"], as_of="2026-12-31")
            self.assertEqual([item["chunk_id"] for item in result["items"]], ["aaa"])

    def test_disabled_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, rows=[VALID])
            disabled = MeetingTools(_settings(path, enabled=False))
            with self.assertRaisesRegex(ToolError, "MEETINGS_DISABLED"):
                disabled.search("actor", "needle", as_of="2026-01-01")
            tool = MeetingTools(_settings(path))
            for args, code in (({"actor": "", "query": "needle", "as_of": "2026-01-01"}, "INVALID_ACTOR"),
                               ({"actor": "actor", "query": "needle", "as_of": "2026-02-30"}, "INVALID_AS_OF"),
                               ({"actor": "actor", "query": "needle", "as_of": "2026-01-01", "incident_ids": ["1", "2", "3"]}, "INVALID_INCIDENT_IDS")):
                with self.subTest(code=code), self.assertRaisesRegex(ToolError, code):
                    tool.search(**args)

    def test_http_success_and_rejections(self):
        handler = _StubHandler
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
        old_key = os.environ.get("MEETING_TEST_KEY")
        try:
            os.environ["MEETING_TEST_KEY"] = "secret-token"
            for mode, expected in (("ok", None), ("future", "INVALID_MEETING_ROW"), ("outscope", "INVALID_MEETING_ROW"), ("huge-score", "INVALID_MEETING_ROW"), ("oversized", "MEETING_RESPONSE_TOO_LARGE"), ("redirect", "MEETING_REDIRECT_REFUSED")):
                with self.subTest(mode=mode):
                    handler.mode, handler.paths, handler.auth = mode, [], []
                    settings = _settings(Path("/unused"), backend="http", endpoint=endpoint + "/" + mode, api_key_env="MEETING_TEST_KEY")
                    tool = MeetingTools(settings)
                    if expected:
                        with self.assertRaisesRegex(ToolError, expected):
                            tool.search("actor", "needle", incident_ids=["I1"], as_of="2026-12-31")
                    else:
                        result = tool.search("actor", "needle", incident_ids=["I1"], as_of="2026-12-31")
                        self.assertEqual(result["status"], "OK")
                        self.assertEqual(set(result["items"][0]), {"chunk_id", "meeting_id", "title", "meeting_date", "version", "status", "incident_ids", "text", "source_ref", "score"})
                    self.assertEqual(handler.auth[0], "Bearer secret-token")
                    if mode == "redirect":
                        self.assertEqual(handler.paths, ["/redirect"])
        finally:
            server.shutdown()
            server.server_close()
            if old_key is None:
                os.environ.pop("MEETING_TEST_KEY", None)
            else:
                os.environ["MEETING_TEST_KEY"] = old_key


class _StubHandler(BaseHTTPRequestHandler):
    mode = "ok"
    paths = []
    auth = []

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.__class__.paths.append(self.path)
        self.__class__.auth.append(self.headers.get("Authorization"))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.__class__.mode == "oversized":
            body = b"x" * (1024 * 1024 + 1)
        else:
            item = {"chunk_id": VALID[0], "meeting_id": VALID[1], "title": VALID[2],
                    "meeting_date": VALID[3], "version": VALID[4], "status": "approved",
                    "incident_ids": json.loads(VALID[6]), "text": VALID[7],
                    "source_ref": VALID[8], "score": -1.0}
            if self.__class__.mode == "future":
                item["meeting_date"] = "2027-01-01"
            if self.__class__.mode == "outscope":
                item["incident_ids"] = ["I2"]
            if self.__class__.mode == "huge-score":
                item["score"] = 10 ** 400
            item["untrusted_extra"] = "must not escape adapter"
            body = json.dumps({"retrieval_method": "remote_hybrid", "items": [item]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    unittest.main()
