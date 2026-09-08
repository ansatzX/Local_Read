import os
from typing import Any

from .base import DocumentConverterResult
from ._compat import _CustomMarkdownify, BeautifulSoup
from .utils import html_to_markdown_result


def convert_html_to_md(html_content: str) -> DocumentConverterResult:
    """Convert HTML content to Markdown format.

    This function parses HTML content using BeautifulSoup, removes script and style tags,
    and converts the remaining content to Markdown format using a custom Markdown converter.

    Args:
        html_content: Raw HTML content string to convert

    Returns:
        DocumentConverterResult with the converted Markdown text and title

    Raises:
        Exception: If HTML parsing or conversion fails

    Example:
        >>> html = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
        >>> result = convert_html_to_md(html)
        >>> "Hello" in result.text_content
        True

    Note:
        - JavaScript and CSS are automatically removed
        - Only the <body> content is converted if present, otherwise full document
        - Uses _CustomMarkdownify for conversion with enhanced security
    """
    if BeautifulSoup is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: beautifulsoup4 not installed]",
            error="beautifulsoup4 not installed"
        )
    if _CustomMarkdownify is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: markdownify not installed]",
            error="markdownify not installed"
        )

    soup = BeautifulSoup(html_content, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()

    # Print only the main content
    body_elm = soup.find("body")
    webpage_text = ""
    if body_elm:
        webpage_text = _CustomMarkdownify().convert_soup(body_elm)
    else:
        webpage_text = _CustomMarkdownify().convert_soup(soup)

    assert isinstance(webpage_text, str)

    return DocumentConverterResult(
        title=None if soup.title is None else soup.title.string,
        text_content=webpage_text,
    )


def HtmlConverter(
    local_path: str,
    extract_metadata: bool = False,
    extract_sections: bool = False,
    extract_tables: bool = False,
    **kwargs
) -> DocumentConverterResult:
    """
    Convert an HTML file to Markdown format with enhanced features.

    Args:
        local_path: Path to the HTML file to convert.
        extract_metadata: Whether to extract metadata (file size, etc.)
        extract_sections: Whether to extract sections from content
        extract_tables: Whether to extract tables (not implemented yet)

    Returns:
        DocumentConverterResult containing the converted Markdown text and optional metadata/sections.
    """
    try:
        with open(local_path, "rt", encoding="utf-8") as fh:
            html_content = fh.read()

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
            text_content=f"Error converting HTML: {str(e)}",
            error=str(e)
        )
