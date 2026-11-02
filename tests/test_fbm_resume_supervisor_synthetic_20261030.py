import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "research" / "fbm_resume_supervisor_synthetic_20261030.py"
spec = importlib.util.spec_from_file_location("fbm_supervisor", MODULE_PATH)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.var = self.root / "var"
        self.var.mkdir()
        supervisor.VAR = self.var
        self.files = {}
        for name in ("prior", "primary", "backbone", "head"):
            p = self.root / name
            p.write_bytes(name.encode())
            self.files[name] = p
        self.out = self.var / "fresh"
        self.args = argparse.Namespace(
            gate="unit-gate", prior_manifest=self.files["prior"], prior_sha256=supervisor._sha(self.files["prior"]),
            primary_manifest=self.files["primary"], primary_sha256=supervisor._sha(self.files["primary"]),
            backbone=self.files["backbone"], backbone_sha256=supervisor._sha(self.files["backbone"]),
            head=self.files["head"], head_sha256=supervisor._sha(self.files["head"]), output_dir=self.out)
        self.env_patch = patch.dict(os.environ, {supervisor.GATE_ENV: "unit-gate", "SECRET_TEST_VALUE": "must-not-leak"})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp.cleanup()

    @patch.object(supervisor.os, "name", "nt")
    @patch.object(supervisor.subprocess, "Popen")
    def test_argv_gate_shell_wait_and_atomic_status(self, popen):
        child = Mock(pid=4321)
        child.wait.return_value = 0
        popen.return_value = child
        with patch.object(supervisor, "_atomic_json", wraps=supervisor._atomic_json) as atomic:
            self.assertEqual(supervisor.run(self.args), 0)
        argv = popen.call_args.args[0]
        kwargs = popen.call_args.kwargs
        self.assertEqual(argv[0], supervisor.sys.executable)
        self.assertIn("--run", argv)
        self.assertIn(str(self.out / "runner_output"), argv)
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["env"][supervisor.GATE_ENV], "unit-gate")
        self.assertNotIn("SECRET_TEST_VALUE", kwargs["env"])
        self.assertNotIn("QAGENT_CONFIG", kwargs["env"])
        self.assertEqual(kwargs["env"]["OMP_NUM_THREADS"], "1")
        child.wait.assert_called_once_with()
        self.assertGreaterEqual(atomic.call_count, 2)
        status = json.loads((self.out / "supervisor_status.json").read_text())
        self.assertEqual(status["child_pid"], 4321)
        self.assertEqual(status["returncode"], 0)
        self.assertTrue(status["process_exited"])
        self.assertFalse(status["completion_verified"])
        self.assertEqual(status["status"], "process_exited_zero_manifest_not_independently_verified")
        self.assertNotIn("must-not-leak", json.dumps(status))
        self.assertTrue((self.out / "runner.stdout.log").exists())
        self.assertTrue((self.out / "runner.stderr.log").exists())

    @patch.object(supervisor.os, "name", "nt")
    @patch.object(supervisor.subprocess, "Popen")
    def test_nonzero_child_returncode_is_failed(self, popen):
        child = Mock(pid=51); child.wait.return_value = 7; popen.return_value = child
        self.assertEqual(supervisor.run(self.args), 7)
        status = json.loads((self.out / "supervisor_status.json").read_text())
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["returncode"], 7)
        self.assertTrue(status["process_exited"])
        self.assertFalse(status["completion_verified"])

    @patch.object(supervisor.os, "name", "nt")
    def test_existing_output_refused(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):
            supervisor.run(self.args)

    def test_reparse_component_rejected_before_resolution(self):
        target = self.var / "junction" / "nested"
        original = Path.lstat
        def fake_lstat(path):
            if path == self.var / "junction":
                return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
            return original(path)
        with patch.object(Path, "lstat", autospec=True, side_effect=fake_lstat):
            with self.assertRaisesRegex(ValueError, "reparse"):
                supervisor._under_var(target)

    @patch.object(supervisor.os, "name", "nt")
    @patch.object(supervisor.subprocess, "Popen", side_effect=OSError("mock failure"))
    def test_spawn_exception_records_inconclusive_error_without_secrets(self, _popen):
        with self.assertRaises(OSError):
            supervisor.run(self.args)
        status = json.loads((self.out / "supervisor_status.json").read_text())
        self.assertEqual(status["status"], "supervisor_error")
        self.assertFalse(status["completion_verified"])
        self.assertNotIn("must-not-leak", json.dumps(status))

    def test_self_check_does_not_launch(self):
        self.assertFalse(supervisor._self_check()["child_started"])


if __name__ == "__main__":
    unittest.main()
