"""Processing orchestration: chunk planning, single-chunk processing, and merging."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from ..index_generator import IndexGenerator
from ..markdown_converter import MarkdownConverter
from ..segmenter import Chunk, ChunkPlanner, TocExtractor

logger = logging.getLogger(__name__)


def resolve_page_range(
    file_path: str,
    format: str,
    start_page: int | None,
    end_page: int | None,
    page_range_mode: str = "physical",
) -> tuple[int | None, int | None, dict[str, Any]]:
    """Resolve user page range to physical 0-based pages for processing."""
    mode = (page_range_mode or "physical").lower()
    if mode not in {"physical", "logical"}:
        mode = "physical"

    mapping: dict[str, Any] = {
        "mode": mode,
        "strategy": "identity" if mode == "physical" else "logical_minus_one",
        "requested": {"start_page": start_page, "end_page": end_page},
        "resolved": {"start_page": start_page, "end_page": end_page},
    }

    if format != "pdf":
        return start_page, end_page, mapping

    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        if mode == "logical":
            fallback_start = 0 if start_page is None else max(0, int(start_page) - 1)
            fallback_end = None if end_page is None else max(fallback_start, int(end_page) - 1)
            mapping["strategy"] = "logical_minus_one"
            mapping["resolved"] = {"start_page": fallback_start, "end_page": fallback_end}
            return fallback_start, fallback_end, mapping
        return start_page, end_page, mapping

    try:
        doc = fitz.open(file_path)
    except Exception:
        return start_page, end_page, mapping

    total_pages = int(getattr(doc, "page_count", 0) or 0)
    try:
        if total_pages <= 0:
            mapping["strategy"] = "empty_document"
            mapping["resolved"] = {"start_page": 0, "end_page": 0}
            return 0, 0, mapping

        if mode == "logical":
            extractor = TocExtractor()
            resolved_start, resolved_end, logical_map = extractor.resolve_logical_range(
                doc, start_page, end_page
            )
            if isinstance(logical_map, dict):
                mapping.update(logical_map)
            mapping["mode"] = "logical"
            mapping["resolved"] = {"start_page": resolved_start, "end_page": resolved_end}
            return resolved_start, resolved_end, mapping

        resolved_start = 0 if start_page is None else int(start_page)
        resolved_end = (total_pages - 1) if end_page is None else int(end_page)
        resolved_start = max(0, min(resolved_start, total_pages - 1))
        resolved_end = max(0, min(resolved_end, total_pages - 1))
        if resolved_start > resolved_end:
            resolved_start, resolved_end = resolved_end, resolved_start
        mapping["strategy"] = "clamped_physical"
        mapping["resolved"] = {"start_page": resolved_start, "end_page": resolved_end}
        return resolved_start, resolved_end, mapping
    finally:
        doc.close()


def plan_chunks(
    file_path: str,
    format: str,
    backend_name: str,
    chapter_split: bool | str | int,
    start_page: int | None,
    end_page: int | None,
    page_batch_size: int = 64,
    enable_toc_auto_fallback: bool = False,
    toc_confidence_threshold: float = 0.55,
    return_diagnostics: bool = False,
) -> list[Any] | tuple[list[Any], dict[str, Any]]:
    """Determine processing chunks for the given document.

    Returns a list of Chunk objects (from the segmenter module).
    A single-element list means no splitting.
    """
    diagnostics: dict[str, Any] = {
        "mode": "not_evaluated",
        "confidence": None,
        "offset": None,
        "evidence_pages": [],
    }

    def _return(chunks: list[Any]) -> list[Any] | tuple[list[Any], dict[str, Any]]:
        if return_diagnostics:
            return chunks, diagnostics
        return chunks

    def _default_start() -> int:
        return 0 if start_page is None else int(start_page)

    def _default_end(max_end: int = 2**31 - 1) -> int:
        return max_end if end_page is None else int(end_page)

    # No splitting requested
    if chapter_split is False or chapter_split is None:
        return _return([Chunk(phys_start=_default_start(), phys_end=_default_end())])

    # Only PDF + layout-capable backend triggers the segmenter
    if format != "pdf":
        return _return([Chunk(phys_start=_default_start(), phys_end=_default_end())])

    # Load document for page count and chapter detection
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        logger.warning("PyMuPDF not available, cannot detect chapters")
        return _return([Chunk(phys_start=_default_start(), phys_end=_default_end())])

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.warning("Cannot open PDF for chapter detection: %s, processing whole file", e)
        s = _default_start()
        e = _default_end()
        return _return([Chunk(phys_start=s, phys_end=e)])

    total = doc.page_count

    # Determine if splitting is worthwhile
    need_split = False
    split_type: str | int = "auto"
    if chapter_split is True:
        need_split = True
        split_type = "chapter"
    elif isinstance(chapter_split, str) and chapter_split == "auto":
        need_split = total > 30
        split_type = "auto"
    elif isinstance(chapter_split, str) and chapter_split in ("chapter", "section"):
        need_split = True
        split_type = chapter_split
    elif isinstance(chapter_split, int):
        need_split = True
        split_type = chapter_split

    if not need_split:
        doc.close()
        s = _default_start()
        e = min(_default_end(total - 1), total - 1)
        return _return([Chunk(phys_start=s, phys_end=e)])

    # Run segmenter
    try:
        extractor = TocExtractor()
        extracted = extractor.extract(doc, with_diagnostics=True)
        if isinstance(extracted, tuple):
            chapters, toc_diagnostics = extracted
        else:
            chapters = extracted
            toc_diagnostics = None
        if toc_diagnostics is not None:
            diagnostics = toc_diagnostics.as_dict()
        planner = ChunkPlanner(overlap=2)

        use_chapters = bool(chapters)
        if (
            use_chapters
            and enable_toc_auto_fallback
            and diagnostics.get("mode") != "not_evaluated"
            and isinstance(diagnostics.get("confidence"), (int, float))
            and float(diagnostics["confidence"]) < float(toc_confidence_threshold)
            and not isinstance(split_type, int)
        ):
            use_chapters = False
            diagnostics["fallback_applied"] = True
            diagnostics["fallback_reason"] = (
                f"TOC confidence {float(diagnostics['confidence']):.2f} below threshold "
                f"{float(toc_confidence_threshold):.2f}; using fixed chunks."
            )

        if use_chapters:
            raw_chunks = planner.plan_from_chapters(chapters, total_pages=total)
        elif isinstance(split_type, int):
            raw_chunks = planner.plan_fixed(total, chunk_size=split_type)
        else:
            raw_chunks = planner.plan_fixed(total, chunk_size=page_batch_size)

        doc.close()
    except Exception as e:
        logger.warning("Chapter detection failed: %s, falling back to fixed chunks", e)
        doc.close()
        planner = ChunkPlanner()
        raw_chunks = planner.plan_fixed(total, chunk_size=page_batch_size)

    # Apply start_page / end_page bounds
    if start_page is not None or end_page is not None:
        bounded: list[Any] = []
        for c in raw_chunks:
            s = c.phys_start
            e = c.phys_end
            if start_page is not None:
                s = max(s, start_page)
            if end_page is not None:
                e = min(e, end_page)
            if s <= e:
                bounded.append(Chunk(phys_start=s, phys_end=e, title=c.title, level=c.level, batch_size=c.batch_size))
        return _return(bounded)

    return _return(raw_chunks)


def process_and_save(
    file_path: str,
    backend,
    format: str,
    output_path: Path,
    images_dir: Path,
    chunk: Any,
    backend_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Process one chunk through the backend and save all outputs."""
    # For PDF page-range chunks, slice the PDF into a temp file
    # so the backend receives a PDF that starts at page 0.
    if format == "pdf":
        import fitz  # noqa: PLC0415

        try:
            src = fitz.open(file_path)
        except Exception:
            sliced_path = Path(file_path)
        else:
            total = src.page_count
            p_start = max(0, min(chunk.phys_start, total - 1))
            p_end = max(p_start, min(chunk.phys_end, total - 1))

            if p_start == 0 and p_end >= total - 1:
                sliced_path = Path(file_path)
                src.close()
            else:
                sliced = fitz.open()
                sliced.insert_pdf(src, from_page=p_start, to_page=p_end)
                if images_dir:
                    images_dir.mkdir(parents=True, exist_ok=True)
                tmp_dir = str(images_dir.parent) if images_dir else str(Path.cwd() / ".local_read_mcp")
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
                os.close(tmp_fd)
                sliced.save(tmp_path_str)
                sliced.close()
                sliced_path = Path(tmp_path_str)
                src.close()
    else:
        sliced_path = Path(file_path)

    try:
        intermediate = backend.process(sliced_path, format, **backend_kwargs)
    finally:
        pass  # sliced PDF kept under .local_read_mcp/ for agent inspection

    # Save intermediate.json
    intermediate_path = output_path / "intermediate.json"
    with open(intermediate_path, 'w', encoding='utf-8') as f:
        json.dump(intermediate, f, ensure_ascii=False, indent=2)

    # Save output.md
    markdown_converter = MarkdownConverter(intermediate)
    markdown_content = markdown_converter.convert()
    markdown_path = output_path / "output.md"
    with open(markdown_path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)

    # Save index.json
    index_generator = IndexGenerator(intermediate)
    index_path = output_path / "index.json"
    index_generator.save_to_file(str(index_path))

    result: dict[str, Any] = {
        "title": chunk.title if hasattr(chunk, 'title') else "",
        "phys_start": chunk.phys_start if hasattr(chunk, 'phys_start') else 0,
        "phys_end": chunk.phys_end if hasattr(chunk, 'phys_end') else 0,
        "intermediate_path": intermediate_path,
        "markdown_path": markdown_path,
        "index_path": index_path,
        "intermediate": intermediate,
        "markdown_content": markdown_content,
    }
    if format == "pdf" and sliced_path != Path(file_path):
        result["sliced_pdf_path"] = str(sliced_path)

    if images_dir.exists():
        image_files = list(images_dir.iterdir())
        if image_files:
            result["image_files"] = image_files

    return result


