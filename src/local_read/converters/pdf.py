import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import DocumentConverterResult
from ._compat import pdfminer, fitz
from .pdf_inspector import inspect_pdf
from .pdf_rendering import render_pdf_to_images
from .pdf_forms import extract_form_fields
from .pdf_tables import extract_tables
from .utils import apply_content_limit
from .section_extractor import extract_sections_from_markdown
from .latex_fixer import fix_latex_formulas


PDF_QUALITY_WARNING_BY_STATE: dict[str, str] = {
    "warn": "Extracted PDF text quality is degraded; review output before downstream use.",
    "unreadable": "Extracted PDF text appears unreadable; OCR is likely required.",
}


def get_pdf_quality_warning(state: str) -> str | None:
    """Return canonical warning text for a computed PDF quality state."""
    return PDF_QUALITY_WARNING_BY_STATE.get(state)


def evaluate_pdf_text_quality(
    text_content: str,
    page_count: Optional[int],
) -> dict[str, Any]:
    """Evaluate extracted PDF text quality with deterministic heuristics."""
    text = text_content or ""
    total_chars = len(text)
    pages = page_count if isinstance(page_count, int) and page_count > 0 else 1

    if total_chars == 0:
        metrics = {
            "control_char_ratio": 0.0,
            "printable_ratio": 0.0,
            "alpha_numeric_density": 0.0,
            "avg_readable_chars_per_page": 0.0,
        }
        return {
            "quality_state": "unreadable",
            "quality_metrics": metrics,
            "requires_ocr": True,
            "quality_warning": get_pdf_quality_warning("unreadable"),
        }

    allowed_whitespace = {"\n", "\r", "\t"}
    control_count = sum(
        1 for ch in text if (ord(ch) < 32 and ch not in allowed_whitespace) or ord(ch) == 127
    )
    readable_count = sum(1 for ch in text if ch.isprintable() or ch in allowed_whitespace)
    alnum_count = sum(1 for ch in text if ch.isalnum())

    control_char_ratio = control_count / total_chars
    printable_ratio = readable_count / total_chars
    alpha_numeric_density = alnum_count / total_chars
    avg_readable_chars_per_page = readable_count / pages

    metrics = {
        "control_char_ratio": round(control_char_ratio, 4),
        "printable_ratio": round(printable_ratio, 4),
        "alpha_numeric_density": round(alpha_numeric_density, 4),
        "avg_readable_chars_per_page": round(avg_readable_chars_per_page, 2),
    }

    state = "ok"
    warning = None
    if (
        control_char_ratio >= 0.30
        or printable_ratio < 0.60
        or alpha_numeric_density < 0.10
        or avg_readable_chars_per_page < 40
    ):
        state = "unreadable"
        warning = get_pdf_quality_warning(state)
    elif (
        control_char_ratio >= 0.12
        or printable_ratio < 0.85
        or alpha_numeric_density < 0.25
        or avg_readable_chars_per_page < 180
    ):
        state = "warn"
        warning = get_pdf_quality_warning(state)

    return {
        "quality_state": state,
        "quality_metrics": metrics,
        "requires_ocr": state == "unreadable",
        "quality_warning": warning,
    }


def _rect_from_any(rect_obj: Any) -> Optional[tuple[float, float, float, float]]:
    """Convert an arbitrary rect object into normalized (x0, y0, x1, y1)."""
    if rect_obj is None:
        return None

    x0 = y0 = x1 = y1 = None
    if all(hasattr(rect_obj, attr) for attr in ("x0", "y0", "x1", "y1")):
        x0 = float(rect_obj.x0)
        y0 = float(rect_obj.y0)
        x1 = float(rect_obj.x1)
        y1 = float(rect_obj.y1)
    elif isinstance(rect_obj, (list, tuple)) and len(rect_obj) >= 4:
        x0 = float(rect_obj[0])
        y0 = float(rect_obj[1])
        x1 = float(rect_obj[2])
        y1 = float(rect_obj[3])
    elif isinstance(rect_obj, dict) and all(k in rect_obj for k in ("x0", "y0", "x1", "y1")):
        x0 = float(rect_obj["x0"])
        y0 = float(rect_obj["y0"])
        x1 = float(rect_obj["x1"])
        y1 = float(rect_obj["y1"])

    if x0 is None:
        return None

    x_min, x_max = sorted((x0, x1))
    y_min, y_max = sorted((y0, y1))
    return x_min, y_min, x_max, y_max


