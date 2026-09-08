"""
Content Index Generator.

This module provides the IndexGenerator class for generating content indexes
from Intermediate JSON format documents. The index includes sections, tables,
figures, formulas, and page information.
"""

import json
import secrets
from typing import Any, Dict, List, Optional
from pathlib import Path


class IndexGenerator:
    """
    Generates content indexes from Intermediate JSON documents.

    This class processes an Intermediate JSON document and creates a structured
    index containing sections, tables, figures, formulas, and page information.
    """

    def __init__(self, intermediate_json: Dict[str, Any]):
        """
        Initialize the IndexGenerator.

        Args:
            intermediate_json: The Intermediate JSON document to process.
        """
        self.doc = intermediate_json
        self.blocks = self.doc.get("blocks", {})
        self.reading_order = self.doc.get("reading_order", [])

    def _generate_id(self) -> str:
        """Generate a unique ID for index entries."""
        return f"idx_{secrets.token_hex(8)}"

    def generate(self) -> Dict[str, Any]:
        """
        Generate the content index.

        Returns:
            A dictionary containing the complete content index.
        """
        index: Dict[str, Any] = {
            "source": self._extract_source(),
            "sections": self._extract_sections(),
            "tables": self._extract_tables(),
            "figures": self._extract_figures(),
            "formulas": self._extract_formulas(),
            "pages": self._extract_pages(),
            "unlocated_block_ids": [key for key in self.reading_order
                                    if not isinstance(self.blocks.get(key, {}).get("page"), int)],
        }
        return index

    def _extract_source(self) -> Dict[str, Any]:
        """Extract source information from the document."""
        source = self.doc.get("source", {}).copy()
        return source

    def _extract_sections(self) -> List[Dict[str, Any]]:
        """
        Extract sections from the document with hierarchy information.

        Returns:
            List of section entries with title, level, page, and parent info.
        """
        sections: List[Dict[str, Any]] = []
        section_stack: List[Dict[str, Any]] = []

        entries = [(key, self.blocks.get(key, {})) for key in self.reading_order]
        entries.extend((None, {**item, "type": "section", "page": None})
                       for item in self.doc.get("annotations", {}).get("sections", []))
        for block_id, block in entries:
            if block.get("type") in ("section", "header"):
                level = block.get("level", 1)
                section_entry: Dict[str, Any] = {
                    "id": self._generate_id(),
                    "block_id": block_id,
                    "title": block.get("title") or block.get("content", ""),
                    "level": level,
                    "page": block.get("page"),
                }

                # Find parent by popping stack until we find a lower level
                while section_stack and section_stack[-1]["level"] >= level:
                    section_stack.pop()

                if section_stack:
                    section_entry["parent_id"] = section_stack[-1]["id"]

                sections.append(section_entry)
                section_stack.append(section_entry)

        return sections

    def _extract_tables(self) -> List[Dict[str, Any]]:
        """
        Extract tables from the document.

        Returns:
            List of table entries with caption, page, and block reference.
        """
        tables: List[Dict[str, Any]] = []

        entries = [(key, self.blocks.get(key, {})) for key in self.reading_order]
        entries.extend((None, {**item, "type": "table", "page": None})
                       for item in self.doc.get("annotations", {}).get("tables", []))
        for block_id, block in entries:
            if block.get("type") == "table":
                table_entry: Dict[str, Any] = {
                    "id": self._generate_id(),
                    "block_id": block_id,
                    "caption": block.get("caption", ""),
                    "page": block.get("page"),
                }
                tables.append(table_entry)

        return tables

    def _extract_figures(self) -> List[Dict[str, Any]]:
        """
        Extract figures/images from the document.

        Returns:
            List of figure entries with caption, path, page, and block reference.
        """
        figures: List[Dict[str, Any]] = []

        for block_id in self.reading_order:
            block = self.blocks.get(block_id, {})
            if block.get("type") == "image":
                figure_entry: Dict[str, Any] = {
                    "id": self._generate_id(),
                    "block_id": block_id,
                    "caption": block.get("caption", ""),
                    "path": block.get("path", ""),
                    "page": block.get("page"),
                }
                figures.append(figure_entry)

        return figures

    def _extract_formulas(self) -> List[Dict[str, Any]]:
        """
        Extract formulas from the document.

        Returns:
            List of formula entries with latex, number, type, page, and block reference.
        """
        formulas: List[Dict[str, Any]] = []

        for block_id in self.reading_order:
            block = self.blocks.get(block_id, {})
            block_type = block.get("type")
            if block_type in ("display_formula", "inline_formula"):
                formula_entry: Dict[str, Any] = {
                    "id": self._generate_id(),
                    "block_id": block_id,
                    "type": block_type,
                    "latex": block.get("latex", ""),
                    "number": block.get("number", ""),
                    "page": block.get("page"),
                }
                formulas.append(formula_entry)

        return formulas

    def _extract_pages(self) -> List[Dict[str, Any]]:
        """
        Extract page information from the document.

        Returns:
            List of page entries with page number and list of block IDs on that page.
        """
        page_blocks: Dict[int, List[str]] = {}

        # First, group blocks by page
        for block_id in self.reading_order:
            block = self.blocks.get(block_id, {})
            page = block.get("page")
            if not isinstance(page, int) or page < 1:
                continue
            if page not in page_blocks:
                page_blocks[page] = []
            page_blocks[page].append(block_id)

        # Then create page entries in order
        pages: List[Dict[str, Any]] = []
        source = self.doc.get("source", {})
        page_count = source.get("page_count", 0)

        # If we have page_count from source, use it to ensure we cover all pages
        if page_count > 0:
            for page_num in source.get("processed_pages", range(1, page_count + 1)):
                page_entry: Dict[str, Any] = {
                    "page": page_num,
                    "block_ids": page_blocks.get(page_num, []),
                }
                pages.append(page_entry)
        else:
            # Otherwise, just use the pages we found
            for page_num in sorted(page_blocks.keys()):
                page_entry = {
                    "page": page_num,
                    "block_ids": page_blocks[page_num],
                }
                pages.append(page_entry)

        return pages

    def save_to_file(self, file_path: str) -> None:
        """
        Save the generated index to a JSON file.

        Args:
            file_path: Path to the output JSON file.
        """
        index = self.generate()
        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
