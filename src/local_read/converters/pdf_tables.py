import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Optional import - pdfplumber
try:
    import pdfplumber
except ImportError:
    pdfplumber = None


def extract_tables(
    pdf_path: str,
    page_range: Optional[Tuple[int, int]] = None
) -> List[Dict[str, Any]]:
    """Extract tables from PDF using pdfplumber.

    Args:
        pdf_path: Path to PDF file
        page_range: Tuple (start_page, end_page) 0-indexed, None for all

    Returns:
        List of table info dicts
    """
    if pdfplumber is None:
        return [{
            "error": "pdfplumber not installed. Install with: uv pip install 'local_read[pdf]'"
        }]

    tables = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Determine page range
            start_page = 0
            end_page = len(pdf.pages)
            if page_range:
                start_page, end_page = page_range
                start_page = max(0, start_page)
                end_page = min(len(pdf.pages), end_page)

            for page_num in range(start_page, end_page):
                page = pdf.pages[page_num]
                page_tables = page.extract_tables()

                for table_idx, table in enumerate(page_tables):
                    if not table or len(table) == 0:
                        continue

                    # Clean up table (remove None/empty values)
                    cleaned_table = []
                    for row in table:
                        cleaned_row = [cell.strip() if cell else "" for cell in row]
                        cleaned_table.append(cleaned_row)

                    # Generate markdown table
                    headers = cleaned_table[0] if cleaned_table else []
                    rows = cleaned_table[1:] if len(cleaned_table) > 1 else []

                    markdown = ""
                    if headers:
                        markdown = "| " + " | ".join(str(h) for h in headers) + " |\n"
                        markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                        for row in rows:
                            markdown += "| " + " | ".join(str(cell) for cell in row) + " |\n"

                    tables.append({
                        "page": page_num + 1,  # 1-indexed
                        "table_index": table_idx,
                        "headers": headers,
                        "rows": rows,
                        "markdown": markdown.strip()
                    })

        return tables

    except Exception as e:
        logger.error(f"Error extracting tables: {e}")
        return [{"error": str(e)}]
