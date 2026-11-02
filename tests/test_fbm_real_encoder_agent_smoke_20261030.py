"""Cheap prechecks for the explicitly gated local encoder Agent smoke."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "research" / "fbm_real_encoder_agent_smoke_20261030.py"
sys.path.insert(0, str(ROOT / "research"))

import fbm_real_encoder_agent_smoke_20261030 as smoke


class FBMRealEncoderAgentSmokeTests(unittest.TestCase):
    def test_default_cli_is_weight_free_structural_self_check(self):
        proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True,
                              capture_output=True, check=True)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "structural-self-check-pass")
        self.assertFalse(result["weights_loaded"])
        self.assertFalse(result["inference_run"])
        self.assertTrue(result["synthetic_only"])
        self.assertEqual(result["model_version"], "synthetic-local-smoke")

    def test_synthetic_images_are_separate_query_and_gallery_assets(self):
        images = smoke._make_images()
        self.assertEqual(set(images), {"raw_fbm", "object_id_yield"})
        for pair in images.values():
            self.assertTrue(pair["query"].startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertTrue(pair["gallery"].startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertNotEqual(pair["query"], pair["gallery"])
        self.assertNotEqual(images["raw_fbm"]["query"], images["object_id_yield"]["query"])

    def test_run_requires_parent_gate_before_checkpoint_arguments(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "--run"], cwd=ROOT,
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("parent audit/resource gate", proc.stderr)

    def test_encoder_setup_does_not_set_interop_threads_before_loader(self):
        # A fresh interpreter imports real torch first. The fake loader mirrors
        # _load_encoder's sole interop-thread setup, then completes four fake forwards.
        code = f'''\
import json, sys, types
from pathlib import Path
import torch
sys.path.insert(0, {str(ROOT / "research")!r})
import fbm_real_encoder_agent_smoke_20261030 as smoke
torchvision = types.ModuleType("torchvision")
transforms = types.ModuleType("torchvision.transforms")
transforms.InterpolationMode = types.SimpleNamespace(BILINEAR=0)
transforms.Compose = lambda operations: (lambda image: torch.ones((3, 384, 384)))
transforms.Resize = lambda *args, **kwargs: None
transforms.ToTensor = lambda: None
transforms.Normalize = lambda *args, **kwargs: None
torchvision.transforms = transforms
sys.modules["torchvision"] = torchvision
sys.modules["torchvision.transforms"] = transforms
calls = []
class Backbone:
    def forward_features(self, tensor):
        return torch.ones((1, 1024, 2, 2))
head = torch.nn.Linear(1024, 128)
def fake_load(*args):
    torch.set_num_interop_threads(1)
    calls.append("loader")
    return Backbone(), head, "d" * 64, "e" * 64, torch.nn.functional
smoke._BASE._load_encoder = fake_load
vectors, checkpoint_hash = smoke._encode_images(Path("fake-backbone"), Path("fake-head"),
                                                  "b" * 64, "c" * 64, smoke._make_images())
print(json.dumps({{"loader_calls": calls, "vector_count": len(vectors),
                  "checkpoint_hash_length": len(checkpoint_hash)}}))
'''
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True,
                              capture_output=True, check=True)
        result = json.loads(proc.stdout)
        self.assertEqual(result, {"loader_calls": ["loader"], "vector_count": 4,
                                  "checkpoint_hash_length": 64})

    def test_mocked_model_runs_full_execute_for_both_representations(self):
        # Exercise _execute end to end with fake embeddings; this covers the
        # synthetic DB, catalog, callback, scripted Agent, and response validator.
        vectors = {
            (rep, role): ([1.0] + [0.0] * 127 if role == "query"
                          else [0.0, 1.0] + [0.0] * 126)
            for rep in ("raw_fbm", "object_id_yield")
            for role in ("query", "gallery")
        }
        with patch.object(smoke, "_encode_images", return_value=(vectors, "a" * 64)), \
             patch.object(smoke._BASE, "_job_memory_cap"), \
             patch.object(smoke._BASE, "_disable_network"), \
             patch.object(smoke, "SyntheticFBMAgentCatalogAdapter",
                          wraps=smoke.SyntheticFBMAgentCatalogAdapter) as adapter_factory:
            result = smoke._execute(Path("mock-backbone"), Path("mock-head"), "b" * 64, "c" * 64)

        self.assertEqual(adapter_factory.call_count, 3)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(set(result["representations"]), {"raw_fbm", "object_id_yield_fbm"})
        for representation, report in result["representations"].items():
            with self.subTest(representation=representation):
                self.assertEqual(report["agent_status"], "answered")
                self.assertEqual(report["router_tool_sequence"][:3],
                                 ["find_incidents", "list_incident_lots", "list_incident_wafers"])
                self.assertEqual(report["router_tool_sequence"][3], "search_similar_fbm")
                self.assertFalse(report["query_asset_self_match_present"])
                self.assertEqual(report["query_only_status"], "NO_MATCH")
                self.assertTrue(report["different_wafer_gallery_match_present"])
                self.assertFalse(report["source_reported_truncated"])
                self.assertEqual(report["model_version"], "synthetic-local-smoke")
                self.assertEqual(report["query_vector_provenance"], "cached_same_process_model_vector")
                self.assertFalse(report["fresh_callback_inference"])
                self.assertFalse(report["physical_identity_verified"])
        self.assertEqual(result["source_acl_and_physical_identity"], "unverified")
        self.assertFalse(result["quality_performance_claim"])


if __name__ == "__main__":
    unittest.main()
