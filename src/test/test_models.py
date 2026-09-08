"""Local model preparation/readiness and offline execution boundaries."""

import json
import os
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from local_read import models
from local_read.local_runtime import cache_environment, offline_execution


@pytest.fixture
def cached_models(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", str(tmp_path / "shared-models"))
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.setattr(
        models,
        "_package_versions",
        lambda: {
            "mineru": models.SUPPORTED_MINERU,
            "torch": "test",
            "torchvision": "test",
            "transformers": "test",
            "accelerate": "test",
        },
    )
    catalog = ModuleType("mineru.utils.enum_class")
    catalog.ModelPath = SimpleNamespace(
        **{name: f"models/{name}" for name in models.PIPELINE_COMPONENTS}
    )
    monkeypatch.setitem(sys.modules, "mineru.utils.enum_class", catalog)
    pipeline = tmp_path / "existing-models/pipeline"
    vlm = tmp_path / "existing-models/vlm"
    for name in models.PIPELINE_COMPONENTS:
        directory = pipeline / getattr(catalog.ModelPath, name)
        directory.mkdir(parents=True)
        (directory / "weights.bin").write_bytes(b"fake-local-weight")
    vlm.mkdir(parents=True)
    (vlm / "config.json").write_text("{}")
    (vlm / "tokenizer.json").write_text("{}")
    (vlm / "model.safetensors").write_bytes(b"fake-local-vlm")
    config = models.managed_config_path()
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "models-dir": {"pipeline": str(pipeline), "vlm": str(vlm)},
                "llm-aided-config": {
                    "title_aided": {"enable": True, "api_key": "test-secret"}
                },
            }
        )
    )
    return config, pipeline, vlm


def test_readiness_does_not_claim_inference(cached_models):
    with offline_execution():
        status = models.model_status()
    assert status["models_ready"]
    assert status["readiness"] == "files_present"
    assert status["inference_verified"] is False


def test_empty_directory_not_a_model(cached_models):
    _, pipeline, _ = cached_models
    next(pipeline.rglob("weights.bin")).unlink()
    assert not models.model_status()["models_ready"]


def test_missing_vlm_shard_reported(cached_models):
    _, _, vlm = cached_models
    (vlm / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"layer": "missing.safetensors"}})
    )
    status = models.model_status()
    assert not status["models_ready"]
    assert "vlm:shard:missing.safetensors" in status["missing"]


def test_local_config_disables_api_without_mutating_source(cached_models):
    source, _, _ = cached_models
    before = source.read_bytes()
    generated = models.local_inference_config()
    config = json.loads(generated.read_text())
    assert config["model-source"] == "local"
    assert config["llm-aided-config"] == {}
    assert "test-secret" not in generated.read_text()
    assert source.read_bytes() == before
    assert generated.is_relative_to(Path.cwd() / ".local_read_mcp")