def merge_chunk_markdowns(chunk_results: list[dict[str, Any]]) -> str:
    """Concatenate chunk markdowns with chapter separators."""
    def _trim_overlap_window_duplicate(previous_md: str, current_md: str, overlap_pages: int) -> str:
        """Drop duplicated prefix in current chunk when adjacent chunks overlap in page range."""
        if not previous_md or not current_md or overlap_pages <= 0:
            return current_md

        previous_lines = previous_md.splitlines()
        current_lines = current_md.splitlines()
        # Keep dedupe conservative: only inspect a plausible window derived from
        # page overlap between adjacent chunks, not an unbounded/global prefix.
        max_lines_per_overlap_page = 40
        max_overlap_lines = min(
            len(previous_lines),
            len(current_lines),
            overlap_pages * max_lines_per_overlap_page,
        )
        if max_overlap_lines <= 0:
            return current_md

        for overlap in range(max_overlap_lines, 0, -1):
            if previous_lines[-overlap:] != current_lines[:overlap]:
                continue

            overlap_text = "\n".join(current_lines[:overlap]).strip()
            if overlap >= 2 or len(overlap_text) >= 40:
                return "\n".join(current_lines[overlap:]).lstrip("\n")

        return current_md

    parts: list[str] = []
    previous_success: dict[str, Any] | None = None
    for cr in chunk_results:
        if "error" in cr:
            parts.append(
                f"\n\n---\n## [{cr.get('title', 'error')}] (processing failed)\n\n"
                f"Error: {cr['error']}\n"
            )
            previous_success = None
            continue
        md = cr.get("markdown_content", "")
        original_md = md
        title = cr.get("title", "")
        p_start = cr.get("phys_start", 0)
        p_end = cr.get("phys_end", 0)

        if previous_success is not None:
            previous_end = int(previous_success.get("phys_end", -1))
            overlap_pages = previous_end - int(p_start) + 1
            if overlap_pages > 0:
                md = _trim_overlap_window_duplicate(
                    str(previous_success.get("markdown_content", "")),
                    md,
                    overlap_pages=overlap_pages,
                )

        header = f"\n\n---\n# {title}  (pages {p_start + 1}–{p_end + 1})\n\n"
        parts.append(header + md)
        previous_success = {
            "phys_end": p_end,
            # Preserve raw chunk markdown as the next dedupe context.
            "markdown_content": original_md,
        }
    return "\n".join(parts).strip()




