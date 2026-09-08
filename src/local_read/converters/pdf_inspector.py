import logging
from typing import Dict, Any, List, Optional
from ._compat import fitz

logger = logging.getLogger(__name__)


def inspect_pdf(pdf_path: str) -> Dict[str, Any]:
    """Get comprehensive PDF structure information.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dictionary with metadata, page count, outline, fonts, etc.
    """
    if fitz is None:
        return {"error": "PyMuPDF (fitz) not installed"}

    try:
        doc = fitz.open(pdf_path)

        # Get metadata
        metadata = doc.metadata or {}

        # Get outline (bookmarks)
        outline = []
        try:
            toc = doc.get_toc()
            for item in toc:
                outline.append({
                    "title": item[1],
                    "page": item[2] - 1,  # convert to 0-indexed
                    "level": item[0]
                })
        except Exception as e:
            logger.debug(f"Could not extract outline: {e}")

        # Get fonts
        fonts = []
        try:
            for page_num in range(min(len(doc), 10)):  # Check first 10 pages max
                page = doc[page_num]
                font_list = page.get_fonts()
                for font in font_list:
                    font_info = {
                        "xref": font[0],
                        "name": font[4],
                        "type": font[1],
                        "page": page_num
                    }
                    if font_info not in fonts:
                        fonts.append(font_info)
        except Exception as e:
            logger.debug(f"Could not extract fonts: {e}")

        result = {
            "metadata": {
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "subject": metadata.get("subject", ""),
                "keywords": metadata.get("keywords", ""),
                "creator": metadata.get("creator", ""),
                "producer": metadata.get("producer", ""),
                "creation_date": metadata.get("creationDate", ""),
                "modification_date": metadata.get("modDate", "")
            },
            "page_count": len(doc),
            "outline": outline,
            "fonts": fonts,
            "has_acroform": doc.is_form_pdf,
            "is_encrypted": doc.is_encrypted
        }

        doc.close()
        return result

    except Exception as e:
        logger.error(f"Error inspecting PDF: {e}")
        return {"error": str(e)}


def get_pdf_metadata(pdf_path: str) -> Dict[str, Any]:
    """Get PDF metadata (simplified version)."""
    result = inspect_pdf(pdf_path)
    return result.get("metadata", {}) if "error" not in result else result
