import unittest

from research.fbm_split_integrity_synthetic_20261102 import MaskRecord
from research.fbm_mask_symmetry_candidates_synthetic_20261102 import _d4, find_mask_symmetry_candidates


N = 192


def record(sample_id, role, bits):
    return MaskRecord(sample_id, f"family-{sample_id}", role, bytes(bits), (N, N), "uint8")


def rotate(bits):
    return [bits[(N - 1 - c) * N + r] for r in range(N) for c in range(N)]


def flip_lr(bits):
    return [bits[r * N + (N - 1 - c)] for r in range(N) for c in range(N)]


def pattern():
    bits = [0] * (N * N)
    for r, c in ((9, 13), (9, 14), (31, 27), (48, 19), (48, 20), (48, 21)):
        bits[r * N + c] = 1
    return bits


class MaskSymmetryCandidatesTests(unittest.TestCase):
    def test_rotation_and_reflection_hits_and_determinism(self):
        base = pattern()
        rotated = rotate(base)
        reflected = flip_lr(base)
        rows = [record("pilot-a", "pilot", base), record("query-r", "query", rotated),
                record("holdout-f", "holdout", reflected)]
        result = find_mask_symmetry_candidates(rows)
        self.assertEqual(result, find_mask_symmetry_candidates(reversed(rows)))
        self.assertEqual(result["candidate_count"], 3)
        for pair in result["candidate_pairs"]:
            self.assertTrue(pair["canonical_sha256"])
            self.assertTrue(pair["matching_transforms_left_to_right"])
        self.assertIn("not establish ancestry", result["interpretation"])

    def test_all_eight_transforms_are_distinct_and_exact(self):
        marked = [0] * (N * N)
        marked[7 * N + 19] = 1
        marked[23 * N + 41] = 1
        base = tuple(bytes(marked[r * N:(r + 1) * N]) for r in range(N))
        variants = dict(_d4(base))
        self.assertEqual(len(variants), 8)
        self.assertEqual(len(set(variants.values())), 8)
        expected = {
            "identity": {(7, 19), (23, 41)},
            "rot90": {(19, 184), (41, 168)},
            "rot180": {(184, 172), (168, 150)},
            "rot270": {(172, 7), (150, 23)},
            "identity_then_flip_lr": {(7, 172), (23, 150)},
            "rot90_then_flip_lr": {(172, 184), (150, 168)},
            "rot180_then_flip_lr": {(184, 19), (168, 41)},
            "rot270_then_flip_lr": {(19, 7), (41, 23)},
        }
        actual = {
            name: {(r, c) for r in range(N) for c in range(N)
                   if data[r * N + c]}
            for name, data in variants.items()
        }
        self.assertEqual(actual, expected)

    def test_transform_names_are_left_to_right(self):
        base = pattern()
        rotated = rotate(base)
        result = find_mask_symmetry_candidates([
            record("a-source", "pilot", base), record("b-target", "query", rotated)
        ])
        pair = result["candidate_pairs"][0]
        self.assertEqual(pair["left"]["sample_id"], "a-source")
        self.assertEqual(pair["right"]["sample_id"], "b-target")
        self.assertEqual(pair["matching_transforms_left_to_right"], ["rot90"])

    def test_asymmetric_negative(self):
        base = pattern()
        altered = base.copy()
        altered[80 * N + 81] = 1
        result = find_mask_symmetry_candidates([record("a", "pilot", base), record("b", "query", altered)])
        self.assertEqual(result["candidate_pairs"], [])

    def test_same_role_and_self_pairs_excluded(self):
        base = pattern()
        result = find_mask_symmetry_candidates([record("a", "pilot", base), record("b", "pilot", rotate(base))])
        self.assertEqual(result["candidate_count"], 0)

    def test_input_contract(self):
        with self.assertRaises(ValueError):
            find_mask_symmetry_candidates([])
        with self.assertRaises(ValueError):
            find_mask_symmetry_candidates([record("a", "bad-role", pattern())])
        bad = MaskRecord("a", "family-a", "pilot", bytes([2]) + bytes(N * N - 1), (N, N), "uint8")
        with self.assertRaises(ValueError):
            find_mask_symmetry_candidates([bad])
        with self.assertRaises(ValueError):
            find_mask_symmetry_candidates([record("a", "pilot", pattern()), record("a", "query", pattern())])


if __name__ == "__main__":
    unittest.main()
