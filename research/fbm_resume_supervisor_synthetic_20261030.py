#!/usr/bin/env python3
"""Single-child, synthetic-only monitor for the gated FBM resume runner."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import stat
import uuid

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
RUNNER = ROOT / "research" / "fbm_paired_controls_resume_synthetic_20261030.py"
GATE_ENV = "QAGENT_FBM_MODEL_LOAD_GATE"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _under_var(path: Path) -> Path:
    lexical = path if path.is_absolute() else Path.cwd() / path
    lexical = Path(os.path.abspath(lexical))
    lexical_var = Path(os.path.abspath(VAR))
    try:
        lexical.relative_to(lexical_var)
    except ValueError:
        raise ValueError("output and logs must be inside the existing repository var directory")
    # Inspect lexical components before resolve so junctions cannot disappear from view.
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & 0x400):
            raise ValueError("reparse points are not allowed in output paths")
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(VAR.resolve(strict=True))
    except (ValueError, FileNotFoundError):
        raise ValueError("resolved output path must remain inside the repository var directory")
    return resolved


def _child_environment(gate: str) -> dict[str, str]:
    allowed = ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATH", "PATHEXT",
               "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA")
    parent = {key.upper(): (key, value) for key, value in os.environ.items()}
    env = {name: parent[name.upper()][1] for name in allowed if name.upper() in parent}
    env.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", GATE_ENV: gate})
    return env


def _self_check() -> dict:
    return {"status": "supervisor_self_check_pass", "child_started": False, "synthetic_only": True}


def run(args: argparse.Namespace) -> int:
    if os.name != "nt":
        raise RuntimeError("supervisor requires Windows for the resume runner's Job Object enforcement")
    if os.environ.get(GATE_ENV) != args.gate:
        raise ValueError("explicit gate value does not match the inherited model-load gate")
    prior = args.prior_manifest.resolve(strict=True)
    primary = args.primary_manifest.resolve(strict=True)
    backbone = args.backbone.resolve(strict=True)
    head = args.head.resolve(strict=True)
    if _sha(prior) != args.prior_sha256.lower() or _sha(primary) != args.primary_sha256.lower():
        raise ValueError("manifest hash mismatch")
    if _sha(backbone) != args.backbone_sha256.lower() or _sha(head) != args.head_sha256.lower():
        raise ValueError("checkpoint hash mismatch")
    out = _under_var(args.output_dir)
    if out.exists():
        raise FileExistsError("fresh output directory already exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()  # Exclusive reservation prevents duplicate launches.
    status_path = out / "supervisor_status.json"
    stdout_path, stderr_path = out / "runner.stdout.log", out / "runner.stderr.log"
    for p in (status_path, stdout_path, stderr_path):
        if p.exists():
            raise FileExistsError("supervisor output collision")
    argv = [sys.executable, str(RUNNER), "--run", "--prior-manifest", str(prior),
            "--primary-manifest", str(primary), "--output-dir", str(out / "runner_output"),
            "--backbone", str(backbone), "--head", str(head),
            "--expected-backbone-sha256", args.backbone_sha256.lower(),
            "--expected-head-sha256", args.head_sha256.lower()]
    started = _utc()
    state = {"status": "running", "synthetic_only": True, "pid": os.getpid(),
             "child_pid": None, "started_utc": started, "ended_utc": None,
             "process_exited": False, "returncode": None, "completion_verified": False,
             "prior_manifest_sha256": args.prior_sha256.lower(),
             "primary_manifest_sha256": args.primary_sha256.lower(),
             "backbone_sha256": args.backbone_sha256.lower(), "head_sha256": args.head_sha256.lower(),
             "argv": argv, "stdout_log": str(stdout_path), "stderr_log": str(stderr_path),
             "note": "If forcibly terminated, running status is inconclusive; check PID and command line. No retry, restart, or kill is performed."}
    # Exclusive status creation before child launch protects against duplicate starts.
    with status_path.open("x", encoding="utf-8") as f:
        json.dump(state, f, indent=2); f.write("\n")
    child_env = _child_environment(args.gate)
    try:
        with stdout_path.open("x", encoding="utf-8") as stdout, stderr_path.open("x", encoding="utf-8") as stderr:
            child = subprocess.Popen(argv, shell=False, stdout=stdout, stderr=stderr, env=child_env)
            state["child_pid"] = child.pid
            _atomic_json(status_path, state)
            rc = child.wait()
        state.update(process_exited=True, returncode=rc, ended_utc=_utc(), completion_verified=False,
                     status=("process_exited_zero_manifest_not_independently_verified" if rc == 0 else "failed"))
        _atomic_json(status_path, state)
        return rc
    except BaseException as exc:
        state.update(status="supervisor_error", ended_utc=_utc(), completion_verified=False,
                     error_type=type(exc).__name__)
        _atomic_json(status_path, state)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-check", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--gate")
    p.add_argument("--prior-manifest", type=Path); p.add_argument("--prior-sha256")
    p.add_argument("--primary-manifest", type=Path); p.add_argument("--primary-sha256")
    p.add_argument("--backbone", type=Path); p.add_argument("--backbone-sha256")
    p.add_argument("--head", type=Path); p.add_argument("--head-sha256")
    p.add_argument("--output-dir", type=Path)
    a = p.parse_args(argv)
    if a.self_check and not a.run:
        print(json.dumps(_self_check(), indent=2)); return 0
    required = (a.gate, a.prior_manifest, a.prior_sha256, a.primary_manifest, a.primary_sha256,
                a.backbone, a.backbone_sha256, a.head, a.head_sha256, a.output_dir)
    if not a.run or not all(required):
        p.error("--run requires gate, explicit manifests/checkpoints and hashes, and fresh output directory")
    for value in (a.prior_sha256, a.primary_sha256, a.backbone_sha256, a.head_sha256):
        if len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            p.error("all expected hashes must be 64 hexadecimal characters")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
