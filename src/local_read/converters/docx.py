import os

from .base import DocumentConverterResult
from ._compat import mammoth
from .utils import html_to_markdown_result


def DocxConverter(
    local_path: str,
    extract_metadata: bool = False,
    extract_sections: bool = False,
    extract_tables: bool = False,
    **kwargs
) -> DocumentConverterResult:
    """
    Convert a DOCX file to Markdown format with enhanced features.

    Uses mammoth library to first convert DOCX to HTML, then converts
    the HTML to Markdown using the shared html_to_markdown_result helper.

    Args:
        local_path: Path to the DOCX file to convert.
        extract_metadata: Whether to extract metadata (file size, etc.)
        extract_sections: Whether to extract sections from content
        extract_tables: Whether to extract tables (not implemented yet)

    Returns:
        DocumentConverterResult containing the converted Markdown text and optional metadata/sections.
    """
    if mammoth is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: mammoth not installed]",
            error="mammoth not installed"
        )

    try:
        with open(local_path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            html_content = result.value

        # Use shared helper function for HTML processing
        return html_to_markdown_result(
            html_content=html_content,
            file_path=local_path,
            extract_metadata=extract_metadata,
            extract_sections=extract_sections,
            extract_tables=extract_tables
        )

    except Exception as e:
        return DocumentConverterResult(
            title=None,
            text_content=f"Error converting DOCX: {str(e)}",
            error=str(e)
        )
