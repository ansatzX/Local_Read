"""
Unit tests for document converters.

This module contains comprehensive tests for all document conversion functions
in the converters module, including:
- PDF conversion
- Word document conversion
- Excel spreadsheet conversion
- PowerPoint presentation conversion
- HTML conversion
- Text file conversion
- JSON/YAML/CSV conversion
- Pagination and session management
- LaTeX formula fixing
- Section extraction
"""

import pytest
import os
import tempfile
import json
from pathlib import Path

# Import the converters module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read.converters import (
    DocumentConverterResult,
    TextConverter,
    JsonConverter,
    YamlConverter,
    CsvConverter,
    apply_content_limit,
    extract_sections_from_markdown,
    fix_latex_formulas,
    inspect_pdf,
    render_pdf_to_images,
    extract_form_fields,
    extract_tables,
)


class TestDocumentConverterResult:
    """Tests for DocumentConverterResult class."""
    
    def test_initialization_basic(self):
        """Test basic initialization of DocumentConverterResult."""
        result = DocumentConverterResult(
            title="Test Document",
            text_content="This is test content"
        )
        
        assert result.title == "Test Document"
        assert result.text_content == "This is test content"
        assert result.metadata == {}
        assert result.sections == []
        assert result.tables == []
        assert result.pagination_info == {}
        assert result.processing_time_ms is None
        assert result.error is None
    
    def test_initialization_with_metadata(self):
        """Test initialization with metadata."""
        metadata = {"file_size": 12345, "author": "Test Author"}
        result = DocumentConverterResult(
            title="Test",
            text_content="Content",
            metadata=metadata
        )
        
        assert result.metadata == metadata
        assert result.metadata["file_size"] == 12345
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = DocumentConverterResult(
            title="Test",
            text_content="Content",
            metadata={"key": "value"},
            processing_time_ms=100
        )
        
        d = result.to_dict()
        assert d["title"] == "Test"
        assert d["text_content"] == "Content"
        assert d["metadata"] == {"key": "value"}
        assert d["processing_time_ms"] == 100
    
    def test_with_error(self):
        """Test result with error."""
        result = DocumentConverterResult(
            title=None,
            text_content="Error occurred",
            error="File not found"
        )
        
        assert result.error == "File not found"
        d = result.to_dict()
        assert "error" in d
        assert d["error"] == "File not found"


class TestTextConverter:
    """Tests for TextConverter."""
    
    def test_text_converter_basic(self, tmp_path):
        """Test basic text file conversion."""
        # Create a temporary text file
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!\nThis is a test."
        test_file.write_text(test_content, encoding="utf-8")
        
        result = TextConverter(str(test_file))
        
        assert result.text_content == test_content
        assert result.title is None
    
    def test_text_converter_empty_file(self, tmp_path):
        """Test conversion of empty text file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("", encoding="utf-8")
        
        result = TextConverter(str(test_file))
        
        assert result.text_content == ""
    
    def test_text_converter_unicode(self, tmp_path):
        """Test conversion of text file with Unicode characters."""
        test_file = tmp_path / "unicode.txt"
        test_content = "中文内容 αβγδ 🎉"
        test_file.write_text(test_content, encoding="utf-8")
        
        result = TextConverter(str(test_file))
        
        assert result.text_content == test_content


class TestJsonConverter:
    """Tests for JsonConverter."""
    
    def test_json_converter_basic(self, tmp_path):
        """Test basic JSON file conversion."""
        test_file = tmp_path / "test.json"
        test_data = {"name": "Test", "value": 123, "nested": {"key": "value"}}
        test_file.write_text(json.dumps(test_data), encoding="utf-8")
        
        result = JsonConverter(str(test_file))
        
        # The converter formats JSON with indentation
        assert "Test" in result.text_content
        assert "123" in result.text_content
        assert "nested" in result.text_content
    
    def test_json_converter_array(self, tmp_path):
        """Test JSON converter with array."""
        test_file = tmp_path / "array.json"
        test_data = [1, 2, 3, {"key": "value"}]
        test_file.write_text(json.dumps(test_data), encoding="utf-8")
        
        result = JsonConverter(str(test_file))
        
        assert "1" in result.text_content
        assert "key" in result.text_content


class TestYamlConverter:
    """Tests for YamlConverter."""
    
    def test_yaml_converter_basic(self, tmp_path):
        """Test basic YAML file conversion."""
        test_file = tmp_path / "test.yaml"
        test_content = """
name: Test
value: 123
nested:
  key: value