def merge_chunk_intermediates(source_path: str, format: str, chunk_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge successful chunk intermediate JSON objects into a top-level intermediate document."""
    merged: dict[str, Any] = {
        "source": {"path": str(Path(source_path).absolute()), "format": format, "page_count": 0},
        "metadata": {},
        "blocks": {},
        "reading_order": [],
    }
    block_index = 0
    for result in chunk_results:
        if "error" in result:
            continue
        offset = int(result.get("phys_start", 0))
        intermediate = result["intermediate"]
        merged["source"]["page_count"] = max(
            merged["source"]["page_count"], int(result.get("phys_end", offset)) + 1
        )
        for old_id in intermediate.get("reading_order", []):
            block = dict(intermediate.get("blocks", {}).get(old_id, {}))
            if "page" in block:
                block["page"] = offset + int(block["page"])
            new_id = f"block_{block_index:08x}"
            block_index += 1
            merged["blocks"][new_id] = block
            merged["reading_order"].append(new_id)
    return merged

def save_structural_toc(output_path: Path, chunks: list[Any]) -> None:
    """Save the structural table of contents as JSON."""
    toc_data = []
    for idx, c in enumerate(chunks):
        toc_data.append({
            "chunk_index": idx + 1,
            "title": getattr(c, "title", ""),
            "level": getattr(c, "level", 1),
            "phys_start": getattr(c, "phys_start", 0),
            "phys_end": getattr(c, "phys_end", 0),
        })

    toc_path = output_path / "structural_toc.json"
    with open(toc_path, 'w', encoding='utf-8') as f:
        json.dump(toc_data, f, ensure_ascii=False, indent=2)
