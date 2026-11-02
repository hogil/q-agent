import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from mes_reference_contract import validate_mes_reference_response


class MESReferenceScopeContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = ["INC-1", "INC-2"]
        self.as_of = "2026-10-30"

    def item(self, *, record_id="R-1", relation="current_scope", incident_ids=None,
             applicability="confirmed", available_at="2026-10-29T12:00:00+09:00",
             effective_from="2026-10-01", effective_to=None):
        return {
            "kind": "procedure",
            "record_id": record_id,
            "version": "v1",
            "name": "Synthetic procedure",
            "source_ref": "synthetic://procedure/R-1",
            "available_at": available_at,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "applicability": applicability,
            "scope_relation": relation,
            "incident_ids": list(incident_ids if incident_ids is not None else ["INC-1"]),
        }

    def response(self, items, *, candidate_count=None, truncated=False, status="OK"):
        if candidate_count is None:
            candidate_count = len(items)
        return {
            "status": status,
            "as_of": self.as_of,
            "incident_ids": list(self.scope),
            "items": items,
            "truncated": truncated,
            "candidate_count": candidate_count,
        }

    def validate(self, response, *, top_k=10):
        return validate_mes_reference_response(
            response,
            incident_ids=self.scope,
            as_of=self.as_of,
            timezone_name="Asia/Seoul",
            allowed_kinds={"procedure"},
            top_k=top_k,
        )

    def validate_at(self, response, *, as_of, timezone_name):
        return validate_mes_reference_response(
            response,
            incident_ids=self.scope,
            as_of=as_of,
            timezone_name=timezone_name,
            allowed_kinds={"procedure"},
            top_k=10,
        )

    def test_valid_mixed_multi_scope_and_catalog_candidate(self):
        items = [
            self.item(record_id="R-1", incident_ids=["INC-1", "INC-2"]),
            self.item(record_id="R-2", relation="catalog_candidate", incident_ids=[]),
        ]
        result = self.validate(self.response(items))
        self.assertEqual(result["items"][0]["incident_ids"], ["INC-1", "INC-2"])
        self.assertEqual(result["items"][0]["scope_relation"], "current_scope")
        self.assertEqual(result["items"][1]["incident_ids"], [])
        self.assertEqual(result["items"][1]["scope_relation"], "catalog_candidate")

    def test_catalog_candidate_with_incident_ids_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "catalog_candidate incident_ids must be empty"):
            self.validate(self.response([
                self.item(relation="catalog_candidate", incident_ids=["INC-1"])
            ]))

    def test_out_of_scope_and_duplicate_item_incident_ids_are_rejected(self):
        for incident_ids in (["INC-3"], ["INC-1", "INC-1"]):
            with self.subTest(incident_ids=incident_ids):
                with self.assertRaises(ValueError):
                    self.validate(self.response([self.item(incident_ids=incident_ids)]))

    def test_current_scope_empty_ids_fail_but_nonempty_subset_is_valid(self):
        with self.assertRaisesRegex(ValueError, "current_scope incident_ids must be a nonempty subset"):
            self.validate(self.response([self.item(incident_ids=[])]))
        result = self.validate(self.response([self.item(incident_ids=["INC-2"])]))
        self.assertEqual(result["items"][0]["incident_ids"], ["INC-2"])

    def test_applicability_labels_are_preserved_independently_of_relation(self):
        for relation, ids in (("current_scope", ["INC-1"]), ("catalog_candidate", [])):
            for label in ("confirmed", "candidate", "unknown"):
                with self.subTest(relation=relation, applicability=label):
                    result = self.validate(self.response([
                        self.item(record_id=f"{relation}-{label}", relation=relation,
                                  incident_ids=ids, applicability=label)
                    ]))
                    self.assertEqual(result["items"][0]["applicability"], label)

    def test_truncation_count_invariants_are_enforced(self):
        item = self.item()
        accepted = self.validate(self.response([item], candidate_count=3, truncated=True), top_k=1)
        self.assertTrue(accepted["truncated"])
        self.assertEqual(accepted["candidate_count"], 3)
        for candidate_count, truncated in ((1, True), (2, False), (0, False)):
            with self.subTest(candidate_count=candidate_count, truncated=truncated):
                with self.assertRaises(ValueError):
                    self.validate(self.response([item], candidate_count=candidate_count,
                                                truncated=truncated), top_k=1)

    def test_available_at_cutoff_is_exclusive_and_effective_end_is_inclusive(self):
        before = self.item(available_at="2026-10-29T23:59:59+09:00")
        self.assertEqual(self.validate(self.response([before]))["items"][0]["time_status"], "active")

        at_cutoff = self.item(available_at="2026-10-31T00:00:00+09:00")
        with self.assertRaisesRegex(ValueError, "available_at must be before"):
            self.validate(self.response([at_cutoff]))

        ends_at_boundary = self.item(effective_to="2026-10-31")
        self.assertEqual(
            self.validate(self.response([ends_at_boundary]))["items"][0]["time_status"],
            "active",
        )

    def test_berlin_dst_fold_compares_effective_interval_by_utc_instant(self):
        item = self.item(
            available_at="2026-10-25T12:00:00+02:00",
            effective_from="2026-10-25T02:45:00+02:00",
            effective_to="2026-10-25T02:15:00+01:00",
        )
        response = self.response([item])
        response["as_of"] = "2026-10-25"
        result = self.validate_at(response, as_of="2026-10-25", timezone_name="Europe/Berlin")
        self.assertEqual(result["items"][0]["time_status"], "expired")

        reversed_item = self.item(
            available_at="2026-10-25T12:00:00+02:00",
            effective_from="2026-10-25T02:15:00+01:00",
            effective_to="2026-10-25T02:45:00+02:00",
        )
        reversed_response = self.response([reversed_item])
        reversed_response["as_of"] = "2026-10-25"
        with self.assertRaisesRegex(ValueError, "effective_from must be before effective_to"):
            self.validate_at(reversed_response, as_of="2026-10-25", timezone_name="Europe/Berlin")

    def test_berlin_as_of_cutoff_uses_utc_instant_and_date_local_midnight(self):
        before = self.item(
            available_at="2026-10-25T23:59:59+01:00",
            effective_from="2026-10-01",
            effective_to="2026-10-26",
        )
        response = self.response([before])
        response["as_of"] = "2026-10-25"
        result = self.validate_at(response, as_of="2026-10-25", timezone_name="Europe/Berlin")
        self.assertEqual(result["items"][0]["time_status"], "active")

        at_cutoff = self.item(
            available_at="2026-10-26T00:00:00+01:00",
            effective_from="2026-10-01",
            effective_to="2026-10-26",
        )
        cutoff_response = self.response([at_cutoff])
        cutoff_response["as_of"] = "2026-10-25"
        with self.assertRaisesRegex(ValueError, "available_at must be before"):
            self.validate_at(cutoff_response, as_of="2026-10-25", timezone_name="Europe/Berlin")

        starts_at_cutoff = self.item(
            available_at="2026-10-25T12:00:00+02:00",
            effective_from="2026-10-26T00:00:00+01:00",
            effective_to=None,
        )
        status_response = self.response([starts_at_cutoff])
        status_response["as_of"] = "2026-10-25"
        status_result = self.validate_at(
            status_response, as_of="2026-10-25", timezone_name="Europe/Berlin"
        )
        self.assertEqual(status_result["items"][0]["time_status"], "future")


if __name__ == "__main__":
    unittest.main()
