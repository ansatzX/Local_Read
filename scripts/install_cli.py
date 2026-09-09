#!/usr/bin/env python3
"""Explicitly install one user-level CLI using uv's tool manager (macOS/Linux)."""

import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Replace the managed installation with this checkout",
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    helper = runpy.run_path(str(root / "src/local_read/local_runtime.py"))
    uv = shutil.which("uv")
    if not uv or os.name != "posix":
        print("Installation requires uv on macOS/Linux.", file=sys.stderr)
        return 1
    home = helper["installation_root"]()
    entry = helper["cli_path"]()
    environment = helper["installed_environment"]()
    artifacts = Path.cwd() / ".local_read_mcp/install"
    try:
        with helper["file_lock"](home / "installation.lock", timeout=120):
            if (
                entry.exists() or entry.is_symlink()
            ) and not entry.resolve().is_relative_to(environment.resolve()):
                raise ValueError(f"Refusing to overwrite an unmanaged CLI: {entry}")
            if environment.exists() and not args.upgrade:
                raise ValueError(
                    "A managed installation already exists. Use --upgrade explicitly."
                )
            artifacts.mkdir(parents=True, exist_ok=True)
            constraints = artifacts / "constraints.txt"
            env = os.environ.copy()
            # Ignore activated project environments and route all tool installations
            # from this installer into the same user directory.
            env.pop("VIRTUAL_ENV", None)
            env.pop("PYTHONPATH", None)
            env["UV_TOOL_DIR"] = str(home / "tools")
            env["UV_TOOL_BIN_DIR"] = str(entry.parent)
            env["UV_CACHE_DIR"] = str(home / "cache")
            env["UV_PYTHON_INSTALL_DIR"] = str(home / "python")
            subprocess.run(
                [
                    uv,
                    "export",
                    "--project",
                    str(root),
                    "--locked",
                    "--no-dev",
                    "--no-emit-project",
                    "--no-hashes",
                    "--output-file",
                    str(constraints),
                ],
                env=env,
                check=True,
                stdout=sys.stderr,
            )
            subprocess.run(
                [
                    uv,
                    "tool",
                    "install",
                    "--python",
                    "3.12",
                    "--constraints",
                    str(constraints),
                    *(["--force"] if args.upgrade else []),
                    str(root),
                ],
                env=env,
                check=True,
                stdout=sys.stderr,
            )
            if not entry.is_file() or not entry.resolve().is_relative_to(
                environment.resolve()
            ):
                raise ValueError("uv did not create the expected managed CLI entry")
            print(
                json.dumps(
                    {
                        "success": True,
                        "executable": str(entry),
                        "installation_root": str(home),
                        "source": str(root),
                    }
                )
            )
            return 0
    except (OSError, ValueError, TimeoutError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
