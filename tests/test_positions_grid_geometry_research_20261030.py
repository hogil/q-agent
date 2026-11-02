import copy
import math
import unittest
from datetime import datetime, timezone, timedelta

from research.positions_grid_geometry_research_20261030 import positions_to_geometry
from research.wafer_position_permutation_20261030 import analyze_wafer_positions
from research.wafer_polar_permutation_20261030 import analyze_wafer_polar_positions


def sample(width=4, height=3, rot=5):
    xmin, ymin = -2, 4
    xmax, ymax = xmin+width-1, ymin+height-1
    rw, rh = (height, width) if rot in (3, 7) else (width, height)
    chips = []
    for ya in range(ymin, ymax+1):
        for xa in range(xmin, xmax+1):
            i0, j0 = xa-xmin, ya-ymin
            i, j = ((i0,j0) if rot == 5 else
                    (j0,width-1-i0) if rot == 7 else
                    (height-1-j0,i0) if rot == 3 else
                    (width-1-i0,height-1-j0))
            xc = i-(rw//2-1) if rw % 2 == 0 else i-rw//2
            yc = j-rh//2
            chips.append({"x_abs": xa, "y_abs": ya, "x_cal": xc, "y_cal": yc})
    return {"coord": {"x_min_abs": xmin, "x_max_abs": xmax, "y_min_abs": ymin, "y_max_abs": ymax,
                      "rot_code": rot, "tiles_w_rot": rw, "tiles_h_rot": rh}, "chips": chips}


ASOF = datetime(2026, 10, 30, tzinfo=timezone.utc)


def registration(**changes):
    value = {"frame": "rotated-grid", "wafer_center_col": 1.5, "wafer_center_row": 1.0,
             "pitch_x_mm": 1.0, "pitch_y_mm": 2.0, "wafer_radius_mm": 100.0,
             "axis_sign_x": -1, "axis_sign_y": 1, "source_ref": "synthetic:registration", "version": "v1",
             "available_at": ASOF-timedelta(days=1)}
    value.update(changes)
    return value


class GridGeometryTests(unittest.TestCase):
    def test_hand_computed_nonsquare_rotations_odd_and_even(self):
        # Source is 4x3; source cell (x_min,y_min) has independently computed targets.
        expected = {5: (0, 0), 7: (0, 3), 3: (2, 0), 0: (3, 2)}
        for rot, point in expected.items():
            result = positions_to_geometry(sample(4, 3, rot))
            first = result["rows"][0]
            self.assertEqual((first["i"], first["j"]), point, rot)
            self.assertEqual(result["original_grid"]["rotated_width"], 3 if rot in (3, 7) else 4)
            self.assertEqual(result["original_grid"]["rotated_height"], 4 if rot in (3, 7) else 3)
        for rot, point in {5:(0,0),7:(0,3),3:(2,0),0:(3,2)}.items():
            result = positions_to_geometry(sample(4, 3, rot))
            self.assertEqual((result["rows"][0]["i"], result["rows"][0]["j"]), point)
        even = positions_to_geometry(sample(4, 2, 5))
        self.assertEqual(even["rows"][0]["grid_geometric_center_offset"], {"col": -1.5, "row": -0.5})
        odd = positions_to_geometry(sample(3, 3, 5))
        self.assertEqual(odd["rows"][4]["grid_geometric_center_offset"], {"col": 0.0, "row": 0.0})

    def test_real_like_coord_dimensions_and_malicious_inputs(self):
        for mutate in (
            lambda d: d["coord"].update(rot_code=9), lambda d: d["coord"].update(x_min_abs=True),
            lambda d: d["coord"].update(tiles_w_rot=99), lambda d: d["coord"].pop("tiles_h_rot"),
            lambda d: d["coord"].update(x_max_abs=10_000_000), lambda d: d["chips"].clear(),
            lambda d: d["chips"][0].update(x_abs=100), lambda d: d["chips"][0].update(x_cal=999),
            lambda d: d["chips"].append(copy.deepcopy(d["chips"][0])),
        ):
            data = sample(); mutate(data)
            with self.assertRaises(ValueError): positions_to_geometry(data)

    def test_registration_datetime_axis_sign_and_theta_origin(self):
        data = sample(3, 3, 5)
        invalid = positions_to_geometry(data, registration=registration(wafer_center_col=1, wafer_center_row=1), as_of=ASOF,
                                        validate_registration=lambda *_: True)
        self.assertEqual(invalid["rows"][0]["physical"]["x"], 0.01)
        self.assertEqual(invalid["rows"][0]["physical"]["y"], -0.02)
        self.assertIsNone(invalid["rows"][0]["physical"]["theta_rad"])
        self.assertIsNone(invalid["rows"][4]["physical"]["theta_rad"])  # registered origin
        calls = {"reg":0, "orientation":0}
        def vr(*_): calls["reg"] += 1; return True
        def vo(*_): calls["orientation"] += 1; return True
        oriented = positions_to_geometry(data, registration=registration(wafer_center_col=1, wafer_center_row=1), as_of=ASOF,
            validate_registration=vr, orientation_assertion={"notch_mapping":"east=0", "theta_offset_rad":0.2,
            "source_ref":"synthetic:registration", "version":"v1", "available_at":ASOF}, validate_orientation=vo)
        self.assertIsNone(oriented["rows"][4]["physical"]["theta_rad"])
        self.assertEqual(calls, {"reg":1, "orientation":1})
        self.assertTrue(all(r["physical"]["provenance"] == "caller_asserted_unverified" for r in oriented["rows"]))
        wrong_time = positions_to_geometry(data, registration=registration(), as_of=ASOF.replace(tzinfo=None), validate_registration=vr)
        self.assertIsNone(wrong_time["rows"][0]["physical"])
        too_late = positions_to_geometry(data, registration=registration(available_at=ASOF+timedelta(seconds=1)), as_of=ASOF,
                                         validate_registration=lambda *_: True)
        self.assertIsNone(too_late["rows"][0]["physical"])
        with self.assertRaises(ValueError):
            positions_to_geometry(data, registration=registration(wafer_radius_mm=0.001), as_of=ASOF, validate_registration=lambda *_: True)

    def test_inspection_exclusions_strata_gate_and_analysis_roundtrip(self):
        data = sample(3, 3, 5)
        statuses = iter(["eligible_inspected"]*6+["not_inspected","unknown","eligible_inspected"])
        outcomes = iter([False, True, None, False, True, False, True])
        result = positions_to_geometry(data, registration=registration(wafer_radius_mm=10), as_of=ASOF,
            validate_registration=lambda *_: True, resolve_inspection=lambda _: next(statuses),
            resolve_defect=lambda _: next(outcomes), strata="product-A")
        counts = result["inspection"]["counts"]
        self.assertEqual(counts, {"eligible_inspected":7,"not_inspected":1,"unknown":1,"outcome_missing":1,"outcomes":6})
        rows = result["inspection"]["analysis_rows"]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(set(r) == {"x","y","defect","strata"} for r in rows))
        analyzed = analyze_wafer_positions(rows, permutations=99, seed=7)
        self.assertEqual(analyzed["coverage"]["eligible_inspected_die_count"], 6)
        self.assertIsNone(result["inspection"]["angular_analysis_rows"])
        no_strata = positions_to_geometry(data, registration=registration(wafer_radius_mm=10), as_of=ASOF,
            validate_registration=lambda *_: True, resolve_inspection=lambda _: "eligible_inspected", resolve_defect=lambda _: False)
        self.assertIsNone(no_strata["inspection"]["analysis_rows"])
        self.assertIsNone(no_strata["inspection"]["angular_analysis_rows"])
        no_reg = positions_to_geometry(data, resolve_inspection=lambda _: "eligible_inspected", resolve_defect=lambda _: False, strata="x")
        self.assertIsNone(no_reg["inspection"]["analysis_rows"])
        self.assertIsNone(no_reg["inspection"]["angular_analysis_rows"])
        with self.assertRaises(ValueError):
            positions_to_geometry(data, resolve_inspection=lambda _: "eligible_inspected", resolve_defect=lambda _: 0)

    def test_orientation_rotation_rows_nested_strata_and_coordinate_collapse(self):
        data = sample(3, 3, 5)
        orientation = {"notch_mapping":"synthetic mapping", "theta_offset_rad":math.pi/2,
                       "source_ref":"synthetic:registration", "version":"v1", "available_at":ASOF}
        result = positions_to_geometry(data, registration=registration(wafer_center_col=1, wafer_center_row=1, wafer_radius_mm=4),
            as_of=ASOF, validate_registration=lambda *_: True, orientation_assertion=orientation,
            validate_orientation=lambda *_: True, resolve_inspection=lambda _: "eligible_inspected",
            resolve_defect=lambda chip: chip["x_abs"] % 2 == 0, strata=("product-A", 1))
        radial = result["inspection"]["analysis_rows"]
        angular = result["inspection"]["angular_analysis_rows"]
        self.assertIsNotNone(angular)
        self.assertEqual(len(analyze_wafer_polar_positions(angular, orientation_asserted=True, permutations=99)["bins"]), 12)
        for src, rotated in zip(radial, angular):
            self.assertAlmostEqual(rotated["x"], -src["y"], places=12)
            self.assertAlmostEqual(rotated["y"], src["x"], places=12)
            self.assertAlmostEqual(math.hypot(src["x"], src["y"]),
                                   math.hypot(rotated["x"], rotated["y"]), delta=1e-12)
        nested = positions_to_geometry(data, registration=registration(wafer_center_col=1, wafer_center_row=1, wafer_radius_mm=4),
            as_of=ASOF, validate_registration=lambda *_: True, resolve_inspection=lambda _: "eligible_inspected",
            resolve_defect=lambda _: False, strata=(("nested",),))
        self.assertIsNone(nested["inspection"]["analysis_rows"])
        collapsed = positions_to_geometry(data, registration=registration(wafer_center_col=1e300, wafer_center_row=1e300,
            pitch_x_mm=1e-300, pitch_y_mm=1e-300, wafer_radius_mm=1e300), as_of=ASOF,
            validate_registration=lambda *_: True, resolve_inspection=lambda _: "eligible_inspected",
            resolve_defect=lambda _: False, strata="S")
        self.assertIsNone(collapsed["inspection"]["analysis_rows"])
        self.assertEqual(collapsed["inspection"]["analysis_rows_unavailable_reason"],
                         "registered_coordinates_collapse_to_duplicate_normalized_points")


if __name__ == "__main__":
    unittest.main()
