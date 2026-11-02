import math
import unittest

from research.wafer_polar_permutation_20261030 import analyze_wafer_polar_positions
from research.wafer_position_permutation_20261030 import analyze_wafer_positions


def ring_rows():
    rows = []
    for b, radius in enumerate((0.12, 0.40, 0.68, 0.92)):
        for i in range(16):
            a = 2 * math.pi * (i + 0.1*b) / 16
            rows.append({"x": radius*math.cos(a), "y": radius*math.sin(a),
                         "defect": int(b == 1 and i < 8), "strata": "S"})
    return rows


class WaferPolarPermutationTests(unittest.TestCase):
    def test_false_radial_output_matches_existing(self):
        rows = ring_rows()
        old = analyze_wafer_positions(rows, permutations=199, seed=41)
        new = analyze_wafer_polar_positions(rows, permutations=199, seed=41)
        for key, value in old.items():
            self.assertEqual(new[key], value, key)
        self.assertFalse(new["angular_included"])

    def test_orientation_must_be_bool_and_true_enables_angular(self):
        for value in (1, "yes", None):
            with self.assertRaises(ValueError):
                analyze_wafer_polar_positions(ring_rows(), orientation_asserted=value)
        result = analyze_wafer_polar_positions(ring_rows(), orientation_asserted=True, permutations=99)
        self.assertTrue(result["angular_included"])
        self.assertEqual(sum(x["eligible_count"] for x in result["bins"] if x["family"] == "angular"), 64)
        self.assertIn("not independently measured", result["orientation_warning"])

    def test_origin_excluded_and_sector_boundary(self):
        rows = [{"x": 0.0, "y": 0.0, "defect": 0, "strata": "S"}]
        for i in range(16):
            angle = -math.pi + i*math.pi/8
            rows.append({"x": .5*math.cos(angle), "y": .5*math.sin(angle),
                         "defect": int(i < 8), "strata": "S"})
        result = analyze_wafer_polar_positions(rows, orientation_asserted=True, permutations=99)
        sectors = [x for x in result["bins"] if x["family"] == "angular"]
        self.assertEqual(sum(x["eligible_count"] for x in sectors), 16)
        self.assertEqual([x["eligible_count"] for x in sectors], [2]*8)
        self.assertEqual(result["coverage"]["angular_origin_excluded_count"], 1)
        self.assertEqual(result["coverage"]["angular_eligible_count"], 16)
        # atan2 maps signed zero to exact opposite pi values; both normalize to sector_0.
        edge_rows = [{"x": -0.5, "y": 0.0, "defect": 1, "strata": "S"},
                     {"x": -0.5000000000000001, "y": -0.0, "defect": 0, "strata": "S"}]
        edge = analyze_wafer_polar_positions(edge_rows, orientation_asserted=True, permutations=99)
        s0 = next(x for x in edge["bins"] if x["bin"] == "sector_0")
        self.assertEqual(s0["eligible_count"], 2)
        self.assertEqual(math.atan2(edge_rows[0]["y"], edge_rows[0]["x"]), math.pi)
        self.assertEqual(math.atan2(edge_rows[1]["y"], edge_rows[1]["x"]), -math.pi)
        self.assertIn("both -pi and +pi", edge["angular_sector_boundary_rule"])

    def test_directional_pattern_and_joint_max_manual(self):
        rows = []
        for b, radius in enumerate((.1, .4, .7, .9)):
            for sector in range(8):
                for rep in range(6):
                    angle = -math.pi + (sector+.5)*math.pi/4 + rep*.0001
                    rows.append({"x": radius*math.cos(angle), "y": radius*math.sin(angle),
                                 "defect": int(sector == 2 and rep < 3), "strata": "S"})
        result = analyze_wafer_polar_positions(rows, orientation_asserted=True, permutations=499, seed=12)
        self.assertIn(result["status"], {"spatial_evidence", "no_detected_spatial_evidence"})
        self.assertIsNotNone(result["p_value"])
        radial = [abs(x["standardized_residual"]) for x in result["bins"] if x["family"] == "radial" and x["standardized_residual"] is not None]
        angular = [abs(x["standardized_residual"]) for x in result["bins"] if x["family"] == "angular" and x["standardized_residual"] is not None]
        self.assertTrue(all(x["variance"] > 0 for x in result["bins"] if x["family"] == "angular"))
        self.assertEqual(result["observed_max_abs_standardized_residual"], max(radial+angular))
        self.assertGreater(max(angular), max(radial))

    def test_insufficient_strata_and_limits(self):
        rows = [{"x": .2, "y": 0, "defect": 0, "strata": "S"},
                {"x": .4, "y": 0, "defect": 0, "strata": "S"}]
        result = analyze_wafer_polar_positions(rows, orientation_asserted=True, permutations=99)
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("labels are exchangeable within caller-supplied strata", result["assumptions"])
        self.assertTrue(any("wafer/Lot" in x for x in result["limits"]))
        self.assertTrue(any("p > alpha" in x for x in result["limits"]))

    def test_angular_only_variance_and_independent_joint_max_reconstruction(self):
        # Within each radial bin, keep labels constant so every radial variance is zero.
        rows = []
        for b, radius in enumerate((.1, .4, .7, .9)):
            for sector in range(8):
                for rep in range(8):
                    angle = -math.pi + (sector+.5)*math.pi/4 + rep*(math.pi/4/9)
                    rows.append({"x": radius*math.cos(angle), "y": radius*math.sin(angle),
                                 "defect": int((sector == 3) if b % 2 == 0 else (sector != 3)), "strata": ("radial", b)})
        result = analyze_wafer_polar_positions(rows, orientation_asserted=True, permutations=199, seed=77)
        radial_rows = [x for x in result["bins"] if x["family"] == "radial"]
        self.assertTrue(all(x["variance"] == 0 for x in radial_rows))
        self.assertIn(result["status"], {"spatial_evidence", "no_detected_spatial_evidence"})
        self.assertIsNotNone(result["p_value"])
        if result["p_value"] > result["alpha"]:
            self.assertEqual(result["status"], "no_detected_spatial_evidence")
            self.assertIn("does not establish randomness", result["interpretation"])

        # Reconstruct the exact common label permutations and the full valid-family maxT.
        import random
        strata = {}
        for i, row in enumerate(rows):
            strata.setdefault(row["strata"], []).append(i)
        variances = {(x["family"], x["bin"]): x["variance"] for x in result["bins"]}
        moments = {(x["family"], x["bin"]): x["expected_fail_count"] for x in result["bins"]}
        observed = {}
        for item in result["bins"]:
            kind, name = item["family"], item["bin"]
            observed[(kind, name)] = abs(item["standardized_residual"]) if item["standardized_residual"] is not None else None
        obs_max = max(v for v in observed.values() if v is not None)
        rng = random.Random(77)
        exceed = 0
        for _ in range(199):
            permuted = [r["defect"] for r in rows]
            for members in strata.values():
                group = [permuted[i] for i in members]
                rng.shuffle(group)
                for i, label in zip(members, group):
                    permuted[i] = label
            stat = 0.0
            for item in result["bins"]:
                kind, name = item["family"], item["bin"]
                var = variances[(kind, name)]
                if var <= 0:
                    continue
                if kind == "radial":
                    indices = [i for i, row in enumerate(rows) if math.hypot(row["x"], row["y"]) <= dict(center=.25, inner_ring=.55, outer_ring=.82, edge=1.0)[name]]
                    lower = {"center": 0, "inner_ring": .25, "outer_ring": .55, "edge": .82}[name]
                    indices = [i for i in indices if math.hypot(rows[i]["x"], rows[i]["y"]) > lower or name == "center"]
                else:
                    sector = int(name.split("_")[1])
                    indices = []
                    for i, row in enumerate(rows):
                        a = math.atan2(row["y"], row["x"])
                        if a == math.pi: a = -math.pi
                        if row["x"] == 0 and row["y"] == 0: continue
                        if min(7, int((a+math.pi)/(math.pi/4))) == sector: indices.append(i)
                count = sum(permuted[i] for i in indices)
                stat = max(stat, abs((count-moments[(kind,name)])/math.sqrt(var)))
            exceed += stat >= obs_max - 1e-12
        self.assertEqual(result["exceedances"], exceed)
        self.assertEqual(result["p_value"], (1+exceed)/200)


if __name__ == "__main__":
    unittest.main()
