# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
Local Read MCP Server

A Model Context Protocol server for processing various file formats.
Converts documents to markdown/text without requiring external APIs.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ..backends import BackendType, get_registry
from ..config import get_config as _get_config
from ..converters.pdf import evaluate_pdf_text_quality, get_pdf_quality_warning
from ..output_manager import OutputManager
from ..index_generator import IndexGenerator
from ..markdown_converter import MarkdownConverter
from .orchestrator import (
    merge_chunk_intermediates,
    merge_chunk_markdowns,
    plan_chunks,
    process_and_save,
    resolve_page_range,
    save_structural_toc,
)
from .vision import analyze_image_with_config, save_analysis_markdown
from .vision_batch import analyze_images_batch_with_cache

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("local_read_mcp-server")

# Initialize config to check if vision features should be enabled
_config = _get_config()
VISION_ENABLED = _config.vision_enabled

if VISION_ENABLED:
    logger.info(f"Vision features ENABLED (model: {_config.model})")
else:
    logger.info("Vision features DISABLED - configure VISION_API_KEY or OPENAI_API_KEY in .env file to enable")


_FORMAT_BY_EXTENSION: dict[str, str] = {
    # Text formats
    ".txt": "text",
    ".md": "text",
    ".py": "text",
    ".sh": "text",
    ".log": "text",
    ".rst": "text",
    ".json": "json",
    ".csv": "csv",
    ".yaml": "yaml",
    ".yml": "yaml",
    # Binary/document formats
    ".pdf": "pdf",
    ".docx": "word",
    ".doc": "word",
    ".xlsx": "excel",
    ".xls": "excel",
    ".pptx": "ppt",
    ".ppt": "ppt",
    ".html": "html",
    ".htm": "html",
    ".zip": "zip",
}

def detect_format(file_path: str) -> str | None:
    """Detect file format from extension.

    Returns:
        Format string or None for unknown (use markitdown fallback)
    """
    ext = os.path.splitext(file_path)[1].lower()

    return _FORMAT_BY_EXTENSION.get(ext)


_IMAGE_NAME_PATTERN = re.compile(r"page(\d+)_img(\d+)", re.IGNORECASE)
_FIGURE_REF_PATTERN = re.compile(r"\bFigure\s+(\d+)\b", re.IGNORECASE)


def _build_image_metadata(
    image_files: list[Path],
    phys_start: int,
    phys_end: int,
    chunk_index: int | None = None,
    chunk_title: str | None = None,
) -> list[dict[str, Any]]:
    """Build image metadata from extracted file paths."""
    metadata: list[dict[str, Any]] = []
    for image_path in sorted(image_files, key=lambda p: p.name):
        item: dict[str, Any] = {
            "path": str(image_path),
            "phys_start": phys_start,
            "phys_end": phys_end,
        }
        if chunk_index is not None:
            item["chunk_index"] = chunk_index
        if chunk_title:
            item["chunk_title"] = chunk_title

        match = _IMAGE_NAME_PATTERN.search(image_path.name)
        if match:
            page_in_chunk = int(match.group(1))
            image_index_in_page = int(match.group(2))
            item["page_in_chunk"] = page_in_chunk
            item["image_index_in_page"] = image_index_in_page
            # Convert 0-based physical page index to human-readable 1-based page number.
            item["estimated_pdf_page"] = phys_start + page_in_chunk + 1

        metadata.append(item)

    return metadata


def _extract_figure_references(markdown: str) -> list[int]:
    """Extract unique figure numbers referenced in markdown text."""
    figure_numbers = {int(m.group(1)) for m in _FIGURE_REF_PATTERN.finditer(markdown or "")}
    return sorted(figure_numbers)


