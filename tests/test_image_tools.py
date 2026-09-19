import inspect
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from incident_tools import ToolError
from image_tools import ImageTools


ASSET_FIELDS = {
    "asset_id", "incident_id", "lot_id", "wafer_id", "item", "step",
    "equipment", "modality", "coordinate_system", "acquisition",
    "acquired_at", "revision",
}


def _asset(asset_id, incident_id="I1", **changes):
    value = {
        "asset_id": asset_id, "incident_id": incident_id, "lot_id": "L1",
        "wafer_id": "W1", "item": "ITEM-A", "step": "STEP-1",
        "equipment": "EQ-1", "modality": "sem", "coordinate_system": "XY",
        "acquisition": "recipe-1", "acquired_at": "2026-01-02T10:00:00+09:00",
        "revision": "r1",
    }
    value.update(changes)
    return value


class _IncidentStub:
    def __init__(self, ids=("I1",), wafers=None):
        self.ids = tuple(ids)
        self.wafers = wafers or [
            {"incident_id": "I1", "lot_id": "L1", "wafer_id": "W1"},
            {"incident_id": "I1", "lot_id": "L1", "wafer_id": "W2"},
        ]
        self.scope_calls = []
        self.wafer_calls = []
        self.expired = False

    def _scope(self, actor, scope_id):
        self.scope_calls.append((actor, scope_id))
        if self.expired:
            raise ToolError("INCIDENT_LOOKUP_REQUIRED_OR_SCOPE_EXPIRED")
        return {"ids": self.ids}

    def list_incident_wafers(self, actor, scope_id, page_size=None, offset=0):
        self.wafer_calls.append((actor, scope_id, page_size, offset))
        pages = [self.wafers[offset:offset + page_size]]
        items = pages[0]
        next_offset = offset + len(items) if offset + len(items) < len(self.wafers) else None
        return {"items": items, "next_offset": next_offset}


