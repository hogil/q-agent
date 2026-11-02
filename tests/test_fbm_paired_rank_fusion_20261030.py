import copy
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "research/fbm_paired_rank_fusion_20261030.py"
SPEC = importlib.util.spec_from_file_location("fbm_paired_rank_fusion_20261030", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    classes = ["a", "b", "c", "d"]
    result = {"experiment_scope": "small synthetic functionality probe", "results": {}}
    for rep in ("raw_fbm", "object_id_yield"):
        queries = []
        for qi in range(8):
            label = classes[qi // 2]
            ranking = []
            for rank in range(1, 9):
                idx = (rank - 1) if rep == "raw_fbm" else (rank - 1)
                gallery_label = classes[idx // 2]
                ranking.append({"rank": rank, "asset_id": f"g{idx}", "label": gallery_label,
                                "similarity": 1.0 - rank / 100 + qi / 10000})
            queries.append({"query_asset_id": f"q{qi}", "query_label": label, "ranking": ranking})
        result["results"][rep] = {"queries": queries}
    return result


class PairedRankFusionTests(unittest.TestCase):
    def test_validation_accepts_full_paired_input(self):
        reps, labels = MODULE._validate(fixture())
        self.assertEqual(len(reps["raw_fbm"]), 8)
        self.assertEqual(labels["q0"], "a")

    def test_missing_duplicate_and_mismatched_labels_fail(self):
        d = fixture()
        del d["results"]["raw_fbm"]["queries"][0]["ranking"][0]["label"]
        with self.assertRaisesRegex(ValueError, "missing gallery label"):
            MODULE._validate(d)
        d = fixture()
        d["results"]["raw_fbm"]["queries"][0]["ranking"][1]["asset_id"] = "g0"
        with self.assertRaisesRegex(ValueError, "duplicate gallery ID"):
            MODULE._validate(d)
        d = fixture()
        d["results"]["object_id_yield"]["queries"][0]["query_label"] = "wrong"
        with self.assertRaisesRegex(ValueError, "query label mismatch"):
            MODULE._validate(d)
        d = fixture()
        d["results"]["object_id_yield"]["queries"][0]["ranking"][0]["label"] = "wrong"
        with self.assertRaisesRegex(ValueError, "gallery label mismatch"):
            MODULE._validate(d)

    def test_ties_use_asset_id_hash_only(self):
        rows = [{"asset_id": "z", "fusion_score": 1.0}, {"asset_id": "a", "fusion_score": 1.0}]
        expected = sorted(rows, key=lambda x: __import__("hashlib").sha256(x["asset_id"].encode()).hexdigest())
        self.assertEqual(MODULE._order(rows, "fusion_score"), expected)

    def test_fusion_formula_and_rank_fields(self):
        d = fixture()
        out = MODULE.analyze(d)
        q = next(x for x in out["fused_queries"]["rrf"] if x["query_asset_id"] == "q0")
        first = q["ranking"][0]
        self.assertEqual(first["fusion_score"], 2 / 61)
        mean = next(x for x in out["fused_queries"]["mean_cosine"] if x["query_asset_id"] == "q0")
        self.assertAlmostEqual(mean["ranking"][0]["fusion_score"], (0.99 + 0.99) / 2)
        self.assertEqual([x["rank"] for x in q["ranking"]], list(range(1, 9)))

    def test_aggregate_and_pairwise_changes(self):
        d = fixture()
        out = MODULE.analyze(d)
        self.assertEqual(out["metrics"]["rrf"]["overall"]["queries"], 8)
        self.assertEqual(out["metrics"]["rrf"]["by_query_class"]["a"]["queries"], 2)
        pair = out["paired_changes_vs_baselines"]["rrf"]["raw_fbm"]["top1"]
        self.assertEqual(pair["improved_queries"] + pair["worsened_queries"] + pair["unchanged_queries"], 8)
        self.assertEqual(out["random_rank_reference"]["top1_accuracy"], 0.25)
        self.assertAlmostEqual(out["random_rank_reference"]["top3_accuracy"], 9 / 14)


if __name__ == "__main__":
    unittest.main()