def _expand_rect(
    rect: tuple[float, float, float, float],
    margin: float,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    """Expand rect by margin and clamp within page bounds."""
    x0, y0, x1, y1 = rect
    x0 = max(0.0, x0 - margin)
    y0 = max(0.0, y0 - margin)
    x1 = min(page_width, x1 + margin)
    y1 = min(page_height, y1 + margin)
    return x0, y0, x1, y1


def extract_text_pymupdf(pdf_path: str) -> str:
    """Extract text using PyMuPDF (better accuracy)."""
    if fitz is None:
        return None
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.debug(f"PyMuPDF text extraction failed: {e}")
        return None


def extract_pdf_blocks(pdf_path: str, fix_latex: bool = True) -> tuple[list[dict], int | None]:
    """Read native text blocks; pages are 1-based, boxes are PDF points."""
    if fitz is None:
        return [], None
    try:
        blocks = []
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, 1):
                for item in page.get_text("blocks"):
                    if len(item) > 6 and item[6] != 0:
                        continue
                    content = item[4]
                    if not content.strip():
                        continue
                    blocks.append({
                        "type": "text", "page": page_num,
                        "bbox": list(item[:4]),
                        "page_size": [page.cropbox.width, page.cropbox.height],
                        "coordinate_system": "pymupdf_unrotated_points",
                        "page_rotation": page.rotation,
                        "content": fix_latex_formulas(content) if fix_latex else content,
                        "confidence": None,
                    })
            return blocks, len(doc)
    except Exception as exc:
        logging.getLogger(__name__).debug("PDF block extraction unavailable: %s", exc)
        return [], None


