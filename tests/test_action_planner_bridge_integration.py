"""Synthetic integration contract for the incident bridge and standalone planner.

Run with PYTHONPATH explicitly containing this repository and q-agent-models/src.
This test exercises synthetic data only and grants no execution authority.
"""
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    from qmodels.action_evidence_planner_v1 import (
        CandidateTest, EvidenceFact, Hypothesis, PlannerError, TrustedContext, plan,
    )
except ImportError as exc:  # The separate research repository is optional.
    PLANNER_IMPORT_ERROR = str(exc)
else:
    PLANNER_IMPORT_ERROR = None

from app.action_scope_bridge import ActionScopeBridgeError, build_scoped_action_input


class _IncidentTools:
    def __init__(self):
        self.scope_id = "incident-selection-1"
        self.scope = {"ids": ("synthetic-incident-1",), "requires_selection": False,
                      "summary_only": False}

    def _scope(self, actor, scope_id):
        if scope_id != self.scope_id:
            raise ValueError("unknown synthetic scope")
        return self.scope

    def _page(self, *, kind, offset):
        items = ([{"incident_id": "synthetic-incident-1", "lot_id": "lot-a"}]
                 if kind == "lot" else [
                     {"incident_id": "synthetic-incident-1", "lot_id": "lot-a",
                      "wafer_id": "wafer-1"},
                     {"incident_id": "synthetic-incident-1", "lot_id": "lot-a",
                      "wafer_id": "wafer-2"},
                 ])
        page_items = items[offset:offset + 1]
        end = offset + len(page_items)
        count_key = "lots" if kind == "lot" else "wafers"
        result = {
            "status": "OK", "scope_id": self.scope_id, "items": page_items,
            "total_memberships": len(items), "offset": offset,
            "next_offset": end if end < len(items) else None,
            "source_completeness": "declared_complete", "mapping_version": "fixture-v1",
            "coverage": [{"incident_id": "synthetic-incident-1",
                          f"expected_{count_key}": len(items),
                          f"returned_total_{count_key}": len(items),
                          "state": "complete_by_declared_source_and_count"}],
        }
        if kind == "wafer":
            result["wafer_scope"] = "incident_affected"
            result["lot_coverage"] = [{"incident_id": "synthetic-incident-1",
                                       "expected_lots": 1, "returned_total_lots": 1,
                                       "state": "complete_by_declared_source_and_count"}]
        return result

    def list_incident_lots(self, actor, scope_id, *, page_size, offset):
        return self._page(kind="lot", offset=offset)

    def list_incident_wafers(self, actor, scope_id, *, page_size, offset):
        return self._page(kind="wafer", offset=offset)


class _Lease:
    atomic_snapshot = True
    snapshot_token = "synthetic-lease-token"
    revision = "synthetic-db-revision-17"
    as_of = "2026-10-29T00:00:00Z"

    def __init__(self, tools, *, bad_revision=False):
        self.tools = tools
        self.bad_revision = bad_revision

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def _bind(self, page):
        page["_snapshot_token"] = self.snapshot_token
        page["_snapshot_revision"] = "wrong-revision" if self.bad_revision else self.revision
        page["_snapshot_as_of"] = self.as_of
        return page

    def list_incident_lots(self, actor, scope_id, **kwargs):
        return self._bind(self.tools.list_incident_lots(actor, scope_id, **kwargs))

    def list_incident_wafers(self, actor, scope_id, **kwargs):
        return self._bind(self.tools.list_incident_wafers(actor, scope_id, **kwargs))

    def validate(self):
        return True


def _lease_provider(*, bad_revision=False):
    @contextmanager
    def provide(tools, actor, scope_id):
        with _Lease(tools, bad_revision=bad_revision) as lease:
            yield lease
    return provide


@unittest.skipIf(PLANNER_IMPORT_ERROR, f"q-agent-models planner unavailable: {PLANNER_IMPORT_ERROR}")
class ActionPlannerBridgeIntegrationTests(unittest.TestCase):
    def _bridge(self):
        tools = _IncidentTools()
        bridge = build_scoped_action_input(
            tools, "synthetic-research-caller", tools.scope_id,
            snapshot_lease_provider=_lease_provider(), page_size=1)
        self.assertTrue(bridge["synthetic_only"])
        self.assertTrue(bridge["synthetic_planner_input_eligible"])
        self.assertFalse(bridge["execution_granted"])
        return bridge

    def test_bridge_context_reaches_real_plan_with_scope_time_and_revision(self):
        bridge = self._bridge()
        context = TrustedContext(scope=bridge["scope"], as_of=bridge["as_of"],
                                 revision=bridge["revision"])
        # These hypotheses are caller-supplied synthetic assumptions, not an inference
        # that the incident DB established the full hypothesis space.
        hypotheses = (
            Hypothesis("safe", ("RELEASE",)),
            Hypothesis("risk", ("HOLD",), risk=True),
        )
        candidate = CandidateTest("synthetic-discriminating-check", 1.0,
                                  {"safe-result": ("safe",), "risk-result": ("risk",)})
        result = plan(context, hypotheses, tests=(candidate,), requested_action="RELEASE",
                      spent_cost=0.0, cost_budget=1.0)

        self.assertEqual(result["scope"], [list(pair) for pair in bridge["scope"]])
        self.assertEqual(result["as_of"], bridge["as_of"].isoformat())
        self.assertEqual(result["revision"], bridge["revision"])
        self.assertEqual(result["remaining_hypotheses"], ["risk", "safe"])
        self.assertEqual(result["next_test"]["id"], candidate.id)
        self.assertFalse(result["next_test"]["execution_granted"])
        self.assertFalse(result["release_allowed"])

    def test_rejects_future_out_of_scope_and_wrong_revision_evidence(self):
        bridge = self._bridge()
        context = TrustedContext(bridge["scope"], bridge["as_of"], bridge["revision"])
        hypotheses = (Hypothesis("safe", ("HOLD",)), Hypothesis("risk", ("HOLD",), risk=True))
        def fact(**overrides):
            values = dict(id="fixture-evidence", scope=bridge["scope"],
                          observed_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
                          available_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
                          version="fixture-v1", revision=bridge["revision"], refutes=("risk",))
            values.update(overrides)
            return EvidenceFact(**values)

        cases = (
            (fact(observed_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
                  available_at=datetime(2026, 10, 30, tzinfo=timezone.utc)), "stale or available after as_of"),
            (fact(scope=(("wafer-outside", "lot-a"),)), "within trusted scope"),
            (fact(revision="wrong-revision"), "version or hypothesis reference is invalid"),
        )
        for evidence, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(PlannerError, message):
                plan(context, hypotheses, evidence=(evidence,), spent_cost=0.0, cost_budget=0.0)

    def test_bridge_rejects_snapshot_revision_mismatch(self):
        tools = _IncidentTools()
        with self.assertRaisesRegex(ActionScopeBridgeError, "LOT_SNAPSHOT_BINDING_MISMATCH"):
            build_scoped_action_input(
                tools, "synthetic-research-caller", tools.scope_id,
                snapshot_lease_provider=_lease_provider(bad_revision=True), page_size=1)


if __name__ == "__main__":
    unittest.main()
