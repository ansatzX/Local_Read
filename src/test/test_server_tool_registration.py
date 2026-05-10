"""Tests for MCP tool registration and public parameters."""

import importlib

import pytest


async def _tool_names(app_module) -> list[str]:
    tools = await app_module.mcp.get_tools()
    return list(tools.keys())


async def _analyze_image_param_names(app_module) -> list[str]:
    tools = await app_module.mcp.get_tools()
    props = tools["analyze_image"].parameters.get("properties", {})
    return list(props.keys())


@pytest.mark.asyncio
async def test_toolset_hides_vision_status_tool():
    from local_read_mcp.server import app as app_module

    names = await _tool_names(app_module)
    assert "get_vision_status" not in names


@pytest.mark.asyncio
async def test_analyze_image_does_not_expose_api_key_parameter(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "dummy-key")

    import local_read_mcp.config as config_module
    from local_read_mcp.server import app as app_module

    config_module._config = None
    reloaded = importlib.reload(app_module)
    param_names = await _analyze_image_param_names(reloaded)
    assert "api_key" not in param_names


@pytest.mark.asyncio
async def test_analyze_image_not_registered_without_vision_credentials(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    import local_read_mcp.config as config_module
    from local_read_mcp.server import app as app_module

    config_module._config = None
    reloaded = importlib.reload(app_module)
    names = await _tool_names(reloaded)

    assert "process_binary_file" in names
    assert "analyze_image" not in names
    assert "analyze_images_batch" not in names


@pytest.mark.asyncio
async def test_analyze_images_batch_registered_with_vision_credentials(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "dummy-key")

    import local_read_mcp.config as config_module
    from local_read_mcp.server import app as app_module

    config_module._config = None
    reloaded = importlib.reload(app_module)
    names = await _tool_names(reloaded)

    assert "analyze_image" in names
    assert "analyze_images_batch" in names
