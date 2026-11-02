import json
import unittest

import numpy as np

from research import fbm_class_position_synthetic_generator_20261102 as study


class ClassPositionSyntheticGeneratorTests(unittest.TestCase):
    def test_pairs_share_fail_mask_bytes_and_have_complement_maps(self):
        samples = study.generate(7)
        groups = {}
        for sample in samples:
            groups.setdefault(sample.family_id, []).append(sample)
        self.assertEqual(len(groups), 15)
        for pair in groups.values():
            self.assertEqual(len(pair), 2)
            a, b = sorted(pair, key=lambda s: s.true_class)
            self.assertEqual((a.true_class, b.true_class), ("A", "B"))
            self.assertEqual(a.fail_mask.tobytes(), b.fail_mask.tobytes())
            self.assertEqual(a.raw_array.tobytes(), b.raw_array.tobytes())
            self.assertEqual(int(a.fail_mask.sum()), 20)
            self.assertTrue(np.all(a.id_maps["A"][a.fail_mask] + a.id_maps["B"][a.fail_mask] == 3))
            for sample in pair:
                self.assertEqual(int((sample.id_maps[sample.true_class] == 1).sum()), 10)
                self.assertEqual(int((sample.id_maps[sample.true_class] == 2).sum()), 10)

    def test_roles_have_disjoint_families_and_exact_masks(self):
        samples = study.generate(19)
        roles = {role: [s for s in samples if s.role == role] for role in study.ROLES}
        for role, items in roles.items():
            self.assertEqual(len(items), 6)
            self.assertEqual({s.true_class for s in items}, {"A", "B"})
            self.assertEqual(len({s.family_id for s in items}), 3)
        for i, role in enumerate(study.ROLES):
            for other in study.ROLES[i + 1:]:
                self.assertTrue({s.metadata["mask_hash"] for s in roles[role]}.isdisjoint(
                    {s.metadata["mask_hash"] for s in roles[other]}))
                self.assertTrue({s.family_id for s in roles[role]}.isdisjoint(
                    {s.family_id for s in roles[other]}))

    def test_regimes_are_balanced_and_position_contract_is_explicit(self):
        samples = study.generate(2)
        for regime in study.REGIMES:
            items = [s for s in samples if s.regime == regime]
            self.assertEqual(len(items), 10)
            self.assertEqual(sum(s.true_class == "A" for s in items), 5)
            self.assertEqual(sum(s.true_class == "B" for s in items), 5)
            self.assertTrue(all(study.POSITION_DEFINITION[regime] in s.metadata["position_definition"]
                                for s in items))
        note = study.LIMITATIONS
        self.assertIn("not field-measured raw FBM", note)
        self.assertIn("not a claim that a family has an invariant class", note)
        self.assertIn("must not both be represented as roster entries", note)

    def test_determinism_opaque_ids_and_manifest_roundtrip(self):
        first, second = study.generate(11), study.generate(11)
        self.assertEqual([s.sample_id for s in first], [s.sample_id for s in second])
        self.assertEqual(len({s.sample_id for s in first}), len(first))
        self.assertTrue(all(len(s.sample_id) == 32 for s in first))
        for a, b in zip(first, second):
            self.assertEqual(a.family_id, b.family_id)
            self.assertEqual(a.fail_mask.tobytes(), b.fail_mask.tobytes())
            self.assertEqual(a.id_maps["A"].tobytes(), b.id_maps["A"].tobytes())
            self.assertEqual(a.id_maps["B"].tobytes(), b.id_maps["B"].tobytes())
        encoded = json.dumps(study.manifest(11), sort_keys=True)
        roundtrip = json.loads(json.dumps(json.loads(encoded), sort_keys=True))
        self.assertEqual(json.loads(encoded), roundtrip)
        self.assertIn("duplicate family IDs", roundtrip["roster_constraint"])

    def test_invalid_seed_rejected(self):
        with self.assertRaises(ValueError):
            study.generate(-1)
        with self.assertRaises(ValueError):
            study.generate(True)

    def test_default_remains_30_samples_and_multi_family_configuration(self):
        self.assertEqual(len(study.generate(20261102)), 30)
        counts = {"pilot": 1, "development": 1, "gallery": 6, "query": 2, "holdout": 1}
        samples = study.generate(20261102, family_counts=counts)
        self.assertEqual(len(samples), 66)
        for role, count in counts.items():
            role_samples = [s for s in samples if s.role == role]
            self.assertEqual(len({s.family_id for s in role_samples}), count * len(study.REGIMES))
            for regime in study.REGIMES:
                cell = [s for s in role_samples if s.regime == regime]
                self.assertEqual(len(cell), count * 2)
                self.assertEqual(sum(s.true_class == "A" for s in cell), count)
                self.assertEqual(sum(s.true_class == "B" for s in cell), count)

    def test_family_count_input_fails_closed(self):
        good = {role: 1 for role in study.ROLES}
        for invalid in (
            {**good, "extra": 1},
            {role: 1 for role in study.ROLES[:-1]},
            {**good, "gallery": 0},
            {**good, "query": True},
            {**good, "holdout": study.MAX_FAMILIES_PER_ROLE_REGIME + 1},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                study.generate(5, family_counts=invalid)


if __name__ == "__main__":
    unittest.main()
