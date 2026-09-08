import logging
import os
import re
import time
import traceback
from typing import Any, Dict, List, Optional

from .base import DocumentConverterResult
from ._compat import openpyxl, get_column_letter
from .utils import apply_content_limit


def XlsxConverter(
    local_path: str,
    extract_metadata: bool = False,
    extract_tables: bool = False,
    **kwargs
) -> DocumentConverterResult:
    """
    Converts Excel files to Markdown using openpyxl with enhanced features.
    Preserves color formatting and other cell styling information.

    Args:
        local_path: Path to the Excel file
        extract_metadata: Whether to extract metadata (file size, sheet info, etc.)
        extract_tables: Whether to extract table information (currently always extracts tables)

    Returns:
        DocumentConverterResult with the Markdown representation and optional metadata
    """
    if openpyxl is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: openpyxl not installed]",
            error="openpyxl not installed"
        )

    try:
        # Load the workbook
        wb = openpyxl.load_workbook(local_path, data_only=True)
        md_content = ""

        # Prepare metadata
        metadata = {}
        tables = []

        if extract_metadata:
            # Collect workbook metadata
            sheet_names = wb.sheetnames
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
                "sheet_count": len(sheet_names),
                "sheet_names": sheet_names,
                "active_sheet": wb.active.title if wb.active else None
            }

        if extract_tables:
            # For Excel, each sheet is considered a table
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                # Get table dimensions
                min_row, min_col = 1, 1
                max_row = max(
                    (cell.row for cell in sheet._cells.values() if cell.value is not None),
                    default=0,
                )
                max_col = max(
                    (cell.column for cell in sheet._cells.values() if cell.value is not None),
                    default=0,
                )
                if max_row > 0 and max_col > 0:
                    tables.append({
                        "sheet_name": sheet_name,
                        "rows": max_row,
                        "columns": max_col,
                        "has_data": True
                    })

        # Helper function to convert RGB color to hex
        def rgb_to_hex(rgb_value):
            if not rgb_value:
                return None

            # Convert RGB value to string for processing
            rgb_string = str(rgb_value)

            # Handle RGB format like 'RGB(255, 255, 255)'
            if isinstance(rgb_value, str) and rgb_string.startswith("RGB"):
                rgb_match = re.match(r"RGB\((\d+), (\d+), (\d+)\)", rgb_string)
                if rgb_match:
                    r, g, b = map(int, rgb_match.groups())
                    return f"#{r:02x}{g:02x}{b:02x}"

            # Special handling for FFFFFFFF (white) and 00000000 (transparent/none)
            if rgb_string in ["FFFFFFFF", "00000000", "none", "auto"]:
                return None

            # Handle ARGB format (common in openpyxl)
            if len(rgb_string) == 8:  # ARGB format like 'FF5733FF'
                return f"#{rgb_string[2:]}"  # Strip alpha channel

            # Handle direct hex values like 'FF5733'
            if isinstance(rgb_value, str):
                return f"#{rgb_string}" if not rgb_string.startswith("#") else rgb_string

            return None  # Return None for unrecognized formats

        # Helper function to detect and format cell styling
        def get_cell_format_info(cell):
            info = {}

            # Get background color if it exists
            if cell.fill and hasattr(cell.fill, "fgColor") and cell.fill.fgColor:
                # Get the RGB value - in openpyxl this can be stored in different attributes
                rgb_value = None
                if hasattr(cell.fill.fgColor, "rgb") and cell.fill.fgColor.rgb:
                    rgb_value = cell.fill.fgColor.rgb
                elif hasattr(cell.fill.fgColor, "value") and cell.fill.fgColor.value:
                    rgb_value = cell.fill.fgColor.value

                if rgb_value:
                    bg_color = rgb_to_hex(rgb_value)
                    if bg_color:  # Skip transparent or white (handled in rgb_to_hex)
                        info["bg_color"] = bg_color

            # Get font color if it exists
            if cell.font and hasattr(cell.font, "color") and cell.font.color:
                # Get the RGB value - in openpyxl this can be stored in different attributes
                rgb_value = None
                if hasattr(cell.font.color, "rgb") and cell.font.color.rgb:
                    rgb_value = cell.font.color.rgb
                elif hasattr(cell.font.color, "value") and cell.font.color.value:
                    rgb_value = cell.font.color.value

                if rgb_value:
                    font_color = rgb_to_hex(rgb_value)
                    if font_color:  # Skip transparent (handled in rgb_to_hex)
                        info["font_color"] = font_color

            # Get font weight (bold)
            if cell.font and cell.font.bold:
                info["bold"] = True

            # Get font style (italic)
            if cell.font and cell.font.italic:
                info["italic"] = True

            # Get font underline
            if cell.font and cell.font.underline and cell.font.underline != "none":
                info["underline"] = True

            return info

        # Process each sheet in the workbook
        for sheet_name in wb.sheetnames:
            try:
                sheet = wb[sheet_name]
                md_content += f"## {sheet_name}\n\n"

                # Get the dimensions of the used part of the sheet
                min_row, min_col = 1, 1
                max_row = max(
                    (cell.row for cell in sheet._cells.values() if cell.value is not None),
                    default=0,
                )
                max_col = max(
                    (
                        cell.column
                        for cell in sheet._cells.values()
                        if cell.value is not None
                    ),
                    default=0,
                )

                if max_row == 0 or max_col == 0:
                    md_content += "This sheet is empty.\n\n"
                    continue
            except Exception as e:
                error_msg = f"Error processing sheet '{sheet_name}': {str(e)}"
                logging.warning(error_msg)
                md_content += (
                    f"## {sheet_name}\n\nError processing this sheet: {str(e)}\n\n"
                )
                continue

            try:
                # First, determine column widths
                col_widths = {}
                for col_idx in range(min_col, max_col + 1):
                    max_length = 0
                    for row_idx in range(min_row, max_row + 1):
                        try:
                            cell = sheet.cell(row=row_idx, column=col_idx)
                            cell_value = str(cell.value) if cell.value is not None else ""
                            max_length = max(max_length, len(cell_value))
                        except Exception as e:
                            logging.warning(
                                f"Warning: Error processing cell at row {row_idx}, column {col_idx}: {str(e)}"
                            )
                            max_length = max(max_length, 10)  # Use reasonable default
                    col_widths[col_idx] = max(max_length + 2, 5)  # Min width of 5

                # Start building the table
                # Header row with column separators
                md_content += "|"
                for col_idx in range(min_col, max_col + 1):
                    md_content += " " + " " * col_widths[col_idx] + " |"
                md_content += "\n"

                # Separator row
                md_content += "|"
                for col_idx in range(min_col, max_col + 1):
                    md_content += ":" + "-" * col_widths[col_idx] + ":|"
                md_content += "\n"

                # Data rows
                for row_idx in range(min_row, max_row + 1):
                    md_content += "|"
                    for col_idx in range(min_col, max_col + 1):
                        try:
                            cell = sheet.cell(row=row_idx, column=col_idx)
                            cell_value = str(cell.value) if cell.value is not None else ""

                            # Get formatting info
                            try:
                                format_info = get_cell_format_info(cell)
                            except Exception as e:
                                logging.warning(
                                    f"Warning: Error getting formatting for cell at row {row_idx}, column {col_idx}: {str(e)}"
                                )
                                format_info = {}

                            formatted_value = cell_value

                            # Add HTML-style formatting if needed
                            if format_info:
                                style_parts = []

                                if "bg_color" in format_info:
                                    style_parts.append(
                                        f"background-color:{format_info['bg_color']}"
                                    )

                                if "font_color" in format_info:
                                    style_parts.append(f"color:{format_info['font_color']}")

                                span_attributes = []
                                if style_parts:
                                    span_attributes.append(
                                        f'style="{"; ".join(style_parts)}"'
                                    )

                                # Format with bold/italic/underline if needed
                                inner_value = cell_value
                                if "bold" in format_info:
                                    inner_value = f"<strong>{inner_value}</strong>"
                                if "italic" in format_info:
                                    inner_value = f"<em>{inner_value}</em>"
                                if "underline" in format_info:
                                    inner_value = f"<u>{inner_value}</u>"

                                # Only add a span if we have style attributes
                                if span_attributes:
                                    formatted_value = f"<span {' '.join(span_attributes)}>{inner_value}</span>"
                                else:
                                    formatted_value = inner_value

                            # Pad to column width and add to markdown
                            padding = col_widths[col_idx] - len(cell_value)
                            padded_value = " " + formatted_value + " " * (padding + 1)
                            md_content += padded_value + "|"
                        except Exception as e:
                            logging.warning(
                                f"Error processing cell at row {row_idx}, column {col_idx}: {str(e)}"
                            )
                            # Add a placeholder for the failed cell
                            padded_value = " [Error] " + " " * (col_widths[col_idx] - 7)
                            md_content += padded_value + " |"

                    md_content += "\n"
            except Exception as e:
                error_msg = f"Error generating table for sheet '{sheet_name}': {str(e)}\n{traceback.format_exc()}"
                logging.warning(error_msg)
                md_content += f"Error generating table: {str(e)}\n\n"

            # Add formatting legend
            has_formatting = False
            for row_idx in range(min_row, max_row + 1):
                for col_idx in range(min_col, max_col + 1):
                    cell = sheet.cell(row=row_idx, column=col_idx)
                    if get_cell_format_info(cell):
                        has_formatting = True
                        break
                if has_formatting:
                    break

            if has_formatting:
                md_content += "\n### Formatting Information\n"
                md_content += "The table above includes HTML formatting to represent colors and styles from the original Excel file.\n"
                md_content += "This formatting may not display in all Markdown viewers.\n"

            md_content += "\n\n"  # Extra newlines between sheets

        # Apply content limit
        final_content = apply_content_limit(md_content.strip())

        # Use filename without extension as title
        filename = os.path.basename(local_path)
        title = os.path.splitext(filename)[0]

        return DocumentConverterResult(
            title=title,
            text_content=final_content,
            metadata=metadata,
            sections=[],  # Excel doesn't have sections in markdown sense
            tables=tables,
            processing_time_ms=None  # Can be calculated by caller
        )

    except Exception as e:
        return DocumentConverterResult(
            title=None,
            text_content=f"Error converting Excel: {str(e)}",
            error=str(e)
        )
