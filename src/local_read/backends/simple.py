# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
Simple backend implementation using existing converters.
"""

import logging
from pathlib import Path
from typing import Any

from ..converters import (
    CsvConverter,
    DocxConverter,
    HtmlConverter,
    JsonConverter,
    MarkItDownConverter,
    PdfConverter,
    PptxConverter,
    TextConverter,
    XlsxConverter,
    YamlConverter,
    ZipConverter,
)
from ..intermediate_json import IntermediateJSONBuilder
from .base import DocumentBackend

logger = logging.getLogger(__name__)


class SimpleBackend(DocumentBackend):
    """Simple backend using existing converters."""

    @property
    def name(self) -> str:
        return "Simple"

    @property
    def description(self) -> str:
        return "Simple backend using existing converters (no ML models required)"

    @property
    def available(self) -> bool:
        return True

    @property
    def warning(self) -> None:
        return None

    def process(
        self,
        file_path: Path,
        format: str,
        **kwargs
    ) -> dict[str, Any]:
        """Process a document using simple converters."""
        logger.info(f"Processing with Simple backend: {file_path}")

        # Get file size
        try:
            file_size = file_path.stat().st_size
        except (FileNotFoundError, OSError):
            file_size = None

        # Get converter and convert
        kwargs.pop("mineru_engine", None)
        kwargs.pop("mineru_effort", None)
        converter = self._get_converter(format)
        if converter:
            # Pass kwargs to converter (converter is a function)
            result = converter(str(file_path), **kwargs)
            markdown_content = result.text_content
            # Handle images if they were extracted
            if hasattr(result, 'images') and result.images:
                logger.info(f"Extracted {len(result.images)} images")
        else:
            # Fallback to MarkItDownConverter
            result = MarkItDownConverter(str(file_path))
            markdown_content = result.text_content

        if getattr(result, "error", None):
            raise RuntimeError(str(result.error))

        # Prefer explicit converter pagination; fall back to metadata when available.
        page_count = 1
        if result and hasattr(result, 'pagination_info'):
            page_count = result.pagination_info.get('page_count') or 1
        if (
            result
            and page_count == 1
            and hasattr(result, 'metadata')
            and isinstance(result.metadata, dict)
        ):
            page_count = result.metadata.get('pdf_page_count') or result.metadata.get('page_count', 1)

        # Create builder
        builder = IntermediateJSONBuilder(
            source_path=str(file_path.absolute()),
            source_format=format,
            page_count=page_count,
            file_size=file_size
        )

        # Set metadata if available
        if result:
            metadata = {}
            if result.title:
                metadata['title'] = result.title
            if hasattr(result, 'metadata') and result.metadata:
                # Map common metadata fields
                if 'author' in result.metadata:
                    metadata['author'] = str(result.metadata['author'])
                if 'subject' in result.metadata:
                    metadata['subject'] = str(result.metadata['subject'])
                if 'keywords' in result.metadata:
                    metadata['keywords'] = str(result.metadata['keywords'])
                if 'created_at' in result.metadata:
                    metadata['created_at'] = str(result.metadata['created_at'])
                if 'modified_at' in result.metadata:
                    metadata['modified_at'] = str(result.metadata['modified_at'])
            if metadata:
                builder.set_metadata(**metadata)

        # Native PDF text has real page and coordinate provenance. Other
        # converters may supply only a document-wide body: location is unknown.
        native_blocks = getattr(result, "blocks", [])
        for block in native_blocks:
            builder.add_block(**block)
        if not native_blocks and markdown_content:
            builder.add_block(
                type="text", page=None, bbox=None, confidence=None,
                content=markdown_content,
            )

        # Converter sections/tables annotate the same body; do not render them
        # again as additional text blocks.
        for image in getattr(result, "images", []):
            page = image.get("page")
            if format == "pdf" and isinstance(page, int):
                page += 1  # PDF image extractor uses zero-based pages.
            else:
                page = None
            builder.add_block(
                type="image", page=page, bbox=image.get("bbox"), confidence=None,
                path=image.get("saved_path") or image.get("path", ""),
                caption=image.get("description", ""),
            )

        document = builder.build()
        document["annotations"] = {
            "sections": getattr(result, "sections", []),
            "tables": getattr(result, "tables", []),
        }
        document["provenance"] = {
            "page_numbering": "physical_1_based",
            "page_scope": "input_file",
            "unknown_location": None,
        }
        return document

    def _get_converter(self, format: str):
        """Get the appropriate converter for the format."""
        converter_map = {
            "pdf": PdfConverter,
            "word": DocxConverter,
            "excel": XlsxConverter,
            "ppt": PptxConverter,
            "html": HtmlConverter,
            "zip": ZipConverter,
            "text": TextConverter,
            "json": JsonConverter,
            "yaml": YamlConverter,
            "csv": CsvConverter,
        }
        return converter_map.get(format)
