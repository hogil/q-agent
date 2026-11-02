import copy
import unittest

from research.known_object_map_alignment_audit_20261030 import audit_object_map_alignment


def sample(width=4, height=3, rot=5, xmin=0, ymin=0):
    xmax, ymax = xmin + width - 1, ymin + height - 1
    rw, rh = (height, width) if rot in (3, 7) else (width, height)
    chips = []
    for ya in range(ymin, ymax + 1):
        for xa in range(xmin, xmax + 1):
            i0, j0 = xa - xmin, ya - ymin
            if rot == 5: i, j = i0, j0
            elif rot == 7: i, j = j0, width - 1 - i0
            elif rot == 3: i, j = height - 1 - j0, i0
            else: i, j = width - 1 - i0, height - 1 - j0
            xc = i - (rw // 2 - 1) if rw % 2 == 0 else i - rw // 2
            chips.append({"x_abs": xa, "y_abs": ya, "x_cal": xc, "y_cal": j - rh // 2})
    return {"coord": {"x_min_abs": xmin, "x_max_abs": xmax, "y_min_abs": ymin,
                      "y_max_abs": ymax, "rot_code": rot, "tiles_w_rot": rw, "tiles_h_rot": rh}, "chips": chips}


class ObjectMapAlignmentAuditTests(unittest.TestCase):
    def test_identity_origin_is_consistent_and_conservative(self):
        result = audit_object_map_alignment(sample(), object_map_width=4, object_map_height=3)
        self.assertEqual(result["alignment_status"], "structural_index_mapping_consistent")
        self.assertEqual(result["counts"]["raw_rotated_indices_differ"], 0)
        self.assertFalse(any(result["claims"].values()))
        self.assertEqual(result["scope"], "all_position_chips")

    def test_nonzero_origin_is_oob_for_raw_absolute_indices(self):
        result = audit_object_map_alignment(sample(xmin=10, ymin=-2), object_map_width=4, object_map_height=3)
        self.assertEqual(result["counts"]["raw_indices_out_of_bounds"], 12)
        self.assertEqual(result["alignment_status"], "structural_index_mapping_mismatch")

    def test_negative_origin_and_width_height_swap(self):
        negative = audit_object_map_alignment(sample(xmin=-4, ymin=-3), object_map_width=4, object_map_height=3)
        self.assertEqual(negative["counts"]["raw_indices_out_of_bounds"], 12)
        source = sample(rot=7)
        swapped = audit_object_map_alignment(source, object_map_width=3, object_map_height=4)
        self.assertFalse(swapped["shape_mismatch"])

    def test_nonsquare_rotations_compare_indices_and_shapes(self):
        for rot in (0, 3, 7):
            with self.subTest(rot=rot):
                source = sample(rot=rot)
                result = audit_object_map_alignment(source, object_map_width=4, object_map_height=3)
                self.assertGreater(result["counts"]["raw_rotated_indices_differ"], 0)
                self.assertEqual(result["shape_mismatch"], rot in (3, 7))
                self.assertEqual(result["alignment_status"], "structural_index_mapping_mismatch")

    def test_duplicates_unknown_rotation_and_source_immutability(self):
        source = sample()
        before = copy.deepcopy(source)
        source["chips"].append(copy.deepcopy(source["chips"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_object_map_alignment(source, object_map_width=4, object_map_height=3)
        self.assertEqual(source["coord"], before["coord"])
        bad = sample(); bad["coord"]["rot_code"] = 9
        with self.assertRaisesRegex(ValueError, "rotation"):
            audit_object_map_alignment(bad, object_map_width=4, object_map_height=3)

    def test_shape_mismatch(self):
        result = audit_object_map_alignment(sample(), object_map_width=5, object_map_height=3)
        self.assertTrue(result["shape_mismatch"])
        self.assertEqual(result["alignment_status"], "structural_index_mapping_mismatch")

    def test_invalid_dimensions_and_duplicate_policy(self):
        for width, height in ((True, 3), (0, 3), (3, False), (3, 2.5)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                audit_object_map_alignment(sample(), object_map_width=width, object_map_height=height)
        duplicate = sample()
        duplicate["chips"].append(copy.deepcopy(duplicate["chips"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_object_map_alignment(duplicate, object_map_width=4, object_map_height=3)
        result = audit_object_map_alignment(sample(), object_map_width=4, object_map_height=3)
        self.assertEqual(result["duplicate_positions_policy"], "reject_before_audit")
        self.assertNotIn("duplicate_raw_positions", result["counts"])
        self.assertFalse(result["claims"]["rect_to_grid_edges_verified"])


if __name__ == "__main__":
    unittest.main()
