"""
Unit tests for MCP server tools.

This module contains tests for the FastMCP server implementation.
"""

import sys
import asyncio
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read_mcp.server import app as server_app


class TestProcessBinaryFileExtractImagesDefault:
    """Tests for extract_images default behavior in process_binary_file."""

    @pytest.mark.asyncio
    async def test_auto_enable_extract_images_when_vision_enabled(self, monkeypatch, tmp_path):
        """When not specified and vision is enabled, processing should extract images for PDFs."""
        called = {}
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Fake"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                called.update(kwargs)
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(server_app, "VISION_ENABLED", True)

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
        )

        assert result["success"] is True
        assert called["extract_images"] is True

    @pytest.mark.asyncio
    async def test_default_extract_images_false_when_vision_disabled(self, monkeypatch, tmp_path):
        """When vision is disabled and not specified, processing should not extract images."""
        called = {}
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Fake"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                called.update(kwargs)
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(server_app, "VISION_ENABLED", False)

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
        )

        assert result["success"] is True
        assert called["extract_images"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])



class TestProcessBinaryFileFallback:
    """Tests for VLM-to-Simple fallback in process_binary_file."""

    @pytest.mark.asyncio
    async def test_process_binary_file_falls_back_to_simple_when_vlm_process_fails(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.backends.base import BackendType

        test_file = tmp_path / 'sample.pdf'
        test_file.write_text('fake pdf', encoding='utf-8')

        class FailingVlm:
            name = 'VLM-Hybrid'
            warning = None
            def supports_format(self, format_name): return format_name == 'pdf'
            def process(self, file_path, format_name, **kwargs):
                raise RuntimeError('mineru failed')

        class PassingSimple:
            name = 'Simple'
            warning = None
            def supports_format(self, format_name): return True
            def process(self, file_path, format_name, **kwargs):
                return {
                    'source': {'path': str(file_path), 'format': format_name, 'page_count': 1},
                    'metadata': {},
                    'blocks': {'block_00000000': {'type': 'text', 'page': 1, 'bbox': [0, 0, 1, 1], 'content': 'ok'}},
                    'reading_order': ['block_00000000'],
                }

        class FakeRegistry:
            def select_best(self, format_name=None): return FailingVlm()
            def get(self, backend_type):
                if backend_type == BackendType.SIMPLE:
                    return PassingSimple()
                return FailingVlm()

        monkeypatch.setattr(server_app, 'get_registry', lambda: FakeRegistry())

        result = await server_app.process_binary_file.fn(file_path=str(test_file), format='pdf')

        assert result['success'] is True
        assert result['backend_used'] == 'Simple'
        assert any('VLM-Hybrid' in warning and 'mineru failed' in warning for warning in result['warnings'])



class TestProcessBinaryFileChunkPlanning:
    """Tests for chunk parameter semantics."""

    def test_plan_chunks_uses_page_batch_size_for_fixed_auto(self, monkeypatch):
        from local_read_mcp.server import orchestrator
        from types import SimpleNamespace

        class FakeDoc:
            page_count = 50
            def get_toc(self): return []
            def __getitem__(self, index):
                class Page:
                    def get_text(self): return ''
                    def get_label(self): return ''
                return Page()
            def close(self): pass

        monkeypatch.setitem(__import__('sys').modules, 'fitz', SimpleNamespace(open=lambda path: FakeDoc()))

        chunks = orchestrator.plan_chunks(
            file_path='sample.pdf',
            format='pdf',
            backend_name='Simple',
            chapter_split='auto',
            start_page=None,
            end_page=None,
            page_batch_size=7,
        )

        assert [c.phys_end - c.phys_start + 1 for c in chunks[:2]] == [7, 7]

    def test_plan_chunks_true_is_not_treated_as_one_page_chunks(self, monkeypatch):
        from local_read_mcp.server import orchestrator
        from types import SimpleNamespace

        class FakeDoc:
            page_count = 50
            def get_toc(self): return []
            def __getitem__(self, index):
                class Page:
                    def get_text(self): return ''
                    def get_label(self): return ''
                return Page()
            def close(self): pass

        monkeypatch.setitem(__import__('sys').modules, 'fitz', SimpleNamespace(open=lambda path: FakeDoc()))

        chunks = orchestrator.plan_chunks(
            file_path='sample.pdf',
            format='pdf',
            backend_name='Simple',
            chapter_split=True,
            start_page=None,
            end_page=None,
            page_batch_size=10,
        )

        assert all((c.phys_end - c.phys_start + 1) > 1 for c in chunks)

    def test_plan_chunks_page_batch_size_defaults_to_64(self, monkeypatch):
        from local_read_mcp.server import orchestrator
        from types import SimpleNamespace

        class FakeDoc:
            page_count = 50
            def get_toc(self): return []
            def __getitem__(self, index):
                class Page:
                    def get_text(self): return ''
                    def get_label(self): return ''
                return Page()
            def close(self): pass

        monkeypatch.setitem(__import__('sys').modules, 'fitz', SimpleNamespace(open=lambda path: FakeDoc()))

        # chapter_split='auto' on 50 pages -> splits (50>30), no TOC, uses page_batch_size=64 (1 chunk)
        chunks = orchestrator.plan_chunks(
            file_path='sample.pdf',
            format='pdf',
            backend_name='Simple',
            chapter_split='auto',
            start_page=None,
            end_page=None,
            page_batch_size=64,
        )

        assert len(chunks) == 1
        assert chunks[0].phys_end - chunks[0].phys_start + 1 == 50

    def test_plan_chunks_low_confidence_falls_back_when_enabled(self, monkeypatch):
        from local_read_mcp.server import orchestrator
        from local_read_mcp.segmenter import Chapter
        from local_read_mcp.segmenter.toc_extractor import TocDiagnostics
        from types import SimpleNamespace

        class FakeDoc:
            page_count = 50
            def close(self):
                pass

        class FakeExtractor:
            def extract(self, doc, with_diagnostics=False):
                chapters = [
                    Chapter(1, "Ch 1", 1, 0),
                    Chapter(1, "Ch 2", 20, 19),
                ]
                diagnostics = TocDiagnostics(
                    mode="heuristic",
                    confidence=0.2,
                    offset=0,
                    evidence_pages=[1],
                )
                if with_diagnostics:
                    return chapters, diagnostics
                return chapters

        monkeypatch.setitem(__import__('sys').modules, 'fitz', SimpleNamespace(open=lambda path: FakeDoc()))
        monkeypatch.setattr(orchestrator, "TocExtractor", FakeExtractor)

        chunks, diagnostics = orchestrator.plan_chunks(
            file_path='sample.pdf',
            format='pdf',
            backend_name='Simple',
            chapter_split=True,
            start_page=None,
            end_page=None,
            page_batch_size=10,
            enable_toc_auto_fallback=True,
            toc_confidence_threshold=0.55,
            return_diagnostics=True,
        )

        assert len(chunks) == 5
        assert diagnostics["mode"] == "heuristic"
        assert diagnostics["confidence"] == 0.2
        assert diagnostics["fallback_applied"] is True
        assert "below threshold" in diagnostics["fallback_reason"]

    def test_plan_chunks_low_confidence_does_not_fallback_by_default(self, monkeypatch):
        from local_read_mcp.server import orchestrator
        from local_read_mcp.segmenter import Chapter
        from local_read_mcp.segmenter.toc_extractor import TocDiagnostics
        from types import SimpleNamespace

        class FakeDoc:
            page_count = 50
            def close(self):
                pass

        class FakeExtractor:
            def extract(self, doc, with_diagnostics=False):
                chapters = [
                    Chapter(1, "Ch 1", 1, 0),
                    Chapter(1, "Ch 2", 20, 19),
                ]
                diagnostics = TocDiagnostics(
                    mode="heuristic",
                    confidence=0.2,
                    offset=0,
                    evidence_pages=[1],
                )
                if with_diagnostics:
                    return chapters, diagnostics
                return chapters

        monkeypatch.setitem(__import__('sys').modules, 'fitz', SimpleNamespace(open=lambda path: FakeDoc()))
        monkeypatch.setattr(orchestrator, "TocExtractor", FakeExtractor)

        chunks, diagnostics = orchestrator.plan_chunks(
            file_path='sample.pdf',
            format='pdf',
            backend_name='Simple',
            chapter_split=True,
            start_page=None,
            end_page=None,
            page_batch_size=10,
            return_diagnostics=True,
        )

        assert len(chunks) == 2
        assert diagnostics["mode"] == "heuristic"
        assert diagnostics["confidence"] == 0.2
        assert "fallback_applied" not in diagnostics



class TestProcessBinaryFileMultiChunk:
    """Tests for multi-chunk processing output shape."""

    @pytest.mark.asyncio
    async def test_multi_chunk_writes_top_level_artifacts(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / 'sample.pdf'
        test_file.write_text('fake pdf', encoding='utf-8')

        monkeypatch.chdir(tmp_path)

        class FakeBackend:
            name = 'Simple'
            warning = None
            def supports_format(self, format_name): return True
            def process(self, file_path, format_name, **kwargs):
                return {
                    'source': {'path': str(file_path), 'format': format_name, 'page_count': 1},
                    'metadata': {},
                    'blocks': {'block_00000000': {'type': 'text', 'page': 0, 'bbox': [0, 0, 1, 1], 'content': 'ok'}},
                    'reading_order': ['block_00000000'],
                }

        class FakeRegistry:
            def select_best(self, format_name=None): return FakeBackend()
            def get(self, backend_type): return FakeBackend()

        monkeypatch.setattr(server_app, 'get_registry', lambda: FakeRegistry())
        monkeypatch.setattr(server_app, 'plan_chunks', lambda **kwargs: [
            Chunk(phys_start=0, phys_end=0, title='a'),
            Chunk(phys_start=1, phys_end=1, title='b'),
        ])

        result = await server_app.process_binary_file.fn(file_path=str(test_file), format='pdf')

        assert result['success'] is True
        assert Path(result['files']['intermediate_json']).exists()
        assert Path(result['files']['markdown']).exists()
        assert Path(result['files']['index_json']).exists()
        assert Path(result['files']['structural_toc']).exists()

    @pytest.mark.asyncio
    async def test_multi_chunk_returns_image_metadata_and_uses_per_chunk_image_dirs(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / 'sample.pdf'
        test_file.write_text('fake pdf', encoding='utf-8')

        monkeypatch.chdir(tmp_path)

        seen_image_dirs = []

        class FakeBackend:
            name = 'Simple'
            warning = None
            def supports_format(self, format_name): return True
            def process(self, file_path, format_name, **kwargs):
                image_dir = Path(kwargs["images_output_dir"])
                image_dir.mkdir(parents=True, exist_ok=True)
                # Same filename in every chunk to catch overwrite bugs.
                (image_dir / "page000_img00.png").write_bytes(b"fake-image")
                seen_image_dirs.append(str(image_dir))
                return {
                    'source': {'path': str(file_path), 'format': format_name, 'page_count': 1},
                    'metadata': {},
                    'blocks': {'block_00000000': {'type': 'text', 'page': 0, 'bbox': [0, 0, 1, 1], 'content': 'ok'}},
                    'reading_order': ['block_00000000'],
                }

        class FakeRegistry:
            def select_best(self, format_name=None): return FakeBackend()
            def get(self, backend_type): return FakeBackend()

        monkeypatch.setattr(server_app, 'get_registry', lambda: FakeRegistry())
        monkeypatch.setattr(server_app, 'plan_chunks', lambda **kwargs: [
            Chunk(phys_start=0, phys_end=0, title='a'),
            Chunk(phys_start=1, phys_end=1, title='b'),
        ])

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format='pdf',
            extract_images=True,
        )

        assert result['success'] is True
        assert result['chunk_count'] == 2
        assert result['image_count'] == 2
        assert len(result['image_metadata']) == 2
        assert len(set(seen_image_dirs)) == 2
        assert all("chunk_" in d for d in seen_image_dirs)
        # Aggregated links should be in top-level images dir, not copied.
        aggregated_images_dir = Path(result['files']['images'])
        assert aggregated_images_dir.name == "images"
        assert aggregated_images_dir.parent == Path(result['output_directory'])
        linked = sorted(aggregated_images_dir.iterdir())
        assert [p.name for p in linked] == [
            "chunk-1-images-1.png",
            "chunk-2-images-1.png",
        ]
        assert all(p.is_symlink() for p in linked)
        assert all(p.resolve().parent.name == "images" for p in linked)


class TestProcessBinaryFileAdditiveContract:
    """Tests for additive API params and response keys."""

    @pytest.mark.asyncio
    async def test_process_binary_file_accepts_new_request_params(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        called = {}
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                called["invoked"] = True
                called.update(kwargs)
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
            page_range_mode="physical",
            strict_page_range=False,
            enable_toc_auto_fallback=False,
            toc_confidence_threshold=0.55,
            fail_on_unreadable=False,
            skip_quality_check=False,
        )

        assert result["success"] is True
        assert called["invoked"] is True
        assert not any("enforced in later phases" in warning for warning in result["warnings"])

    @pytest.mark.asyncio
    async def test_process_binary_file_returns_additive_response_fields(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                readable = ("This is readable content with many words and numbers 12345. " * 20).strip()
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": readable,
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
        )

        assert result["success"] is True
        assert "warnings" in result
        assert "quality_state" in result
        assert "quality_metrics" in result
        assert "requires_ocr" in result
        assert "toc_confidence" in result
        assert "toc_resolution_mode" in result
        assert "toc_offset" in result
        assert "toc_evidence_pages" in result
        assert isinstance(result["warnings"], list)
        assert result["quality_state"] == "ok"
        assert set(result["quality_metrics"]) == {
            "control_char_ratio",
            "printable_ratio",
            "alpha_numeric_density",
            "avg_readable_chars_per_page",
        }
        assert result["requires_ocr"] is False
        assert result["toc_confidence"] is None
        assert result["toc_resolution_mode"] == "not_evaluated"
        assert result["toc_offset"] is None
        assert result["toc_evidence_pages"] == []
        assert "resolved_start_page" in result
        assert "resolved_end_page" in result
        assert "resolved_page_map" in result

    @pytest.mark.asyncio
    async def test_process_binary_file_threads_toc_diagnostics(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: (
                [Chunk(phys_start=0, phys_end=0, title="single")],
                {
                    "mode": "heuristic",
                    "confidence": 0.63,
                    "offset": 3,
                    "evidence_pages": [4, 8],
                },
            ),
        )

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
        )

        assert result["success"] is True
        assert result["toc_confidence"] == 0.63
        assert result["toc_resolution_mode"] == "heuristic"
        assert result["toc_offset"] == 3
        assert result["toc_evidence_pages"] == [4, 8]

    @pytest.mark.asyncio
    async def test_process_binary_file_preserves_existing_additive_fields(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {},
                    "reading_order": [],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        def fake_process_and_save(**kwargs):
            return {
                "title": "single",
                "phys_start": 0,
                "phys_end": 0,
                "intermediate_path": tmp_path / "intermediate.json",
                "markdown_path": tmp_path / "output.md",
                "index_path": tmp_path / "index.json",
                "markdown_content": "content",
                "quality_state": "unreadable",
                "quality_metrics": {},
                "requires_ocr": True,
                "toc_confidence": 0.8,
                "toc_resolution_mode": "heuristic",
                "warnings": ["backend warning"],
            }

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )
        monkeypatch.setattr(server_app, "process_and_save", fake_process_and_save)

        result = await server_app.process_binary_file.fn(file_path=str(test_file), format="pdf")

        assert result["quality_state"] == "unreadable"
        assert result["quality_metrics"] == {}
        assert result["requires_ocr"] is True
        assert result["toc_confidence"] == 0.8
        assert result["toc_resolution_mode"] == "heuristic"
        assert "backend warning" in result["warnings"]
        assert any("OCR is likely required" in warning for warning in result["warnings"])

    @pytest.mark.asyncio
    async def test_process_binary_file_preserves_converter_metadata_quality(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {},
                    "reading_order": [],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        def fake_process_and_save(**kwargs):
            return {
                "title": "single",
                "phys_start": 0,
                "phys_end": 0,
                "intermediate_path": tmp_path / "intermediate.json",
                "markdown_path": tmp_path / "output.md",
                "index_path": tmp_path / "index.json",
                "intermediate": {
                    "source": {"page_count": 1},
                    "metadata": {
                        "quality_state": "unreadable",
                        "quality_metrics": {},
                        "requires_ocr": True,
                    },
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "content": "Readable fallback text that should not be rescored.",
                        }
                    },
                    "reading_order": ["block_00000000"],
                },
                "markdown_content": "Readable markdown fallback text.",
                "warnings": [],
            }

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )
        monkeypatch.setattr(server_app, "process_and_save", fake_process_and_save)

        result = await server_app.process_binary_file.fn(file_path=str(test_file), format="pdf")

        assert result["quality_state"] == "unreadable"
        assert result["quality_metrics"] == {}
        assert result["requires_ocr"] is True
        assert any("OCR is likely required" in warning for warning in result["warnings"])

    @pytest.mark.asyncio
    async def test_process_binary_file_marks_empty_extracted_text_unreadable(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {},
                    "reading_order": [],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        def fake_process_and_save(**kwargs):
            return {
                "title": "single",
                "phys_start": 0,
                "phys_end": 0,
                "intermediate_path": tmp_path / "intermediate.json",
                "markdown_path": tmp_path / "output.md",
                "index_path": tmp_path / "index.json",
                "intermediate": {
                    "source": {"page_count": 1},
                    "metadata": {},
                    "blocks": {},
                    "reading_order": [],
                },
                # Markdown scaffolding should not drive quality when raw extracted text exists.
                "markdown_content": "# Title\n\n## Section\n\nNo extracted blocks.",
                "warnings": [],
            }

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )
        monkeypatch.setattr(server_app, "process_and_save", fake_process_and_save)

        result = await server_app.process_binary_file.fn(file_path=str(test_file), format="pdf")

        assert result["quality_state"] == "unreadable"
        assert result["requires_ocr"] is True

    @pytest.mark.asyncio
    async def test_process_binary_file_adds_quality_warning_when_unreadable(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {},
                    "reading_order": [],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        def fake_process_and_save(**kwargs):
            return {
                "title": "single",
                "phys_start": 0,
                "phys_end": 0,
                "intermediate_path": tmp_path / "intermediate.json",
                "markdown_path": tmp_path / "output.md",
                "index_path": tmp_path / "index.json",
                "intermediate": {"source": {"page_count": 1}},
                "markdown_content": "\x01\x02\x03\x04\x05",
                "warnings": [],
            }

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )
        monkeypatch.setattr(server_app, "process_and_save", fake_process_and_save)

        result = await server_app.process_binary_file.fn(file_path=str(test_file), format="pdf")

        assert result["quality_state"] == "unreadable"
        assert result["requires_ocr"] is True
        assert result["quality_metrics"]["printable_ratio"] == 0.0
        assert any("OCR is likely required" in warning for warning in result["warnings"])

    @pytest.mark.asyncio
    async def test_process_binary_file_warns_when_non_default_reliability_controls_passed(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(
            server_app,
            "plan_chunks",
            lambda **kwargs: [Chunk(phys_start=0, phys_end=0, title="single")],
        )

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
            fail_on_unreadable=True,
        )

        assert result["success"] is True
        assert any("enforced in later phases" in warning for warning in result["warnings"])

    @pytest.mark.asyncio
    async def test_process_binary_file_strict_mode_disables_split_and_uses_resolved_span(
        self, monkeypatch, tmp_path
    ):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        observed = {}
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        def fake_plan_chunks(**kwargs):
            observed["chapter_split"] = kwargs["chapter_split"]
            observed["start_page"] = kwargs["start_page"]
            observed["end_page"] = kwargs["end_page"]
            return [Chunk(phys_start=kwargs["start_page"], phys_end=kwargs["end_page"], title="single")]

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(server_app, "plan_chunks", fake_plan_chunks)
        monkeypatch.setattr(
            server_app,
            "resolve_page_range",
            lambda **kwargs: (
                70,
                75,
                {
                    "mode": "logical",
                    "strategy": "toc_offset",
                    "requested": {"start_page": 60, "end_page": 65},
                    "resolved": {"start_page": 70, "end_page": 75},
                },
            ),
        )

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
            chapter_split="auto",
            page_range_mode="logical",
            strict_page_range=True,
            start_page=60,
            end_page=65,
        )

        assert result["success"] is True
        assert observed["chapter_split"] is False
        assert observed["start_page"] == 70
        assert observed["end_page"] == 75
        assert result["resolved_start_page"] == 70
        assert result["resolved_end_page"] == 75
        assert result["resolved_page_map"]["strategy"] == "toc_offset"

    @pytest.mark.asyncio
    async def test_process_binary_file_page_range_mode_is_case_insensitive(self, monkeypatch, tmp_path):
        from local_read_mcp.server import app as server_app
        from local_read_mcp.segmenter import Chunk

        observed = {}
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("fake pdf", encoding="utf-8")

        class FakeBackend:
            name = "Simple"
            warning = None

            def supports_format(self, format_name):
                return True

            def process(self, file_path, format_name, **kwargs):
                return {
                    "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                    "metadata": {},
                    "blocks": {
                        "block_00000000": {
                            "type": "text",
                            "page": 1,
                            "bbox": [0, 0, 612, 792],
                            "confidence": 0.9,
                            "content": "content",
                        }
                    },
                    "reading_order": ["block_00000000"],
                }

        class FakeRegistry:
            def select_best(self, format_name=None):
                return FakeBackend()

            def get(self, backend_type):
                return FakeBackend()

        def fake_plan_chunks(**kwargs):
            observed["start_page"] = kwargs["start_page"]
            observed["end_page"] = kwargs["end_page"]
            return [Chunk(phys_start=kwargs["start_page"], phys_end=kwargs["end_page"], title="single")]

        monkeypatch.setattr(server_app, "get_registry", lambda: FakeRegistry())
        monkeypatch.setattr(server_app, "plan_chunks", fake_plan_chunks)
        monkeypatch.setattr(
            server_app,
            "resolve_page_range",
            lambda **kwargs: (
                70,
                75,
                {
                    "mode": "logical",
                    "strategy": "toc_offset",
                    "requested": {"start_page": 60, "end_page": 65},
                    "resolved": {"start_page": 70, "end_page": 75},
                },
            ),
        )

        result = await server_app.process_binary_file.fn(
            file_path=str(test_file),
            format="pdf",
            chapter_split="auto",
            page_range_mode="LoGiCaL",
            strict_page_range=False,
            start_page=60,
            end_page=65,
        )

        assert result["success"] is True
        assert observed["start_page"] == 70
        assert observed["end_page"] == 75


