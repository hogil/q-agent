"""Synthetic scope projection contract tests for the meeting adapter."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from incident_tools import ToolError
from meeting_tools import MeetingTools


AS_OF = "2026-10-30"
BASE = {
    "chunk_id": "chunk-1", "meeting_id": "meeting-1", "title": "Synthetic notes",
    "meeting_date": "2026-10-01", "version": "v1", "status": "approved",
    "incident_ids": ["A", "B"], "text": "synthetic unchanged evidence",
    "source_ref": "synthetic://meeting/chunk-1", "score": -1.25,
}


def _settings(backend, path=None):
    cfg = {"enabled": True, "backend": backend, "sqlite_file": str(path or Path("/unused")),
           "table": "meeting_chunks", "fts_table": "meeting_fts", "endpoint": "http://synthetic.invalid",
           "api_key_env": "", "top_k": 5, "max_top_k": 10, "timeout_seconds": 2}
    return SimpleNamespace(data={"meetings": cfg, "runtime": {"max_scope_incidents": 10}})


def _database(path, incident_ids):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE meeting_chunks (chunk_id TEXT PRIMARY KEY, meeting_id TEXT, title TEXT, meeting_date TEXT, version TEXT, status TEXT, incident_ids TEXT, text TEXT, source_ref TEXT)")
    db.execute("CREATE VIRTUAL TABLE meeting_fts USING fts5(chunk_id UNINDEXED, title, text)")
    row = ("chunk-1", "meeting-1", "Synthetic notes", "2026-10-01", "v1", "approved",
           json.dumps(incident_ids), BASE["text"], BASE["source_ref"])
    db.execute("INSERT INTO meeting_chunks VALUES (?,?,?,?,?,?,?,?,?)", row)
    db.execute("INSERT INTO meeting_fts VALUES (?,?,?)", (row[0], row[2], row[7]))
    db.commit()
    db.close()


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class MeetingScopeProjectionTests(unittest.TestCase):
    def _search(self, tool, ids):
        return tool.search("synthetic-actor", "evidence", incident_ids=ids, as_of=AS_OF)

    def test_sqlite_projects_selected_ids_and_preserves_independent_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, ["A", "B"])
            tool = MeetingTools(_settings("sqlite", path))
            result = self._search(tool, ["A"])
            self.assertEqual(result["items"][0]["incident_ids"], ["A"])
            self.assertEqual(result["items"][0]["text"], BASE["text"])
            self.assertEqual(result["items"][0]["source_ref"], BASE["source_ref"])
            self.assertNotIn("acl_verified", result)
            self.assertEqual(self._search(tool, None)["items"][0]["incident_ids"], ["A", "B"])

    def test_http_projects_selected_ids_and_rejects_unmatched_remote_item(self):
        def opener(_request, timeout):
            self.assertEqual(timeout, 2)
            return _Response({"retrieval_method": "remote_hybrid", "items": [dict(BASE)]})

        tool = MeetingTools(_settings("http"))
        with patch("meeting_tools.build_opener", return_value=SimpleNamespace(open=opener)):
            result = self._search(tool, ["A"])
            self.assertEqual(result["items"][0]["incident_ids"], ["A"])
            self.assertEqual(result["items"][0]["text"], BASE["text"])
            self.assertEqual(result["items"][0]["source_ref"], BASE["source_ref"])
            self.assertNotIn("acl_verified", result)
            with self.assertRaisesRegex(ToolError, "INVALID_MEETING_ROW"):
                self._search(tool, ["C"])

    def test_empty_scope_is_no_match_for_both_backends(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, ["A", "B"])
            result = self._search(MeetingTools(_settings("sqlite", path)), [])
            self.assertEqual((result["status"], result["items"]), ("NO_MATCH", []))

        tool = MeetingTools(_settings("http"))
        with patch("meeting_tools.build_opener") as opener:
            result = self._search(tool, [])
        self.assertEqual((result["status"], result["items"]), ("NO_MATCH", []))
        opener.assert_not_called()

    def test_multiple_selected_ids_keep_requested_scope_order_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meetings.sqlite"
            _database(path, ["A", "B", "C"])
            result = self._search(MeetingTools(_settings("sqlite", path)), ["C", "A", "C"])
            self.assertEqual(result["incident_ids"], ["C", "A"])
            self.assertEqual(result["items"][0]["incident_ids"], ["A", "C"])


if __name__ == "__main__":
    unittest.main()