class _ImageHandler(BaseHTTPRequestHandler):
    mode = "success"
    assets = [_asset("A1"), _asset("A2", wafer_id="W2", revision="r2")]
    requests = []

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size)
        self.__class__.requests.append((self.path, self.headers.get("Authorization"), json.loads(raw)))
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.mode == "oversized":
            body = b"x" * (1024 * 1024 + 1)
        elif self.path == "/assets":
            body = json.dumps({"assets": self.assets}).encode()
        else:
            request = self.__class__.requests[-1][2]
            body = json.dumps({
                "request_id": request["request_id"],
                "model": request["model"],
                "model_version": "model-v7",
                "item": request["item"],
                "modality": request["modality"],
                "asset_ids": request["asset_ids"],
                "asset_revisions": request["asset_revisions"],
                "status": "OK",
                "alignment_verified": True,
                "similarity": 0.75,
                "findings": ["model similarity only"],
                "limitations": ["not a defect probability"],
                "artifact_ids": ["artifact-1"],
            }).encode()
            if self.mode == "bad-model-version":
                result = json.loads(body)
                result["model_version"] = 4
                body = json.dumps(result).encode()
            elif self.mode in ("nan-score", "inf-score", "out-of-range-score"):
                result = json.loads(body)
                result["similarity"] = {
                    "nan-score": float("nan"),
                    "inf-score": float("inf"),
                    "out-of-range-score": 1.01,
                }[self.mode]
                body = json.dumps(result).encode()
            elif self.mode == "bad-alignment":
                result = json.loads(body)
                result["alignment_verified"] = False
                result["similarity"] = None
                body = json.dumps(result).encode()
            elif self.mode in ("bad-request-id", "bad-model", "bad-asset-ids", "bad-revisions"):
                result = json.loads(body)
                if self.mode == "bad-request-id":
                    result["request_id"] = "00000000-0000-0000-0000-000000000000"
                elif self.mode == "bad-model":
                    result["model"] = "unexpected-model"
                elif self.mode == "bad-asset-ids":
                    result["asset_ids"] = ["A2", "A1"]
                else:
                    result["asset_revisions"] = ["wrong-r1", "wrong-r2"]
                body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ImageToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _ImageHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _ImageHandler.mode = "success"
        _ImageHandler.assets = [_asset("A1"), _asset("A2", wafer_id="W2", revision="r2")]
        _ImageHandler.requests = []
        self.incidents = _IncidentStub()

    def settings(self, **changes):
        sem = {"enabled": True, "endpoint": self.endpoint, "api_key_env": "",
               "timeout_seconds": 2, "served_model": "sem-model"}
        overlay = {"enabled": True, "endpoint": self.endpoint, "api_key_env": "",
                   "timeout_seconds": 2, "served_model": "overlay-model"}
        sem.update(changes.pop("sem", {}))
        overlay.update(changes.pop("overlay", {}))
        return SimpleNamespace(data={"image_tools": {"sem": sem, "overlay": overlay},
                                     "runtime": {"max_page_size": 2}, **changes})

    def tool(self, **changes):
        return ImageTools(self.settings(**changes), self.incidents)

    def list_assets(self, tool=None):
        return (tool or self.tool()).list_comparison_assets(
            "actor", "scope", "ITEM-A", "sem", "2026-12-31")

    def test_public_signatures_are_parent_integration_surface(self):
        self.assertEqual(list(inspect.signature(ImageTools.__init__).parameters), ["self", "settings", "incident_tools"])
        self.assertEqual(list(inspect.signature(ImageTools.list_comparison_assets).parameters),
                         ["self", "actor", "scope_id", "item", "modality", "as_of"])
        self.assertEqual(list(inspect.signature(ImageTools.compare_sem_images).parameters),
                         ["self", "actor", "scope_id", "item", "asset_ids", "as_of"])
        self.assertEqual(list(inspect.signature(ImageTools.compare_overlay_maps).parameters),
                         ["self", "actor", "scope_id", "item", "asset_ids", "as_of"])

    def test_disabled_is_rejected_before_network(self):
        tool = self.tool(sem={"enabled": False, "endpoint": "", "served_model": ""})
        with self.assertRaisesRegex(ToolError, "IMAGE_MODEL_DISABLED"):
            self.list_assets(tool)
        self.assertEqual(_ImageHandler.requests, [])

    def test_scope_empty_and_cross_incident_asset_are_rejected(self):
        self.incidents.ids = ()
        with self.assertRaisesRegex(ToolError, "IMAGE_SCOPE_EMPTY"):
            self.list_assets()
        self.incidents.ids = ("I1",)
        _ImageHandler.assets = [_asset("A1", incident_id="I2")]
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_ASSET"):
            self.list_assets()

    def test_list_paginates_registry_and_caches_verified_assets(self):
        self.incidents.wafers = [
            {"incident_id": "I1", "lot_id": "L1", "wafer_id": "W1"},
            {"incident_id": "I1", "lot_id": "L1", "wafer_id": "W2"},
            {"incident_id": "I1", "lot_id": "L1", "wafer_id": "W3"},
        ]
        result = self.list_assets()
        self.assertEqual(set(result["assets"][0]), ASSET_FIELDS)
        self.assertEqual([call[2:] for call in self.incidents.wafer_calls], [(2, 0), (2, 2)])
        self.assertEqual(_ImageHandler.requests[0][2]["incident_ids"], ["I1"])

    def test_compare_requires_cached_ids_and_rejects_metadata_mismatch(self):
        tool = self.tool()
        with self.assertRaisesRegex(ToolError, "IMAGE_ASSET_UNKNOWN"):
            tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")
        self.list_assets(tool)
        _ImageHandler.assets[1] = _asset("A2", wafer_id="W2", step="STEP-2", revision="r2")
        tool = self.tool()
        self.list_assets(tool)
        with self.assertRaisesRegex(ToolError, "IMAGE_COMPARISON_INCOMPATIBLE"):
            tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")
        self.assertEqual([request[0] for request in _ImageHandler.requests], ["/assets", "/assets"])

    def test_compare_rejects_step_acquisition_and_coordinate_mismatches(self):
        for field in ("step", "acquisition", "coordinate_system"):
            with self.subTest(field=field):
                tool = self.tool()
                _ImageHandler.assets[1] = _asset("A2", wafer_id="W2", revision="r2", **{field: "different"})
                self.list_assets(tool)
                with self.assertRaisesRegex(ToolError, "IMAGE_COMPARISON_INCOMPATIBLE"):
                    tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")

    def test_list_rejects_same_item_mismatch_before_compare(self):
        tool = self.tool()
        _ImageHandler.assets[1] = _asset("A2", wafer_id="W2", revision="r2", item="ITEM-B")
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_ASSET"):
            self.list_assets(tool)

    def test_expired_scope_is_rechecked_before_compare(self):
        tool = self.tool()
        self.list_assets(tool)
        self.incidents.expired = True
        with self.assertRaisesRegex(ToolError, "INCIDENT_LOOKUP_REQUIRED_OR_SCOPE_EXPIRED"):
            tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")
        self.assertEqual([request[0] for request in _ImageHandler.requests], ["/assets"])

    def test_success_posts_only_ids_and_returns_model_score_provenance(self):
        tool = self.tool()
        self.list_assets(tool)
        result = tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")
        request = _ImageHandler.requests[-1][2]
        self.assertEqual(request["asset_ids"], ["A1", "A2"])
        self.assertEqual(request["asset_revisions"], ["r1", "r2"])
        self.assertNotIn("paths", request)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["provenance"]["score_type"], "model_similarity")
        self.assertEqual(result["provenance"]["model_score"], 0.75)
        self.assertEqual(result["provenance"]["validated_asset_metadata"], [_asset("A1"), _asset("A2", wafer_id="W2", revision="r2")])

    def test_wrong_model_version_and_nonfinite_or_out_of_range_scores_are_rejected(self):
        tool = self.tool()
        self.list_assets(tool)
        _ImageHandler.mode = "bad-model-version"
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_COMPARE_RESULT"):
            tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")
        for mode in ("nan-score", "inf-score", "out-of-range-score"):
            with self.subTest(mode=mode):
                _ImageHandler.mode = mode
                with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_COMPARE_RESULT"):
                    tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")

    def test_ok_result_requires_verified_alignment_and_finite_similarity(self):
        tool = self.tool()
        self.list_assets(tool)
        _ImageHandler.mode = "bad-alignment"
        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_COMPARE_RESULT"):
            tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")

    def test_asset_cache_is_bound_to_as_of(self):
        tool = self.tool()
        self.list_assets(tool)
        with self.assertRaisesRegex(ToolError, "IMAGE_ASSET_UNKNOWN"):
            tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-30")

    def test_compare_requires_echoed_request_model_ids_and_revisions(self):
        tool = self.tool()
        self.list_assets(tool)
        for mode in ("bad-request-id", "bad-model", "bad-asset-ids", "bad-revisions"):
            with self.subTest(mode=mode):
                _ImageHandler.mode = mode
                with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_COMPARE_RESULT"):
                    tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")

    def test_missing_credential_and_authorization_header(self):
        tool = self.tool(sem={"api_key_env": "QAGENT_IMAGE_TEST_KEY"})
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ToolError, "IMAGE_API_KEY_UNAVAILABLE"):
                self.list_assets(tool)
        self.assertEqual(_ImageHandler.requests, [])

        with patch.dict(os.environ, {"QAGENT_IMAGE_TEST_KEY": "secret-token"}, clear=False):
            self.list_assets(tool)
        self.assertEqual(_ImageHandler.requests[0][1], "Bearer secret-token")

    def test_overlay_success_uses_overlay_model_and_real_compare_post(self):
        tool = self.tool()
        _ImageHandler.assets = [
            _asset("O1", modality="overlay"),
            _asset("O2", wafer_id="W2", modality="overlay", revision="r2"),
        ]
        listed = tool.list_comparison_assets("actor", "scope", "ITEM-A", "overlay", "2026-12-31")
        result = tool.compare_overlay_maps("actor", "scope", "ITEM-A", ["O1", "O2"], "2026-12-31")
        self.assertEqual([asset["asset_id"] for asset in listed["assets"]], ["O1", "O2"])
        self.assertEqual(_ImageHandler.requests[-1][2]["model"], "overlay-model")
        self.assertEqual(result["modality"], "overlay")
        self.assertEqual(result["status"], "OK")

    def test_sem_success_with_disabled_other_modality_empty_model(self):
        tool = self.tool(overlay={"enabled": False, "endpoint": "", "served_model": ""})
        result = self.list_assets(tool)
        compared = tool.compare_sem_images("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")
        self.assertEqual(result["assets"][0]["modality"], "sem")
        self.assertEqual(compared["model"], "sem-model")
        with self.assertRaisesRegex(ToolError, "IMAGE_MODEL_DISABLED"):
            tool.compare_overlay_maps("actor", "scope", "ITEM-A", ["A1", "A2"], "2026-12-31")

    def test_redirect_and_oversized_response_are_refused(self):
        _ImageHandler.mode = "redirect"
        with self.assertRaisesRegex(ToolError, "IMAGE_REDIRECT_REFUSED"):
            self.list_assets()
        _ImageHandler.mode = "oversized"
        with self.assertRaisesRegex(ToolError, "IMAGE_RESPONSE_TOO_LARGE"):
            self.list_assets()


if __name__ == "__main__":
    unittest.main()
