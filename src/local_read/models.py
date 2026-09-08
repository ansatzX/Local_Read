"""Prepare and inspect MinerU models using its own downloader and model catalog."""

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from .config import _project_root
from .local_runtime import cache_environment, file_lock, model_root

SUPPORTED_MINERU = "3.4.5"
PIPELINE_COMPONENTS = (
    "pp_doclayout_v2",
    "unimernet_small",
    "pytorch_paddle",
    "slanet_plus",
    "unet_structure",
    "paddle_table_cls",
    "pp_formulanet_plus_m",
)
WEIGHT_SUFFIXES = {".safetensors", ".bin", ".pth", ".pt", ".onnx"}


def managed_config_path() -> Path:
    return model_root() / "mineru.json"


def config_path() -> Path:
    explicit = os.environ.get("MINERU_TOOLS_CONFIG_JSON")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if managed_config_path().is_file():
        return managed_config_path()
    legacy = Path.cwd() / ".local_read_mcp/models/mineru.json"
    if legacy.is_file():
        return legacy
    return _project_root() / "mineru.json"


def _read_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("MinerU configuration must be a JSON object")
    return result


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _package_versions() -> dict[str, str | None]:
    versions = {}
    for package in ("mineru", "torch", "torchvision", "transformers", "accelerate"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def _model_paths(config: dict, origin: Path) -> dict[str, Path]:
    paths = {}
    configured = config.get("models-dir", {})
    if not isinstance(configured, dict):
        raise ValueError("MinerU models-dir must be an object")
    for kind in ("pipeline", "vlm"):
        value = configured.get(kind)
        if isinstance(value, str) and value:
            path = Path(value).expanduser()
            paths[kind] = (
                path if path.is_absolute() else origin.parent / path
            ).resolve()
    return paths


def _has_weights(path: Path) -> bool:
    candidates = [path] if path.is_file() else path.rglob("*") if path.is_dir() else []
    return any(
        p.is_file() and p.suffix in WEIGHT_SUFFIXES and p.stat().st_size > 0
        for p in candidates
    )


def model_status(path: Path | None = None, check_inventory: bool = True) -> dict:
    origin = path or config_path()
    if origin == managed_config_path() and origin.parent.exists():
        with file_lock(model_root() / ".prepare.lock"):
            return _model_status(origin, check_inventory)
    return _model_status(origin, check_inventory)


def _model_status(path: Path | None = None, check_inventory: bool = True) -> dict:
    """Check packages and local files, without importing models or contacting hubs."""
    origin = path or config_path()
    versions = _package_versions()
    missing = [f"package:{name}" for name, version in versions.items() if not version]
    if versions["mineru"] and versions["mineru"] != SUPPORTED_MINERU:
        missing.append(
            f"unsupported MinerU {versions['mineru']}; expected {SUPPORTED_MINERU}"
        )
    paths = {}
    try:
        config = _read_config(origin)
        paths = _model_paths(config, origin)
        if versions["mineru"] == SUPPORTED_MINERU:
            from mineru.utils.enum_class import ModelPath

            for name in PIPELINE_COMPONENTS:
                relative = getattr(ModelPath, name)
                if "pipeline" not in paths or not _has_weights(
                    paths["pipeline"] / relative
                ):
                    missing.append(f"pipeline:{relative}")
        else:
            missing.append("pipeline model catalog unavailable")
        vlm = paths.get("vlm")
        if vlm is None or not (vlm / "config.json").is_file() or not _has_weights(vlm):
            missing.append("vlm:config.json and model weights")
        if vlm and not any(
            (vlm / name).is_file()
            for name in ("tokenizer.json", "tokenizer.model", "vocab.json")
        ):
            missing.append("vlm:tokenizer")
        if vlm and (vlm / "model.safetensors.index.json").is_file():
            shards = json.loads((vlm / "model.safetensors.index.json").read_text())[
                "weight_map"
            ]
            for shard in sorted(set(shards.values())):
                if not (vlm / shard).is_file() or (vlm / shard).stat().st_size == 0:
                    missing.append(f"vlm:shard:{shard}")
        manifest_path = origin.with_name("model_manifest.json")
        if check_inventory and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            for kind, files in manifest.get("inventory", {}).items():
                if kind not in paths:
                    continue
                for relative, size in files.items():
                    file = paths[kind] / relative
                    if not file.is_file() or file.stat().st_size != size:
                        missing.append(f"{kind}:changed-or-missing:{relative}")
    except (OSError, ValueError, KeyError, ImportError, AttributeError) as exc:
        missing.append(f"configuration: {exc}")
    return {
        "success": not missing,
        "models_ready": not missing,
        "readiness": "files_present" if not missing else "not_ready",
        "inference_verified": False,
        "config_path": str(origin),
        "packages": versions,
        "model_paths": {key: str(value) for key, value in paths.items()},
        "missing": missing,
        "offline": True,
    }


def local_inference_config() -> Path:
    """Materialize local-only config; never overwrite the user's configuration."""
    origin = config_path()
    if origin == managed_config_path():
        with file_lock(model_root() / ".prepare.lock"):
            config = _read_config(origin)
    else:
        config = _read_config(origin)
    config["models-dir"] = {
        kind: str(path) for kind, path in _model_paths(config, origin).items()
    }
    config["model-source"] = "local"
    # Disable any upstream LLM API postprocessing configured in a reused file.
    config["llm-aided-config"] = {}
    destination = Path.cwd() / ".local_read_mcp/models" / f"inference-{uuid4().hex}.json"
    _atomic_json(destination, config)
    return destination


def prepare_models(source: str = "huggingface") -> dict:
    """Serialize download, validation and publication across all projects."""
    with file_lock(model_root() / ".prepare.lock", timeout=3600):
        return _prepare_models(source)


def _prepare_models(source: str) -> dict:
    """Explicit online operation; delegate downloads/cache reuse to MinerU."""
    versions = _package_versions()
    if versions.get("mineru") != SUPPORTED_MINERU or any(
        not value for value in versions.values()
    ):
        return {
            "success": False,
            "error": "Run Local_Read setup to install the pinned inference dependencies before preparing models.",
            "packages": versions,
        }
    if source not in {"huggingface", "modelscope", "auto"}:
        raise ValueError("Unsupported model source")
    destination = managed_config_path()
    config = _read_config(destination)
    config.setdefault("config_version", "1.3.2")
    config["llm-aided-config"] = {}
    staging = destination.with_name(f".prepare-{uuid4().hex}.json")
    _atomic_json(staging, config)
    try:
        return _download_models(source, destination, staging)
    finally:
        staging.unlink(missing_ok=True)


def _download_models(source: str, destination: Path, staging: Path) -> dict:
    env = (
        os.environ.copy()
        | cache_environment()
        | {
            "MINERU_TOOLS_CONFIG_JSON": str(staging),
            "MINERU_MODEL_SOURCE": source,
            "HF_HUB_OFFLINE": "0",
            "TRANSFORMERS_OFFLINE": "0",
        }
    )
    command = [
        sys.executable,
        "-m",
        "mineru.cli.models_download",
        "--source",
        source,
        "--model_type",
        "all",
    ]
    completed = subprocess.run(
        command, env=env, stdout=sys.stderr, stderr=sys.stderr, check=False
    )
    if completed.returncode:
        return {
            "success": False,
            "error": "MinerU model preparation failed; cached downloads are retained for retry.",
            "config_path": str(destination),
        }
    # Discard an old inventory before checking a successful updated download.
    manifest_path = destination.with_name("model_manifest.json")
    status = _model_status(staging, check_inventory=False)
    if not status["models_ready"]:
        return dict(
            status,
            config_path=str(destination),
            error="Downloaded model files are incomplete; inspect missing entries.",
        )
    inventory = {}
    for kind, directory in status["model_paths"].items():
        root = Path(directory)
        inventory[kind] = {
            p.relative_to(root).as_posix(): p.stat().st_size
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }
    _atomic_json(destination, _read_config(staging))
    status["config_path"] = str(destination)
    _atomic_json(
        manifest_path,
        {
            "mineru_version": SUPPORTED_MINERU,
            "source": source,
            "model_paths": status["model_paths"],
            "inventory": inventory,
        },
    )
    if os.environ.get("MINERU_TOOLS_CONFIG_JSON"):
        status["warnings"] = [
            "Models prepared in the managed config; MINERU_TOOLS_CONFIG_JSON still selects your explicit config for conversion."
        ]
    return dict(status, manifest_path=str(manifest_path))