class TestAnalyzeImagesBatch:
    """Tests for analyze_images_batch tool behavior."""

    @pytest.mark.asyncio
    async def test_analyze_images_batch_ordering_and_cache_hit_with_batch_size_gt_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VISION_API_KEY", "dummy-key")
        monkeypatch.chdir(tmp_path)

        import local_read_mcp.config as config_module
        from local_read_mcp.server import app as app_module
        from local_read_mcp.server import vision as vision_module

        config_module._config = None
        reloaded = importlib.reload(app_module)

        call_count = {"n": 0}

        async def fake_call_vision_api(image_path, question, api_key, base_url, model):
            call_count["n"] += 1
            return f"analysis:{Path(image_path).name}:{question}:{model}"

        monkeypatch.setattr(vision_module, "call_vision_api", fake_call_vision_api)

        image1 = tmp_path / "a.png"
        image2 = tmp_path / "b.png"
        image3 = tmp_path / "c.png"
        image1.write_bytes(b"image-a")
        image2.write_bytes(b"image-b")
        image3.write_bytes(b"image-c")
        ordered_paths = [str(image3), str(image1), str(image2)]

        first = await reloaded.analyze_images_batch.fn(
            image_paths=ordered_paths,
            question="what is this?",
            batch_size=2,
        )

        assert first["success"] is True
        assert len(first["results"]) == 3
        assert [item["image_path"] for item in first["results"]] == ordered_paths
        assert [item["cache_hit"] for item in first["results"]] == [False, False, False]
        assert all(("analysis" in item) for item in first["results"])

        second = await reloaded.analyze_images_batch.fn(
            image_paths=ordered_paths,
            question="what is this?",
            batch_size=2,
        )

        assert second["success"] is True
        assert [item["cache_hit"] for item in second["results"]] == [True, True, True]
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_analyze_images_batch_same_stem_paths_do_not_collide(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VISION_API_KEY", "dummy-key")
        monkeypatch.chdir(tmp_path)

        import local_read_mcp.config as config_module
        from local_read_mcp.server import app as app_module
        from local_read_mcp.server import vision as vision_module

        config_module._config = None
        reloaded = importlib.reload(app_module)

        async def fake_call_vision_api(image_path, question, api_key, base_url, model):
            return f"analysis:{Path(image_path).parent.name}"

        monkeypatch.setattr(vision_module, "call_vision_api", fake_call_vision_api)
        monkeypatch.setattr(vision_module.time, "strftime", lambda *args, **kwargs: "fixed-second")
        monkeypatch.setattr(vision_module.time, "time_ns", lambda: 1)

        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        image1 = dir1 / "same.png"
        image2 = dir2 / "same.png"
        image1.write_bytes(b"image-1")
        image2.write_bytes(b"image-2")

        result = await reloaded.analyze_images_batch.fn(
            image_paths=[str(image1), str(image2)],
            question="what is this?",
            batch_size=2,
        )

        assert result["success"] is True
        saved_paths = [item["saved_path"] for item in result["results"]]
        assert saved_paths[0] != saved_paths[1]
        assert Path(saved_paths[0]).exists()
        assert Path(saved_paths[1]).exists()

    @pytest.mark.asyncio
    async def test_analyze_images_batch_duplicate_key_in_same_batch_avoids_duplicate_calls(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VISION_API_KEY", "dummy-key")
        monkeypatch.chdir(tmp_path)

        import local_read_mcp.config as config_module
        from local_read_mcp.server import app as app_module
        from local_read_mcp.server import vision as vision_module

        config_module._config = None
        reloaded = importlib.reload(app_module)

        call_count = {"n": 0}

        async def fake_call_vision_api(image_path, question, api_key, base_url, model):
            call_count["n"] += 1
            return "analysis:shared"

        monkeypatch.setattr(vision_module, "call_vision_api", fake_call_vision_api)

        image = tmp_path / "dup.png"
        image.write_bytes(b"image-dup")

        result = await reloaded.analyze_images_batch.fn(
            image_paths=[str(image), str(image)],
            question="what is this?",
            batch_size=2,
        )

        assert result["success"] is True
        assert [item["cache_hit"] for item in result["results"]] == [False, True]
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_analyze_images_batch_concurrent_calls_same_key_use_one_underlying_call(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VISION_API_KEY", "dummy-key")
        monkeypatch.chdir(tmp_path)

        import local_read_mcp.config as config_module
        from local_read_mcp.server import app as app_module
        from local_read_mcp.server import vision as vision_module

        config_module._config = None
        reloaded = importlib.reload(app_module)

        call_count = {"n": 0}

        async def fake_call_vision_api(image_path, question, api_key, base_url, model):
            call_count["n"] += 1
            await asyncio.sleep(0.05)
            return "analysis:shared"

        monkeypatch.setattr(vision_module, "call_vision_api", fake_call_vision_api)

        image = tmp_path / "concurrent.png"
        image.write_bytes(b"same-bytes")

        first_task = asyncio.create_task(
            reloaded.analyze_images_batch.fn(
                image_paths=[str(image)],
                question="what is this?",
                batch_size=1,
            )
        )
        second_task = asyncio.create_task(
            reloaded.analyze_images_batch.fn(
                image_paths=[str(image)],
                question="what is this?",
                batch_size=1,
            )
        )
        first_result, second_result = await asyncio.gather(first_task, second_task)

        assert first_result["success"] is True
        assert second_result["success"] is True
        assert call_count["n"] == 1
        assert sorted(
            [
                first_result["results"][0]["cache_hit"],
                second_result["results"][0]["cache_hit"],
            ]
        ) == [False, True]