def extract_pdf_images(
    pdf_path: str,
    output_dir: Optional[str] = None,
    page_range: Optional[tuple] = None
) -> List[Dict[str, Any]]:
    """
    Extract image-like content from PDF using PyMuPDF.

    This includes:
    - Embedded raster images (`page.get_images`)
    - Suspected figure regions from vector graphics (rendered clips, no dedupe)

    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save extracted images. If None, creates temp directory
        page_range: Tuple of (start_page, end_page) to extract from specific pages.
                    If None, extracts from all pages. Page numbers are 0-indexed.

    Returns:
        List of dictionaries containing image information:
        [
            {
                "page": int,  # Page number (0-indexed)
                "index": int,  # Image index on the page
                "xref": int | None,  # PDF object reference (None for rendered region clips)
                "width": int,  # Image width in pixels
                "height": int,  # Image height in pixels
                "format": str,  # Image format (png, jpeg, etc.)
                "size": int,  # File size in bytes
                "saved_path": str,  # Path where image was saved
                "kind": str,  # "raster" or "vector_region"
            },
            ...
        ]

    Raises:
        ImportError: If PyMuPDF (fitz) is not installed
        FileNotFoundError: If PDF file doesn't exist
    """
    if fitz is None:
        raise ImportError(
            "PyMuPDF (fitz) is required for image extraction. "
            "Install with: pip install pymupdf"
        )

    # Create output directory if needed
    if output_dir is None:
        from pathlib import Path as _P
        import time as _t
        base = _P.cwd() / ".local_read_mcp"
        ts = _t.strftime("%Y%m%d_%H%M%S", _t.localtime())
        output_dir = str(base / f"pdf_images_{ts}")
    os.makedirs(output_dir, exist_ok=True)

    logger = logging.getLogger(__name__)
    logger.info(f"Extracting images from PDF: {pdf_path}")
    logger.info(f"Saving images to: {output_dir}")

    images_info = []

    try:
        doc = fitz.open(pdf_path)

        # Determine page range
        start_page = 0
        end_page = len(doc)
        if page_range:
            start_page, end_page = page_range
            start_page = max(0, start_page)
            end_page = min(len(doc), end_page)

        # Extract images from each page
        for page_num in range(start_page, end_page):
            page = doc[page_num]
            image_list = page.get_images(full=True)

            logger.debug(f"Page {page_num}: found {len(image_list)} images")
            page_output_index = 0

            for img_index, img in enumerate(image_list):
                xref = img[0]  # XREF number

                # Extract image
                try:
                    base_image = doc.extract_image(xref)

                    # Get image properties
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]  # png, jpeg, etc.
                    image_width = base_image["width"]
                    image_height = base_image["height"]

                    # Generate filename
                    image_filename = f"page{page_num:03d}_img{page_output_index:04d}_raster.{image_ext}"
                    image_path = os.path.join(output_dir, image_filename)

                    # Save image
                    with open(image_path, "wb") as f:
                        f.write(image_bytes)

                    # Record image info
                    images_info.append({
                        "page": page_num,
                        "index": img_index,
                        "xref": xref,
                        "width": image_width,
                        "height": image_height,
                        "format": image_ext,
                        "size": len(image_bytes),
                        "saved_path": image_path,
                        "kind": "raster",
                    })
                    page_output_index += 1

                    logger.debug(
                        f"Extracted: {image_filename} "
                        f"({image_width}x{image_height}, {len(image_bytes)} bytes)"
                    )

                except Exception as e:
                    logger.warning(
                        f"Failed to extract image {img_index} from page {page_num}: {e}"
                    )
                    continue

            # Vector-first "suspicious figure" extraction path (no dedupe):
            # We prefer over-extraction to avoid missing LaTeX/TikZ-like figures.
            suspicious_regions: list[tuple[str, tuple[float, float, float, float]]] = []
            try:
                clustered = []
                if hasattr(page, "cluster_drawings"):
                    clustered = page.cluster_drawings() or []

                if clustered:
                    for rect_obj in clustered:
                        rect = _rect_from_any(rect_obj)
                        if rect is not None:
                            suspicious_regions.append(("cluster", rect))
                else:
                    for drawing in page.get_drawings() or []:
                        rect = _rect_from_any(drawing.get("rect"))
                        if rect is not None:
                            suspicious_regions.append(("drawing", rect))
            except Exception as e:
                logger.debug(f"Vector region discovery failed on page {page_num}: {e}")

            # Also include image blocks from text dict as suspicious regions.
            # This may duplicate raster extraction by design.
            try:
                blocks = page.get_text("dict").get("blocks", [])
                for block in blocks:
                    if block.get("type") == 1 and "bbox" in block:
                        rect = _rect_from_any(block["bbox"])
                        if rect is not None:
                            suspicious_regions.append(("image_block", rect))
            except Exception as e:
                logger.debug(f"Image block discovery failed on page {page_num}: {e}")

            page_rect = _rect_from_any(page.rect)
            if page_rect is not None and suspicious_regions:
                _, _, page_w, page_h = page_rect
                for region_kind, rect in suspicious_regions:
                    x0, y0, x1, y1 = rect
                    width = x1 - x0
                    height = y1 - y0

                    # Keep threshold low to avoid misses; skip only tiny noise.
                    if width < 12 or height < 12:
                        continue
                    if width * height < 144:
                        continue

                    clip_rect = _expand_rect(rect, margin=3.0, page_width=page_w, page_height=page_h)
                    fitz_rect = fitz.Rect(*clip_rect) if hasattr(fitz, "Rect") else clip_rect

                    try:
                        pix = page.get_pixmap(clip=fitz_rect, dpi=200, alpha=False)
                        image_filename = (
                            f"page{page_num:03d}_img{page_output_index:04d}_{region_kind}.png"
                        )
                        image_path = os.path.join(output_dir, image_filename)
                        pix.save(image_path)

                        size = 0
                        try:
                            size = os.path.getsize(image_path)
                        except Exception:
                            pass

                        images_info.append({
                            "page": page_num,
                            "index": page_output_index,
                            "xref": None,
                            "width": pix.width,
                            "height": pix.height,
                            "format": "png",
                            "size": size,
                            "saved_path": image_path,
                            "kind": "vector_region",
                            "region_source": region_kind,
                            "bbox": [x0, y0, x1, y1],
                        })
                        page_output_index += 1
                    except Exception as e:
                        logger.debug(
                            f"Failed rendering suspicious region on page {page_num}: {e}"
                        )
                        continue

        doc.close()

        logger.info(f"Successfully extracted {len(images_info)} images")

    except Exception as e:
        logger.error(f"Error extracting images from PDF: {e}")
        raise

    return images_info


