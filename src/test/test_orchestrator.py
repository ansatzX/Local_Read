"""Unit tests for server orchestrator helpers."""

import builtins
from pathlib import Path
from types import SimpleNamespace


def test_resolve_page_range_logical_uses_extractor_mapping(monkeypatch):
    """Logical page mode should resolve through TOC/page-label aware extractor mapping."""
    from local_read_mcp.server import orchestrator

    observed = {}

    class FakeDoc:
        page_count = 200

        def close(self):
            return None

    class FakeExtractor:
        def resolve_logical_range(self, doc, start_page, end_page):
            observed["start_page"] = start_page
            observed["end_page"] = end_page
            return 70, 75, {
                "mode": "logical",
                "strategy": "toc_offset",
                "offset": 10,
                "requested": {"start_page": 60, "end_page": 65},
                "resolved": {"start_page": 70, "end_page": 75},
            }

    monkeypatch.setitem(
        __import__("sys").modules,
        "fitz",
        SimpleNamespace(open=lambda path: FakeDoc()),
    )
    monkeypatch.setattr(orchestrator, "TocExtractor", FakeExtractor)

    start_page, end_page, page_map = orchestrator.resolve_page_range(
        file_path="sample.pdf",
        format="pdf",
        start_page=60,
        end_page=65,
        page_range_mode="logical",
    )

    assert observed["start_page"] == 60
    assert observed["end_page"] == 65
    assert start_page == 70
    assert end_page == 75
    assert page_map["strategy"] == "toc_offset"
    assert page_map["resolved"]["start_page"] == 70
    assert page_map["resolved"]["end_page"] == 75


def test_resolve_page_range_logical_without_fitz_keeps_open_ended_range(monkeypatch):
    """When fitz is unavailable, logical open-ended ranges should remain open-ended."""
    from local_read_mcp.server import orchestrator

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("fitz not available")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    start_page, end_page, page_map = orchestrator.resolve_page_range(
        file_path="sample.pdf",
        format="pdf",
        start_page=3,
        end_page=None,
        page_range_mode="logical",
    )

    assert start_page == 2
    assert end_page is None
    assert page_map["strategy"] == "logical_minus_one"
    assert page_map["resolved"]["start_page"] == 2
    assert page_map["resolved"]["end_page"] is None


def test_plan_chunks_no_split_keeps_zero_end_page():
    """end_page=0 must not be treated as falsy and expanded."""
    from local_read_mcp.server import orchestrator

    chunks = orchestrator.plan_chunks(
        file_path="sample.pdf",
        format="pdf",
        backend_name="Simple",
        chapter_split=False,
        start_page=0,
        end_page=0,
        return_diagnostics=False,
    )

    assert len(chunks) == 1
    assert chunks[0].phys_start == 0
    assert chunks[0].phys_end == 0


def test_process_and_save_slices_pdf_chunk_without_name_error(monkeypatch, tmp_path):
    """PDF chunk slicing path should work (regression for missing tempfile import)."""
    from local_read_mcp.server import orchestrator
    from local_read_mcp.segmenter import Chunk

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_text("fake pdf", encoding="utf-8")

    class FakeSrcDoc:
        page_count = 5

        def close(self):
            return None

    class FakeSlicedDoc:
        def insert_pdf(self, src, from_page, to_page):
            self.from_page = from_page
            self.to_page = to_page

        def save(self, path):
            Path(path).write_text("sliced", encoding="utf-8")

        def close(self):
            return None

    def fake_fitz_open(*args, **kwargs):
        if len(args) == 0:
            return FakeSlicedDoc()
        return FakeSrcDoc()

    monkeypatch.setitem(
        __import__("sys").modules,
        "fitz",
        SimpleNamespace(open=fake_fitz_open),
    )

    class FakeBackend:
        def process(self, file_path, format_name, **kwargs):
            return {
                "source": {"path": str(file_path), "format": format_name, "page_count": 1},
                "metadata": {},
                "blocks": {
                    "block_00000000": {
                        "type": "text",
                        "page": 0,
                        "bbox": [0, 0, 1, 1],
                        "content": "ok",
                    }
                },
                "reading_order": ["block_00000000"],
            }

    output_path = tmp_path / "out"
    output_path.mkdir()
    images_dir = output_path / "images"
    chunk = Chunk(phys_start=1, phys_end=2, title="middle")

    result = orchestrator.process_and_save(
        file_path=str(input_pdf),
        backend=FakeBackend(),
        format="pdf",
        output_path=output_path,
        images_dir=images_dir,
        chunk=chunk,
        backend_kwargs={},
    )

    assert "sliced_pdf_path" in result
    assert Path(result["sliced_pdf_path"]).exists()


