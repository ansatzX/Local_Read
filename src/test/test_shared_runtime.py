"""Shared environment identity and real process locking contracts."""

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from local_read.local_runtime import file_lock, runtime_path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "src/local_read/local_runtime.py"


def test_runtime_identity_survives_relocation_but_not_code_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_READ_RUNTIME_DIR", str(tmp_path / "shared"))
    first = tmp_path / "skill-one"
    (first / "src/local_read").mkdir(parents=True)
    (first / "pyproject.toml").write_text("project")
    (first / "uv.lock").write_text("locked")
    (first / "src/local_read/app.py").write_text("version = 1")
    second = tmp_path / "skill-two"
    shutil.copytree(first, second)
    assert runtime_path(first) == runtime_path(second)
    (second / "src/local_read/app.py").write_text("version = 2")
    assert runtime_path(first) != runtime_path(second)


def test_lock_excludes_other_process_and_recovers_after_failure(tmp_path):
    lock = tmp_path / "shared.lock"
    code = (
        "import runpy,sys; from pathlib import Path; "
        "helper=runpy.run_path(sys.argv[1]); "
        "\nwith helper['file_lock'](Path(sys.argv[2]), timeout=0.1): print('acquired')"
    )
    def contender():
        return subprocess.run(
            [sys.executable, "-c", code, str(HELPER), str(lock)],
            capture_output=True, text=True, timeout=5,
        )
    with pytest.raises(ValueError):
        with file_lock(lock):
            blocked = contender()
            assert blocked.returncode != 0
            assert "Timed out" in blocked.stderr
            raise ValueError("simulated failed download")
    assert contender().stdout.strip() == "acquired"


def test_two_workspaces_reuse_prepared_runtime_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_READ_RUNTIME_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", str(tmp_path / "models"))
    environment = runtime_path(ROOT)
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("prepared")
    launcher = ROOT / "scripts/local_read.py"
    monkeypatch.setattr(sys, "argv", [str(launcher), "convert", "sample.pdf"])
    monkeypatch.setattr(shutil, "which", lambda _: "/fake/uv")
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda args, env: calls.append((args, env)) or 0)
    for name in ("one", "two"):
        project = tmp_path / name
        project.mkdir()
        monkeypatch.chdir(project)
        assert runpy.run_path(str(launcher))["main"]() == 0
        assert not (project / ".local_read_mcp/runtime").exists()
    assert calls[0][1]["UV_PROJECT_ENVIRONMENT"] == calls[1][1]["UV_PROJECT_ENVIRONMENT"]
    for args, env in calls:
        assert "--offline" in args and "--no-sync" in args
        assert env["HF_HUB_OFFLINE"] == "1"


def test_lock_released_when_owner_is_killed(tmp_path):
    lock = tmp_path / "death.lock"
    code = (
        "import runpy,sys,time; from pathlib import Path; "
        "helper=runpy.run_path(sys.argv[1]); "
        "\nwith helper['file_lock'](Path(sys.argv[2])): "
        "print('locked', flush=True); time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(HELPER), str(lock)], stdout=subprocess.PIPE,
        text=True, env=os.environ.copy(),
    )
    try:
        assert process.stdout.readline().strip() == "locked"
        process.kill()
        process.wait(timeout=5)
        with file_lock(lock, timeout=0.2):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