def extract_text_with_coordinates(pdf_path: str) -> List[Dict[str, Any]]:
    """Extract text with bounding box coordinates."""
    if fitz is None:
        return []
    results = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Get text with more details
            words = page.get_text("words")  # (x0, y0, x1, y1, text, block_no, line_no, word_no)
            for word in words:
                result = {
                    "text": word[4],
                    "page": page_num,
                    "rect": [word[0], word[1], word[2], word[3]],
                }
                # Try to get font info (more complex)
                try:
                    # Get spans for font info
                    blocks = page.get_text("dict")["blocks"]
                    for block in blocks:
                        if "lines" in block:
                            for line in block["lines"]:
                                for span in line["spans"]:
                                    # This is a simplification - full matching would be better
                                    if word[4] in span["text"]:
                                        result["font"] = span.get("font", None)
                                        result["size"] = span.get("size", None)
                                        break
                except Exception:
                    pass
                results.append(result)
        doc.close()
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.debug(f"Coordinate extraction failed: {e}")
    return results


def PdfConverter(
    local_path: str,
    extract_metadata: bool = False,
    extract_sections: bool = False,
    extract_images: bool = False,
    images_output_dir: Optional[str] = None,
    fix_latex: bool = True,
    # New parameters
    render_images: bool = False,
    render_dpi: int = 200,
    render_format: str = "png",
    extract_tables: bool = False,  # Consistent naming
    extract_forms: bool = False,
    inspect_struct: bool = False,
    include_coords: bool = False,
    page_range: Optional[tuple] = None,  # New: page range for rendering/tables
) -> DocumentConverterResult:
    """
    Convert a PDF file to text format with enhanced features.

    Args:
        local_path: Path to PDF file to convert.
        extract_metadata: Whether to extract metadata (file size, etc.)
        extract_sections: Whether to extract sections from content
        extract_images: Whether to extract images from PDF (requires PyMuPDF)
        images_output_dir: Directory to save extracted images (default: temp directory)
        fix_latex: Whether to fix LaTeX formula parsing issues
        render_images: Whether to render PDF pages to images (requires PyMuPDF)
        render_dpi: DPI for rendered images (default: 200)
        render_format: Format for rendered images (default: "png")
        extract_tables: Whether to extract tables from PDF
        extract_forms: Whether to extract form fields from PDF (requires PyMuPDF)
        inspect_struct: Whether to inspect PDF structure (requires PyMuPDF)
        include_coords: Whether to extract text with coordinates (requires PyMuPDF)
        page_range: Tuple of (start_page, end_page) for rendering/tables (0-indexed)

    Returns:
        DocumentConverterResult containing extracted text and optional metadata/sections/images.
    """
    logger = logging.getLogger(__name__)

    try:
        # Try PyMuPDF first, fall back to pdfminer
        text_content = extract_text_pymupdf(local_path)
        if text_content is None:
            if pdfminer is None:
                return DocumentConverterResult(
                    title=None,
                    text_content="[Error: pdfminer-six not installed]",
                    error="pdfminer-six not installed"
                )
            text_content = pdfminer.high_level.extract_text(local_path)

        # Get PDF page count
        pdf_page_count = None
        try:
            from pdfminer.pdfparser import PDFParser
            from pdfminer.pdfdocument import PDFDocument
            from pdfminer.pdfpage import PDFPage

            with open(local_path, 'rb') as fp:
                parser = PDFParser(fp)
                document = PDFDocument(parser)
                pdf_page_count = len(list(PDFPage.create_pages(document)))
        except Exception as e:
            logger.warning(f"Could not extract PDF page count: {e}")

        # Apply LaTeX fixes if requested
        if fix_latex:
            text_content = fix_latex_formulas(text_content)

        # Apply content limit (200,000 characters)
        text_content = apply_content_limit(text_content)
        quality_info = evaluate_pdf_text_quality(text_content, pdf_page_count)
        blocks, native_page_count = extract_pdf_blocks(local_path, fix_latex=fix_latex)
        pdf_page_count = native_page_count or pdf_page_count

        # Prepare metadata
        metadata = {}
        sections = []
        images = []
        # New features
        rendered_pages = []
        extracted_tables_list = []
        form_fields = []
        structure = {}
        text_with_coords = []

        if extract_metadata:
            file_size = None
            try:
                file_size = os.path.getsize(local_path)
            except (OSError, Exception):
                pass
            metadata = {
                "file_path": local_path,
                "file_size": file_size,
                "file_extension": os.path.splitext(local_path)[1],
                "conversion_timestamp": time.time(),
                "pdf_page_count": pdf_page_count,  # Add actual PDF page count
            }
        metadata["quality_state"] = quality_info["quality_state"]
        metadata["quality_metrics"] = quality_info["quality_metrics"]
        metadata["requires_ocr"] = quality_info["requires_ocr"]
        if quality_info["quality_warning"]:
            metadata["quality_warning"] = quality_info["quality_warning"]

        if extract_sections:
            sections = extract_sections_from_markdown(text_content)

        # Extract images if requested
        if extract_images:
            if fitz is None:
                logger.warning(
                    "PyMuPDF not installed. Cannot extract images. "
                    "Install with: pip install pymupdf"
                )
                metadata["image_extraction_error"] = "PyMuPDF not installed"
            else:
                try:
                    images = extract_pdf_images(local_path, output_dir=images_output_dir)
                    logger.info(f"Extracted {len(images)} images from PDF")

                    # Add image count to metadata
                    if extract_metadata:
                        metadata["image_count"] = len(images)
                        if images_output_dir:
                            metadata["images_directory"] = images_output_dir

                except Exception as e:
                    logger.error(f"Failed to extract images: {e}")
                    metadata["image_extraction_error"] = str(e)

        # New features
        if render_images and fitz is not None:
            try:
                render_output_dir = (
                    str(Path(images_output_dir) / 'rendered_pages')
                    if images_output_dir
                    else None
                )
                rendered_pages = render_pdf_to_images(
                    local_path,
                    output_dir=render_output_dir,
                    dpi=render_dpi,
                    format=render_format,
                    page_range=page_range
                )
            except Exception as e:
                logger.error(f"Failed to render images: {e}")

        if extract_tables:
            try:
                extracted_tables_list = extract_tables(local_path, page_range=page_range)
            except Exception as e:
                logger.error(f"Failed to extract tables: {e}")

        if extract_forms and fitz is not None:
            try:
                form_result = extract_form_fields(local_path)
                if "error" not in form_result:
                    form_fields = form_result.get("fields", [])
            except Exception as e:
                logger.error(f"Failed to extract forms: {e}")

        if inspect_struct and fitz is not None:
            try:
                structure = inspect_pdf(local_path)
            except Exception as e:
                logger.error(f"Failed to inspect structure: {e}")

        if include_coords and fitz is not None:
            try:
                text_with_coords = extract_text_with_coordinates(local_path)
            except Exception as e:
                logger.error(f"Failed to extract text with coords: {e}")

        # Try to extract title from first line or metadata
        title = None
        if text_content:
            first_line = text_content.split('\n')[0].strip()
            if first_line and len(first_line) < 200:  # Reasonable title length
                title = first_line

        return DocumentConverterResult(
            title=title,
            text_content=text_content,
            metadata=metadata,
            sections=sections,
            tables=[],  # Keep for backward compatibility (empty)
            images=images,
            processing_time_ms=None,
            # New fields
            rendered_pages=rendered_pages,
            extracted_tables=extracted_tables_list,
            form_fields=form_fields,
            structure=structure,
            text_with_coords=text_with_coords,
            blocks=blocks,
            pagination_info={"page_count": pdf_page_count},
        )

    except Exception as e:
        logger.error(f"Error converting PDF: {e}")
        return DocumentConverterResult(
            title=None,
            text_content=f"Error converting PDF: {str(e)}",
            error=str(e)
        )
