"""Optional dependency compatibility module — centralized providers."""

import html
import re
from urllib.parse import quote, unquote, urlparse, urlunparse

# Optional imports
try:
    import mammoth
except ImportError:
    mammoth = None

try:
    import markdownify
except ImportError:
    markdownify = None

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None
    get_column_letter = None

try:
    import pdfminer
    import pdfminer.high_level
except ImportError:
    pdfminer = None

try:
    import pptx
except ImportError:
    pptx = None

try:
    from markitdown import MarkItDown
except ImportError:
    MarkItDown = None

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import yaml
except ImportError:
    yaml = None


# ── Custom Markdownify ──────────────────────────────────────────────

_CustomMarkdownify = None
if markdownify is not None:
    class _CustomMarkdownify(markdownify.MarkdownConverter):
        def __init__(self, **options):
            options["heading_style"] = options.get("heading_style", markdownify.ATX)
            super().__init__(**options)

        def convert_hn(self, n, el, text, convert_as_inline):
            if not convert_as_inline:
                if not re.search(r"^\n", text):
                    return "\n" + super().convert_hn(n, el, text, convert_as_inline)
            return super().convert_hn(n, el, text, convert_as_inline)

        def convert_a(self, el, text, convert_as_inline):
            prefix, suffix, text = markdownify.chomp(text)
            if not text:
                return ""
            href = el.get("href")
            title = el.get("title")
            if href:
                try:
                    parsed_url = urlparse(href)
                    if parsed_url.scheme and parsed_url.scheme.lower() not in [
                        "http", "https", "file",
                    ]:
                        return "%s%s%s" % (prefix, text, suffix)
                    href = urlunparse(
                        parsed_url._replace(path=quote(unquote(parsed_url.path)))
                    )
                except ValueError:
                    return "%s%s%s" % (prefix, text, suffix)
            if (
                self.options["autolinks"]
                and text.replace(r"\_", "_") == href
                and not title
                and not self.options["default_title"]
            ):
                return "<%s>" % href
            if self.options["default_title"] and not title:
                title = href
            title_part = ' "%s"' % title.replace('"', r"\"") if title else ""
            return (
                "%s[%s](%s%s)%s" % (prefix, text, href, title_part, suffix)
                if href
                else text
            )

        def convert_img(self, el, text, convert_as_inline):
            alt = el.attrs.get("alt", None) or ""
            src = el.attrs.get("src", None) or ""
            title = el.attrs.get("title", None) or ""
            title_part = ' "%s"' % title.replace('"', r"\"") if title else ""
            if (
                convert_as_inline
                and el.parent.name not in self.options["keep_inline_images_in"]
            ):
                return alt
            if src.startswith("data:"):
                src = src.split(",")[0] + "..."
            return "![%s](%s%s)" % (alt, src, title_part)

        def convert_soup(self, soup):
            return super().convert_soup(soup)
