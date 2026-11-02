import copy
import hashlib
import unittest

import numpy as np

from research import fbm_paired_factorial_synthetic_20261030 as generator
from research import fbm_paired_retrieval_eval_synthetic_20261030 as evaluator


def _hash(array):
    return hashlib.sha256(np.asarray(array).tobytes()).hexdigest()


def _arrays(sample, policy):
    oid = sample.object_id_arrays_by_policy[policy]
    yld = sample.yield_array
    return {"raw": sample.raw_array, "object_id": oid, "yield": yld,
            "object_id_yield": np.stack((oid, yld), axis=-1)}


class PairedRetrievalEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = generator.generate(42)

    def test_fixed_cohort_hits_recall_and_paired_scores(self):
        mapping = {}
        for sample in self.samples:
            for view, array in _arrays(sample, "spatial_coupled").items():
                # Test-only hash fixture; the callable itself receives only ndarray + view.
                class_index = 0 if sample.wafer_class == "A" else 3
                regime_index = generator.REGIMES.index(sample.regime)
                index = regime_index if view == "raw" else class_index + regime_index
                if view in ("object_id", "object_id_yield") and sample.split == "query":
                    index = ((3 if sample.wafer_class == "A" else 0) + regime_index)
                vec = np.zeros(6)
                vec[index] = 1
                mapping[(view, _hash(array))] = vec

        def encode(image_array, view):
            self.assertIs(type(image_array), np.ndarray)
            self.assertNotIsInstance(image_array, generator.Sample)
            return mapping[(view, _hash(image_array))]

        result = evaluator.evaluate(self.samples, encode, label_policy="spatial_coupled", error_rate=0, reject_rate=0)
        self.assertEqual((result["query_count"], result["gallery_count"]), (12, 12))
        self.assertEqual(result["arms"]["raw_only"]["n"], 12)
        self.assertEqual(result["arms"]["object_id_only"]["mean_hit_at_1"], 0.0)
        self.assertEqual(result["arms"]["object_id_only"]["mean_recall_at_1"], 0.0)
        delta = result["arms"]["object_id_only"]["mean_hit_at_3"] - result["arms"]["raw_only"]["mean_hit_at_3"]
        self.assertEqual(result["paired_mean_differences_vs_raw"]["object_id_only"]["hit_at_3"], delta)
        for q in result["per_query"]:
            row = q["arms"]["raw_only"]
            self.assertEqual(len(row["candidate_ids"]), 12)
            self.assertEqual(set(row["ranks"].values()), set(range(1, 13)))
            self.assertEqual(row["recall_at_3"], sum(row["ranks"][sid] <= 3 for sid in q["relevant_candidate_ids"]) / 2)

    def test_ties_use_lineage_then_sample_id_and_hit_any_relevant(self):
        result = evaluator.evaluate(self.samples, lambda image, view: np.array([1.0, 0.0]), label_policy="spatial_coupled")
        q = result["per_query"][0]
        ordered = q["arms"]["raw_only"]["candidate_ids"]
        seed = self.samples[0].master_seed
        expected = sorted((s for s in self.samples if s.split == "gallery"),
                          key=lambda s: (hashlib.sha256(f"fbm-tie-v1|{seed}|{s.sample_id}".encode("utf-8")).hexdigest(), s.sample_id))
        self.assertEqual(ordered, [s.sample_id for s in expected])
        repeated = evaluator.evaluate(self.samples, lambda image, view: np.array([1.0, 0.0]), label_policy="spatial_coupled")
        self.assertEqual(ordered, repeated["per_query"][0]["arms"]["raw_only"]["candidate_ids"])
        first_rel = min(q["arms"]["raw_only"]["ranks"][sid] for sid in q["relevant_candidate_ids"])
        self.assertEqual(q["arms"]["raw_only"]["hit_at_3"], int(first_rel <= 3))

    def test_seeded_tie_order_is_not_fixed_a_before_b_across_five_seeds(self):
        a_before_b = b_before_a = 0
        for seed in generator.SEEDS:
            samples = generator.generate(seed)
            result = evaluator.evaluate(samples, lambda image, view: np.array([1.0, 0.0]), label_policy="spatial_coupled")
            ranks = result["per_query"][0]["arms"]["raw_only"]["ranks"]
            groups = {}
            for sample in samples:
                if sample.split == "gallery":
                    groups.setdefault(sample.lineage_group_id, []).append(sample)
            for pair in groups.values():
                a = next(s for s in pair if s.wafer_class == "A")
                b = next(s for s in pair if s.wafer_class == "B")
                a_before_b += ranks[a.sample_id] < ranks[b.sample_id]
                b_before_a += ranks[b.sample_id] < ranks[a.sample_id]
        self.assertGreater(a_before_b, 0)
        self.assertGreater(b_before_a, 0)

    def test_tie_summary_zero_tie_and_complete_tie(self):
        arrays = [_arrays(s, "spatial_coupled")["object_id"] for s in self.samples]
        hashes = [_hash(a) for a in arrays]
        self.assertEqual(len(hashes), len(set(hashes)), "fixture requires unique object-ID arrays")
        vectors = {}
        for digest in hashes:
            rng = np.random.default_rng(int(digest[:16], 16))
            vectors[digest] = rng.normal(size=32)
        def untied_encoder(image, view):
            return vectors[_hash(image)] if view == "object_id" else [1.0, 0.0]

        untied = evaluator.evaluate(self.samples, untied_encoder, label_policy="spatial_coupled")
        self.assertTrue(all(row["tie_summary"]["object_id_only"]["score_tie_group_count"] == 0
                            for row in untied["per_query"]))
        self.assertEqual(untied["tie_summary_by_arm"]["object_id_only"]["tie_group_count"], 0)

        tied = evaluator.evaluate(self.samples, lambda image, view: [1.0, 0.0], label_policy="spatial_coupled")
        for row in tied["per_query"]:
            summary = row["tie_summary"]["object_id_only"]
            self.assertEqual(summary["score_tie_group_count"], 1)
            self.assertEqual(summary["tied_candidate_count"], 12)
            self.assertEqual(summary["tied_candidate_wafer_class_counts"], {"A": 6, "B": 6})
        self.assertEqual(tied["tie_summary_by_arm"]["object_id_only"]["tie_group_count"], 12)

    def test_hit_at_3_differs_from_recall_at_3_when_one_or_two_relevant_are_found(self):
        """Test-only fake embeddings exercise the full evaluator's metric equations."""
        query = next(s for s in self.samples if s.split == "query")
        gallery = [s for s in self.samples if s.split == "gallery"]
        relevant = [s for s in gallery if (s.wafer_class, s.regime) == (query.wafer_class, query.regime)]
        irrelevant = [s for s in gallery if s not in relevant]
        self.assertEqual(len(relevant), 2)

        def run(found_two):
            mapping = {_hash(_arrays(query, "spatial_coupled")["object_id"]): np.array([1.0, 0.0, 0.0])}
            mapping[_hash(_arrays(relevant[0], "spatial_coupled")["object_id"])] = np.array([1.0, 0.0, 0.0])
            if found_two:
                mapping[_hash(_arrays(relevant[1], "spatial_coupled")["object_id"])] = np.array([0.8, 0.6, 0.0])
            else:
                mapping[_hash(_arrays(relevant[1], "spatial_coupled")["object_id"])] = np.array([0.5, np.sqrt(0.75), 0.0])
                mapping[_hash(_arrays(irrelevant[0], "spatial_coupled")["object_id"])] = np.array([0.8, 0.6, 0.0])
                mapping[_hash(_arrays(irrelevant[1], "spatial_coupled")["object_id"])] = np.array([0.7, np.sqrt(0.51), 0.0])

            def fake_encoder(image_array, view):
                self.assertIs(type(image_array), np.ndarray)
                if view == "object_id":
                    return mapping.get(_hash(image_array), np.array([0.0, 0.0, 1.0]))
                return np.array([0.0, 0.0, 1.0])

            return evaluator.evaluate(self.samples, fake_encoder, label_policy="spatial_coupled")

        one_found = next(row for row in run(False)["per_query"] if row["query_id"] == query.sample_id)["arms"]["object_id_only"]
        self.assertEqual(one_found["hit_at_3"], 1)
        self.assertEqual(one_found["recall_at_3"], 0.5)
        two_found = next(row for row in run(True)["per_query"] if row["query_id"] == query.sample_id)["arms"]["object_id_only"]
        self.assertEqual(two_found["hit_at_3"], 1)
        self.assertEqual(two_found["recall_at_3"], 1.0)

    def test_rejects_cross_split_group_or_duplicate_mask_hash(self):
        samples = copy.deepcopy(self.samples)
        object.__setattr__(samples[12], "fail_mask", samples[0].fail_mask.copy())
        samples[12].metadata["mask_hash"] = samples[0].metadata["mask_hash"]
        with self.assertRaisesRegex(ValueError, "duplicate mask hash"):
            evaluator.evaluate(samples, lambda image, view: [1.0], label_policy="spatial_coupled")
        samples = copy.deepcopy(self.samples)
        object.__setattr__(samples[0], "lineage_group_id", samples[12].lineage_group_id)
        with self.assertRaisesRegex(ValueError, "lineage group crosses"):
            evaluator.evaluate(samples, lambda image, view: [1.0], label_policy="spatial_coupled")

    def test_mask_hash_is_recomputed_from_fail_mask(self):
        samples = copy.deepcopy(self.samples)
        samples[0].metadata["mask_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "disagrees with fail mask"):
            evaluator.evaluate(samples, lambda image, view: [1.0], label_policy="spatial_coupled")

        samples = copy.deepcopy(self.samples)
        gallery = next(s for s in samples if s.split == "gallery")
        query = next(s for s in samples if s.split == "query")
        object.__setattr__(query, "fail_mask", gallery.fail_mask.copy())
        query.metadata["mask_hash"] = gallery.metadata["mask_hash"]
        with self.assertRaisesRegex(ValueError, "duplicate mask hash across gallery/query"):
            evaluator.evaluate(samples, lambda image, view: [1.0], label_policy="spatial_coupled")

    def test_encoder_gets_only_copied_arrays_and_rejects_invalid_vectors(self):
        originals = [s.raw_array.copy() for s in self.samples]
        seen = []

        def mutate_copy(image, view):
            self.assertIs(type(image), np.ndarray)
            seen.append((view, image.shape))
            image.flat[0] = 99
            return [1.0]

        evaluator.evaluate(self.samples, mutate_copy, label_policy="spatial_coupled")
        self.assertTrue(seen)
        self.assertTrue(all(np.array_equal(before, sample.raw_array) for before, sample in zip(originals, self.samples)))
        with self.assertRaises(ValueError):
            evaluator.evaluate(self.samples, lambda image, view: [np.nan], label_policy="spatial_coupled")
        with self.assertRaises(KeyError):
            evaluator.evaluate(self.samples, lambda image, view: (_ for _ in ()).throw(KeyError(view)), label_policy="spatial_coupled")

    def test_rejects_candidate_mismatch_and_counterparts_stay_within_split(self):
        with self.assertRaisesRegex(ValueError, "exactly 12 gallery and 12 query"):
            evaluator.evaluate(self.samples[:-1], lambda image, view: [1.0], label_policy="spatial_coupled")
        grouped = {}
        for sample in self.samples:
            grouped.setdefault(sample.lineage_group_id, []).append(sample)
        for pair in grouped.values():
            self.assertEqual(len(pair), 2)
            self.assertEqual({s.split for s in pair}, {pair[0].split})
            self.assertEqual({s.metadata["mask_hash"] for s in pair}, {pair[0].metadata["mask_hash"]})


if __name__ == "__main__":
    unittest.main()
