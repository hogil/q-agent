import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

from app.detection_workflow import DetectionWorkflow


class DetectionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "chat.sqlite"
        self.calls = []
        self.failure = False

        def analyze(event):
            self.calls.append(event)
            if self.failure:
                raise RuntimeError("secret should not be stored")
            return {"room_id": "room-demo", "analysis_mode": "demo", "event_id": event["event_id"]}

        self.workflow = DetectionWorkflow(self.db, analyze)

    def tearDown(self):
        self.workflow.stop()
        self.temp.cleanup()

    def event(self, event_id="event-1", score=.8, threshold=.5, **extra):
        value = {"event_id": event_id, "item": "synthetic-item", "source": "synthetic_replay",
                 "context": {"incident": "SYN-2026-01"}, "comparison": {"baseline": .4},
                 "score": score, "threshold": threshold, "model_id": "synthetic-event-fixture",
                 "model_version": "1"}
        value.update(extra)
        return value

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail("timed out waiting for workflow")

    def test_thresholds_and_snapshot_metadata(self):
        below = self.workflow.submit(self.event("below", score=.2, threshold=.2 - .001))
        self.assertEqual(below["state"], "queued")
        self.assertEqual(self.workflow.submit(self.event("low", score=.2, threshold=.3))["state"], "below_threshold")
        snapshot = self.workflow.snapshot()
        self.assertFalse(snapshot["model_connected"])
        self.assertFalse(snapshot["llm_connected"])
        self.assertFalse(snapshot["production_connected"])
        self.assertEqual(snapshot["counts"]["queued"], 1)

    def test_duplicate_replay_and_conflict(self):
        first = self.workflow.submit(self.event("same", context={"z": 1, "a": "x"}))
        replay = self.workflow.submit(self.event("same", context={"a": "x", "z": 1}))
        self.assertEqual(first, replay)
        with self.assertRaises(ValueError):
            self.workflow.submit(self.event("same", context={"z": 1, "a": "different"}))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM detection_events").fetchone()[0], 1)

    def test_validation_rejects_malformed_values(self):
        cases = [
            ("score", True), ("score", "0.5"), ("threshold", float("nan")),
            ("event_id", ""), ("event_id", "x" * 129), ("event_id", 42),
            ("item", " "), ("source", "production"), ("context", []),
            ("unexpected", "extra field"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = self.event("bad-" + field)
                payload[field] = value
                with self.assertRaises(ValueError):
                    self.workflow.submit(payload)

    def test_callback_failure_retry_and_sanitized_error(self):
        self.failure = True
        self.workflow.submit(self.event("retry-me"))
        self.assertTrue(self.workflow.process_next())
        failed = self.workflow.snapshot()["events"][0]
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error"], "RuntimeError")
        self.assertNotIn("secret", json.dumps(failed))
        self.failure = False
        self.workflow.retry("retry-me")
        self.assertTrue(self.workflow.process_next())
        result = self.workflow.snapshot()["events"][0]
        self.assertEqual(result["state"], "review_required")
        self.assertEqual(result["action_status"], "requested")
        self.assertEqual(result["result"]["analysis_mode"], "demo")
        with self.assertRaises(ValueError):
            self.workflow.retry("retry-me")

    def test_restart_recovers_analyzing_and_persists(self):
        event = self.event("recover-me")
        self.workflow.submit(event)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE detection_events SET state='analyzing' WHERE event_id=?", ("recover-me",))
            db.commit()
        restarted = DetectionWorkflow(self.db, lambda value: {"room_id": "r", "analysis_mode": "demo"})
        try:
            recovered = restarted.snapshot()["events"][0]
            self.assertEqual(recovered["state"], "failed")
            self.assertEqual(recovered["error"], "WorkerRecovery")
            restarted.retry("recover-me")
            self.assertTrue(restarted.process_next())
            self.assertEqual(restarted.snapshot()["events"][0]["state"], "review_required")
        finally:
            restarted.stop()

    def test_worker_sequential_processing_and_decision_idempotency(self):
        self.workflow.submit(self.event("worker-1"))
        self.workflow.submit(self.event("worker-2"))
        self.workflow.start()
        self.wait_for(lambda: self.workflow.snapshot()["counts"]["review_required"] == 2)
        self.assertEqual([event["event_id"] for event in self.calls], ["worker-1", "worker-2"])
        acknowledged = self.workflow.decide("worker-1", "acknowledge")
        self.assertEqual(acknowledged["state"], "acknowledged")
        self.assertEqual(acknowledged, self.workflow.decide("worker-1", "acknowledge"))
        with self.assertRaises(ValueError):
            self.workflow.decide("worker-1", "reject")
        with self.assertRaises(ValueError):
            self.workflow.decide("worker-2", "approve")
        with self.assertRaises(ValueError):
            self.workflow.decide("worker-2", [])
        rejected = self.workflow.decide("worker-2", "reject")
        self.assertEqual(rejected["state"], "rejected")

    def test_snapshot_keeps_last_50_and_counts_full_history(self):
        for index in range(51):
            self.workflow.submit(self.event(f"history-{index}"))
        snapshot = self.workflow.snapshot()
        self.assertEqual(len(snapshot["events"]), 50)
        self.assertEqual(snapshot["counts"]["queued"], 51)
        self.assertNotIn("history-0", {event["event_id"] for event in snapshot["events"]})

    def test_callback_is_outside_transaction_and_production_result_is_rejected(self):
        entered = threading.Event()
        observed = {}

        def analyze(event):
            with closing(sqlite3.connect(self.db)) as db:
                observed["state"] = db.execute("SELECT state FROM detection_events WHERE event_id=?", (event["event_id"],)).fetchone()[0]
            entered.set()
            return {"room_id": "r", "analysis_mode": "production"}

        workflow = DetectionWorkflow(self.db, analyze)
        try:
            workflow.submit(self.event("outside-tx"))
            self.assertTrue(workflow.process_next())
            self.assertTrue(entered.is_set())
            self.assertEqual(observed["state"], "analyzing")
            self.assertEqual(workflow.snapshot()["events"][0]["state"], "failed")
        finally:
            workflow.stop()


if __name__ == "__main__":
    unittest.main()
