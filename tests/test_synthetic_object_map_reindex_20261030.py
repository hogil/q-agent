import copy
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import research.synthetic_object_map_reindex_20261030 as reindex_module
from research.synthetic_object_map_reindex_20261030 import reindex_synthetic_object_map

ASOF = datetime(2026, 10, 30, tzinfo=timezone.utc)


def source(width=3, height=2, rot=5, xmin=0, ymin=0):
    rw, rh = (height, width) if rot in (3, 7) else (width, height)
    chips = []
    for y in range(ymin, ymin + height):
        for x in range(xmin, xmin + width):
            a, b = x - xmin, y - ymin
            if rot == 5: i, j = a, b
            elif rot == 7: i, j = b, width - 1 - a
            elif rot == 3: i, j = height - 1 - b, a
            else: i, j = width - 1 - a, height - 1 - b
            xc = i - (rw // 2 - 1) if rw % 2 == 0 else i - rw // 2
            chips.append({"x_abs": x, "y_abs": y, "x_cal": xc, "y_cal": j - rh // 2})
    return {"coord": {"x_min_abs": xmin, "x_max_abs": xmin + width - 1,
                      "y_min_abs": ymin, "y_max_abs": ymin + height - 1,
                      "rot_code": rot, "tiles_w_rot": rw, "tiles_h_rot": rh}, "chips": chips}


def invoke(pos=None, raw=None, rows=None, **kw):
    as_of = kw.pop("as_of", ASOF)
    binding = kw.pop("source_binding", None)
    validator = kw.pop("validate_binding", lambda *_: True)
    fixture = kw.pop("synthetic_fixture_asserted", True)
    return reindex_synthetic_object_map(
        pos if pos is not None else source(), raw if raw is not None else [[1, 0, 0], [0, 0, 0]],
        rows if rows is not None else [(0, 0, 1, "A", .9, ASOF)], {1: "A", 2: "B"},
        as_of=as_of, source_binding=binding or {"available_at": ASOF, **{
            name: {"source_ref": name + ":fixture", "version": "1", "available_at": ASOF}
            for name in ("positions", "raw_map", "predictions")
        }}, validate_binding=validator,
        synthetic_fixture_asserted=fixture, **kw)


class SyntheticObjectMapReindexTests(unittest.TestCase):
    def test_non_square_rotations_and_nonzero_origin(self):
        for rot in (0, 3, 5, 7):
            with self.subTest(rot=rot):
                # Zero raw map makes every source coordinate outside raw-index
                # map range visible as unrecoverable for nonzero origin.
                rw, rh = (2, 3) if rot in (3, 7) else (3, 2)
                result = invoke(pos=source(rot=rot, xmin=10, ymin=0), raw=[[0] * rw for _ in range(rh)], rows=[])
                self.assertIn("partial_raw_index_oob", result["status"])
                self.assertTrue(any(map(any, result["raw_index_oob_unrecoverable_mask"])))
                self.assertTrue(any(map(any, result["support_mask"])))
                self.assertTrue(all(v is None for row in result["object_id_grid"] for v in row))

    def test_nonzero_origin_in_bounds_positive_assignment(self):
        raw = [[0, 2, 0], [0, 0, 0]]
        result = invoke(pos=source(xmin=1), raw=raw,
                        rows=[(1, 0, 2, "B", .61, ASOF)])
        self.assertEqual(result["object_id_grid"][0][0], 2)
        self.assertEqual(result["confidence_grid"][0][0], .61)
        self.assertTrue(result["assigned_mask"][0][0])

    def test_assignment_masks_and_zero_ambiguity(self):
        result = invoke()
        self.assertEqual(result["object_id_grid"][0][0], 1)
        self.assertEqual(result["confidence_grid"][0][0], .9)
        self.assertTrue(result["support_mask"][0][0])
        self.assertTrue(result["assigned_mask"][0][0])
        self.assertTrue(result["unassigned_zero_ambiguous_mask"][0][1])
        self.assertFalse(result["assigned_mask"][0][1])
        self.assertIn("inspected/eligible", result["mask_semantics"]["support_mask"])
        self.assertFalse(result["inspection_outcome_verified"])
        self.assertEqual(result["status"], "partial_unassigned_zero_ambiguous")

    def test_positive_assignment_rotates_to_hand_computed_cells(self):
        expected = {0: (2, 1), 3: (1, 0), 5: (0, 0), 7: (0, 2)}
        for rot, (i, j) in expected.items():
            with self.subTest(rot=rot):
                rw, rh = (2, 3) if rot in (3, 7) else (3, 2)
                raw = [[0] * rw for _ in range(rh)]
                raw[0][0] = 2
                result = invoke(pos=source(rot=rot), raw=raw,
                                rows=[(0, 0, 2, "B", .73, ASOF)])
                self.assertEqual(result["object_id_grid"][j][i], 2)
                self.assertEqual(result["confidence_grid"][j][i], .73)
                self.assertTrue(result["assigned_mask"][j][i])

    def test_missing_unmatched_nonzero_and_map_disagreement_rejected(self):
        with self.assertRaisesRegex(ValueError, "unmatched nonzero"):
            invoke(rows=[])
        with self.assertRaisesRegex(ValueError, "does not match"):
            invoke(raw=[[2, 0, 0], [0, 0, 0]])

    def test_class_confidence_duplicates_bounds_and_boolean_inputs(self):
        for row in ((0, 0, 1, "B", .5, ASOF), (0, 0, 1, "A", float("nan"), ASOF),
                    (True, 0, 1, "A", .5, ASOF),
                    (9, 0, 1, "A", .5, ASOF)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                invoke(rows=[row])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            invoke(rows=[(0, 0, 1, "A", .5, ASOF), (0, 0, 1, "A", .6, ASOF)])
        with self.assertRaisesRegex(ValueError, "integer"):
            invoke(raw=[[True, 0, 0], [0, 0, 0]])

    def test_binding_fixture_and_future_cutoffs(self):
        with self.assertRaisesRegex(ValueError, "fixture assertion"):
            reindex_synthetic_object_map(source(), [[0]*3 for _ in range(2)], [], {1: "A"},
                as_of=ASOF, source_binding={"available_at": ASOF}, validate_binding=lambda *_: True,
                synthetic_fixture_asserted=False)
        with self.assertRaisesRegex(ValueError, "callback rejected"):
            invoke(rows=[], validate_binding=lambda *_: False)
        with self.assertRaisesRegex(ValueError, "source_ref and version"):
            reindex_synthetic_object_map(source(), [[0]*3 for _ in range(2)], [], {1: "A"},
                as_of=ASOF, source_binding={"available_at": ASOF}, validate_binding=lambda *_: True,
                synthetic_fixture_asserted=True)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            invoke(rows=[], as_of=ASOF.replace(tzinfo=None))
        with self.assertRaisesRegex(ValueError, "future-dated"):
            invoke(rows=[(0, 0, 1, "A", .5, ASOF + timedelta(seconds=1))])

    def test_each_component_cutoff_and_timezone_equivalent_boundary(self):
        callback_called = False
        def callback(*_):
            nonlocal callback_called
            callback_called = True
            return True
        for future_name in ("positions", "raw_map", "predictions"):
            binding = {"available_at": ASOF}
            for name in ("positions", "raw_map", "predictions"):
                binding[name] = {"source_ref": name, "version": "v1", "available_at": ASOF}
            binding[future_name]["available_at"] = ASOF + timedelta(microseconds=1)
            callback_called = False
            with self.subTest(component=future_name), self.assertRaisesRegex(ValueError, "future-dated"):
                invoke(rows=[], source_binding=binding, validate_binding=callback)
            self.assertFalse(callback_called)

        local_cutoff = ASOF.astimezone(timezone(timedelta(hours=9)))
        equal_instant = ASOF.astimezone(timezone(timedelta(hours=9)))
        binding = {"available_at": equal_instant}
        for name in ("positions", "raw_map", "predictions"):
            binding[name] = {"source_ref": name, "version": "v1", "available_at": equal_instant}
        self.assertEqual(invoke(rows=[], raw=[[0]*3 for _ in range(2)], as_of=local_cutoff,
                                source_binding=binding)["status"],
                         "partial_unassigned_zero_ambiguous")

    def test_oob_and_zero_ambiguity_masks_are_disjoint_and_partial(self):
        pos = source(xmin=-1)
        result = invoke(pos=pos, raw=[[0, 0, 0], [0, 0, 0]], rows=[])
        oob = result["raw_index_oob_unrecoverable_mask"]
        ambiguous = result["unassigned_zero_ambiguous_mask"]
        self.assertTrue(any(map(any, oob)))
        self.assertTrue(any(map(any, ambiguous)))
        self.assertFalse(any(oob[y][x] and ambiguous[y][x]
                             for y in range(len(oob)) for x in range(len(oob[0]))))
        self.assertEqual(result["status"], "partial_raw_index_oob_and_unassigned_zero_ambiguous")

    def test_grid_cap_rejected_before_geometry_or_output_allocation(self):
        oversized = source(width=3, height=2)
        with patch.object(reindex_module, "MAX_REINDEX_CELLS", 5), \
             patch.object(reindex_module, "positions_to_geometry", side_effect=AssertionError("must not run")):
            with self.assertRaisesRegex(ValueError, "cell cap"):
                reindex_synthetic_object_map(oversized, [[0]*2 for _ in range(2)], [], {1: "A"},
                    as_of=ASOF, source_binding={"available_at": ASOF, **{
                        name: {"source_ref": name, "version": "1", "available_at": ASOF}
                        for name in ("positions", "raw_map", "predictions")}},
                    validate_binding=lambda *_: True, synthetic_fixture_asserted=True)

    def test_immutability_and_empty_predictions(self):
        pos, raw = source(), [[0, 0, 0], [0, 0, 0]]
        before = copy.deepcopy((pos, raw))
        result = invoke(pos=pos, raw=raw, rows=[])
        self.assertEqual((pos, raw), before)
        self.assertTrue(all(v is None for row in result["object_id_grid"] for v in row))
        self.assertTrue(all(map(any, result["support_mask"])))
        self.assertTrue(all(all(row) for row in result["unassigned_zero_ambiguous_mask"]))
        self.assertEqual(result["status"], "partial_unassigned_zero_ambiguous")
        self.assertFalse(result["claims"]["source_bytes_hash_or_wafer_identity_verified"])


if __name__ == "__main__":
    unittest.main()
