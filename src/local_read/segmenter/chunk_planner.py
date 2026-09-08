"""Plan page-range chunks from chapter boundaries for batched processing."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .toc_extractor import Chapter

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A page range ready for backend processing.

    Attributes:
        phys_start: 0-based start page (inclusive).
        phys_end:   0-based end page (inclusive).
        title:      Display title (chapter name, or auto-generated).
        level:      TOC level (0 = auto-generated fixed chunk).
        batch_size: Suggested window size for the backend.
    """
    phys_start: int
    phys_end: int
    title: str = ""
    level: int = 1
    batch_size: int = 64


class ChunkPlanner:
    """Convert detected chapters into page-range chunks with configurable overlap.

    Ensures every page of the document is covered exactly once, with overlap
    pages duplicated between adjacent chunks for context continuity.
    """

    def __init__(self, overlap: int = 2, min_chunk_pages: int = 1):
        """
        Args:
            overlap: Number of pages from the *start* of the next chunk to
                append to the current chunk (to avoid broken paragraphs).
            min_chunk_pages: Minimum pages per chunk; chunks below this
                threshold are merged into the previous one.
        """
        self.overlap = overlap
        self.min_chunk_pages = min_chunk_pages

    def plan_from_chapters(self, chapters: list[Chapter],
                           total_pages: Optional[int] = None) -> list[Chunk]:
        """Convert resolved chapters to processing chunks.

        Each chunk covers from its chapter's physical start to the next
        chapter's physical start, with overlap pages added.
        """
        if not chapters:
            return self._fallback(total_pages or 0)

        chapters = sorted(chapters, key=lambda c: c.phys_index)

        # Filter out entries beyond the document
        if total_pages:
            chapters = [c for c in chapters if c.phys_index < total_pages]

        # Deduplicate: keep only the first entry per unique physical page
        seen: set[int] = set()
        unique: list[Chapter] = []
        for c in chapters:
            if c.phys_index not in seen:
                seen.add(c.phys_index)
                unique.append(c)

        # Build chunks from chapter boundaries
        chunks: list[Chunk] = []
        for i, ch in enumerate(unique):
            ch_start = ch.phys_index
            if i + 1 < len(unique):
                ch_end = unique[i + 1].phys_index - 1
            else:
                ch_end = (total_pages - 1) if total_pages else ch_start

            # Append overlap from next chapter
            if self.overlap and i + 1 < len(unique):
                next_start = unique[i + 1].phys_index
                ch_end = max(ch_end, next_start + self.overlap - 1)

            if total_pages:
                ch_end = min(ch_end, total_pages - 1)

            page_count = ch_end - ch_start + 1
            if page_count < self.min_chunk_pages:
                # Merge into previous chunk
                if chunks:
                    chunks[-1].phys_end = ch_end
                    chunks[-1].title = f"{chunks[-1].title} / {ch.title}"
                continue

            chunks.append(Chunk(
                phys_start=ch_start,
                phys_end=ch_end,
                title=ch.title,
                level=ch.level,
                batch_size=min(64, ch_end - ch_start + 1 + self.overlap),
            ))

        if not chunks and total_pages:
            return self._fallback(total_pages)

        logger.info("Planned %d chunk(s) from %d chapter(s) (overlap=%d)",
                    len(chunks), len(chapters), self.overlap)
        return chunks

    def plan_fixed(self, page_count: int, chunk_size: int = 20) -> list[Chunk]:
        """Fallback planner: split the document into fixed-size chunks.

        Used when chapter detection yields no results.
        """
        chunks: list[Chunk] = []
        start = 0
        index = 0
        while start < page_count:
            end = min(start + chunk_size - 1, page_count - 1)
            chunks.append(Chunk(
                phys_start=start,
                phys_end=end,
                title=f"chunk_{index:04d}",
                level=1,
                batch_size=min(64, chunk_size),
            ))
            start = end + 1
            index += 1

        logger.info("Fallback: planned %d fixed-size chunk(s) of %d pages.",
                    len(chunks), chunk_size)
        return chunks

    # ── Internal ──────────────────────────────────────────────────────

    def _fallback(self, total_pages: int) -> list[Chunk]:
        """Return a single chunk covering the entire document."""
        return [Chunk(
            phys_start=0,
            phys_end=total_pages - 1,
            title="full_document",
            batch_size=min(64, total_pages),
        )]
