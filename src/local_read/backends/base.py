# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
Backend interface and registry for Local_Read.
"""

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any

# Default page size (letter size in points)
DEFAULT_PAGE_WIDTH = 612
DEFAULT_PAGE_HEIGHT = 792
DEFAULT_BBOX = [0, 0, DEFAULT_PAGE_WIDTH, DEFAULT_PAGE_HEIGHT]


class BackendType(Enum):
    """Supported backend types."""
    AUTO = "auto"
    SIMPLE = "simple"
    VLM_HYBRID = "vlm-hybrid"


class DocumentBackend(ABC):
    """Abstract base class for document processing backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this backend."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Get a description of this backend."""
        pass

    @property
    @abstractmethod
    def available(self) -> bool:
        """Check if this backend is available (models installed, API configured, etc.)."""
        pass

    @property
    def warning(self) -> str | None:
        """Get a warning message if backend is not available or has limitations."""
        return None

    def supports_format(self, format: str) -> bool:
        """Check if this backend supports the given format.

        Args:
            format: Format string to check

        Returns:
            True if the backend supports this format
        """
        return True

    @abstractmethod
    def process(
        self,
        file_path: Path,
        format: str,
        **kwargs
    ) -> dict[str, Any]:
        """Process a document file.

        Args:
            file_path: Path to the document file
            format: Format of the document
            **kwargs: Additional backend-specific parameters

        Returns:
            Intermediate JSON dictionary
        """
        pass


class BackendRegistry:
    """Registry for document backends."""

    def __init__(self):
        self._backends: dict[BackendType, type[DocumentBackend]] = {}
        self._instances: dict[BackendType, DocumentBackend] = {}

    def register(self, backend_type: BackendType, backend_class: type[DocumentBackend]):
        """Register a backend class."""
        self._backends[backend_type] = backend_class

    def get(self, backend_type: BackendType) -> DocumentBackend | None:
        """Get a backend instance, creating it if necessary."""
        if backend_type not in self._instances:
            if backend_type not in self._backends:
                return None
            self._instances[backend_type] = self._backends[backend_type]()
        return self._instances[backend_type]

    def list_available(self) -> list[dict[str, Any]]:
        """List all available backends."""
        result = []
        for backend_type in BackendType:
            backend = self.get(backend_type)
            if backend:
                result.append({
                    "type": backend_type.value,
                    "name": backend.name,
                    "description": backend.description,
                    "available": backend.available,
                    "warning": backend.warning
                })
        return result

    def select_best(self, format: str | None = None) -> DocumentBackend:
        """Select the best available backend.

        Args:
            format: If provided, only backends that support this format will be considered

        Returns:
            The best available backend
        """
        # Try in order: vlm-hybrid -> simple
        priority_order = [
            BackendType.VLM_HYBRID,
            BackendType.SIMPLE
        ]

        for backend_type in priority_order:
            backend = self.get(backend_type)
            if backend and backend.available:
                if format is None or backend.supports_format(format):
                    return backend

        # Fallback to simple backend (should always be available)
        simple_backend = self.get(BackendType.SIMPLE)
        if not simple_backend:
            raise RuntimeError("No backend available")
        return simple_backend


# Global registry instance
_registry: BackendRegistry | None = None


def get_registry() -> BackendRegistry:
    """Get the global backend registry."""
    global _registry
    if _registry is None:
        _registry = BackendRegistry()
    return _registry


def register_simple_backend():
    """Register SimpleBackend - called after SimpleBackend is defined."""
    registry = get_registry()
    from .simple import SimpleBackend
    registry.register(BackendType.SIMPLE, SimpleBackend)


def register_vlm_hybrid_backend():
    """Register VlmHybridBackend - called after VlmHybridBackend is defined."""
    registry = get_registry()
    try:
        from .mineru import VlmHybridBackend
        registry.register(BackendType.VLM_HYBRID, VlmHybridBackend)
    except ImportError:
        # MinerU optional dependency not installed
        pass
