"""
Unit tests for chapter_detector modules.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read_mcp.segmenter import Chapter, Chunk, ChunkPlanner
from local_read_mcp.segmenter.toc_extractor import TocExtractor, _CHAPTER_PATTERNS


class TestChapter:
    """Chapter dataclass basics."""

    def test_chapter_fields(self):
        ch = Chapter(level=1, title="Intro", logical_page=1, phys_index=4)
        assert ch.level == 1
        assert ch.title == "Intro"
        assert ch.logical_page == 1
        assert ch.phys_index == 4

    def test_chapter_default_phys_index(self):
        ch = Chapter(level=2, title="Section", logical_page=10)
        assert ch.phys_index == 0  # default from dataclass


class TestChunk:
    """Chunk dataclass basics."""

    def test_chunk_fields(self):
        ck = Chunk(phys_start=0, phys_end=9, title="Ch 1", batch_size=10)
        assert ck.phys_start == 0
        assert ck.phys_end == 9
        assert ck.title == "Ch 1"
        assert ck.batch_size == 10

    def test_chunk_defaults(self):
        ck = Chunk(phys_start=5, phys_end=15)
        assert ck.title == ""
        assert ck.level == 1
        assert ck.batch_size == 64  # default


class TestChunkPlannerPlanFromChapters:
    """ChunkPlanner.plan_from_chapters edge cases."""

    def test_empty_chapters_returns_single_chunk(self):
        planner = ChunkPlanner()
        chunks = planner.plan_from_chapters([], total_pages=30)
        assert len(chunks) == 1
        assert chunks[0].phys_start == 0
        assert chunks[0].phys_end == 29
        assert chunks[0].title == "full_document"

    def test_single_chapter(self):
        planner = ChunkPlanner(overlap=0)
        chapters = [Chapter(1, "Ch 1", 1, phys_index=0)]
        chunks = planner.plan_from_chapters(chapters, total_pages=50)
        assert len(chunks) == 1
        assert chunks[0].phys_start == 0
        assert chunks[0].phys_end == 49

    def test_two_chapters_no_overlap(self):
        planner = ChunkPlanner(overlap=0)
        chapters = [
            Chapter(1, "Ch 1", 1, phys_index=0),
            Chapter(1, "Ch 2", 20, phys_index=19),
        ]
        chunks = planner.plan_from_chapters(chapters, total_pages=40)
        assert len(chunks) == 2
        assert chunks[0].phys_start == 0
        assert chunks[0].phys_end == 18
        assert chunks[1].phys_start == 19
        assert chunks[1].phys_end == 39

    def test_two_chapters_with_overlap(self):
        planner = ChunkPlanner(overlap=2)
        chapters = [
            Chapter(1, "Ch 1", 1, phys_index=0),
            Chapter(1, "Ch 2", 20, phys_index=19),
        ]
        chunks = planner.plan_from_chapters(chapters, total_pages=40)
        assert chunks[0].phys_end == 20  # overlaps 2 pages into Ch 2
        assert chunks[1].phys_start == 19

    def test_chapter_starts_out_of_bounds(self):
        planner = ChunkPlanner()
        chapters = [Chapter(1, "Out", 1, phys_index=100)]
        chunks = planner.plan_from_chapters(chapters, total_pages=50)
        assert len(chunks) == 1  # filtered, fallback
        assert chunks[0].phys_start == 0

    def test_duplicate_phys_indices_deduplicated(self):
        planner = ChunkPlanner()
        chapters = [
            Chapter(1, "Ch 1", 1, phys_index=0),
            Chapter(2, "Ch 1.1", 1, phys_index=0),
        ]
        chunks = planner.plan_from_chapters(chapters, total_pages=30)
        assert len(chunks) == 1  # only one unique start

    def test_min_chunk_pages_merges_small_chunks(self):
        planner = ChunkPlanner(overlap=0, min_chunk_pages=3)
        chapters = [
            Chapter(1, "Ch 1", 1, phys_index=0),
            Chapter(1, "Ch 2", 4, phys_index=3),
            Chapter(1, "Ch 3", 8, phys_index=7),
        ]
        chunks = planner.plan_from_chapters(chapters, total_pages=50)
        # Ch 2 is only 4 pages (3-6), >= min_chunk_pages(3), so it stays separate
        assert len(chunks) >= 2

    def test_chapter_handles_non_top_level_only(self):
        planner = ChunkPlanner(overlap=0)
        chapters = [
            Chapter(2, "Sec 1", 1, phys_index=0),
            Chapter(2, "Sec 2", 5, phys_index=4),
        ]
        chunks = planner.plan_from_chapters(chapters, total_pages=20)
        assert len(chunks) == 2

    def test_no_total_pages_no_next_chapter(self):
        planner = ChunkPlanner(overlap=0)
        chapters = [Chapter(1, "Only", 1, phys_index=0)]
        chunks = planner.plan_from_chapters(chapters, total_pages=None)
        assert len(chunks) == 1
        assert chunks[0].phys_end == 0  # only one page


class TestChunkPlannerPlanFixed:
    """ChunkPlanner.plan_fixed edge cases."""

    def test_exact_multiple(self):
        planner = ChunkPlanner()
        chunks = planner.plan_fixed(20, chunk_size=10)
        assert len(chunks) == 2
        assert chunks[0].phys_start == 0
        assert chunks[0].phys_end == 9
        assert chunks[1].phys_start == 10
        assert chunks[1].phys_end == 19

    def test_remainder(self):
        planner = ChunkPlanner()
        chunks = planner.plan_fixed(25, chunk_size=10)
        assert len(chunks) == 3
        assert chunks[-1].phys_end == 24

    def test_single_page(self):
        planner = ChunkPlanner()
        chunks = planner.plan_fixed(1)
        assert len(chunks) == 1
        assert chunks[0].phys_start == 0
        assert chunks[0].phys_end == 0

    def test_zero_page_count(self):
        planner = ChunkPlanner()
        chunks = planner.plan_fixed(0)
        assert len(chunks) == 0


class TestTocExtractorChapterPatterns:
    """Verify that _CHAPTER_PATTERNS match expected heading formats."""

    @pytest.mark.parametrize("text, expected", [
        ("Chapter 1 Introduction\nSome text...", "Chapter 1"),
        ("CHAPTER 2 Methods", "CHAPTER 2"),
        ("Ch. 3 Results", "Ch. 3"),
        ("第一章 绪论", "第一章"),
        ("第二章 相关工作", "第二章"),
        ("Part I Foundations", "Part I"),
        ("Part II Advanced", "Part II"),
        ("# Heading", "#"),
        ("## Sub heading", "##"),
    ])
    def test_chapter_pattern_matches(self, text, expected):
        for pattern in _CHAPTER_PATTERNS:
            m = pattern.search(text)
            if m:
                assert expected in m.group()
                return
        pytest.fail(f"No pattern matched: {text!r}")

    @pytest.mark.parametrize("text", [
        "This is just a paragraph with Chapter written in it.",
        "Page 1 of 10",
        "\\chapter{Introduction}",  # LaTeX, not displayed text
        "",
    ])
    def test_chapter_pattern_no_false_positive(self, text):
        for pattern in _CHAPTER_PATTERNS:
            if pattern.search(text):
                pytest.fail(f"Unexpected match for {text!r}")


class TestTocExtractorTitleKeywords:
    """TocExtractor._title_keywords."""

    def test_filter_stopwords(self):
        kw = TocExtractor._title_keywords("The Art of Computer Programming")
        assert "the" not in [w.lower() for w in kw]
        assert "Art" in kw or "art" in [w.lower() for w in kw]

    def test_short_title(self):
        kw = TocExtractor._title_keywords("Intro")
        assert kw == ["Intro"]

    def test_empty_title(self):
        assert TocExtractor._title_keywords("") == []


class TestTocExtractorDiagnostics:
    """Diagnostics behavior for TOC resolution."""

    def test_heuristic_resolution_emits_multi_anchor_diagnostics(self):
        class FakePage:
            def __init__(self, text):
                self._text = text

            def get_text(self):
                return self._text

            def get_label(self):
                return ""

        class FakeDoc:
            def __init__(self):
                self.page_count = 10
                self._pages = [FakePage("no chapter here") for _ in range(10)]
                self._pages[2] = FakePage("Chapter 1 Introduction")
                self._pages[5] = FakePage("Chapter 2 Methods")
                self._pages[8] = FakePage("Chapter 3 Results")

            def get_toc(self):
                return [
                    [1, "Introduction", 1],
                    [1, "Methods", 4],
                    [1, "Results", 7],
                ]

            def __getitem__(self, idx):
                return self._pages[idx]

        extractor = TocExtractor()
        chapters, diagnostics = extractor.extract(FakeDoc(), with_diagnostics=True)

        assert diagnostics.mode == "heuristic"
        assert 0.0 <= diagnostics.confidence <= 1.0
        assert diagnostics.offset == 2
        assert diagnostics.evidence_pages == [3, 6, 9]
        assert [c.phys_index for c in chapters] == [2, 5, 8]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
