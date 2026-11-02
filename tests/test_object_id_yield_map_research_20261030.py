import copy
import unittest
from datetime import datetime, timedelta, timezone

import struct
import zlib

from research.object_id_yield_map_research_20261030 import encode_object_id_yield_map, render_palette_rgba

ASOF = datetime(2026, 10, 30, tzinfo=timezone.utc)
FBM = {"reference": "synthetic:fbm", "hash": "a" * 64, "provenance": "caller_asserted"}


def pred(cid=3, score=.9, **kw):
    value = {"id": cid, "score": score, "source": "synthetic:model", "version": "v1", "available_at": ASOF}
    value.update(kw)
    return value


def threshold(value=.8, **kw):
    result = {"threshold": value, "source": "synthetic:threshold", "version": "v1", "available_at": ASOF}
    result.update(kw)
    return result


class ObjectYieldMapTests(unittest.TestCase):
    def encode(self, rows, thresholds=None):
        return encode_object_id_yield_map(width=4, height=2, rows=rows,
            thresholds=thresholds if thresholds is not None else {3: threshold()}, as_of=ASOF, fbm_snapshot=FBM,
            support_mask=[[True, True, True, True], [True, True, False, False]])

    def test_missing_valid_and_explicit_statuses(self):
        result = self.encode([
            {"col": 0, "row": 0, "inspection": "NOT_INSPECTED", "outcome": "UNKNOWN", "predictions": []},
            {"col": 1, "row": 0, "inspection": "UNKNOWN", "outcome": "UNKNOWN", "predictions": []},
            {"col": 2, "row": 0, "inspection": "INSPECTED", "outcome": "FAIL", "predictions": []},
        ])
        self.assertEqual([result["legend"][x] for x in result["raster"][0]], ["UNKNOWN", "UNKNOWN", "FAIL_UNCLASSIFIED", "MISSING"])
        self.assertEqual(result["valid_mask"][0], [True, True, True, False])
        self.assertEqual(result["inspection"][0][0], "NOT_INSPECTED")

    def test_known_multi_conflict_and_unknown_threshold(self):
        result = self.encode([
            {"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()]},
            {"col": 1, "row": 0, "inspection": "INSPECTED", "outcome": "PASS", "predictions": [pred()]},
            {"col": 2, "row": 0, "inspection": "INSPECTED", "outcome": "FAIL", "predictions": [pred(3), pred(4)]},
            {"col": 3, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred(5)]},
        ], {3: threshold(), 4: threshold(), 5: {"threshold": .5}})
        self.assertEqual([result["legend"][x] for x in result["raster"][0]], ["KNOWN:3", "CONFLICT", "MULTI_KNOWN", "UNKNOWN"])
        self.assertEqual(result["known_channels"][3][0][2], 1)
        self.assertEqual(result["known_channels"][4][0][2], 1)
        self.assertEqual(result["prediction_status"][0][3][0]["status"], "unverified")

    def test_fail_closed_input_validation_and_temporal_availability(self):
        for p in (pred(0), pred(-1), pred(True), pred(3, float("nan")), pred(3, 1.1)):
            with self.assertRaises(ValueError):
                self.encode([{"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [p]}])
        with self.assertRaises(ValueError):
            self.encode([{"col": 4, "row": 0, "inspection": "INSPECTED", "outcome": "PASS", "predictions": []}])
        with self.assertRaises(ValueError):
            self.encode([{"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "PASS", "predictions": []},
                         {"col": 0, "row": 0, "inspection": "UNKNOWN", "outcome": "UNKNOWN", "predictions": []}])
        future = pred(3, .99, available_at=ASOF+timedelta(seconds=1))
        result = self.encode([{"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "FAIL", "predictions": [future]}])
        self.assertEqual(result["prediction_status"][0][0], [])
        self.assertNotIn(3, result["score_channels"])
        self.assertEqual(result["legend"][result["raster"][0][0]], "FAIL_UNCLASSIFIED")

    def test_raw_snapshot_unchanged_and_timezone_required(self):
        snapshot = copy.deepcopy(FBM)
        self.encode([])
        self.assertEqual(FBM, snapshot)
        with self.assertRaises(ValueError):
            encode_object_id_yield_map(width=1, height=1, rows=[], thresholds={}, as_of=ASOF.replace(tzinfo=None), fbm_snapshot=FBM,
                support_mask=[[True]])
        with self.assertRaises(ValueError):
            self.encode([], {True: threshold()})

    def test_support_missing_outside_duplicate_class_and_budget(self):
        result = self.encode([])
        self.assertEqual(result["legend"][result["raster"][0][3]], "MISSING")
        self.assertEqual(result["legend"][result["raster"][1][2]], "OUTSIDE")
        self.assertFalse(result["support_mask"][1][2])
        with self.assertRaises(ValueError):
            self.encode([{"col": 2, "row": 1, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": []}])
        with self.assertRaises(ValueError):
            self.encode([{"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred(), pred()]}])
        with self.assertRaises(ValueError):
            encode_object_id_yield_map(width=1000, height=1000, rows=[{"col": 0, "row": 0, "inspection": "UNKNOWN", "outcome": "UNKNOWN",
                "predictions": [pred(i) for i in range(1, 6)]}],
                thresholds={}, as_of=ASOF, fbm_snapshot=FBM,
                support_mask=[[True] * 1000 for _ in range(1000)])

    def test_uninspected_prediction_cannot_be_known_or_pass(self):
        result = self.encode([{"col": 0, "row": 0, "inspection": "NOT_INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()]}])
        self.assertEqual(result["legend"][result["raster"][0][0]], "UNKNOWN")
        self.assertIsNone(result["known_channels"][3][0][0])
        self.assertEqual(result["prediction_status"][0][0][0]["status"], "threshold_met_inspection_unconfirmed")

    def test_future_threshold_is_not_exported_or_applied(self):
        future_threshold = threshold(available_at=ASOF + timedelta(seconds=1))
        result = self.encode([{"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()]}],
                             {3: future_threshold})
        self.assertNotIn(3, result["threshold_provenance"])
        self.assertEqual(result["prediction_status"][0][0][0]["status"], "unverified")
        self.assertIsNone(result["known_channels"][3][0][0])

    def test_unknown_evidence_tri_state_is_independent_of_known_classes(self):
        def evidence(status, available_at=ASOF):
            return {"status": status, "source": "synthetic:evidence", "version": "v2", "available_at": available_at}
        result = self.encode([
            {"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()],
             "unknown_evidence": evidence("PRESENT")},
            {"col": 1, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()],
             "unknown_evidence": evidence("ABSENT")},
            {"col": 2, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()]},
            {"col": 3, "row": 0, "inspection": "INSPECTED", "outcome": "UNKNOWN", "predictions": [pred()],
             "unknown_evidence": evidence("PRESENT", ASOF + timedelta(seconds=1))},
        ])
        self.assertEqual(result["unknown_evidence"][0], ["PRESENT", "ABSENT", "UNASSESSED", "UNASSESSED"])
        self.assertEqual(result["known_channels"][3][0], [1, 1, 1, 1])
        self.assertIsNotNone(result["unknown_evidence_provenance"][0][0])
        self.assertIsNone(result["unknown_evidence_provenance"][0][3])
        self.assertEqual(result["legend"][result["raster"][0][0]], "KNOWN:3")

    def test_unclassified_failure_does_not_claim_unknown_evidence(self):
        result = self.encode([{"col": 0, "row": 0, "inspection": "INSPECTED", "outcome": "FAIL", "predictions": []}])
        self.assertEqual(result["legend"][result["raster"][0][0]], "FAIL_UNCLASSIFIED")
        self.assertEqual(result["unknown_evidence"][0][0], "UNASSESSED")

    def test_uninspected_explicit_outcomes_are_conflict_before_unclassified(self):
        result = self.encode([
            {"col": 0, "row": 0, "inspection": "NOT_INSPECTED", "outcome": "FAIL", "predictions": []},
            {"col": 1, "row": 0, "inspection": "UNKNOWN", "outcome": "PASS", "predictions": []},
            {"col": 2, "row": 0, "inspection": "NOT_INSPECTED", "outcome": "FAIL", "predictions": [pred()]},
            {"col": 3, "row": 0, "inspection": "UNKNOWN", "outcome": "PASS", "predictions": [pred(), pred(4)]},
        ], {3: threshold(), 4: threshold()})
        self.assertEqual([result["legend"][i] for i in result["raster"][0]], ["CONFLICT"] * 4)
        self.assertEqual(result["known_channels"][3][0][2], None)
        self.assertEqual(result["known_channels"][3][0][3], None)

    def test_row_and_class_count_preflight_limits(self):
        with self.assertRaisesRegex(ValueError, "row count"):
            self.encode([{"col": 0, "row": 0, "inspection": "UNKNOWN", "outcome": "UNKNOWN", "predictions": []}] * 9)
        with self.assertRaisesRegex(ValueError, "class count"):
            self.encode([], {i: threshold() for i in range(1, 258)})

    def test_caller_palette_rgba_png_pixels_and_validation(self):
        result = self.encode([
            {"col": 0, "row": 0, "inspection": "NOT_INSPECTED", "outcome": "PASS", "predictions": []},
            {"col": 1, "row": 0, "inspection": "INSPECTED", "outcome": "FAIL", "predictions": []},
        ])
        palette = {"CONFLICT": (9, 8, 7, 255), "FAIL_UNCLASSIFIED": (1, 2, 3, 255),
                   "MISSING": (4, 5, 6, 255), "OUTSIDE": (7, 8, 9, 0)}
        png = render_palette_rgba(result, palette)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        pos = 8; compressed = bytearray(); dimensions = None
        while pos < len(png):
            size = struct.unpack(">I", png[pos:pos+4])[0]; kind = png[pos+4:pos+8]
            payload = png[pos+8:pos+8+size]; pos += 12 + size
            if kind == b"IHDR": dimensions = struct.unpack(">II", payload[:8])
            if kind == b"IDAT": compressed.extend(payload)
        self.assertEqual(dimensions, (4, 2))
        pixels = zlib.decompress(compressed)
        self.assertEqual(pixels[:17], b"\x00" + bytes(palette["CONFLICT"])+bytes(palette["FAIL_UNCLASSIFIED"])+bytes(palette["MISSING"])+bytes(palette["MISSING"]))
        with self.assertRaises(ValueError):
            render_palette_rgba(result, {**palette, "PASS": (0, 0, 0, 0)})
        with self.assertRaises(ValueError):
            render_palette_rgba(result, {"CONFLICT": (1, 1, 1, 255), "FAIL_UNCLASSIFIED": (1, 1, 1, 255),
                                         "MISSING": (4, 5, 6, 255), "OUTSIDE": (7, 8, 9, 0)})

    def test_renderer_rejects_malformed_raster_before_index_processing(self):
        base = self.encode([])
        palette = {"MISSING": (1, 1, 1, 255), "OUTSIDE": (2, 2, 2, 255)}
        for raster in (
            [[0] * 5] + [[0] * 4],
            [None] + [[0] * 4],
            [[[0]]] + [[0] * 4],
            [[True] + [0] * 3] + [[0] * 4],
            [[999] + [0] * 3] + [[0] * 4],
        ):
            forged = {**base, "raster": raster}
            with self.assertRaises(ValueError):
                render_palette_rgba(forged, palette)

    def test_future_threshold_ids_do_not_consume_class_cap(self):
        future = {i: threshold(available_at=ASOF + timedelta(seconds=1)) for i in range(1, 300)}
        result = self.encode([], future)
        self.assertEqual(result["threshold_provenance"], {})

    def test_renderer_bounds_forged_legend_palette_and_label_lengths(self):
        base = self.encode([])
        palette = {"MISSING": (1, 1, 1, 255), "OUTSIDE": (2, 2, 2, 255)}
        too_many = {i: f"L{i}" for i in range(265)}
        with self.assertRaises(ValueError):
            render_palette_rgba({**base, "legend": too_many}, palette)
        with self.assertRaises(ValueError):
            render_palette_rgba(base, {**palette, **{f"L{i}": (i % 256, 0, 0, 255) for i in range(300)}})
        too_long = "x" * 257
        with self.assertRaises(ValueError):
            render_palette_rgba({**base, "legend": {0: too_long, 1: "OUTSIDE"}},
                                {too_long: (1, 1, 1, 255), "OUTSIDE": (2, 2, 2, 255)})
        self.assertEqual(len(base["legend"]), 8)
        self.assertLessEqual(len("KNOWN:" + str(2**63 - 1)), 256)


if __name__ == "__main__":
    unittest.main()
