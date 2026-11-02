import unittest

from research.fbm_split_integrity_synthetic_20261102 import MaskRecord, validate_split_integrity


def record(sample, role, n, *, family=None, ancestry=(), derived=(), claimed=None):
    mask = bytearray(192 * 192)
    mask[n] = 1
    return MaskRecord(sample, family or f"family-{sample}", role, bytes(mask),
                      (192, 192), "uint8", tuple(ancestry), tuple(derived), claimed)


def complete_roles(*rows):
    present = {row.role for row in rows}
    return list(rows) + [record(f"baseline-{role}", role, 100 + index)
                         for index, role in enumerate(("pilot", "development", "gallery", "query", "holdout"))
                         if role not in present]


class SplitIntegrityTests(unittest.TestCase):
    def test_valid_roles_and_all_role_pairs(self):
        rows = [record(role, role, index) for index, role in enumerate(
            ("pilot", "development", "gallery", "query", "holdout"))]
        result = validate_split_integrity(rows)
        self.assertEqual(len(result["cross_role_pairs_checked"]), 10)
        self.assertEqual(result["roles_present"], ["pilot", "development", "gallery", "query", "holdout"])
        self.assertIn("not_implemented", result["near_duplicate_audit"])

    def test_same_role_exact_mask_reuse_is_allowed(self):
        rows = [record("a", "gallery", 10, family="f", derived=("variant-a",)),
                record("b", "gallery", 10, family="f", derived=("variant-b",))]
        rows = complete_roles(*rows)
        self.assertEqual(validate_split_integrity(rows)["sample_count"], 6)

    def test_rejects_family_ancestry_and_exact_mask_cross_role(self):
        with self.assertRaisesRegex(ValueError, "family leakage"):
            validate_split_integrity(complete_roles(record("a", "pilot", 1, family="same"),
                                                    record("b", "query", 2, family="same")))
        with self.assertRaisesRegex(ValueError, "ancestry leakage"):
            validate_split_integrity(complete_roles(record("a", "pilot", 1, ancestry=("root",)),
                                                    record("b", "query", 2, derived=("root",))))
        with self.assertRaisesRegex(ValueError, "exact mask duplicate"):
            validate_split_integrity(complete_roles(record("a", "pilot", 1), record("b", "query", 1)))

    def test_rejects_missing_roles_and_does_not_infer_ancestry_prefix(self):
        with self.assertRaisesRegex(ValueError, "missing required roles: development"):
            validate_split_integrity([record(role, role, index) for index, role in enumerate(
                ("pilot", "gallery", "query", "holdout"))])
        rows = complete_roles(record("a", "pilot", 1, ancestry=("root/flip",)),
                              record("b", "query", 2, derived=("root/rotate",)))
        result = validate_split_integrity(rows)
        self.assertEqual(len(result["cross_role_pairs_checked"]), 10)
        self.assertIn("not inferred", result["lineage_completeness"])

    def test_recomputes_and_validates_mask_input(self):
        with self.assertRaisesRegex(ValueError, "claimed mask hash"):
            validate_split_integrity(complete_roles(record("a", "pilot", 1, claimed="0" * 64)))
        bad = MaskRecord("a", "f", "pilot", b"x", (192, 192), "uint8")
        with self.assertRaisesRegex(ValueError, "byte length"):
            validate_split_integrity(complete_roles(bad))
        nonbinary = bytearray(192 * 192)
        nonbinary[0] = 2
        bad = MaskRecord("a", "f", "pilot", bytes(nonbinary), (192, 192), "uint8")
        with self.assertRaisesRegex(ValueError, "only 0/1"):
            validate_split_integrity(complete_roles(bad))


if __name__ == "__main__":
    unittest.main()
