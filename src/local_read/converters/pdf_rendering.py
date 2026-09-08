import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from ._compat import fitz

logger = logging.getLogger(__name__)


def _local_tmp_dir(prefix: str) -> str:
    """Create a temp directory under .local_read_mcp/ instead of system /tmp."""
    base = Path.cwd() / ".local_read_mcp"
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    d = base / f"{prefix}{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def render_pdf_to_images(
    pdf_path: str,
    output_dir: Optional[str] = None,
    dpi: int = 200,
    page_range: Optional[Tuple[int, int]] = None,
    format: str = "png"
) -> List[Dict[str, Any]]:
    """Render PDF pages to images using PyMuPDF.

    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save images (default: .local_read_mcp/ dir)
        dpi: DPI for rendering (default: 200)
        page_range: Tuple (start_page, end_page) 0-indexed, None for all
        format: Output format (png, jpeg)

    Returns:
        List of rendered page info dicts
    """
    if fitz is None:
        return [{"error": "PyMuPDF (fitz) not installed"}]

    # Create output directory
    if output_dir is None:
        output_dir = _local_tmp_dir("pdf_render_")
    else:
        os.makedirs(output_dir, exist_ok=True)

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

        # Render each page
        for page_num in range(start_page, end_page):
            page = doc[page_num]

            # Calculate zoom based on DPI
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)

            # Render page
            pix = page.get_pixmap(matrix=matrix)

            # Save image
            ext = format.lower()
            if ext not in ["png", "jpeg", "jpg"]:
                ext = "png"
            if ext == "jpg":
                ext = "jpeg"

            filename = f"page{page_num:03d}.{ext}"
            filepath = os.path.join(output_dir, filename)

            if ext == "png":
                pix.save(filepath)
            else:
                pix.save(filepath, output="jpeg")

            images_info.append({
                "page": page_num + 1,  # 1-indexed for users
                "path": filepath,
                "width": pix.width,
                "height": pix.height,
                "dpi": dpi
            })

            logger.debug(f"Rendered page {page_num + 1}: {filepath} ({pix.width}x{pix.height})")

        doc.close()
        return images_info

    except Exception as e:
        logger.error(f"Error rendering PDF: {e}")
        return [{"error": str(e)}]
