"""Tests for Local_Read configuration loading."""

from pathlib import Path

from local_read.config import Config


def test_config_loads_dotenv_from_explicit_project_root(monkeypatch, tmp_path):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VISION_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("VISION_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_VISION_MODEL", raising=False)

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "# Local vision config",
                "VISION_API_KEY=from-dotenv",
                "VISION_BASE_URL='https://example.test/v1'",
                'VISION_MODEL="vision-model"',
            ]
        ),
        encoding="utf-8",
    )

    config = Config(dotenv_path=tmp_path)

    assert config.api_key == "from-dotenv"
    assert config.base_url == "https://example.test/v1"
    assert config.model == "vision-model"
    assert config.vision_enabled is True


def test_environment_overrides_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_API_KEY", "from-env")
    (tmp_path / ".env").write_text("VISION_API_KEY=from-dotenv\n", encoding="utf-8")

    config = Config(dotenv_path=tmp_path)

    assert config.api_key == "from-env"


def test_installed_runtime_uses_skill_config_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_READ_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("VISION_MODEL", raising=False)
    (tmp_path / ".env").write_text("VISION_MODEL=portable-test-model\n", encoding="utf-8")
    config = Config()
    assert config.dotenv_path == tmp_path / ".env"
    assert config.model == "portable-test-model"