def test_prepare_delegates_and_tracks_files(monkeypatch, cached_models):
    config, _, vlm = cached_models
    called = []

    def downloader(command, **kwargs):
        called.append(command)
        assert command[2] == "mineru.cli.models_download"
        assert command[-2:] == ["--model_type", "all"]
        assert Path(kwargs["env"]["MINERU_TOOLS_CONFIG_JSON"]).parent == config.parent
        assert Path(kwargs["env"]["MINERU_TOOLS_CONFIG_JSON"]) != config
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "0"
        assert Path(kwargs["env"]["HF_HOME"]).is_relative_to(
            models.model_root()
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(models.subprocess, "run", downloader)
    status = models.prepare_models("huggingface")
    assert status["models_ready"]
    assert len(called) == 1
    assert Path(status["manifest_path"]).is_file()
    (vlm / "model.safetensors").write_bytes(b"truncated")
    assert not models.model_status()["models_ready"]


def test_download_failure_retains_cache(monkeypatch, cached_models):
    config, _, vlm = cached_models
    before = config.read_bytes()
    def failing_download(*args, **kwargs):
        staging = Path(kwargs["env"]["MINERU_TOOLS_CONFIG_JSON"])
        staging.write_text('{"broken": true}')
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(
        models.subprocess, "run", failing_download
    )
    result = models.prepare_models()
    assert not result["success"]
    assert "retained" in result["error"]
    assert (vlm / "model.safetensors").exists()
    assert config.read_bytes() == before
    assert not list(config.parent.glob(".prepare-*.json"))


def test_preparation_holds_lock_through_inventory(monkeypatch, cached_models):
    from local_read.local_runtime import file_lock

    def downloader(*args, **kwargs):
        with pytest.raises(TimeoutError):
            with file_lock(models.model_root() / ".prepare.lock", timeout=0):
                pass
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(models.subprocess, "run", downloader)
    atomic = models._atomic_json
    def publish(path, value):
        if path.name == "model_manifest.json":
            with pytest.raises(TimeoutError):
                with file_lock(models.model_root() / ".prepare.lock", timeout=0):
                    pass
        atomic(path, value)
    monkeypatch.setattr(models, "_atomic_json", publish)
    assert models.prepare_models()["models_ready"]


def test_offline_blocks_connections_and_restores_environment(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    original_connect = socket.socket.connect
    with offline_execution():
        assert os.environ["MINERU_MODEL_SOURCE"] == "local"
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        with pytest.raises(RuntimeError, match="DNS"):
            socket.getaddrinfo("huggingface.co", 443)
        with socket.socket() as sock:
            with pytest.raises(RuntimeError, match="outbound"):
                sock.connect(("1.1.1.1", 443))
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert socket.socket.connect is original_connect


def test_missing_package_status_is_actionable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", str(tmp_path / "shared-models"))
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.setattr(
        models, "_package_versions", lambda: {"mineru": None, "torch": None}
    )
    result = models.model_status()
    assert not result["models_ready"]
    assert "package:mineru" in result["missing"]


def test_models_reused_across_workspaces(monkeypatch, cached_models, tmp_path):
    config, pipeline, vlm = cached_models
    first_environment = cache_environment()
    first_inference = models.local_inference_config()
    second_project = tmp_path / "second-project"
    second_project.mkdir()
    monkeypatch.chdir(second_project)
    assert cache_environment() == first_environment
    assert models.config_path() == config
    assert models.model_status()["models_ready"]
    second_inference = models.local_inference_config()
    assert second_inference != first_inference
    assert second_inference.is_relative_to(second_project)
    assert json.loads(second_inference.read_text())["models-dir"] == {
        "pipeline": str(pipeline), "vlm": str(vlm)
    }


def test_default_model_store_is_user_global(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCAL_READ_MODEL_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "user")
    expected = tmp_path / "user/.cache/local-read/models"
    assert models.model_root() == expected
    with offline_execution():
        # Setting XDG_CACHE_HOME inside offline mode must not nest the root.
        assert models.model_root() == expected
        assert cache_environment()["HF_HOME"] == str(expected / "huggingface")
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", "relative/models")
    with pytest.raises(ValueError, match="absolute"):
        models.model_root()


def test_legacy_and_explicit_config_selection(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", str(tmp_path / "shared"))
    legacy = tmp_path / ".local_read_mcp/models/mineru.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    assert models.config_path() == legacy
    shared = models.managed_config_path()
    shared.parent.mkdir(parents=True)
    shared.write_text("{}")
    assert models.config_path() == shared
    monkeypatch.setenv("MINERU_TOOLS_CONFIG_JSON", str(legacy))
    assert models.config_path() == legacy


def test_launcher_uses_same_shared_cache(monkeypatch, tmp_path):
    import runpy

    launcher = Path(__file__).resolve().parents[2] / "scripts/local_read.py"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", str(tmp_path / "shared"))
    monkeypatch.setattr(sys, "argv", [str(launcher), "setup"])
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: "/fake/uv")
    captured = {}
    import subprocess

    monkeypatch.setenv("LOCAL_READ_RUNTIME_DIR", str(tmp_path / "runtimes"))
    monkeypatch.setattr(subprocess, "call", lambda args, env: captured.update(env) or 0)
    runpy.run_path(str(launcher))["main"]()
    for key, value in cache_environment().items():
        assert captured[key] == value
    assert Path(captured["UV_PROJECT_ENVIRONMENT"]).parent == tmp_path / "runtimes"
