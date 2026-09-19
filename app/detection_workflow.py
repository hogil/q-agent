"""Bounded synthetic-replay detection workflow for the local demo."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


_STATES = ("below_threshold", "queued", "analyzing", "review_required",
           "failed", "acknowledged", "rejected")
_DECISIONS = {"acknowledge": "acknowledged", "reject": "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


class DetectionWorkflow:
    """Durable, synthetic-only detection queue with a single worker."""

    def __init__(self, db_path: Path, analyze: Callable[[dict], dict]):
        if not callable(analyze):
            raise TypeError("analyze must be callable")
        self.db_path = Path(db_path)
        self.analyze = analyze
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._recover()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()
        finally:
            db.close()

    def _init_db(self):
        with self._db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS detection_events (
                    event_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL,
                    action_status TEXT NOT NULL,
                    result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS detection_events_state_created "
                       "ON detection_events(state, created_at, event_id)")

    def _recover(self):
        with self._db() as db:
            now = _now()
            db.execute("UPDATE detection_events SET state='failed', action_status='failed', "
                       "error='WorkerRecovery', updated_at=? WHERE state='analyzing'", (now,))

    @staticmethod
    def _event_id(value) -> str:
        if (not isinstance(value, str) or not value.strip() or len(value) > 128):
            raise ValueError("event_id must be a stable string of 1-128 characters")
        return value

    @staticmethod
    def _event(value: dict) -> tuple[dict, str, str]:
        required = {"event_id", "item", "source", "context", "comparison", "score", "threshold", "model_id", "model_version"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("event must be an object")
        event = dict(value)
        event_id = DetectionWorkflow._event_id(event.get("event_id"))
        if not isinstance(event.get("item"), str) or not event["item"].strip():
            raise ValueError("item must be a nonempty string")
        if event.get("source") != "synthetic_replay":
            raise ValueError("source must be synthetic_replay")
        if not isinstance(event.get("context"), dict) or not isinstance(event.get("comparison"), dict):
            raise ValueError("context and comparison must be objects")
        for field in ("score", "threshold"):
            number = event.get(field)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError(f"{field} must be a finite number")
            if not math.isfinite(number) or not 0 <= number <= 1:
                raise ValueError(f"{field} must be between 0 and 1")
        if event.get("model_id") != "synthetic-event-fixture" or event.get("model_version") != "1":
            raise ValueError("synthetic fixture model metadata is required")
        try:
            payload = _json(event)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("event must contain JSON-safe values") from None
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return event, event_id, fingerprint

    @staticmethod
    def _record(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        record = dict(payload) if isinstance(payload, dict) else {}
        record.update({
            "state": row["state"], "action_status": row["action_status"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "error": row["error"],
        })
        return record

    def _get(self, event_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM detection_events WHERE event_id=?", (event_id,)).fetchone()
        result = self._record(row)
        if result is None:
            raise ValueError("event not found")
        return result

    def submit(self, event: dict) -> dict:
        event, event_id, fingerprint = self._event(event)
        state = "below_threshold" if event["score"] < event["threshold"] else "queued"
        now = _now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM detection_events WHERE event_id=?", (event_id,)).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise ValueError("event_id already has different content")
                result = self._record(row)
            else:
                db.execute("INSERT INTO detection_events VALUES (?,?,?,?,?,?,?,?,?)",
                           (event_id, fingerprint, _json(event), state, "not_requested",
                            None, now, now, None))
                result = self._record(db.execute(
                    "SELECT * FROM detection_events WHERE event_id=?", (event_id,)).fetchone())
        if state == "queued" and result and result["state"] == "queued":
            self._wake.set()
        return result

    def snapshot(self) -> dict:
        with self._db() as db:
            rows = db.execute("SELECT * FROM detection_events ORDER BY created_at DESC, event_id DESC LIMIT 50").fetchall()
            counts = {state: 0 for state in _STATES}
            for row in db.execute("SELECT state, COUNT(*) AS n FROM detection_events GROUP BY state"):
                counts[row["state"]] = row["n"]
        return {
            "source": "synthetic_replay", "model_connected": False,
            "llm_connected": False, "production_connected": False,
            "events": [self._record(row) for row in rows], "counts": counts,
            "worker_running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
        }

    def _claim(self):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM detection_events WHERE state='queued' "
                             "ORDER BY created_at, event_id LIMIT 1").fetchone()
            if row is None:
                db.commit()
                return None
            now = _now()
            changed = db.execute("UPDATE detection_events SET state='analyzing', updated_at=? "
                                 "WHERE event_id=? AND state='queued'", (now, row["event_id"])).rowcount
            if changed != 1:
                db.rollback()
                return None
            db.commit()
            return json.loads(row["payload"])

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return re.sub(r"[^A-Za-z0-9_.]", "_", type(exc).__name__)[:128] or "Exception"

    def process_next(self) -> bool:
        event = self._claim()
        if event is None:
            return False
        try:
            result = self.analyze(event)
            if (not isinstance(result, dict) or result.get("analysis_mode") != "demo"
                    or not isinstance(result.get("room_id"), str) or not result["room_id"].strip()):
                raise ValueError("demo analysis result is required")
            encoded = _json(result)
            with self._db() as db:
                db.execute("UPDATE detection_events SET state='review_required', action_status='requested', "
                           "result=?, error=NULL, updated_at=? WHERE event_id=? AND state='analyzing'",
                           (encoded, _now(), event["event_id"]))
        except Exception as exc:
            with self._db() as db:
                db.execute("UPDATE detection_events SET state='failed', action_status='failed', "
                           "error=?, updated_at=? WHERE event_id=? AND state='analyzing'",
                           (self._safe_error(exc), _now(), event["event_id"]))
        return True

    def _run(self):
        while not self._stop.is_set():
            if self.process_next():
                continue
            self._wake.wait(0.25)
            self._wake.clear()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="detection-workflow", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)

    def retry(self, event_id) -> dict:
        event_id = self._event_id(event_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM detection_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise ValueError("event not found")
            if row["state"] != "failed":
                raise ValueError("only failed events can be retried")
            db.execute("UPDATE detection_events SET state='queued', action_status='not_requested', "
                       "result=NULL, error=NULL, updated_at=? WHERE event_id=?", (_now(), event_id))
        self._wake.set()
        return self._get(event_id)

    def decide(self, event_id, decision) -> dict:
        event_id = self._event_id(event_id)
        if not isinstance(decision, str) or decision not in _DECISIONS:
            raise ValueError("only acknowledge or reject is allowed")
        target = _DECISIONS[decision]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM detection_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise ValueError("event not found")
            if row["state"] == target:
                return self._record(row)
            if row["state"] != "review_required":
                raise ValueError("decision requires review_required state")
            db.execute("UPDATE detection_events SET state=?, action_status=?, updated_at=? WHERE event_id=?",
                       (target, target, _now(), event_id))
        return self._get(event_id)
