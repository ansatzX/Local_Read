"""
Markdown Converter.

This module provides the MarkdownConverter class for converting Intermediate
JSON format documents to Markdown.
"""

from typing import Any, Dict, List, Optional
from pathlib import Path


class MarkdownConverter:
    """
    Converts Intermediate JSON documents to Markdown.

    This class processes an Intermediate JSON document and generates a
    Markdown representation of the content.
    """

    def __init__(
        self,
        intermediate_json: Dict[str, Any],
        include_page_breaks: bool = True,
        include_metadata: bool = True
    ):
        """
        Initialize the MarkdownConverter.

        Args:
            intermediate_json: The Intermediate JSON document to convert.
            include_page_breaks: Whether to include page break markers.
            include_metadata: Whether to include YAML metadata header.
        """
        self.doc = intermediate_json
        self.blocks = self.doc.get("blocks", {})
        self.reading_order = self.doc.get("reading_order", [])
        self.include_page_breaks = include_page_breaks
        self.include_metadata = include_metadata

    def convert(self) -> str:
        """
        Convert the Intermediate JSON document to Markdown.

        Returns:
            A string containing the Markdown representation.
        """
        lines: List[str] = []

        # Add YAML metadata header if enabled
        if self.include_metadata:
            metadata_lines = self._build_metadata_header()
            if metadata_lines:
                lines.extend(metadata_lines)
                lines.append("")  # Blank line after header

        current_page: Optional[int] = None

        for block_id in self.reading_order:
            block = self.blocks.get(block_id, {})
            block_page = block.get("page")

            # Add page break if page changed
            if self.include_page_breaks and current_page is not None and block_page is not None and block_page != current_page:
                lines.append("")
                lines.append("---")
                lines.append("")

            current_page = block_page

            # Convert the block
            block_type = block.get("type", "")
            block_lines = self._convert_block(block)
            if block_lines:
                # Add a blank line between blocks (except between consecutive list items)
                if lines:
                    # Check if previous block was a list and current is also a list - no blank line
                    prev_was_list = lines[-1].startswith(("- ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."))
                    if not (prev_was_list and block_type == "list"):
                        lines.append("")
                lines.extend(block_lines)

        return "\n".join(lines)

    def _build_metadata_header(self) -> List[str]:
        """Build YAML metadata header from document metadata."""
        source = self.doc.get("source", {})
        metadata = self.doc.get("metadata", {})

        if not source and not metadata:
            return []

        lines: List[str] = ["---"]

        # Source information
        if source.get("path"):
            lines.append(f"source_path: {source['path']}")
        if source.get("format"):
            lines.append(f"source_format: {source['format']}")
        if source.get("page_count"):
            lines.append(f"page_count: {source['page_count']}")

        # Document metadata
        if metadata.get("title"):
            lines.append(f"title: {metadata['title']}")
        if metadata.get("author"):
            lines.append(f"author: {metadata['author']}")
        if metadata.get("subject"):
            lines.append(f"subject: {metadata['subject']}")
        if metadata.get("keywords"):
            lines.append(f"keywords: {metadata['keywords']}")
        if metadata.get("created_at"):
            lines.append(f"created_at: {metadata['created_at']}")
        if metadata.get("modified_at"):
            lines.append(f"modified_at: {metadata['modified_at']}")

        lines.append("---")
        return lines

    def _convert_block(self, block: Dict[str, Any]) -> List[str]:
        """Convert a single block to Markdown lines."""
        block_type = block.get("type", "")

        converters = {
            "section": self._convert_section,
            "header": self._convert_section,
            "paragraph": self._convert_paragraph,
            "text": self._convert_paragraph,
            "list": self._convert_list,
            "image": self._convert_image,
            "table": self._convert_table,
            "display_formula": self._convert_display_formula,
            "inline_formula": self._convert_inline_formula,
        }

        converter = converters.get(block_type)
        if converter:
            return converter(block)

        # Unknown block type - try to handle generically
        return self._convert_generic(block)

    def _convert_section(self, block: Dict[str, Any]) -> List[str]:
        """Convert a section/header block."""
        level = block.get("level", 1)
        content = block.get("content", "")
        prefix = "#" * level
        return [f"{prefix} {content}"]

    def _convert_paragraph(self, block: Dict[str, Any]) -> List[str]:
        """Convert a paragraph/text block."""
        content = block.get("content", "")
        return [content] if content else []

    def _convert_list(self, block: Dict[str, Any]) -> List[str]:
        """Convert a list block."""
        items = block.get("items", [])
        ordered = block.get("ordered", False)

        lines: List[str] = []
        for i, item in enumerate(items, 1):
            if ordered:
                lines.append(f"{i}. {item}")
            else:
                lines.append(f"- {item}")

        return lines

    def _convert_image(self, block: Dict[str, Any]) -> List[str]:
        """Convert an image block."""
        path = block.get("path", "")
        caption = block.get("caption", "Image")

        lines: List[str] = []
        if path:
            lines.append(f"![{caption}]({path})")
        elif caption:
            lines.append(f"**{caption}**")

        return lines

    def _convert_table(self, block: Dict[str, Any]) -> List[str]:
        """Convert a table block."""
        lines: List[str] = []

        # Add caption first if available
        if block.get("caption"):
            lines.append(f"**Table:** {block['caption']}")
            lines.append("")

        # Prefer markdown if available
        markdown = block.get("markdown")
        if markdown:
            lines.extend(markdown.split("\n"))

        return lines

    def _convert_display_formula(self, block: Dict[str, Any]) -> List[str]:
        """Convert a display formula block."""
        latex = block.get("latex", "")
        number = block.get("number", "")

        lines: List[str] = []
        if latex:
            lines.append(f"$${latex}$$")
            if number:
                lines.append(f"\\[{number}\\]")

        return lines

    def _convert_inline_formula(self, block: Dict[str, Any]) -> List[str]:
        """Convert an inline formula block."""
        latex = block.get("latex", "")
        if latex:
            return [f"${latex}$"]
        return []

    def _convert_generic(self, block: Dict[str, Any]) -> List[str]:
        """Generic fallback for unknown block types."""
        # Try content field first
        content = block.get("content")
        if content:
            return [str(content)]

        # Try caption
        caption = block.get("caption")
        if caption:
            return [f"**{caption}**"]

        return []

    def save_to_file(self, file_path: str) -> None:
        """
        Save the converted Markdown to a file.

        Args:
            file_path: Path to the output Markdown file.
        """
        markdown = self.convert()
        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
