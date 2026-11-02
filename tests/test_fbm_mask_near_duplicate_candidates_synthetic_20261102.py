import unittest

from research.fbm_split_integrity_synthetic_20261102 import MaskRecord
from research.fbm_mask_near_duplicate_candidates_synthetic_20261102 import (
    MAX_RECORDS,
    find_mask_near_duplicate_candidates,
)


N = 192


def record(sample_id, role, points):
    bits = bytearray(N * N)
    for row, col in points:
        bits[row * N + col] = 1
    return MaskRecord(sample_id, f"family-{sample_id}", role, bytes(bits), (N, N), "uint8")


def rotate(points):
    return {(col, N - 1 - row) for row, col in points}


class MaskNearDuplicateCandidatesTests(unittest.TestCase):
    def test_rotation_selects_left_to_right_transform_and_is_deterministic(self):
        points = {(3, 7), (4, 8), (19, 11)}
        rows = [record("a", "pilot", points), record("b", "query", rotate(points))]
        result = find_mask_near_duplicate_candidates(rows, 1.0)
        self.assertEqual(result, find_mask_near_duplicate_candidates(reversed(rows), 1.0))
        pair = result["candidate_pairs"][0]
        self.assertEqual(pair["max_jaccard"], 1.0)
        self.assertEqual(pair["best_transform_left_to_right"], "rot90")

    def test_partial_overlap_manual_jaccard_and_threshold(self):
        left = {(1, 1), (1, 2), (2, 1)}
        right = {(1, 1), (1, 2), (8, 8)}
        result = find_mask_near_duplicate_candidates(
            [record("a", "pilot", left), record("b", "query", right)], 0.5
        )
        # Identity has intersection 2 and union 4, hence Jaccard 0.5.
        pair = result["comparisons"][0]
        self.assertEqual(pair["max_jaccard"], 0.5)
        self.assertEqual(pair["best_transform_left_to_right"], "identity")
        self.assertTrue(pair["candidate"])
        self.assertEqual(result["candidate_count"], 1)

    def test_no_overlap_not_candidate(self):
        result = find_mask_near_duplicate_candidates(
            [record("a", "pilot", {(1, 1)}), record("b", "query", {(10, 10)})], 0.1
        )
        self.assertEqual(result["comparisons"][0]["max_jaccard"], 0.0)
        self.assertEqual(result["candidate_count"], 0)

    def test_two_empty_masks_are_indeterminate_not_similarity_one(self):
        result = find_mask_near_duplicate_candidates(
            [record("a", "pilot", set()), record("b", "query", set())], 0.1
        )
        pair = result["comparisons"][0]
        self.assertEqual(pair["similarity_status"], "indeterminate_both_masks_empty")
        self.assertIsNone(pair["max_jaccard"])
        self.assertFalse(pair["candidate"])

    def test_invalid_thresholds_and_input_contract(self):
        base = [record("a", "pilot", {(1, 1)}), record("b", "query", {(1, 1)})]
        for value in (0, -0.1, 1.1, float("nan"), float("inf"), True, "0.5"):
            with self.subTest(threshold=value), self.assertRaises(ValueError):
                find_mask_near_duplicate_candidates(base, value)
        with self.assertRaises(ValueError):
            find_mask_near_duplicate_candidates([], 0.5)
        with self.assertRaises(ValueError):
            find_mask_near_duplicate_candidates(
                [record("a", "pilot", set()), record("a", "query", set())], 0.5
            )
        with self.assertRaises(ValueError):
            find_mask_near_duplicate_candidates(
                [record(str(i), "pilot", set()) for i in range(MAX_RECORDS + 1)], 0.5
            )


if __name__ == "__main__":
    unittest.main()
