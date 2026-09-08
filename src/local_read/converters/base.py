import logging
from typing import Any, Union, Optional, Dict, List

from ._compat import (
    mammoth,
    markdownify,
    openpyxl,
    get_column_letter,
    pdfminer,
    pptx,
    MarkItDown,
    fitz,
    BeautifulSoup,
    yaml,
    html,
    _CustomMarkdownify,
)

# Media file extension constants
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
AUDIO_EXTENSIONS = {"wav", "mp3", "m4a"}
VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


class DocumentConverterResult:
    """Document conversion result with enhanced metadata and structure.

    This class encapsulates the result of converting a document to text/markdown format,
    including optional metadata, sections, tables, images, and pagination information.

    Attributes:
        title: Document title (optional, may be None)
        text_content: Converted text/markdown content
        metadata: Additional metadata dict (file size, timestamps, etc.)
        sections: List of extracted sections with headings
        tables: List of extracted table information
        images: List of extracted image information (for PDFs with extract_images=True)
        pagination_info: Pagination details (page count, offsets, etc.)
        processing_time_ms: Processing time in milliseconds (optional)
        error: Error message if conversion failed (optional)
        rendered_pages: List of rendered page information (for PDF rendering)
        extracted_tables: List of extracted table data
        form_fields: List of form field data
        structure: Document structure information
        text_with_coords: List of text with coordinate information

    Example:
        >>> result = DocumentConverterResult(
        ...     title="My Document",
        ...     text_content="# Heading\n\nContent here",
        ...     metadata={"file_size": 12345}
        ... )
        >>> print(result.title)
        My Document
    """

    def __init__(
        self,
        title: Union[str, None] = None,
        text_content: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        sections: Optional[List[Dict[str, Any]]] = None,
        tables: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[Dict[str, Any]]] = None,
        pagination_info: Optional[Dict[str, Any]] = None,
        processing_time_ms: Optional[int] = None,
        error: Optional[str] = None,
        # New fields
        rendered_pages: Optional[List[Dict[str, Any]]] = None,
        extracted_tables: Optional[List[Dict[str, Any]]] = None,
        form_fields: Optional[List[Dict[str, Any]]] = None,
        structure: Optional[Dict[str, Any]] = None,
        text_with_coords: Optional[List[Dict[str, Any]]] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ):
        """Initialize document converter result.

        Args:
            title: Document title (optional)
            text_content: Converted text content
            metadata: Additional metadata (default: empty dict)
            sections: List of document sections (default: empty list)
            tables: List of extracted tables (default: empty list)
            images: List of extracted images (default: empty list)
            pagination_info: Pagination information (default: empty dict)
            processing_time_ms: Processing time in milliseconds (optional)
            error: Error message if failed (optional)
            rendered_pages: List of rendered page information (default: empty list)
            extracted_tables: List of extracted table data (default: empty list)
            form_fields: List of form field data (default: empty list)
            structure: Document structure information (default: empty dict)
            text_with_coords: List of text with coordinate information (default: empty list)
        """
        self.title: Union[str, None] = title
        self.text_content: str = text_content
        self.metadata = metadata or {}
        self.sections = sections or []
        self.tables = tables or []
        self.images = images or []
        self.pagination_info = pagination_info or {}
        self.processing_time_ms = processing_time_ms
        self.error = error
        self.rendered_pages = rendered_pages or []
        self.extracted_tables = extracted_tables or []
        self.form_fields = form_fields or []
        self.structure = structure or {}
        self.text_with_coords = text_with_coords or []
        self.blocks = blocks or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization.

        Returns:
            Dictionary representation of the conversion result.

        Example:
            >>> result = DocumentConverterResult(title="Test", text_content="Content")
            >>> d = result.to_dict()
            >>> d["title"]
            'Test'
        """
        result = {
            "title": self.title,
            "text_content": self.text_content,
            "metadata": self.metadata,
            "sections": self.sections,
            "tables": self.tables,  # Keep for backward compatibility
            "pagination_info": self.pagination_info,
            "blocks": self.blocks,
        }
        # Add new fields only if they exist and are non-empty
        if hasattr(self, 'rendered_pages') and self.rendered_pages:
            result["rendered_pages"] = self.rendered_pages
        if hasattr(self, 'extracted_tables') and self.extracted_tables:
            result["extracted_tables"] = self.extracted_tables
        if hasattr(self, 'form_fields') and self.form_fields:
            result["form_fields"] = self.form_fields
        if hasattr(self, 'structure') and self.structure:
            result["structure"] = self.structure
        if hasattr(self, 'text_with_coords') and self.text_with_coords:
            result["text_with_coords"] = self.text_with_coords
        if self.processing_time_ms is not None:
            result["processing_time_ms"] = self.processing_time_ms
        if self.error is not None:
            result["error"] = self.error
        return result

