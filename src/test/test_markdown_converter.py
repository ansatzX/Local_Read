"""
Unit tests for Markdown Converter.

This module contains comprehensive tests for the MarkdownConverter class,
including:
- Conversion from Intermediate JSON to Markdown
- Handling various block types (text, headers, tables, images, formulas)
- Section hierarchy
- Page breaks
"""

import pytest
import sys
from pathlib import Path
from typing import Any, Dict

# Import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read.markdown_converter import MarkdownConverter
from local_read.intermediate_json import IntermediateJSONBuilder


class TestMarkdownConverter:
    """Tests for MarkdownConverter class."""

    def _create_sample_document(self) -> Dict[str, Any]:
        """Helper to create a sample intermediate document."""
        builder = IntermediateJSONBuilder(
            source_path="/test/document.pdf",
            source_format="pdf",
            page_count=2
        )

        # Page 1
        builder.add_block(
            type="section",
            page=1,
            bbox=[10, 10, 200, 30],
            level=1,
            content="Introduction"
        )

        builder.add_block(
            type="paragraph",
            page=1,
            bbox=[10, 40, 200, 70],
            content="This is the first paragraph with **bold** and *italic* text."
        )

        builder.add_block(
            type="list",
            page=1,
            bbox=[10, 80, 200, 130],
            items=["Item 1", "Item 2", "Item 3"],
            ordered=False
        )

        # Page 2
        builder.add_block(
            type="section",
            page=2,
            bbox=[10, 10, 200, 30],
            level=2,
            content="Subsection"
        )

        builder.add_block(
            type="image",
            page=2,
            bbox=[100, 40, 300, 140],
            path="images/fig1.png",
            caption="Figure 1: Sample image"
        )

        builder.add_block(
            type="table",
            page=2,
            bbox=[50, 150, 250, 250],
            html="<table><tr><th>Header 1</th><th>Header 2</th></tr><tr><td>Cell 1</td><td>Cell 2</td></tr></table>",
            caption="Table 1: Sample table"
        )

        builder.add_block(
            type="display_formula",
            page=2,
            bbox=[50, 260, 200, 300],
            latex="E = mc^2",
            number="(1)"
        )

        return builder.build()

    def test_convert_basic(self):
        """Test that basic conversion works."""
        doc = self._create_sample_document()
        converter = MarkdownConverter(doc)
        markdown = converter.convert()

        # Check that content is present
        assert "# Introduction" in markdown
        assert "This is the first paragraph" in markdown
        assert "## Subsection" in markdown

    def test_convert_headers(self):
        """Test that headers/sections are converted correctly."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )

        builder.add_block(
            type="section",
            page=1,
            bbox=[0, 0, 10, 10],
            level=1,
            content="Level 1"
        )

        builder.add_block(
            type="section",
            page=1,
            bbox=[0, 0, 10, 10],
            level=2,
            content="Level 2"
        )

        builder.add_block(
            type="header",
            page=1,
            bbox=[0, 0, 10, 10],
            level=3,
            content="Level 3"
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        assert "# Level 1" in markdown
        assert "## Level 2" in markdown
        assert "### Level 3" in markdown

    def test_convert_paragraphs(self):
        """Test that paragraphs are converted correctly."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )

        builder.add_block(
            type="paragraph",
            page=1,
            bbox=[0, 0, 10, 10],
            content="First paragraph."
        )

        builder.add_block(
            type="paragraph",
            page=1,
            bbox=[0, 0, 10, 10],
            content="Second paragraph."
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        assert "First paragraph." in markdown
        assert "Second paragraph." in markdown
        # Paragraphs should be separated by blank lines
        assert "First paragraph.\n\nSecond paragraph." in markdown

    def test_convert_lists(self):
        """Test that lists are converted correctly."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )

        # Unordered list
        builder.add_block(
            type="list",
            page=1,
            bbox=[0, 0, 10, 10],
            items=["Apple", "Banana", "Cherry"],
            ordered=False
        )

        # Ordered list
        builder.add_block(
            type="list",
            page=1,
            bbox=[0, 0, 10, 10],
            items=["First", "Second", "Third"],
            ordered=True
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        # Check unordered list
        assert "- Apple" in markdown
        assert "- Banana" in markdown
        assert "- Cherry" in markdown

        # Check ordered list
        assert "1. First" in markdown
        assert "2. Second" in markdown
        assert "3. Third" in markdown

    def test_convert_images(self):
        """Test that images are converted correctly."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )

        builder.add_block(
            type="image",
            page=1,
            bbox=[0, 0, 10, 10],
            path="images/photo.jpg",
            caption="A beautiful sunset"
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        assert "![A beautiful sunset](images/photo.jpg)" in markdown

    def test_convert_tables(self):
        """Test that tables are converted correctly."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )

        # Table with markdown content
        builder.add_block(
            type="table",
            page=1,
            bbox=[0, 0, 10, 10],
            markdown="| A | B |\n|---|---|\n| 1 | 2 |",
            caption="Sample table"
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        assert "| A | B |" in markdown
        assert "| 1 | 2 |" in markdown
        assert "Sample table" in markdown

    def test_convert_formulas(self):
        """Test that formulas are converted correctly."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )

        # Display formula
        builder.add_block(
            type="display_formula",
            page=1,
            bbox=[0, 0, 10, 10],
            latex="E = mc^2",
            number="(1)"
        )

        # Inline formula
        builder.add_block(
            type="inline_formula",
            page=1,
            bbox=[0, 0, 10, 10],
            latex="x + y = z"
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        assert "$$E = mc^2$$" in markdown
        assert "$x + y = z$" in markdown

    def test_page_breaks(self):
        """Test that page breaks are included when enabled."""
        doc = self._create_sample_document()
        converter = MarkdownConverter(doc, include_page_breaks=True)
        markdown = converter.convert()

        assert "---" in markdown  # Page break marker

        # Test without page breaks
        converter_no_breaks = MarkdownConverter(doc, include_page_breaks=False)
        markdown_no_breaks = converter_no_breaks.convert()

        # Should still have content but no page breaks
        assert "Introduction" in markdown_no_breaks
        assert "Subsection" in markdown_no_breaks

    def test_metadata_in_header(self):
        """Test that metadata is included in header when enabled."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=1
        )
        builder.set_metadata(
            title="Test Document",
            author="John Doe",
            created_at="2026-01-01"
        )

        converter = MarkdownConverter(builder.build(), include_metadata=True)
        markdown = converter.convert()

        assert "---" in markdown  # YAML header start/end
        assert "title: Test Document" in markdown
        assert "author: John Doe" in markdown

    def test_save_to_file(self, tmp_path):
        """Test that markdown can be saved to a file."""
        doc = self._create_sample_document()
        converter = MarkdownConverter(doc)

        output_file = tmp_path / "output.md"
        converter.save_to_file(str(output_file))

        assert output_file.exists()

        # Read back and verify
        with open(output_file, 'r') as f:
            content = f.read()

        assert "# Introduction" in content

    def test_empty_document(self):
        """Test conversion with empty document."""
        builder = IntermediateJSONBuilder(
            source_path="/empty.pdf",
            source_format="pdf",
            page_count=0
        )

        converter = MarkdownConverter(builder.build())
        markdown = converter.convert()

        # Should be empty or minimal
        assert len(markdown.strip()) == 0 or "---" in markdown


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
