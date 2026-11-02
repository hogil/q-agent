import math
import unittest

from research.fbm_separated_rank_metrics_synthetic_20261102 import score_separated_rank_metrics


class SeparatedRankMetricsTests(unittest.TestCase):
    def setUp(self):
        self.ids = [f"b{i}" for i in range(12)]
        self.rel = {
            "class_only": set(self.ids[:6]),
            "position_only": set(self.ids[3:9]),
            "joint": set(self.ids[3:6]),
        }
        self.kw = {
            "relevance": self.rel,
            "schedule_id": "schedule-x",
            "asserted_class_label_free_blind_ids": True,
            "asserted_encoder_metadata_isolated": True,
        }

    def test_hand_checkable_unique_ranking(self):
        scores = {candidate: 12 - i for i, candidate in enumerate(self.ids)}
        got = score_separated_rank_metrics(scores=scores, **self.kw)
        self.assertEqual(got["ranking"], self.ids)
        self.assertEqual(got["metrics"]["class_only"]["hit_at_3"], 1.0)
        self.assertEqual(got["metrics"]["class_only"]["recall_at_3"], 0.5)
        self.assertEqual(got["metrics"]["class_only"]["mrr"], 1.0)
        self.assertEqual(got["metrics"]["class_only"]["ndcg_at_3"], 1.0)
        self.assertEqual(got["metrics"]["position_only"]["mrr"], 0.25)
        self.assertEqual(got["metrics"]["joint"]["expected_hit_at_3_uniform_boundary_tie"], 0.0)

    def test_uniform_boundary_tie_expected_hit(self):
        # Two candidates rank above a four-way boundary tie; one of the four
        # tied candidates is relevant, so the one remaining slot hits with 1/4.
        scores = {x: 10 - i for i, x in enumerate(self.ids)}
        scores.update({x: 5.0 for x in self.ids[2:6]})
        scores[self.ids[0]], scores[self.ids[1]] = 20.0, 19.0
        relevance = {k: set(v) for k, v in self.rel.items()}
        relevance["class_only"] = {self.ids[2], *self.ids[6:11]}
        relevance["joint"] = relevance["class_only"] & relevance["position_only"]
        got = score_separated_rank_metrics(scores=scores, relevance=relevance,
            schedule_id=self.kw["schedule_id"],
            asserted_class_label_free_blind_ids=True,
            asserted_encoder_metadata_isolated=True)
        self.assertAlmostEqual(got["metrics"]["class_only"]["expected_hit_at_3_uniform_boundary_tie"], 0.25)
        self.assertEqual(len(got["tie_groups"]), 1)

    def test_rejects_invalid_inputs(self):
        scores = {candidate: float(i) for i, candidate in enumerate(self.ids)}
        for value in (float("nan"), float("inf")):
            bad = dict(scores)
            bad[self.ids[0]] = value
            with self.assertRaises(ValueError):
                score_separated_rank_metrics(scores=bad, **self.kw)
        with self.assertRaises(ValueError):
            score_separated_rank_metrics(scores=dict(list(scores.items())[:-1]), **self.kw)
        bad_rel = dict(self.rel, joint=set(self.ids[:4]))
        with self.assertRaises(ValueError):
            score_separated_rank_metrics(scores=scores, **dict(self.kw, relevance=bad_rel))
        # Every cardinality is valid, but this joint set is not the intersection.
        bad_intersection = {
            "class_only": set(self.ids[:6]),
            "position_only": set(self.ids[3:9]),
            "joint": set(self.ids[0:3]),
        }
        with self.assertRaises(ValueError):
            score_separated_rank_metrics(scores=scores,
                **dict(self.kw, relevance=bad_intersection))
        with self.assertRaises(ValueError):
            score_separated_rank_metrics(scores=scores, **dict(self.kw, asserted_class_label_free_blind_ids=False))


if __name__ == "__main__":
    unittest.main()
