"""
Unit tests for Intermediate JSON Builder.

This module contains comprehensive tests for the IntermediateJSONBuilder class,
including:
- Basic document creation
- Adding various block types (text, table, image, etc.)
- Reading order management
- Metadata handling
- Block ID generation
"""

import pytest
import sys
from pathlib import Path
from typing import Any, Dict, List

# Import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read.intermediate_json import IntermediateJSONBuilder


class TestIntermediateJSONBuilder:
    """Tests for IntermediateJSONBuilder class."""

    def test_create_basic_document(self):
        """Test that basic document can be created with initialization."""
        # Initialize builder
        builder = IntermediateJSONBuilder(
            source_path="/path/to/document.pdf",
            source_format="pdf",
            page_count=10,
            file_size=1024000
        )

        # Build the document
        doc = builder.build()

        # Verify basic structure
        assert doc["source"]["path"] == "/path/to/document.pdf"
        assert doc["source"]["format"] == "pdf"
        assert doc["source"]["page_count"] == 10
        assert doc["source"]["file_size"] == 1024000
        assert "blocks" in doc
        assert "reading_order" in doc
        assert "metadata" in doc
        assert len(doc["blocks"]) == 0
        assert len(doc["reading_order"]) == 0

    def test_add_text_block(self):
        """Test that text blocks can be added to the document."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=5
        )

        # Add a text block
        block_id = builder.add_block(
            type="paragraph",
            page=1,
            bbox=[10.0, 20.0, 100.0, 50.0],
            content="This is a test paragraph.",
            confidence=0.95
        )

        # Verify block ID format
        assert block_id.startswith("block_")
        assert len(block_id) == len("block_") + 8  # 8 hex chars

        # Build and verify
        doc = builder.build()
        assert len(doc["blocks"]) == 1
        assert len(doc["reading_order"]) == 1
        assert doc["reading_order"][0] == block_id

        # Verify block content
        block = doc["blocks"][block_id]
        assert block["type"] == "paragraph"
        assert block["page"] == 1
        assert block["bbox"] == [10.0, 20.0, 100.0, 50.0]
        assert block["content"] == "This is a test paragraph."
        assert block["confidence"] == 0.95

    def test_add_multiple_blocks(self):
        """Test that multiple blocks are added in correct reading order."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=3
        )

        # Add blocks in reading order
        block1 = builder.add_block(
            type="header",
            page=1,
            bbox=[10, 10, 200, 30],
            level=1,
            content="Introduction"
        )

        block2 = builder.add_block(
            type="paragraph",
            page=1,
            bbox=[10, 40, 200, 70],
            content="First paragraph"
        )

        block3 = builder.add_block(
            type="paragraph",
            page=2,
            bbox=[10, 10, 200, 40],
            content="Second page paragraph"
        )

        # Build and verify
        doc = builder.build()
        assert len(doc["blocks"]) == 3
        assert doc["reading_order"] == [block1, block2, block3]

    def test_add_table_block(self):
        """Test that table blocks can be added with HTML and caption."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=5
        )

        block_id = builder.add_block(
            type="table",
            page=2,
            bbox=[50, 50, 300, 200],
            html="<table><tr><td>Cell 1</td><td>Cell 2</td></tr></table>",
            caption="Sample table caption"
        )

        doc = builder.build()
        block = doc["blocks"][block_id]

        assert block["type"] == "table"
        assert block["page"] == 2
        assert block["bbox"] == [50, 50, 300, 200]
        assert block["html"] == "<table><tr><td>Cell 1</td><td>Cell 2</td></tr></table>"
        assert block["caption"] == "Sample table caption"
        assert block["confidence"] == 0.9  # default

    def test_add_image_block(self):
        """Test that image blocks can be added with all properties."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=5
        )

        block_id = builder.add_block(
            type="image",
            page=3,
            bbox=[100, 100, 400, 300],
            path="/output/images/page3_img1.png",
            format="png",
            width=300,
            height=200,
            caption="Figure 1: System architecture"
        )

        doc = builder.build()
        block = doc["blocks"][block_id]

        assert block["type"] == "image"
        assert block["page"] == 3
        assert block["bbox"] == [100, 100, 400, 300]
        assert block["path"] == "/output/images/page3_img1.png"
        assert block["format"] == "png"
        assert block["width"] == 300
        assert block["height"] == 200
        assert block["caption"] == "Figure 1: System architecture"

    def test_set_metadata(self):
        """Test that document metadata can be set."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=10
        )

        builder.set_metadata(
            title="Test Document",
            author="John Doe",
            subject="Testing",
            keywords=["test", "json", "builder"],
            created_at="2026-01-01T00:00:00Z",
            modified_at="2026-04-10T12:34:56Z"
        )

        doc = builder.build()
        metadata = doc["metadata"]

        assert metadata["title"] == "Test Document"
        assert metadata["author"] == "John Doe"
        assert metadata["subject"] == "Testing"
        assert metadata["keywords"] == ["test", "json", "builder"]
        assert metadata["created_at"] == "2026-01-01T00:00:00Z"
        assert metadata["modified_at"] == "2026-04-10T12:34:56Z"

    def test_set_metadata_partial(self):
        """Test that metadata can be set partially."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=10
        )

        builder.set_metadata(
            title="Only Title",
            author="Only Author"
        )

        doc = builder.build()
        metadata = doc["metadata"]

        assert metadata["title"] == "Only Title"
        assert metadata["author"] == "Only Author"
        assert "subject" not in metadata
        assert "keywords" not in metadata

    def test_formula_blocks(self):
        """Test that formula blocks (display and inline) can be added."""
        builder = IntermediateJSONBuilder(
            source_path="/math.pdf",
            source_format="pdf",
            page_count=5
        )

        # Display formula
        display_id = builder.add_block(
            type="display_formula",
            page=1,
            bbox=[10, 100, 200, 150],
            latex="E = mc^2",
            number="(1)"
        )

        # Inline formula
        inline_id = builder.add_block(
            type="inline_formula",
            page=1,
            bbox=[50, 50, 80, 60],
            latex="x^2 + y^2 = z^2"
        )

        doc = builder.build()

        display_block = doc["blocks"][display_id]
        assert display_block["type"] == "display_formula"
        assert display_block["latex"] == "E = mc^2"
        assert display_block["number"] == "(1)"

        inline_block = doc["blocks"][inline_id]
        assert inline_block["type"] == "inline_formula"
        assert inline_block["latex"] == "x^2 + y^2 = z^2"

    def test_section_block(self):
        """Test that section blocks can be added with level."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=10
        )

        block_id = builder.add_block(
            type="section",
            page=1,
            bbox=[10, 20, 300, 40],
            level=2,
            content="Subsection Title"
        )

        doc = builder.build()
        block = doc["blocks"][block_id]

        assert block["type"] == "section"
        assert block["level"] == 2
        assert block["content"] == "Subsection Title"

    def test_unique_block_ids(self):
        """Test that each block gets a unique ID."""
        builder = IntermediateJSONBuilder(
            source_path="/test.pdf",
            source_format="pdf",
            page_count=5
        )

        block_ids = set()
        for i in range(10):
            block_id = builder.add_block(
                type="paragraph",
                page=1,
                bbox=[10, 10*i, 100, 10*i + 20],
                content=f"Paragraph {i}"
            )
            assert block_id not in block_ids
            block_ids.add(block_id)

        assert len(block_ids) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])