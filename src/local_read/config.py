# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
Configuration management for Local_Read.
"""

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Global config holder
_config = None


class Config:
    """Configuration management for Local_Read."""

    def __init__(self, dotenv_path: Optional[Path] = None):
        """
        Initialize configuration from .env file.

        Args:
            dotenv_path: Path to .env file (only used on first call or if reload=True)
        """
        self.dotenv_path = _resolve_dotenv_path(dotenv_path)
        _load_dotenv(self.dotenv_path)

        # Initialize settings
        self._init_settings()

    def _init_settings(self):
        """Initialize settings from environment variables."""
        # Vision API settings (for OpenAI-compatible APIs like Doubao)
        # Uses simple naming as requested: api_key, base_url, model
        self.api_key = os.environ.get("VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base_url = os.environ.get("VISION_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        self.model = os.environ.get("VISION_MODEL") or os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")

        # Vision settings
        self.vision_max_image_size_mb = int(os.environ.get("VISION_MAX_IMAGE_SIZE_MB", "20"))

        # Logging
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Determine if vision features are enabled
        self._vision_enabled = self._check_vision_enabled()

    def _check_vision_enabled(self) -> bool:
        """
        Check if vision features are enabled based on configuration.

        Vision is enabled if API_KEY is set.
        """
        return bool(self.api_key)

    @property
    def vision_enabled(self) -> bool:
        """Get whether vision features are enabled."""
        return self._vision_enabled

    def __repr__(self):
        """String representation of config (hide sensitive data)."""
        return (
            f"Config(\n"
            f"  dotenv_path={self.dotenv_path},\n"
            f"  api_key={'***' if self.api_key else 'Not Set'},\n"
            f"  base_url={self.base_url},\n"
            f"  model={self.model},\n"
            f"  vision_enabled={self.vision_enabled},\n"
            f")"
        )


def get_config(dotenv_path: Optional[Path] = None, reload: bool = False) -> Config:
    """
    Get global configuration instance.

    Args:
        dotenv_path: Path to .env file (only used on first call or if reload=True)
        reload: Force reload configuration from .env file

    Returns:
        Config instance
    """
    global _config
    if _config is None or reload:
        _config = Config(dotenv_path=dotenv_path)
    return _config


def _project_root() -> Path:
    """Return the repository root for the installed package."""
    if os.environ.get("LOCAL_READ_CONFIG_DIR"):
        return Path(os.environ["LOCAL_READ_CONFIG_DIR"]).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[2]


def _resolve_dotenv_path(dotenv_path: Optional[Path]) -> Path:
    if dotenv_path is None:
        return _project_root() / ".env"

    path = Path(dotenv_path)
    if path.is_dir():
        return path / ".env"
    return path


def _load_dotenv(dotenv_path: Path) -> None:
    """Load simple KEY=value pairs without overriding existing environment."""
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        os.environ[key] = _parse_dotenv_value(value)


def _parse_dotenv_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
