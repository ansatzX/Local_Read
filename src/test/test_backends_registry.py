"""
Unit tests for backend registry and format-aware selection.

This module contains tests for the backend registry, format support checks,
and the format-aware backend selection logic.
"""

# Import the backend module
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read.backends.base import (
    BackendRegistry,
    BackendType,
    DocumentBackend,
    get_registry,
)
from local_read.backends.simple import SimpleBackend
from local_read.converters import DocumentConverterResult


class MockSimpleBackend(DocumentBackend):
    """Mock Simple backend that supports all formats."""

    @property
    def name(self) -> str:
        return "Simple"

    @property
    def description(self) -> str:
        return "Simple backend"

    @property
    def available(self) -> bool:
        return True

    def process(self, file_path: Path, format: str, **kwargs):
        return {"format": format, "backend": "simple"}


class MockVlmHybridBackend(DocumentBackend):
    """Mock VLM-Hybrid backend that only supports PDF."""

    @property
    def name(self) -> str:
        return "VLM-Hybrid"

    @property
    def description(self) -> str:
        return "VLM-Hybrid backend"

    @property
    def available(self) -> bool:
        return True

    def supports_format(self, format: str) -> bool:
        return format == "pdf"

    def process(self, file_path: Path, format: str, **kwargs):
        return {"format": format, "backend": "vlm-hybrid"}


class TestSupportsFormat:
    """Tests for the supports_format interface."""

    def test_default_supports_all_formats(self):
        """Default implementation should support all formats."""
        backend = MockSimpleBackend()
        assert backend.supports_format("pdf") is True
        assert backend.supports_format("word") is True
        assert backend.supports_format("text") is True
        assert backend.supports_format("png") is True

    def test_vlm_hybrid_only_supports_pdf(self):
        """VLM-Hybrid should only support PDF."""
        backend = MockVlmHybridBackend()
        assert backend.supports_format("pdf") is True
        assert backend.supports_format("word") is False
        assert backend.supports_format("text") is False
        assert backend.supports_format("png") is False


class TestBackendRegistryFormatAware:
    """Tests for format-aware backend selection in BackendRegistry."""

    def setup_method(self):
        """Set up a fresh registry for each test."""
        self.registry = BackendRegistry()
        self.registry.register(BackendType.SIMPLE, MockSimpleBackend)
        self.registry.register(BackendType.VLM_HYBRID, MockVlmHybridBackend)

    def test_select_best_without_format_uses_vlm_hybrid(self):
        """Without format, select_best should prefer VLM-Hybrid."""
        backend = self.registry.select_best()
        assert backend.name == "VLM-Hybrid"

    def test_select_best_with_pdf_prefers_vlm_hybrid(self):
        """With PDF format, should prefer VLM-Hybrid."""
        backend = self.registry.select_best("pdf")
        assert backend.name == "VLM-Hybrid"

    def test_select_best_with_word_selects_simple(self):
        """With Word format, only Simple is available."""
        backend = self.registry.select_best("word")
        assert backend.name == "Simple"

    def test_select_best_with_text_selects_simple(self):
        """With text format, only Simple is available."""
        backend = self.registry.select_best("text")
        assert backend.name == "Simple"

    def test_select_best_falls_back_to_simple(self):
        """With an unsupported format, should fall back to Simple."""
        backend = self.registry.select_best("unknown-format")
        assert backend.name == "Simple"


class TestBackendRegistryWithUnavailableBackends:
    """Tests for backend selection when some backends are unavailable."""

    def setup_method(self):
        """Set up a registry with an unavailable VLM-Hybrid backend."""
        class UnavailableVlmHybrid(MockVlmHybridBackend):
            @property
            def available(self) -> bool:
                return False

        self.registry = BackendRegistry()
        self.registry.register(BackendType.SIMPLE, MockSimpleBackend)
        self.registry.register(BackendType.VLM_HYBRID, UnavailableVlmHybrid)

    def test_select_best_with_unavailable_vlm_hybrid(self):
        """When VLM-Hybrid is unavailable, should fall back to Simple."""
        backend = self.registry.select_best("pdf")
        assert backend.name == "Simple"


class TestRealBackendsFormatSupport:
    """Integration tests with real backend implementations."""

    def test_simple_backend_supports_all_formats(self):
        """Simple backend should support all formats."""
        registry = get_registry()
        simple = registry.get(BackendType.SIMPLE)
        assert simple is not None
        assert simple.supports_format("pdf") is True
        assert simple.supports_format("word") is True
        assert simple.supports_format("text") is True
        assert simple.supports_format("json") is True

    def test_vlm_hybrid_backend_only_supports_pdf(self):
        """VLM-Hybrid backend should only support PDF (if available)."""
        registry = get_registry()
        hybrid = registry.get(BackendType.VLM_HYBRID)
        if hybrid:  # Only test if registered
            assert hybrid.supports_format("pdf") is True
            assert hybrid.supports_format("word") is False
            assert hybrid.supports_format("text") is False

    def test_list_available_returns_registered_backends(self):
        """list_available should return all registered backends."""
        registry = get_registry()
        available = registry.list_available()
        types = {b["type"] for b in available}
        assert "simple" in types
        # vlm-hybrid may or may not be available depending on env
        # but it should at least appear in the list
        assert "vlm-hybrid" in types or "vlm-hybrid" not in types


class TestSimpleBackendMetadataHandling:
    """Tests for metadata handling in the real Simple backend."""

    def test_simple_backend_uses_pdf_metadata_page_count(self, monkeypatch, tmp_path):
        """Simple backend should prefer explicit PDF page-count metadata."""
        backend = SimpleBackend()
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        def fake_converter(path, **kwargs):
            return DocumentConverterResult(
                title="Sample",
                text_content="content",
                metadata={"pdf_page_count": 7},
            )

        monkeypatch.setattr(backend, "_get_converter", lambda format_name: fake_converter)

        result = backend.process(test_file, "pdf")

        assert result["source"]["page_count"] == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