if VISION_ENABLED:
    @mcp.tool()
    async def analyze_image(
        image_path: str,
        question: str = "Describe this image in detail. What type of content is it?",
    ) -> dict[str, Any]:
        """Analyze an image using OpenAI-compatible vision API and save result to .local_read_mcp/analysis/.

        Args:
            image_path: Path to the image file to analyze
            question: Question to ask about the image

        Returns:
            Dict with analysis result and saved file path

        Environment Variables (.env):
            VISION_API_KEY: Your API key (or OPENAI_API_KEY)
            VISION_BASE_URL: API base URL (or OPENAI_BASE_URL)
            VISION_MODEL: Model name (or OPENAI_VISION_MODEL, default: gpt-4o)
            VISION_MAX_IMAGE_SIZE_MB: Max image size in MB (default: 20)
        """
        result = await analyze_image_with_config(
            image_path=image_path,
            question=question,
            api_key=_config.api_key,
            base_url=_config.base_url,
            model=_config.model,
            max_size_mb=_config.vision_max_image_size_mb,
        )
        if not result.get("success"):
            return result

        result_text = result["analysis"]
        result_path = save_analysis_markdown(
            image_path=image_path,
            question=question,
            result_text=result_text,
        )

        return {
            "success": True,
            "analysis": result_text,
            "saved_path": str(result_path),
        }

    @mcp.tool()
    async def analyze_images_batch(
        image_paths: list[str],
        question: str = "Describe this image in detail. What type of content is it?",
        batch_size: int = 6,
    ) -> dict[str, Any]:
        """Analyze images in small batches with content-hash cache."""
        return await analyze_images_batch_with_cache(
            image_paths=image_paths,
            question=question,
            batch_size=batch_size,
            api_key=_config.api_key,
            base_url=_config.base_url,
            model=_config.model,
            max_size_mb=_config.vision_max_image_size_mb,
        )









def _fallback_to_simple(registry, backend_instance, warnings, failure):
    """Return Simple backend if the current backend failed, else None."""
    if backend_instance.name == 'Simple':
        return None
    simple = registry.get(BackendType.SIMPLE)
    if simple is None:
        return None
    warnings.append(
        f"{backend_instance.name} failed: {failure}. Falling back to Simple backend."
    )
    return simple


