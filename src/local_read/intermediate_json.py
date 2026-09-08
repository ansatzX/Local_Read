"""
Intermediate JSON Builder.

This module provides the IntermediateJSONBuilder class for constructing
unified intermediate JSON format documents from various source formats.
"""

from typing import Any, Dict, List, Optional


class IntermediateJSONBuilder:
    """
    A builder class for constructing Intermediate JSON format documents.

    This class provides a fluent interface for adding blocks, setting metadata,
    and building the final JSON document structure.
    """

    def __init__(
        self,
        source_path: str,
        source_format: str,
        page_count: int,
        file_size: Optional[int] = None
    ):
        """
        Initialize the IntermediateJSONBuilder.

        Args:
            source_path: Path to the source file
            source_format: Format of the source file (pdf, docx, etc.)
            page_count: Number of pages in the document
            file_size: Size of the source file in bytes (optional)
        """
        self.source_path = source_path
        self.source_format = source_format
        self.page_count = page_count
        self.file_size = file_size

        self.blocks: Dict[str, Dict[str, Any]] = {}
        self.reading_order: List[str] = []
        self.metadata: Dict[str, Any] = {}
        self._block_counter = 0

    def add_block(
        self,
        type: str,
        page: Optional[int],
        bbox: Optional[List[float]],
        **kwargs
    ) -> str:
        """
        Add a block to the document.

        Args:
            type: Block type (header, paragraph, table, image, etc.)
            page: Page number (1-indexed)
            bbox: Bounding box [x0, y0, x1, y1]
            **kwargs: Additional block properties specific to the block type

        Returns:
            Generated block ID in format 'block_<8 hex chars>'
        """
        # Generate unique block ID using counter
        block_id = f"block_{self._block_counter:08x}"
        self._block_counter += 1

        # Create block data
        block_data: Dict[str, Any] = {
            "type": type,
            "page": page,
            "bbox": bbox.copy() if bbox is not None else None,
        }

        # Add confidence with default 0.9 if not provided
        block_data["confidence"] = kwargs.pop("confidence", 0.9)

        # Add all remaining kwargs
        block_data.update(kwargs)

        # Store the block
        self.blocks[block_id] = block_data

        # Add to reading order
        self.reading_order.append(block_id)

        return block_id

    def set_metadata(self, **kwargs):
        """
        Set document metadata.

        Args:
            **kwargs: Metadata fields to set. Valid fields are:
                title, author, subject, keywords, created_at, modified_at
        """
        valid_fields = {"title", "author", "subject", "keywords", "created_at", "modified_at"}

        for key, value in kwargs.items():
            if key in valid_fields:
                self.metadata[key] = value

    def build(self) -> Dict[str, Any]:
        """
        Build the final Intermediate JSON document.

        Returns:
            Dictionary containing the complete Intermediate JSON document
        """
        # Build source information
        source: Dict[str, Any] = {
            "path": self.source_path,
            "format": self.source_format,
            "page_count": self.page_count,
        }

        if self.file_size is not None:
            source["file_size"] = self.file_size

        # Build the complete document
        document: Dict[str, Any] = {
            "source": source,
            "metadata": self.metadata.copy(),
            "blocks": self.blocks.copy(),
            "reading_order": self.reading_order.copy(),
        }

        return document