"""
        test_file.write_text(test_content, encoding="utf-8")
        
        result = YamlConverter(str(test_file))
        
        assert "Test" in result.text_content
        assert "123" in result.text_content
        assert "nested" in result.text_content


class TestCsvConverter:
    """Tests for CsvConverter."""
    
    def test_csv_converter_basic(self, tmp_path):
        """Test basic CSV file conversion."""
        test_file = tmp_path / "test.csv"
        test_content = "Name,Age,City\nAlice,30,New York\nBob,25,Los Angeles"
        test_file.write_text(test_content, encoding="utf-8")
        
        result = CsvConverter(str(test_file))
        
        # CSV converter creates markdown tables
        assert "|" in result.text_content
        assert "Name" in result.text_content
        assert "Alice" in result.text_content
        assert "Bob" in result.text_content
    
    def test_csv_converter_empty(self, tmp_path):
        """Test conversion of empty CSV file."""
        test_file = tmp_path / "empty.csv"
        test_file.write_text("", encoding="utf-8")
        
        result = CsvConverter(str(test_file))
        
        assert "Empty CSV file" in result.text_content


class TestContentLimit:
    """Tests for apply_content_limit function."""
    
    
    def test_apply_content_limit_over_limit(self):
        """Test content over the limit."""
        content = "A" * 300000
        result = apply_content_limit(content, max_chars=200000)
        
        assert len(result) == 200000 + len("\n... [Content truncated]")
        assert result.endswith("\n... [Content truncated]")
    

class TestSectionExtraction:
    """Tests for extract_sections_from_markdown function."""
    
    def test_extract_sections_basic(self):
        """Test basic section extraction."""
        content = """# Section 1
Content for section 1.

## Section 1.1
Subsection content.

# Section 2
Content for section 2.
"""
        sections = extract_sections_from_markdown(content)
        
        assert len(sections) == 3
        assert sections[0]["heading"] == "Section 1"
        assert sections[0]["level"] == 1
        assert sections[1]["heading"] == "Section 1.1"
        assert sections[1]["level"] == 2
        assert sections[2]["heading"] == "Section 2"
    
    def test_extract_sections_no_headings(self):
        """Test extraction from content without headings."""
        content = "This is plain text without any headings."
        sections = extract_sections_from_markdown(content)
        
        assert len(sections) == 0
    
    def test_extract_sections_with_content(self):
        """Test that section content is correctly extracted."""
        content = """# Heading
Line 1
Line 2