def test_merge_chunk_markdowns_dedupes_only_overlap_window():
    """Overlap prefix duplication should be removed for adjacent overlapping chunks only."""
    from local_read_mcp.server import orchestrator

    duplicated_overlap = "\n".join(
        [
            "Shared overlap paragraph line A with enough characters.",
            "Shared overlap paragraph line B with enough characters.",
        ]
    )

    merged = orchestrator.merge_chunk_markdowns(
        [
            {
                "title": "Chapter 1",
                "phys_start": 0,
                "phys_end": 2,
                "markdown_content": "\n".join(["Chunk1 opening", duplicated_overlap]),
            },
            {
                "title": "Chapter 2",
                "phys_start": 2,
                "phys_end": 4,
                "markdown_content": "\n".join([duplicated_overlap, "Chunk2 unique content"]),
            },
            {
                "title": "Chapter 3",
                "phys_start": 5,
                "phys_end": 6,
                "markdown_content": "\n".join([duplicated_overlap, "Chunk3 unique content"]),
            },
        ]
    )

    assert merged.count(duplicated_overlap) == 2
    assert merged.count("Chunk2 unique content") == 1
    assert "# Chapter 1  (pages 1–3)" in merged
    assert "# Chapter 2  (pages 3–5)" in merged
    assert "# Chapter 3  (pages 6–7)" in merged


def test_merge_chunk_markdowns_keeps_short_single_line_overlap():
    """A short single-line duplicate should not be trimmed."""
    from local_read_mcp.server import orchestrator

    short_line = "Figure 1."
    merged = orchestrator.merge_chunk_markdowns(
        [
            {
                "title": "Part A",
                "phys_start": 0,
                "phys_end": 2,
                "markdown_content": "\n".join(["A intro", short_line]),
            },
            {
                "title": "Part B",
                "phys_start": 2,
                "phys_end": 4,
                "markdown_content": "\n".join([short_line, "B unique"]),
            },
        ]
    )

    assert merged.count(short_line) == 2
    assert "B unique" in merged


def test_merge_chunk_markdowns_keeps_repeated_boilerplate_without_page_overlap():
    """Repeated boilerplate in non-overlapping chunks should remain untouched."""
    from local_read_mcp.server import orchestrator

    boilerplate = "Company Internal Use Only"
    merged = orchestrator.merge_chunk_markdowns(
        [
            {
                "title": "S1",
                "phys_start": 0,
                "phys_end": 1,
                "markdown_content": "\n".join([boilerplate, "S1 body"]),
            },
            {
                "title": "S2",
                "phys_start": 2,
                "phys_end": 3,
                "markdown_content": "\n".join([boilerplate, "S2 body"]),
            },
        ]
    )

    assert merged.count(boilerplate) == 2
    assert "S1 body" in merged
    assert "S2 body" in merged


def test_merge_chunk_markdowns_resets_dedupe_context_after_error_chunk():
    """After a failed chunk, the next successful chunk should not dedupe against stale context."""
    from local_read_mcp.server import orchestrator

    overlap_text = "\n".join(
        [
            "Shared overlap line A with enough characters.",
            "Shared overlap line B with enough characters.",
        ]
    )
    merged = orchestrator.merge_chunk_markdowns(
        [
            {
                "title": "Chunk 1",
                "phys_start": 0,
                "phys_end": 2,
                "markdown_content": "\n".join(["C1 intro", overlap_text]),
            },
            {
                "title": "Chunk 2",
                "phys_start": 2,
                "phys_end": 4,
                "error": "backend failed",
            },
            {
                "title": "Chunk 3",
                "phys_start": 2,
                "phys_end": 5,
                "markdown_content": "\n".join([overlap_text, "C3 unique"]),
            },
        ]
    )

    assert merged.count(overlap_text) == 2
    assert "processing failed" in merged
    assert "C3 unique" in merged
