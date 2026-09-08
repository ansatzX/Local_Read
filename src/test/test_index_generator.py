"""
Unit tests for Content Index Generator.

This module contains comprehensive tests for the IndexGenerator class,
including:
- Index generation from Intermediate JSON
- Section extraction and hierarchy
- Table, figure, and formula indexing
- Page information
"""

import pytest
import sys
from pathlib import Path
from typing import Any, Dict

# Import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read.index_generator import IndexGenerator
from local_read.intermediate_json import IntermediateJSONBuilder


class TestIndexGenerator:
    """Tests for IndexGenerator class."""

    def _create_sample_document(self) -> Dict[str, Any]:
        """Helper to create a sample intermediate document."""
        builder = IntermediateJSONBuilder(
            source_path="/test/document.pdf",
            source_format="pdf",
            page_count=3,
            file_size=500000
        )

        builder.set_metadata(
            title="Test Document",
            author="Test Author"
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
            content="This is the introduction."
        )

        builder.add_block(
            type="image",
            page=1,
            bbox=[100, 80, 300, 180],
            path="images/fig1.png",
            caption="Figure 1: System overview"
        )

        # Page 2
        builder.add_block(
            type="section",
            page=2,
            bbox=[10, 10, 200, 30],
            level=1,
            content="Methods"
        )

        builder.add_block(
            type="section",
            page=2,
            bbox=[20, 40, 180, 55],
            level=2,
            content="Data Collection"
        )

        builder.add_block(
            type="table",
            page=2,
            bbox=[50, 70, 250, 170],
            html="<table></table>",
            caption="Table 1: Sample data"
        )

        builder.add_block(
            type="display_formula",
            page=2,
            bbox=[50, 180, 200, 220],
            latex="E = mc^2",
            number="(1)"
        )

        # Page 3
        builder.add_block(
            type="section",
            page=3,
            bbox=[10, 10, 200, 30],
            level=1,
            content="Results"
        )

        builder.add_block(
            type="image",
            page=3,
            bbox=[100, 40, 300, 140],
            path="images/fig2.png",
            caption="Figure 2: Results chart"
        )

        return builder.build()

    def test_generate_index_basic(self):
        """Test that index can be generated from a document."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)
        index = generator.generate()

        # Verify basic structure
        assert "source" in index
        assert "sections" in index
        assert "tables" in index
        assert "figures" in index
        assert "formulas" in index
        assert "pages" in index

        assert index["source"]["path"] == "/test/document.pdf"
        assert index["source"]["format"] == "pdf"
        assert index["source"]["page_count"] == 3

    def test_index_sections(self):
        """Test that sections are correctly indexed with hierarchy."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)
        index = generator.generate()

        sections = index["sections"]
        assert len(sections) == 4  # 3 level-1 + 1 level-2

        # Check first section
        intro = sections[0]
        assert intro["title"] == "Introduction"
        assert intro["level"] == 1
        assert intro["page"] == 1
        assert "id" in intro

        # Check Methods and its subsection
        methods = sections[1]
        assert methods["title"] == "Methods"
        assert methods["level"] == 1
        assert methods["page"] == 2

        data_collection = sections[2]
        assert data_collection["title"] == "Data Collection"
        assert data_collection["level"] == 2
        assert data_collection["page"] == 2
        assert data_collection["parent_id"] == methods["id"]

    def test_index_tables(self):
        """Test that tables are correctly indexed."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)
        index = generator.generate()

        tables = index["tables"]
        assert len(tables) == 1

        table = tables[0]
        assert table["caption"] == "Table 1: Sample data"
        assert table["page"] == 2
        assert "block_id" in table
        assert "id" in table

    def test_index_figures(self):
        """Test that figures/images are correctly indexed."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)
        index = generator.generate()

        figures = index["figures"]
        assert len(figures) == 2

        fig1 = figures[0]
        assert fig1["caption"] == "Figure 1: System overview"
        assert fig1["page"] == 1
        assert fig1["path"] == "images/fig1.png"

        fig2 = figures[1]
        assert fig2["caption"] == "Figure 2: Results chart"
        assert fig2["page"] == 3

    def test_index_formulas(self):
        """Test that formulas are correctly indexed."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)
        index = generator.generate()

        formulas = index["formulas"]
        assert len(formulas) == 1

        formula = formulas[0]
        assert formula["latex"] == "E = mc^2"
        assert formula["number"] == "(1)"
        assert formula["page"] == 2
        assert formula["type"] == "display_formula"

    def test_index_pages(self):
        """Test that page information is correctly indexed."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)
        index = generator.generate()

        pages = index["pages"]
        assert len(pages) == 3

        # Page 1 should have 3 blocks (section, paragraph, image)
        page1 = pages[0]
        assert page1["page"] == 1
        assert len(page1["block_ids"]) == 3

        # Page 2 should have 4 blocks (2 sections, table, formula)
        page2 = pages[1]
        assert page2["page"] == 2
        assert len(page2["block_ids"]) == 4

        # Page 3 should have 2 blocks (section, image)
        page3 = pages[2]
        assert page3["page"] == 3
        assert len(page3["block_ids"]) == 2

    def test_empty_document(self):
        """Test index generation with empty document."""
        builder = IntermediateJSONBuilder(
            source_path="/empty.pdf",
            source_format="pdf",
            page_count=0
        )
        doc = builder.build()

        generator = IndexGenerator(doc)
        index = generator.generate()

        assert len(index["sections"]) == 0
        assert len(index["tables"]) == 0
        assert len(index["figures"]) == 0
        assert len(index["formulas"]) == 0
        assert len(index["pages"]) == 0

    def test_save_index_to_file(self, tmp_path):
        """Test that index can be saved to a JSON file."""
        doc = self._create_sample_document()
        generator = IndexGenerator(doc)

        output_file = tmp_path / "index.json"
        generator.save_to_file(str(output_file))

        assert output_file.exists()

        # Verify we can read it back
        import json
        with open(output_file, 'r') as f:
            loaded_index = json.load(f)

        assert loaded_index["source"]["path"] == "/test/document.pdf"
        assert len(loaded_index["sections"]) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
