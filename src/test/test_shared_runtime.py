"""Shared environment identity and real process locking contracts."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_read.local_runtime import file_lock

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "src/local_read/local_runtime.py"


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
