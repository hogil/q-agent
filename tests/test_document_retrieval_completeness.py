import copy
import unittest

from app.document_evidence_contract import validate_hybrid_response


def _item():
    return {
        "document_id": "SYN-DOC-1", "chunk_id": "SYN-CHUNK-1", "version": "v1",
        "text": "Synthetic fixture text.", "source_ref": "synthetic://document/1",
        "locator": "chunk:1", "status": "active",
        "available_at": "2026-03-01T00:00:00+09:00", "incident_ids": ["INC-1"],
        "relation": "direct", "score": 1.0, "observed_at": None,
        "effective_from": None, "effective_to": None, "applicability": None,
    }


def _response(*, items=None, status="OK", **metadata):
    return {
        "status": status, "retrieval_method": "bm25_vector_hybrid",
        "as_of": "2026-03-31", "items": [_item()] if items is None and status == "OK" else (items or []),
        **metadata,
    }


def _validate(response, *, top_k=5):
    return validate_hybrid_response(
        response, source_kind="engineer_notes", incident_ids=["INC-1"],
        as_of="2026-03-31", timezone_name="Asia/Seoul", top_k=top_k,
        allowed_statuses=["active"],
    )


class DocumentRetrievalCompletenessTests(unittest.TestCase):
    def test_reports_true_false_and_unknown_without_inference(self):
        cases = (
            ({"truncated": True, "candidate_count": 0}, True, 0, "source_reported_truncated"),
            ({"truncated": False, "candidate_count": 99}, False, 99, "source_reported_not_truncated"),
            ({}, None, None, "unknown"),
            ({"truncated": None, "candidate_count": None}, None, None, "unknown"),
        )
        for metadata, truncated, count, completeness in cases:
            with self.subTest(metadata=metadata):
                result = _validate(_response(**metadata))
                self.assertEqual(result["source_reported_truncated"], truncated)
                self.assertEqual(result["source_reported_candidate_count"], count)
                self.assertEqual(result["retrieval_completeness"], completeness)
                self.assertEqual(result["candidate_count_basis"], "source_reported_unverified")

    def test_candidate_count_accepts_zero_and_rejects_invalid_values(self):
        self.assertEqual(_validate(_response(candidate_count=0))["source_reported_candidate_count"], 0)
        for value in (True, False, -1, 1.5, "1", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate(_response(candidate_count=value))

    def test_truncated_requires_boolean_or_null(self):
        for value in (0, 1, "false", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate(_response(truncated=value))

    def test_top_k_and_no_match_preserve_source_claim_scope(self):
        limited = _validate(_response(truncated=True, candidate_count=50), top_k=1)
        self.assertEqual(len(limited["items"]), 1)
        no_match = _validate(_response(status="NO_MATCH", truncated=False, candidate_count=0))
        self.assertEqual(no_match["status"], "NO_MATCH")
        self.assertEqual(no_match["items"], [])
        self.assertEqual(no_match["retrieval_completeness"], "source_reported_not_truncated")
        self.assertEqual(no_match["source_reported_candidate_count"], 0)

    def test_original_callback_fixture_is_not_mutated(self):
        fixture = _response(truncated=False, candidate_count=1)
        original = copy.deepcopy(fixture)
        normalized = _validate(fixture)
        self.assertEqual(fixture, original)
        self.assertEqual(normalized["items"][0]["incident_ids"], ["INC-1"])

    def test_normalized_metadata_survives_revalidation(self):
        first = _validate(_response(truncated=True, candidate_count=17))
        second = _validate(first)
        self.assertEqual(second["source_reported_truncated"], True)
        self.assertEqual(second["source_reported_candidate_count"], 17)
        self.assertEqual(second["retrieval_completeness"], "source_reported_truncated")
        self.assertEqual(second["candidate_count_basis"], "source_reported_unverified")

    def test_raw_normalized_conflicts_and_unsupported_claims_fail_closed(self):
        normalized = _validate(_response(truncated=True, candidate_count=17))
        conflicts = (
            {**normalized, "truncated": False},
            {**normalized, "candidate_count": 18},
            {**normalized, "retrieval_completeness": "unknown"},
            {**normalized, "candidate_count_basis": "verified_total"},
        )
        for response in conflicts:
            with self.subTest(response=response), self.assertRaises(ValueError):
                _validate(response)

    def test_legacy_raw_metadata_remains_supported(self):
        result = _validate(_response(truncated=False, candidate_count=3))
        self.assertEqual(result["source_reported_truncated"], False)
        self.assertEqual(result["source_reported_candidate_count"], 3)


if __name__ == "__main__":
    unittest.main()
