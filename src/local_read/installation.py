"""Read-only diagnostics for the shared CLI and conflicting installations."""

import json
import os
import shutil
import sys
from importlib import metadata
from pathlib import Path

from .local_runtime import (
    cli_path,
    installation_root,
    installed_environment,
    model_root,
)


def doctor() -> dict:
    entry = cli_path()
    expected = installed_environment()
    candidates = []
    for directory in os.get_exec_path():
        path = Path(directory or ".") / "local-read"
        if path.is_file() and os.access(path, os.X_OK):
            item = {"path": str(path.absolute()), "target": str(path.resolve())}
            if item not in candidates:
                candidates.append(item)
    legacy = Path.home() / ".cache/local-read/runtime"
    old_environments = sorted(str(p.parent) for p in legacy.glob("*/pyvenv.cfg"))
    warnings = []
    managed = Path(sys.prefix).resolve() == expected.resolve()
    if not managed:
        warnings.append("This process is running outside the managed CLI environment.")
    if not entry.is_file():
        warnings.append("The canonical CLI entry is missing.")
    elif not entry.resolve().is_relative_to(expected.resolve()):
        warnings.append(
            "The canonical CLI entry points outside the managed environment."
        )
    if len({item["target"] for item in candidates}) > 1:
        warnings.append("Multiple distinct CLI installations are visible on PATH.")
    selected = shutil.which("local-read")
    if selected and Path(selected).resolve() != entry.resolve():
        warnings.append("PATH selects a different CLI than the canonical entry.")
    if old_environments:
        warnings.append(
            "Legacy source-hash environments remain; no files were removed."
        )
    try:
        dist = metadata.distribution("Local_Read")
        version = dist.version
        raw = dist.read_text("direct_url.json")
        origin = json.loads(raw) if raw else {"kind": "index_or_unknown"}
        if origin.get("dir_info", {}).get("editable"):
            warnings.append("This installation is editable and follows source changes.")
    except (metadata.PackageNotFoundError, ValueError):
        version, origin = None, {"kind": "unknown"}
    return {
        "success": True,
        "schema_version": "1.0",
        "version": version,
        "python": sys.executable,
        "package_directory": str(Path(__file__).resolve().parent),
        "environment": sys.prefix,
        "managed": managed,
        "canonical_cli": str(entry),
        "installation_root": str(installation_root()),
        "installation_source": origin,
        "path_candidates": candidates,
        "legacy_environments": old_environments,
        "model_directory": str(model_root()),
        "warnings": warnings,
        "scope": "Current process, canonical entry, PATH and default legacy cache; not a filesystem-wide scan or signature verification",
    }