@mcp.tool()
async def process_binary_file(
    file_path: str,
    format: str | None = None,
    backend: str = "auto",
    # Page range control
    chapter_split: bool | str | int = "auto",
    start_page: int | None = None,
    end_page: int | None = None,
    page_batch_size: int = 64,
    page_range_mode: str = "physical",
    strict_page_range: bool = False,
    enable_toc_auto_fallback: bool = False,
    toc_confidence_threshold: float = 0.55,
    fail_on_unreadable: bool = False,
    skip_quality_check: bool = False,
    # PDF-specific
    extract_images: bool | None = None,
    render_images: bool = False,
    render_dpi: int = 200,
    render_format: str = "png",
    extract_forms: bool = False,
    inspect_struct: bool = False,
    include_coords: bool = False,
) -> dict[str, Any]:
    """MUST use this tool for ANY binary/document file before reading it.

    This includes PDF, Word, Excel, PowerPoint, HTML, ZIP, images, and any
    file that is not plain text. The built-in Read tool cannot handle these
    formats properly; processing them through this tool first is required.

    Results are saved in .local_read_mcp/<file>_<timestamp>/
    with intermediate.json, output.md and index.json.
    For large PDFs, chapter_split detects sections and processes each chunk
    independently, then merges the results.

    Args:
        file_path: Path to the file to process.
        format: Override auto-detected format.
        backend: Backend (auto/simple/vlm-hybrid). Default: auto.
        chapter_split: "auto" (split >30p), "chapter", N (fixed pages), False (off).
        start_page: Inclusive 0-based start page. In `physical` mode this is a physical page
            index. In `logical` mode (PDF only) this is a logical page number mapped to a
            physical index before chunking.
        end_page: Inclusive end page. In `physical` mode this is a physical 0-based index.
            In `logical` mode (PDF only) this is a logical page number mapped to physical.
            `None` means open-ended (through the last page).
        page_batch_size: Pages per batch (default: 64).
        page_range_mode: `physical` or `logical` (case-insensitive). Non-PDF inputs use
            physical semantics.
        strict_page_range: Disable chapter splitting and process only resolved span.
        enable_toc_auto_fallback: Enable TOC auto fallback behavior.
        toc_confidence_threshold: TOC confidence threshold.
        fail_on_unreadable: Fail when unreadable segments are encountered.
        skip_quality_check: Skip quality checks in processing pipeline.
        extract_images: Extract images from PDF (auto if vision configured).
        render_images: Render PDF pages to images.
        render_dpi: Render DPI (default: 200).
        render_format: png or jpeg (default: png).
        extract_forms: Extract PDF form fields.
        inspect_struct: Get PDF structure metadata.
        include_coords: Include text with bounding boxes.
    """
    # ── 1. Format detection ──────────────────────────────────────
    if format is None:
        format = detect_format(file_path)
    if format is None:
        format = "text"

    # Auto-enable extract_images for PDF if vision is configured
    if format == "pdf" and extract_images is None:
        extract_images = bool(VISION_ENABLED)

    # ── 2. Backend selection ─────────────────────────────────────
    registry = get_registry()
    try:
        backend_type = BackendType(backend)
    except ValueError:
        backend_type = BackendType.AUTO

    if backend_type == BackendType.AUTO:
        backend_instance = registry.select_best(format)
    else:
        backend_instance = registry.get(backend_type)

    if backend_instance is None:
        backend_instance = registry.get(BackendType.SIMPLE)

    warnings: list[str] = []
    if backend_instance.warning:
        warnings.append(backend_instance.warning)

    if not backend_instance.supports_format(format):
        raise ValueError(
            f"Backend '{backend_instance.name}' does not support format '{format}'"
        )

    if fail_on_unreadable or skip_quality_check:
        warnings.append(
            "Reliability controls are accepted but enforced in later phases; current behavior remains additive-only."
        )

    normalized_page_range_mode = (page_range_mode or "physical").lower()
    if normalized_page_range_mode not in {"physical", "logical"}:
        normalized_page_range_mode = "physical"

    additive_fields: dict[str, Any] = {
        "warnings": warnings,
        "quality_state": "not_evaluated",
        "quality_metrics": {},
        "requires_ocr": False,
        "toc_confidence": None,
        "toc_resolution_mode": "not_evaluated",
        "toc_offset": None,
        "toc_evidence_pages": [],
        "resolved_start_page": start_page,
        "resolved_end_page": end_page,
        "resolved_page_map": {
            "mode": normalized_page_range_mode,
            "strategy": "identity",
            "requested": {"start_page": start_page, "end_page": end_page},
            "resolved": {"start_page": start_page, "end_page": end_page},
        },
    }

    def _apply_additive_defaults(payload: dict[str, Any]) -> None:
        existing_warnings = payload.get("warnings")
        if isinstance(existing_warnings, list):
            for warning in warnings:
                if warning not in existing_warnings:
                    existing_warnings.append(warning)
        else:
            payload["warnings"] = list(warnings)
        payload.setdefault("quality_state", additive_fields["quality_state"])
        payload.setdefault("quality_metrics", additive_fields["quality_metrics"])
        payload.setdefault("requires_ocr", additive_fields["requires_ocr"])
        payload.setdefault("toc_confidence", additive_fields["toc_confidence"])
        payload.setdefault("toc_resolution_mode", additive_fields["toc_resolution_mode"])
        payload.setdefault("toc_offset", additive_fields["toc_offset"])
        payload.setdefault("toc_evidence_pages", additive_fields["toc_evidence_pages"])
        payload.setdefault("resolved_start_page", additive_fields["resolved_start_page"])
        payload.setdefault("resolved_end_page", additive_fields["resolved_end_page"])
        payload.setdefault("resolved_page_map", additive_fields["resolved_page_map"])

    def _extract_quality_text_from_intermediate(intermediate: Any) -> tuple[str, bool]:
        """Prefer raw extracted block text from intermediate output for quality scoring."""
        if not isinstance(intermediate, dict):
            return "", False

        blocks = intermediate.get("blocks")
        if not isinstance(blocks, dict):
            return "", True

        parts: list[str] = []
        reading_order = intermediate.get("reading_order")
        if isinstance(reading_order, list):
            for block_id in reading_order:
                block = blocks.get(block_id)
                if not isinstance(block, dict):
                    continue
                content = block.get("content")
                if isinstance(content, str):
                    parts.append(content)
        else:
            for block in blocks.values():
                if not isinstance(block, dict):
                    continue
                content = block.get("content")
                if isinstance(content, str):
                    parts.append(content)

        return "\n".join(parts), True

    def _apply_pdf_quality(
        payload: dict[str, Any],
        page_count: int | None,
        *,
        intermediate: dict[str, Any] | None = None,
        fallback_text: str = "",
    ) -> None:
        if format != "pdf":
            return

        existing_state = payload.get("quality_state")
        existing_metrics = payload.get("quality_metrics")
        if existing_state in {"ok", "warn", "unreadable"}:
            if isinstance(existing_metrics, dict):
                payload["quality_metrics"] = existing_metrics
            current_requires_ocr = payload.get("requires_ocr")
            if isinstance(current_requires_ocr, bool):
                payload["requires_ocr"] = current_requires_ocr
            else:
                payload["requires_ocr"] = existing_state == "unreadable"
            warning_text = payload.get("quality_warning")
            if not isinstance(warning_text, str) or not warning_text:
                warning_text = get_pdf_quality_warning(existing_state)
        else:
            intermediate_obj = intermediate if isinstance(intermediate, dict) else payload.get("intermediate")
            metadata = intermediate_obj.get("metadata", {}) if isinstance(intermediate_obj, dict) else {}
            metadata_state = metadata.get("quality_state") if isinstance(metadata, dict) else None
            metadata_metrics = metadata.get("quality_metrics") if isinstance(metadata, dict) else None
            metadata_requires_ocr = metadata.get("requires_ocr") if isinstance(metadata, dict) else None
            metadata_warning = metadata.get("quality_warning") if isinstance(metadata, dict) else None
            metadata_has_quality = (
                metadata_state in {"ok", "warn", "unreadable"}
                or isinstance(metadata_metrics, dict)
                or isinstance(metadata_requires_ocr, bool)
            )

            if metadata_has_quality:
                if metadata_state in {"ok", "warn", "unreadable"}:
                    payload["quality_state"] = metadata_state
                if isinstance(metadata_metrics, dict):
                    payload["quality_metrics"] = metadata_metrics
                if isinstance(metadata_requires_ocr, bool):
                    payload["requires_ocr"] = metadata_requires_ocr
                elif metadata_state in {"ok", "warn", "unreadable"}:
                    payload["requires_ocr"] = metadata_state == "unreadable"
                warning_text = metadata_warning if isinstance(metadata_warning, str) and metadata_warning else None
                if not warning_text and metadata_state in {"warn", "unreadable"}:
                    warning_text = get_pdf_quality_warning(metadata_state)
            else:
                raw_text, has_raw_source = _extract_quality_text_from_intermediate(intermediate_obj)
                quality_text = raw_text if has_raw_source else str(fallback_text or "")
                quality = evaluate_pdf_text_quality(quality_text, page_count)
                payload["quality_state"] = quality["quality_state"]
                payload["quality_metrics"] = quality["quality_metrics"]
                payload["requires_ocr"] = quality["requires_ocr"]
                warning_text = quality.get("quality_warning")

        if warning_text:
            existing_warnings = payload.get("warnings")
            if not isinstance(existing_warnings, list):
                existing_warnings = []
                payload["warnings"] = existing_warnings
            if warning_text not in existing_warnings:
                existing_warnings.append(warning_text)

    # ── 3. Resolve page range and plan chunks (segmenter integration) ──
    resolved_start_page, resolved_end_page, resolved_page_map = resolve_page_range(
        file_path=file_path,
        format=format,
        start_page=start_page,
        end_page=end_page,
        page_range_mode=normalized_page_range_mode,
    )
    additive_fields["resolved_start_page"] = resolved_start_page
    additive_fields["resolved_end_page"] = resolved_end_page
    additive_fields["resolved_page_map"] = resolved_page_map

    effective_start_page = start_page
    effective_end_page = end_page
    effective_chapter_split = chapter_split
    if normalized_page_range_mode == "logical":
        effective_start_page = resolved_start_page
        effective_end_page = resolved_end_page
    if strict_page_range:
        effective_chapter_split = False
        effective_start_page = resolved_start_page
        effective_end_page = resolved_end_page

    chunks_result = plan_chunks(
        file_path=file_path,
        format=format,
        backend_name=backend_instance.name,
        chapter_split=effective_chapter_split,
        start_page=effective_start_page,
        end_page=effective_end_page,
        page_batch_size=page_batch_size,
        enable_toc_auto_fallback=enable_toc_auto_fallback,
        toc_confidence_threshold=toc_confidence_threshold,
        return_diagnostics=True,
    )
    chunk_diagnostics: dict[str, Any] = {
        "mode": "not_evaluated",
        "confidence": None,
        "offset": None,
        "evidence_pages": [],
    }
    if isinstance(chunks_result, tuple) and len(chunks_result) == 2:
        chunks, planned_diagnostics = chunks_result
        if isinstance(planned_diagnostics, dict):
            chunk_diagnostics.update(planned_diagnostics)
    else:
        chunks = chunks_result

    additive_fields["toc_confidence"] = chunk_diagnostics.get("confidence")
    additive_fields["toc_resolution_mode"] = str(chunk_diagnostics.get("mode", "not_evaluated"))
    additive_fields["toc_offset"] = chunk_diagnostics.get("offset")
    evidence_pages = chunk_diagnostics.get("evidence_pages")
    additive_fields["toc_evidence_pages"] = evidence_pages if isinstance(evidence_pages, list) else []
    fallback_reason = chunk_diagnostics.get("fallback_reason")
    if isinstance(fallback_reason, str) and fallback_reason:
        warnings.append(fallback_reason)

    # ── 4. Create output directory ───────────────────────────────
    output_manager = OutputManager()
    output_path = output_manager.create_output_dir(file_path)
    images_dir = output_path / "images"

    # ── 5. Build backend kwargs ──────────────────────────────────
    backend_kwargs: dict[str, Any] = {}
    if format == "pdf":
        backend_kwargs["extract_images"] = extract_images
        backend_kwargs["images_output_dir"] = str(images_dir)
        backend_kwargs["render_images"] = render_images
        backend_kwargs["render_dpi"] = render_dpi
        backend_kwargs["render_format"] = render_format
        backend_kwargs["extract_forms"] = extract_forms
        backend_kwargs["inspect_struct"] = inspect_struct
        backend_kwargs["include_coords"] = include_coords

    # ── 6. Process ───────────────────────────────────────────────
    try:
        if len(chunks) == 1:
            # Single-chunk: process in-place, with fallback to Simple
            effective_backend = backend_instance
            try:
                result = process_and_save(
                    file_path=file_path,
                    backend=effective_backend,
                    format=format,
                    output_path=output_path,
                    images_dir=images_dir,
                    chunk=chunks[0],
                    backend_kwargs=backend_kwargs,
                )
            except Exception as e:
                fallback = _fallback_to_simple(registry, backend_instance, warnings, str(e))
                if fallback is None:
                    raise
                effective_backend = fallback
                result = process_and_save(
                    file_path=file_path,
                    backend=effective_backend,
                    format=format,
                    output_path=output_path,
                    images_dir=images_dir,
                    chunk=chunks[0],
                    backend_kwargs=backend_kwargs,
                )
            result["success"] = True
            result["backend_used"] = effective_backend.name
            result["output_directory"] = str(output_path)
            result["files"] = {
                "intermediate_json": str(result["intermediate_path"]),
                "markdown": str(result["markdown_path"]),
                "index_json": str(result["index_path"]),
            }
            if "image_files" in result:
                result["files"]["images"] = str(result["image_files"][0].parent)
                image_metadata = _build_image_metadata(
                    result["image_files"],
                    result.get("phys_start", 0),
                    result.get("phys_end", 0),
                )
                result["image_count"] = len(image_metadata)
                result["image_metadata"] = image_metadata
            figure_refs = _extract_figure_references(result.get("markdown_content", ""))
            result["figure_reference_count"] = len(figure_refs)
            result["figure_references"] = figure_refs
            page_count = None
            intermediate = result.get("intermediate")
            if isinstance(intermediate, dict):
                page_count = intermediate.get("source", {}).get("page_count")
            if page_count is None:
                try:
                    page_count = max(1, int(result.get("phys_end", 0)) - int(result.get("phys_start", 0)) + 1)
                except Exception:
                    page_count = 1
            _apply_pdf_quality(
                result,
                page_count,
                intermediate=intermediate if isinstance(intermediate, dict) else None,
                fallback_text=result.get("markdown_content", ""),
            )
            _apply_additive_defaults(result)
            return result

        # Multi-chunk: process each chunk independently, then merge
        chunk_results: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            chunk_dir = output_path / f"chunk_{idx + 1:04d}"
            chunk_dir.mkdir(exist_ok=True)
            chunk_backend_kwargs = dict(backend_kwargs)
            if format == "pdf":
                chunk_backend_kwargs["images_output_dir"] = str(chunk_dir / "images")
            try:
                cr = process_and_save(
                    file_path=file_path,
                    backend=backend_instance,
                    format=format,
                    output_path=chunk_dir,
                    images_dir=chunk_dir / "images",
                    chunk=chunk,
                    backend_kwargs=chunk_backend_kwargs,
                )
                chunk_results.append(cr)
            except Exception as e:
                fallback = _fallback_to_simple(registry, backend_instance, warnings, str(e))
                if fallback is not None:
                    try:
                        cr = process_and_save(
                            file_path=file_path,
                            backend=fallback,
                            format=format,
                            output_path=chunk_dir,
                            images_dir=chunk_dir / "images",
                            chunk=chunk,
                            backend_kwargs=chunk_backend_kwargs,
                        )
                        chunk_results.append(cr)
                        continue
                    except Exception as e2:
                        logger.error("Chunk %d (%s) fallback also failed: %s", idx + 1, chunk.title, e2)
                logger.error("Chunk %d (%s) failed: %s", idx + 1, chunk.title, e)
                chunk_results.append({
                    "error": str(e),
                    "title": chunk.title,
                    "phys_start": chunk.phys_start,
                    "phys_end": chunk.phys_end,
                })

        # Merge and save structural TOC
        save_structural_toc(output_path, chunks)

        # Merge chunk markdowns into a single output.md
        merged_md = merge_chunk_markdowns(chunk_results)
        merged_md_path = output_path / "output.md"
        if merged_md:
            with open(merged_md_path, 'w', encoding='utf-8') as f:
                f.write(merged_md)

        succeeded = [cr for cr in chunk_results if "error" not in cr]

        # Build top-level intermediate.json from chunk intermediates
        merged_intermediate = merge_chunk_intermediates(file_path, format, succeeded)
        intermediate_path = output_path / "intermediate.json"
        with open(intermediate_path, 'w', encoding='utf-8') as f:
            json.dump(merged_intermediate, f, ensure_ascii=False, indent=2)

        # Build top-level index.json
        index_generator = IndexGenerator(merged_intermediate)
        index_path = output_path / "index.json"
        index_generator.save_to_file(str(index_path))

        chunk_files = []
        image_metadata_all: list[dict[str, Any]] = []
        image_dirs: set[str] = set()
        linked_image_paths: list[str] = []
        for cr in chunk_results:
            chunk_index = len(chunk_files) + 1
            info = {"title": cr.get("title", ""), "phys_start": cr.get("phys_start"), "phys_end": cr.get("phys_end")}
            if "error" in cr:
                info["error"] = cr["error"]
            else:
                info["intermediate_json"] = str(cr["intermediate_path"])
                info["markdown"] = str(cr["markdown_path"])
                image_files = cr.get("image_files", [])
                if image_files:
                    sorted_image_files = sorted(image_files, key=lambda p: p.name)
                    chunk_image_metadata = _build_image_metadata(
                        sorted_image_files,
                        cr.get("phys_start", 0),
                        cr.get("phys_end", 0),
                        chunk_index=chunk_index,
                        chunk_title=cr.get("title", ""),
                    )
                    # Gather all chunk images to top-level images/ using symlinks (no copy).
                    images_dir.mkdir(parents=True, exist_ok=True)
                    for image_idx, image_path in enumerate(sorted_image_files, start=1):
                        link_name = f"chunk-{chunk_index}-images-{image_idx}{image_path.suffix}"
                        link_path = images_dir / link_name
                        try:
                            if link_path.exists() or link_path.is_symlink():
                                link_path.unlink()
                            os.symlink(str(image_path.resolve()), str(link_path))
                            linked_image_paths.append(str(link_path))
                            if image_idx - 1 < len(chunk_image_metadata):
                                chunk_image_metadata[image_idx - 1]["linked_path"] = str(link_path)
                        except OSError as e:
                            warnings.append(f"Failed to link image '{image_path}' -> '{link_path}': {e}")

                    info["images"] = str(sorted_image_files[0].parent)
                    info["image_count"] = len(chunk_image_metadata)
                    image_metadata_all.extend(chunk_image_metadata)
                    image_dirs.add(str(sorted_image_files[0].parent))
            chunk_files.append(info)

        files_result: dict[str, Any] = {
            "intermediate_json": str(intermediate_path),
            "markdown": str(merged_md_path) if merged_md else None,
            "merged_markdown": str(merged_md_path) if merged_md else None,
            "index_json": str(index_path),
            "structural_toc": str(output_path / "structural_toc.json") if (output_path / "structural_toc.json").exists() else None,
            "chunks": chunk_files,
        }
        if linked_image_paths:
            files_result["images"] = str(images_dir)
            files_result["linked_images"] = linked_image_paths
        elif image_dirs:
            files_result["images"] = sorted(image_dirs)

        result_payload: dict[str, Any] = {
            "success": True,
            "output_directory": str(output_path),
            "backend_used": backend_instance.name,
            "chunk_count": len(chunks),
            "files": files_result,
        }
        merged_page_count = None
        if isinstance(merged_intermediate, dict):
            merged_page_count = merged_intermediate.get("source", {}).get("page_count")
        result_payload["markdown_content"] = merged_md
        _apply_pdf_quality(
            result_payload,
            merged_page_count,
            intermediate=merged_intermediate if isinstance(merged_intermediate, dict) else None,
            fallback_text=merged_md,
        )
        result_payload.pop("markdown_content", None)
        _apply_additive_defaults(result_payload)
        if image_metadata_all:
            result_payload["image_count"] = len(image_metadata_all)
            result_payload["image_metadata"] = image_metadata_all
        figure_refs = _extract_figure_references(merged_md)
        result_payload["figure_reference_count"] = len(figure_refs)
        result_payload["figure_references"] = figure_refs
        return result_payload

    except Exception as e:
        logger.error("Processing failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "backend_used": backend_instance.name,
            "warnings": warnings if "warnings" in locals() else [],
            "quality_state": "not_evaluated",
            "quality_metrics": {},
            "requires_ocr": False,
            "toc_confidence": None,
            "toc_resolution_mode": "not_evaluated",
            "toc_offset": None,
            "toc_evidence_pages": [],
            "resolved_start_page": additive_fields.get("resolved_start_page"),
            "resolved_end_page": additive_fields.get("resolved_end_page"),
            "resolved_page_map": additive_fields.get("resolved_page_map"),
        }


def main():
    """Main entry point for running MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Local Read MCP Server - Document processing tools")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport method: 'stdio' or 'http' (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to use when running with HTTP transport (default: 8080)",
    )
    parser.add_argument(
        "--path",
        type=str,
        default="/mcp",
        help="URL path to use when running with HTTP transport (default: /mcp)",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", port=args.port, path=args.path)


if __name__ == "__main__":
    main()
