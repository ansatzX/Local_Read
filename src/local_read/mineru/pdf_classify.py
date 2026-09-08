# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
PDF classification utility to detect text-based vs scanned PDFs.

Ported and simplified from MinerU's PDF classification logic.
"""

import logging
import re
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.high_level import extract_text
    from pdfminer.layout import LAParams, LTFigure, LTImage
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    PDFMINER_AVAILABLE = True
except ImportError:
    PDFMINER_AVAILABLE = False

try:
    import pypdfium2 as pdfium
    PYPDFIUM_AVAILABLE = True
except ImportError:
    PYPDFIUM_AVAILABLE = False

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


# Configuration constants
MAX_SAMPLE_PAGES = 10
CHARS_THRESHOLD = 50
HIGH_IMAGE_COVERAGE_THRESHOLD = 0.8
CID_RATIO_THRESHOLD = 0.05


def classify_pdf(pdf_source: str | Path | bytes) -> str:
    """
    Classify a PDF as text-based or scanned (OCR-needed).

    Args:
        pdf_source: Path to PDF file or bytes content

    Returns:
        "txt" if text-based PDF, "ocr" if scanned/needs OCR
    """
    # Read PDF bytes if path is provided
    if isinstance(pdf_source, (str, Path)):
        with open(pdf_source, "rb") as f:
            pdf_bytes = f.read()
    else:
        pdf_bytes = pdf_source

    # Try different classification strategies in order of preference
    strategies = [
        _classify_pypdfium,
        _classify_pdfminer,
        _classify_simple,
    ]

    for strategy in strategies:
        try:
            result = strategy(pdf_bytes)
            if result is not None:
                logger.debug(f"PDF classification using {strategy.__name__}: {result}")
                return result
        except Exception as e:
            logger.debug(f"Strategy {strategy.__name__} failed: {e}")
            continue

    # Fallback to OCR if all strategies fail
    logger.warning("All PDF classification strategies failed, defaulting to OCR")
    return "ocr"


def _classify_pypdfium(pdf_bytes: bytes) -> str | None:
    """Classify PDF using pypdfium2 (fastest)."""
    if not PYPDFIUM_AVAILABLE:
        return None

    pdf = None
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        page_count = len(pdf)

        if page_count == 0:
            return "ocr"

        # Sample pages
        page_indices = _get_sample_page_indices(page_count)
        if not page_indices:
            return "ocr"

        total_chars = 0
        pages_with_text = 0

        for page_index in page_indices:
            page = pdf[page_index]
            text_page = page.get_textpage()
            text = text_page.get_text_bounded()

            # Clean and count characters
            cleaned_text = re.sub(r"\s+", "", text)
            total_chars += len(cleaned_text)

            if len(cleaned_text) > 0:
                pages_with_text += 1

        avg_chars = total_chars / len(page_indices) if page_indices else 0

        # Check for CID fonts
        has_cid_issue = _check_cid_fonts_pypdf(pdf_bytes, page_indices)

        # Check for high image coverage
        high_image_coverage = _check_high_image_coverage_pypdfium(pdf, page_indices)

        # Decision logic
        if avg_chars < CHARS_THRESHOLD:
            return "ocr"
        if has_cid_issue:
            return "ocr"
        if high_image_coverage:
            return "ocr"

        return "txt"

    except Exception as e:
        logger.debug(f"pypdfium classification failed: {e}")
        return None
    finally:
        if pdf is not None:
            pdf.close()


def _classify_pdfminer(pdf_bytes: bytes) -> str | None:
    """Classify PDF using pdfminer."""
    if not PDFMINER_AVAILABLE:
        return None

    try:
        # Check text content
        laparams = LAParams()
        text = extract_text(pdf_file=BytesIO(pdf_bytes), laparams=laparams)
        cleaned_text = re.sub(r"\s+", "", text)

        if len(cleaned_text) < CHARS_THRESHOLD * 3:  # Multiply by 3 for more conservative check
            return "ocr"

        # Check for CID characters
        cid_pattern = re.compile(r"\(cid:\d+\)")
        cid_matches = cid_pattern.findall(text)

        if cid_matches:
            cid_count = len(cid_matches)
            cid_len = sum(len(m) for m in cid_matches)
            text_len = len(text.replace("\n", ""))

            if text_len > 0:
                cid_ratio = cid_count / (cid_count + text_len - cid_len)
                if cid_ratio > CID_RATIO_THRESHOLD:
                    return "ocr"

        # Check for high image coverage
        if _check_high_image_coverage_pdfminer(pdf_bytes):
            return "ocr"

        return "txt"

    except Exception as e:
        logger.debug(f"pdfminer classification failed: {e}")
        return None


def _classify_simple(pdf_bytes: bytes) -> str | None:
    """Simple fallback classification using basic text extraction."""
    if not PDFMINER_AVAILABLE:
        return None

    try:
        text = extract_text(pdf_file=BytesIO(pdf_bytes))
        cleaned_text = re.sub(r"\s+", "", text)

        if len(cleaned_text) < CHARS_THRESHOLD * 5:
            return "ocr"

        return "txt"

    except Exception as e:
        logger.debug(f"Simple classification failed: {e}")
        return None


def _get_sample_page_indices(page_count: int) -> list:
    """Get indices of sample pages to analyze."""
    if page_count <= 0:
        return []

    sample_count = min(page_count, MAX_SAMPLE_PAGES)
    if sample_count == page_count:
        return list(range(page_count))
    if sample_count == 1:
        return [0]

    # Sample evenly distributed pages
    indices = []
    seen = set()
    for i in range(sample_count):
        page_index = round(i * (page_count - 1) / (sample_count - 1))
        page_index = max(0, min(page_count - 1, page_index))
        if page_index not in seen:
            indices.append(page_index)
            seen.add(page_index)

    return sorted(indices)


def _check_cid_fonts_pypdf(pdf_bytes: bytes, page_indices: list) -> bool:
    """Check for problematic CID fonts using pypdf."""
    if not PYPDF_AVAILABLE:
        return False

    try:
        reader = PdfReader(BytesIO(pdf_bytes))

        for page_index in page_indices:
            if page_index >= len(reader.pages):
                continue

            page = reader.pages[page_index]
            resources = page.get("/Resources", {})

            if hasattr(resources, "get_object"):
                resources = resources.get_object()

            if not resources:
                continue

            fonts = resources.get("/Font", {})
            if hasattr(fonts, "get_object"):
                fonts = fonts.get_object()

            if not fonts:
                continue

            for _, font_ref in fonts.items():
                font = font_ref
                if hasattr(font, "get_object"):
                    font = font.get_object()

                if not font:
                    continue

                subtype = str(font.get("/Subtype", ""))
                encoding = str(font.get("/Encoding", ""))
                has_descendant = "/DescendantFonts" in font
                has_to_unicode = "/ToUnicode" in font

                if (
                    subtype == "/Type0"
                    and encoding in ("/Identity-H", "/Identity-V")
                    and has_descendant
                    and not has_to_unicode
                ):
                    return True

        return False

    except Exception as e:
        logger.debug(f"CID font check failed: {e}")
        return False


def _check_high_image_coverage_pypdfium(pdf, page_indices: list) -> bool:
    """Check if pages have high image coverage using pypdfium."""
    if not PYPDFIUM_AVAILABLE:
        return False

    try:
        high_coverage_pages = 0

        for page_index in page_indices:
            page = pdf[page_index]
            page_bbox = page.get_bbox()
            page_area = abs(
                (page_bbox[2] - page_bbox[0]) * (page_bbox[3] - page_bbox[1])
            )
            image_area = 0.0

            # Count images on page
            for page_object in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
                left, bottom, right, top = page_object.get_pos()
                image_area += max(0.0, right - left) * max(0.0, top - bottom)

            if page_area > 0:
                coverage = min(image_area / page_area, 1.0)
                if coverage >= HIGH_IMAGE_COVERAGE_THRESHOLD:
                    high_coverage_pages += 1

        if not page_indices:
            return False

        return (high_coverage_pages / len(page_indices)) >= HIGH_IMAGE_COVERAGE_THRESHOLD

    except Exception as e:
        logger.debug(f"High image coverage check failed: {e}")
        return False


def _check_high_image_coverage_pdfminer(pdf_bytes: bytes) -> bool:
    """Check if pages have high image coverage using pdfminer."""
    if not PDFMINER_AVAILABLE:
        return False

    try:
        pdf_stream = BytesIO(pdf_bytes)
        rsrcmgr = PDFResourceManager()
        laparams = LAParams()
        device = PDFPageAggregator(rsrcmgr, laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)

        high_coverage_pages = 0
        page_count = 0
        max_pages = min(MAX_SAMPLE_PAGES, 10)

        for page in PDFPage.create_pages(pdf_stream):
            if page_count >= max_pages:
                break

            interpreter.process_page(page)
            layout = device.get_result()

            page_area = layout.width * layout.height
            image_area = 0

            for element in layout:
                if isinstance(element, (LTImage, LTFigure)):
                    image_area += element.width * element.height

            if page_area > 0:
                coverage = min(image_area / page_area, 1.0)
                if coverage >= HIGH_IMAGE_COVERAGE_THRESHOLD:
                    high_coverage_pages += 1

            page_count += 1

        pdf_stream.close()

        if page_count == 0:
            return False

        return (high_coverage_pages / page_count) >= HIGH_IMAGE_COVERAGE_THRESHOLD

    except Exception as e:
        logger.debug(f"High image coverage check (pdfminer) failed: {e}")
        return False
