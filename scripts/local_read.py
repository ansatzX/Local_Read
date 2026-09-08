#!/usr/bin/env python3
"""Launch the bundled runtime with uv without changing the caller's cwd."""

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "failed",
                    "success": False,
                    "error": "uv is required to launch this skill. Install uv, then retry.",
                }
            )
        )
        return 1
    root = Path(__file__).resolve().parents[1]
    artifacts = Path.cwd() / ".local_read_mcp"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["LOCAL_READ_CONFIG_DIR"] = str(root)
    (artifacts / "tmp").mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(artifacts / "tmp")
    # Load the stdlib-only helper without importing the optional document stack.
    runtime = runpy.run_path(str(root / "src/local_read/local_runtime.py"))
    try:
        env.update(runtime["cache_environment"]())
        shared_root = runtime["runtime_root"]()
        environment = runtime["runtime_path"](root)
        env["UV_CACHE_DIR"] = str(shared_root / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(environment)
        env["UV_PYTHON_INSTALL_DIR"] = str(shared_root / "python")
    except ValueError as exc:
        print(json.dumps({"schema_version": "1.0", "status": "failed", "success": False, "error": str(exc)}))
        return 1
    args = sys.argv[1:]
    # Accepted for older invocations; inference dependencies are now standard.
    args = [arg for arg in args if arg != "--with-mineru"]
    prepare_models = args[:2] == ["models", "prepare"]
    online = bool(args) and (args[0] in {"setup", "analyze"} or prepare_models)
    try:
        with runtime["file_lock"](environment.with_suffix(".lock"), timeout=3600):
            if not online and not (environment / "pyvenv.cfg").is_file():
                print(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "status": "failed",
                            "success": False,
                            "error": "Offline runtime is not prepared. Run this launcher with 'setup' or 'models prepare' (MinerU) while online first.",
                        }
                    )
                )
                return 1
            if not online:
                env["MINERU_MODEL_SOURCE"] = "local"
                env["HF_HUB_OFFLINE"] = "1"
                env["TRANSFORMERS_OFFLINE"] = "1"
            command = [
                uv,
                "run",
                "--project",
                str(root),
                "--locked",
                "--no-dev",
                "--no-editable",
                # Offline reads never resync or
                # resolve packages. Explicit preparation owns dependency changes.
                *([] if online else ["--offline", "--no-sync"]),
                "python",
                "-m",
                "local_read",
                *args,
            ]
            # Hold the runtime lock while uv installs or the reader uses its packages.
            return subprocess.call(command, env=env)
    except (OSError, ValueError, TimeoutError) as exc:
        print(json.dumps({"schema_version": "1.0", "status": "failed", "success": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
