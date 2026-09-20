import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.workbench import Workbench, WorkbenchError, create_server, load_workbench


ROOT = Path(__file__).resolve().parents[1]
RAW_FIXTURE = ROOT / "data/workbench/raw.example.json"


class WorkbenchRawIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "static").mkdir()
        (self.root / "static/index.html").write_text("<main>workbench</main>", encoding="utf-8")
        self.raw = self.root / "raw.json"
        self.raw.write_bytes(RAW_FIXTURE.read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def config(self, *, source=None, port=None):
        lines = [
            "config_version: 1",
            "demo:",
            f"  base_config: {self.yaml_path(ROOT / 'config/config.yaml')}",
            f"  overlay: {self.yaml_path(ROOT / 'config/demo.yaml')}",
            "chat:",
            f"  sqlite_file: {self.yaml_path(self.root / 'chat.sqlite')}",
            "  history_limit: 40",
            "cutoff: 2026-03-31",
            f"static_root: {self.yaml_path(self.root / 'static')}",
        ]
        if port is not None:
            lines.extend(["server:", f"  port: {port}"])
        if source is not None:
            lines.extend(["sources:", f"  raw_file: {self.yaml_path(source)}"])
        path = self.root / f"workbench-{len(list(self.root.glob('workbench-*.yaml')))}.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def yaml_path(path):
        return str(path).replace("\\", "/")

    def test_loader_signature_default_port_and_cli_override(self):
        signature = inspect.signature(load_workbench)
        self.assertEqual(list(signature.parameters), ["path", "raw_file", "agent_overlay"])
        self.assertTrue(all(signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
                            for name in ("raw_file", "agent_overlay")))

        default_config = load_workbench(self.config(source=self.raw))
        self.assertEqual(default_config["port"], 8787)

        configured = self.config(source=self.raw, port=9876)
        self.assertEqual(load_workbench(configured)["port"], 9876)
        server = create_server(configured, 0, raw_file=self.raw)
        try:
            self.assertNotEqual(server.server_port, 9876)
            self.assertGreater(server.server_port, 0)
        finally:
            server.server_close()

    def test_missing_configured_raw_fails_before_generation(self):
        config = self.config(source=self.root / "missing.json")
        with patch("app.workbench.generate") as generate:
            with self.assertRaisesRegex(WorkbenchError, "missing"):
                load_workbench(config)
        generate.assert_not_called()

    def test_valid_raw_reaches_workspace_and_unregistered_fab_is_rejected(self):
        config_path = self.config(source=self.raw)
        loaded = load_workbench(config_path)
        workbench = Workbench(loaded)
        workspace = workbench.workspace("SYN-2026-09")
        self.assertIs(workspace["raw"], loaded["raw_data"]["SYN-2026-09"])
        self.assertEqual(len(workspace["raw"]["engineering"]["signals"]), 7)

        payload = json.loads(self.raw.read_text(encoding="utf-8"))
        payload["incidents"]["SYN-2026-09"]["engineering"]["fab"].append(
            {
                "lotId": "SYN-LOT-09-99",
                "waferId": "W99",
                "timestamp": "2026-03-28T08:05:00.000Z",
                "equipment": "SYN-EQP-01",
                "step": "SYN-ETCH-10",
                "recipe": "SYN-RCP-A",
                "value": 1.0,
            }
        )
        invalid_raw = self.root / "raw-invalid-scope.json"
        invalid_raw.write_text(json.dumps(payload), encoding="utf-8")
        invalid_workbench = Workbench(load_workbench(self.config(source=invalid_raw)))
        with self.assertRaisesRegex(WorkbenchError, "outside"):
            invalid_workbench.workspace("SYN-2026-09")

    def test_cli_raw_override_does_not_fall_back_to_configured_source(self):
        config = self.config(source=self.raw)
        missing_override = self.root / "missing-cli-raw.json"
        with self.assertRaisesRegex(WorkbenchError, "missing"):
            create_server(config, 0, raw_file=missing_override)


if __name__ == "__main__":
    unittest.main()