# Another Heading
Line 3
"""
        sections = extract_sections_from_markdown(content)
        
        assert "Line 1" in sections[0]["content"]
        assert "Line 2" in sections[0]["content"]
        assert "Line 3" in sections[1]["content"]


class TestLatexFixes:
    """Tests for fix_latex_formulas function."""
    
    def test_fix_latex_cid_placeholders(self):
        """Test fixing CID placeholders."""
        content = "Formula (cid:16)x(cid:17) and (cid:40)y(cid:41)"
        result = fix_latex_formulas(content)
        
        assert "(cid:16)" not in result
        assert "(cid:17)" not in result
        assert "〈" in result
        assert "〉" in result
    
    def test_fix_latex_greek_letters(self):
        """Test fixing Greek letters."""
        content = r"\alpha + \beta = \gamma"
        result = fix_latex_formulas(content)
        
        assert "α" in result
        assert "β" in result
        assert "γ" in result
    
    def test_fix_latex_math_symbols(self):
        """Test fixing mathematical symbols."""
        content = r"\times \div \pm \leq \geq"
        result = fix_latex_formulas(content)
        
        assert "×" in result
        assert "÷" in result
        assert "±" in result
        assert "≤" in result
        assert "≥" in result
    
    def test_fix_latex_empty_string(self):
        """Test fixing empty string."""
        result = fix_latex_formulas("")
        assert result == ""
    
    def test_fix_latex_none(self):
        """Test fixing None value."""
        result = fix_latex_formulas(None)
        assert result is None


class TestPdfEnhancements:
    """Tests for PDF enhancement features."""

    def test_pdf_quality_unreadable_for_control_char_heavy_text(self, monkeypatch, tmp_path):
        """PdfConverter marks control-char-heavy extraction as unreadable."""
        import local_read.converters.pdf as pdf_module

        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        noisy_text = ("\x01\x02\x03\x04" * 120) + "abc"
        monkeypatch.setattr(pdf_module, "extract_text_pymupdf", lambda path: noisy_text)
        monkeypatch.setattr(pdf_module, "fix_latex_formulas", lambda text: text)
        monkeypatch.setattr(pdf_module, "apply_content_limit", lambda text: text)

        result = pdf_module.PdfConverter(str(pdf_file))

        assert result.metadata["quality_state"] == "unreadable"
        assert result.metadata["requires_ocr"] is True
        assert result.metadata["quality_metrics"]["control_char_ratio"] >= 0.3
        assert "quality_warning" in result.metadata

    def test_pdf_quality_ok_for_normal_text(self, monkeypatch, tmp_path):
        """PdfConverter marks normal extraction as ok."""
        import local_read.converters.pdf as pdf_module

        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        readable_text = ("This is readable extracted PDF text with words and numbers 12345. " * 40).strip()
        monkeypatch.setattr(pdf_module, "extract_text_pymupdf", lambda path: readable_text)
        monkeypatch.setattr(pdf_module, "fix_latex_formulas", lambda text: text)
        monkeypatch.setattr(pdf_module, "apply_content_limit", lambda text: text)

        result = pdf_module.PdfConverter(str(pdf_file))

        assert result.metadata["quality_state"] == "ok"
        assert result.metadata["requires_ocr"] is False
        assert result.metadata["quality_metrics"]["printable_ratio"] == 1.0
        assert "quality_warning" not in result.metadata

    def test_document_converter_result_new_fields(self):
        """Test that DocumentConverterResult has new fields."""
        result = DocumentConverterResult(
            title="Test",
            text_content="Content",
            rendered_pages=[{"page": 1, "path": "/tmp/page1.png"}],
            extracted_tables=[{"page": 1, "headers": ["A", "B"]}],
            form_fields=[{"name": "field1", "type": "text"}],
            structure={"metadata": {"title": "Test"}},
            text_with_coords=[{"text": "Hello", "page": 0}],
        )

        assert hasattr(result, 'rendered_pages')
        assert hasattr(result, 'extracted_tables')
        assert hasattr(result, 'form_fields')
        assert hasattr(result, 'structure')
        assert hasattr(result, 'text_with_coords')

        d = result.to_dict()
        assert "rendered_pages" in d
        assert "extracted_tables" in d
        assert "form_fields" in d
        assert "structure" in d
        assert "text_with_coords" in d

    def test_document_converter_result_backward_compatibility(self):
        """Test backward compatibility of DocumentConverterResult."""
        # Create with old parameters only
        result = DocumentConverterResult(
            title="Test",
            text_content="Content",
            metadata={"key": "value"},
            sections=[],
            tables=[],
            images=[],
        )

        d = result.to_dict()
        # Old fields should still exist
        assert "title" in d
        assert "text_content" in d
        assert "metadata" in d
        assert "sections" in d
        assert "tables" in d
        # New fields should NOT be in dict if empty
        assert "rendered_pages" not in d
        assert "extracted_tables" not in d


    def test_pdf_render_images_uses_images_output_dir(self, monkeypatch, tmp_path):
        """PdfConverter with render_images=True should pass output_dir under images_output_dir."""
        import local_read.converters.pdf as pdf_module
        from pathlib import Path

        pdf_file = tmp_path / 'sample.pdf'
        pdf_file.write_bytes(b'%PDF-1.4\n')
        images_dir = tmp_path / '.local_read_mcp' / 'sample' / 'images'
        captured = {}

        monkeypatch.setattr(pdf_module, 'extract_text_pymupdf', lambda path: 'hello')
        monkeypatch.setattr(pdf_module, 'fix_latex_formulas', lambda text: text)
        monkeypatch.setattr(pdf_module, 'apply_content_limit', lambda text: text)
        monkeypatch.setattr(pdf_module, 'fitz', object())

        def fake_render(path, output_dir=None, **kwargs):
            captured['output_dir'] = output_dir
            return [{'page': 1, 'path': str(Path(output_dir or '.') / 'page000.png')}]

        monkeypatch.setattr(pdf_module, 'render_pdf_to_images', fake_render)

        result = pdf_module.PdfConverter(str(pdf_file), render_images=True, images_output_dir=str(images_dir))

        assert captured['output_dir'] == str(images_dir / 'rendered_pages')

    def test_extract_pdf_images_includes_suspicious_vector_regions_no_dedupe(self, monkeypatch, tmp_path):
        """Vector suspicious regions should be extracted without dedupe (recall-first)."""
        import local_read.converters.pdf as pdf_module

        class FakePixmap:
            def __init__(self, width=80, height=60):
                self.width = width
                self.height = height

            def save(self, path):
                Path(path).write_bytes(b"PNG")

        class FakePage:
            def __init__(self):
                self.rect = (0, 0, 600, 800)

            def get_images(self, full=True):
                return [(11,)]

            def cluster_drawings(self):
                # duplicate on purpose: no dedupe expected
                return [(10, 10, 120, 100), (10, 10, 120, 100)]

            def get_drawings(self):
                return []

            def get_text(self, mode):
                if mode == "dict":
                    return {"blocks": []}
                return {}

            def get_pixmap(self, clip=None, dpi=200, alpha=False):
                return FakePixmap()

        class FakeDoc:
            def __init__(self):
                self._pages = [FakePage()]

            def __len__(self):
                return len(self._pages)

            def __getitem__(self, idx):
                return self._pages[idx]

            def extract_image(self, xref):
                return {"image": b"RASTER", "ext": "png", "width": 32, "height": 24}

            def close(self):
                return None

        class FakeFitz:
            @staticmethod
            def open(path):
                return FakeDoc()

            @staticmethod
            def Rect(x0, y0, x1, y1):
                return (x0, y0, x1, y1)

        monkeypatch.setattr(pdf_module, "fitz", FakeFitz)

        out_dir = tmp_path / "images"
        infos = pdf_module.extract_pdf_images("fake.pdf", output_dir=str(out_dir))

        # 1 raster + 2 duplicated suspicious regions
        assert len(infos) == 3
        assert sum(1 for i in infos if i.get("kind") == "raster") == 1
        assert sum(1 for i in infos if i.get("kind") == "vector_region") == 2
        for item in infos:
            assert Path(item["saved_path"]).exists()
