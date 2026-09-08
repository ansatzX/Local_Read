"""Converter utility functions: content limiting, HTML conversion."""

import os
import time

from .base import DocumentConverterResult
from ._compat import BeautifulSoup, _CustomMarkdownify


def apply_content_limit(content: str, max_chars: int = 200000) -> str:
    """Apply hard limit to content length."""
    if len(content) > max_chars:
        return content[:max_chars] + "\n... [Content truncated]"
    return content


def html_to_markdown_result(
    html_content: str,
    file_path: str,
    extract_metadata: bool = False,
    extract_sections: bool = False,
    extract_tables: bool = False
) -> DocumentConverterResult:
    """Convert HTML content to a DocumentConverterResult with enhanced features."""
    if BeautifulSoup is None:
        return DocumentConverterResult(
            title=None, text_content="[Error: beautifulsoup4 not installed]",
            error="beautifulsoup4 not installed"
        )
    if _CustomMarkdownify is None:
        return DocumentConverterResult(
            title=None, text_content="[Error: markdownify not installed]",
            error="markdownify not installed"
        )

    from bs4 import BeautifulSoup as _BS
    soup = _BS(html_content, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()

    body_elm = soup.find("body")
    if body_elm:
        webpage_text = _CustomMarkdownify().convert_soup(body_elm)
    else:
        webpage_text = _CustomMarkdownify().convert_soup(soup)

    assert isinstance(webpage_text, str)
    webpage_text = apply_content_limit(webpage_text)

    metadata = {}
    sections = []
    if extract_metadata:
        file_size = None
        try:
            file_size = os.path.getsize(file_path)
        except (OSError, Exception):
            pass
        metadata = {
            "file_path": file_path, "file_size": file_size,
            "file_extension": os.path.splitext(file_path)[1],
            "conversion_timestamp": time.time(),
        }

    if extract_sections:
        from .section_extractor import extract_sections_from_markdown
        sections = extract_sections_from_markdown(webpage_text)

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string
    else:
        title = os.path.splitext(os.path.basename(file_path))[0]

    return DocumentConverterResult(
        title=title, text_content=webpage_text,
        metadata=metadata, sections=sections, tables=[],
        processing_time_ms=None,
    )
