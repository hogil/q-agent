import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from demo_images import DemoImageService, OVERLAY_MODEL, SEM_MODEL
from incident_tools import ToolError
from train_demo_images import _sem_bitmap, train_models


class DemoImageServiceTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model_root = self.root / "models"
        train_models(self.model_root, train_per_class=4, holdout_per_class=2, seed=17)
        assets = self.root / "assets"
        assets.mkdir()
        Image.fromarray(_sem_bitmap(10017, "bridge")).save(assets / "a.png")
        Image.fromarray(_sem_bitmap(20017, "gap")).save(assets / "b.png")
        self.raw = {
            "SYN-1": {
                "engineering": {"signals": [
                    {"item": "ITEM-1", "step": "STEP-1", "equipment": "EQ-1"},
                    {"item": "ITEM-1", "step": "STEP-1", "equipment": "EQ-2"},
                ], "fab": [
                    {"lotId": "LOT-1", "waferId": "W01", "timestamp": "2026-03-01T00:00:00+00:00",
                     "equipment": "EQ-1", "step": "STEP-1", "recipe": "RCP-1"},
                    {"lotId": "LOT-1", "waferId": "W02", "timestamp": "2026-03-01T01:00:00+00:00",
                     "equipment": "EQ-2", "step": "STEP-1", "recipe": "RCP-1"},
                ]},
                "sem_assets": [
                    {"id": "SYN-A", "lotId": "LOT-1", "waferId": "W01", "src": "/assets/a.png",
                     "provenance": "synthetic fixture"},
                    {"id": "SYN-B", "lotId": "LOT-1", "waferId": "W02", "src": "/assets/b.png",
                     "provenance": "synthetic fixture"},
                ],
            }
        }
        self.service = DemoImageService(self.raw, self.root, {"SYN-1": {"incident_id": "INC-1", "incident_number": "SYN-1"}}, self.model_root)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, modality="sem"):
        return {"actor": "local-workbench", "incident_ids": ["INC-1"], "item": "ITEM-1",
                "modality": modality, "as_of": "2026-03-31"}

    def test_surface_and_asset_metadata_are_adapter_compatible(self):
        self.assertEqual(list(inspect.signature(DemoImageService).parameters), ["raw_data", "static_root", "incident_map", "model_root"])
        assets = self.service.assets(self.payload())
        self.assertEqual([asset["asset_id"] for asset in assets["assets"]], ["SYN-A", "SYN-B"])
        self.assertEqual(set(assets["assets"][0]), {
            "asset_id", "incident_id", "lot_id", "wafer_id", "item", "step", "equipment",
            "modality", "coordinate_system", "acquisition", "acquired_at", "revision",
        })
        self.assertEqual(assets["assets"][0]["equipment"], "EQ-1")
        self.assertEqual(assets["assets"][1]["equipment"], "EQ-2")

    def test_sem_compare_returns_measured_incomparable_baseline(self):
        result = self.service.compare({
            **self.payload(), "request_id": "req-1", "model": SEM_MODEL,
            "asset_ids": ["SYN-A", "SYN-B"], "asset_revisions": ["synthetic-asset-v1", "synthetic-asset-v1"],
        })
        self.assertEqual(result["status"], "INCOMPARABLE")
        self.assertIsNone(result["similarity"])
        self.assertFalse(result["alignment_verified"])
        self.assertTrue(any("edge_fraction" in finding for finding in result["findings"]))
        self.assertTrue(any("trained only on generated synthetic SEM classes" in limitation for limitation in result["limitations"]))

    def test_overlay_fixture_is_deterministic_and_honest(self):
        payload = self.overlay_request()
        first = self.service.compare(payload)
        second = self.service.compare(payload)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "INCOMPARABLE")
        self.assertTrue(any("frontend/server synthetic-common-grid-v2" in finding for finding in first["findings"]))
        self.assertTrue(any("exact_coordinate_matches=44" in finding for finding in first["findings"]))

    def overlay_request(self):
        assets = self.service.assets(self.payload("overlay"))["assets"][:2]
        return {**self.payload("overlay"), "request_id": "req-2", "model": OVERLAY_MODEL,
                "asset_ids": [a["asset_id"] for a in assets],
                "asset_revisions": [a["revision"] for a in assets]}

    @unittest.skipUnless(shutil.which("node"), "Node required for actual frontend parity")
    def test_overlay_fixture_matches_actual_typescript_every_point(self):
        pairs = [["SYN-LOT-09-01", f"W{i:02d}"] for i in (1, 2, 3)] + [["LOT-1", "W01"]]
        script = ("import {makeOverlayFixture} from './src/overlayVectors.ts';"
                  "console.log(JSON.stringify(" + json.dumps(pairs) + ".map(([l,w]) => makeOverlayFixture(l,w).points)));")
        output = subprocess.run([shutil.which("node"), "--experimental-strip-types", "--input-type=module", "-e", script],
                                cwd=Path(__file__).resolve().parents[1] / "web", capture_output=True, text=True, check=True)
        for pair, expected in zip(pairs, json.loads(output.stdout)):
            actual = DemoImageService._fixture_vectors(*pair)
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected):
                for key in ("x", "y", "dx", "dy"):
                    self.assertAlmostEqual(left[key], right[key], places=12)

    def test_explicit_overlay_vectors_match_only_exact_coordinates(self):
        self.raw["SYN-1"]["engineering"]["fab"][0]["overlay_vectors"] = [{"x": 0, "y": 0, "dx": 1, "dy": 2}]
        self.raw["SYN-1"]["engineering"]["fab"][1]["overlay_vectors"] = [
            {"x": 0, "y": 0, "dx": 1.5, "dy": 2.5}, {"x": 1, "y": 1, "dx": 9, "dy": 9}
        ]
        result = self.service.compare(self.overlay_request())
        self.assertTrue(any("exact_coordinate_matches=1" in finding for finding in result["findings"]))
        self.assertTrue(any("missing_from_A=1" in finding for finding in result["findings"]))

    def test_loaded_classifier_does_not_collapse_bridge_and_gap(self):
        first = self.service._image_metrics({"_src": "/assets/a.png"})
        second = self.service._image_metrics({"_src": "/assets/b.png"})
        model = self.service._model("sem")
        first_class = self.service._predict(model, self.service._sem_features(first))[0]
        second_class = self.service._predict(model, self.service._sem_features(second))[0]
        self.assertNotEqual(first_class, second_class)

    def test_all_fab_wafers_have_overlay_assets_without_sem_rows(self):
        fab = self.raw["SYN-1"]["engineering"]["fab"]
        fab.append({**fab[0], "waferId": "W03"})
        assets = self.service.assets(self.payload("overlay"))["assets"]
        self.assertEqual(len(assets), 3)
        self.assertTrue(all(a["asset_id"].startswith("SYN-OVL-") for a in assets))
        self.assertEqual(len(self.service.assets(self.payload())["assets"]), 2)
        self.assertEqual(self.service.assets({**self.payload("overlay"), "item": "unknown"}), {"assets": []})
        with self.assertRaisesRegex(ToolError, "IMAGE_SCOPE_INVALID"):
            self.service.assets({**self.payload("overlay"), "incident_ids": ["outside"]})

    def test_incident_fixture_classifications_are_computed_non_nominal(self):
        model = self.service._model("overlay")
        for wafer, expected in (("W01", "radial"), ("W02", "nominal"), ("W03", "translation")):
            vectors = self.service._fixture_vectors("SYN-LOT-09-01", wafer)
            predicted, _, _ = self.service._predict(model, self.service._overlay_features(vectors))
            self.assertEqual(predicted, expected)

    def test_existing_workbench_bitmaps_predict_bridge_and_reference(self):
        service = DemoImageService(self.raw, Path(__file__).resolve().parents[1] / "web" / "public", {}, self.model_root)
        model = service._model("sem")
        for filename, expected in (("synthetic-sem.png", "bridge"), ("synthetic-sem-history.png", "bridge"), ("synthetic-sem-reference.png", "baseline")):
            metrics = service._image_metrics({"_src": "/assets/" + filename})
            self.assertEqual((metrics["width"], metrics["height"]), (1254, 1254))
            predicted, _, _ = service._predict(model, service._sem_features(metrics))
            self.assertEqual(predicted, expected)

    def test_historical_reference_ranking_and_temporal_item_scope(self):
        base = {"id": "SYN-PAST-BRIDGE", "incident_number": "SYN-PAST-1",
                "occurred_at": "2026-02-01T00:00:00Z", "item": "ITEM-1", "step": "STEP-1",
                "modality": "sem", "provenance": "synthetic", "description": "synthetic bridge",
                "src": "/assets/a.png"}
        self.raw["SYN-1"]["image_history"] = [base,
            {**base, "id": "SYN-PAST-GAP", "src": "/assets/b.png"},
            {**base, "id": "SYN-FUTURE", "occurred_at": "2026-04-01T00:00:00Z"},
            {**base, "id": "SYN-WRONG-ITEM", "item": "other"},
            {**base, "id": "SYN-WRONG-STEP", "step": "other"}]
        result = self.service.compare({**self.payload(), "request_id": "r", "model": SEM_MODEL,
                                      "asset_ids": ["SYN-A", "SYN-B"], "asset_revisions": ["synthetic-asset-v1"] * 2})
        history = [line for line in result["findings"] if "historical candidate" in line]
        self.assertEqual(len(history), 4)
        self.assertIn("owner=A, rank=1, reference_id=SYN-PAST-BRIDGE", history[0])
        self.assertIn("descriptor_distance=0.000000", history[0])
        self.assertIn("owner=B, rank=1, reference_id=SYN-PAST-GAP", history[2])
        self.assertNotIn("SYN-FUTURE", str(history))
        self.assertNotIn("SYN-WRONG", str(history))
        self.assertIsNone(result["similarity"])
        self.assertEqual(result["status"], "INCOMPARABLE")
        self.assertEqual(len(self.service.assets(self.payload())["assets"]), 2)

    def test_example_history_uses_distinct_bitmaps_and_computed_overlay_neighbors(self):
        root = Path(__file__).resolve().parents[1]
        raw = json.loads((root / "data/workbench/raw.example.json").read_text(encoding="utf-8"))
        service = DemoImageService(raw, root / "web/public", {}, self.model_root)
        self.assertNotEqual((root / "web/public/assets/synthetic-sem.png").read_bytes(),
                            (root / "web/public/assets/synthetic-sem-history.png").read_bytes())
        for modality in ("sem", "overlay"):
            payload = {"actor": "demo", "incident_ids": ["SYN-2026-01"], "item": "SYN-TEMP",
                       "modality": modality, "as_of": "2026-03-31"}
            assets = service.assets(payload)["assets"][:2]
            result = service.compare({**payload, "request_id": "history-demo",
                                      "model": service.model_ids[modality],
                                      "asset_ids": [a["asset_id"] for a in assets],
                                      "asset_revisions": [a["revision"] for a in assets]})
            history = [line for line in result["findings"] if "historical candidate" in line]
            self.assertEqual(len(history), 4)
            self.assertIn("BRIDGE" if modality == "sem" else "RADIAL", history[0])

    def test_invalid_history_cannot_read_unregistered_files(self):
        self.raw["SYN-1"]["image_history"] = [{"id": "ref", "incident_number": "SYN-PAST",
            "occurred_at": "2026-02-01T00:00:00Z", "item": "ITEM-1", "step": "STEP-1",
            "modality": "sem", "provenance": "synthetic", "description": "synthetic",
            "src": "/assets/../private.png"}]
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_HISTORY"):
            self.service.compare({**self.payload(), "request_id": "r", "model": SEM_MODEL,
                                  "asset_ids": ["SYN-A", "SYN-B"], "asset_revisions": ["synthetic-asset-v1"] * 2})

    def test_missing_or_corrupt_model_never_uses_canned_result(self):
        service = DemoImageService(self.raw, self.root, {"SYN-1": {"incident_id": "INC-1", "incident_number": "SYN-1"}}, self.root / "missing")
        request = {**self.payload(), "request_id": "req", "model": SEM_MODEL,
                   "asset_ids": ["SYN-A", "SYN-B"], "asset_revisions": ["synthetic-asset-v1", "synthetic-asset-v1"]}
        with self.assertRaisesRegex(ToolError, "DEMO_IMAGE_MODEL_INVALID"):
            service.compare(request)
        broken = self.root / "broken" / "sem"
        broken.mkdir(parents=True)
        (broken / "model.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ToolError, "DEMO_IMAGE_MODEL_INVALID"):
            DemoImageService(self.raw, self.root, {"SYN-1": {"incident_id": "INC-1", "incident_number": "SYN-1"}}, self.root / "broken").compare(request)

    def test_scope_revision_model_modality_and_path_validation(self):
        with self.assertRaisesRegex(ToolError, "INVALID_MODALITY"):
            self.service.assets({**self.payload(), "modality": "xray"})
        with self.assertRaisesRegex(ToolError, "IMAGE_ASSET_REVISION_MISMATCH"):
            self.service.compare({**self.payload(), "request_id": "r", "model": SEM_MODEL,
                                  "asset_ids": ["SYN-A", "SYN-B"], "asset_revisions": ["bad", "bad"]})
        with self.assertRaisesRegex(ToolError, "IMAGE_ASSET_IDS_REQUIRED"):
            self.service.compare({**self.payload(), "request_id": "r", "model": SEM_MODEL,
                                  "asset_ids": [["SYN-A"], "SYN-B"], "asset_revisions": ["synthetic-asset-v1", "synthetic-asset-v1"]})
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_COMPARE_RESULT"):
            self.service.compare({**self.payload(), "request_id": "r", "model": OVERLAY_MODEL,
                                  "asset_ids": ["SYN-A", "SYN-B"], "asset_revisions": ["synthetic-asset-v1"]})
        invalid = {"SYN-1": {**self.raw["SYN-1"], "sem_assets": [
            {**self.raw["SYN-1"]["sem_assets"][0], "src": "/assets/../secret.png"},
            self.raw["SYN-1"]["sem_assets"][1],
        ]}}
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_ASSET"):
            DemoImageService(invalid, self.root, {"SYN-1": {"incident_id": "INC-1", "incident_number": "SYN-1"}}).assets(self.payload())


if __name__ == "__main__":
    unittest.main()
