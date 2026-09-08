import logging
from typing import Dict, Any, List, Optional
from ._compat import fitz

logger = logging.getLogger(__name__)


def extract_form_fields(pdf_path: str) -> Dict[str, Any]:
    """Extract all form fields with their values, types, and positions.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dictionary with form fields and info
    """
    if fitz is None:
        return {"error": "PyMuPDF (fitz) not installed"}

    try:
        doc = fitz.open(pdf_path)

        fields = []
        field_names = set()

        # Check if PDF has form
        if not doc.is_form_pdf:
            doc.close()
            return {
                "fields": [],
                "has_acroform": False,
                "is_fillable": False
            }

        # Iterate through pages to find fields
        for page_num in range(len(doc)):
            page = doc[page_num]

            # Get all widgets (form fields) on page
            widgets = page.widgets()
            if widgets is None:
                continue

            for widget in widgets:
                field_name = widget.field_name or f"field_{len(fields)}"

                # Handle duplicate field names
                base_name = field_name
                counter = 1
                while field_name in field_names:
                    field_name = f"{base_name}_{counter}"
                    counter += 1
                field_names.add(field_name)

                # Get field type
                field_type = widget.field_type
                type_name = {
                    fitz.PDF_WIDGET_TYPE_TEXT: "text",
                    fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
                    fitz.PDF_WIDGET_TYPE_RADIO: "radio",
                    fitz.PDF_WIDGET_TYPE_COMBOBOX: "combobox",
                    fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox",  # Fixed typo: PIDF -> PDF
                    fitz.PDF_WIDGET_TYPE_BUTTON: "button",
                }.get(field_type, "unknown")

                # Get field value
                field_value = widget.field_value

                # Get rectangle
                rect = widget.rect
                rect_list = [rect.x0, rect.y0, rect.x1, rect.y1]

                field_info = {
                    "name": field_name,
                    "type": type_name,
                    "value": field_value,
                    "rect": rect_list,
                    "page": page_num,
                    "required": widget.field_flags & fitz.PDF_FIELD_FLAG_REQUIRED != 0,
                    "read_only": widget.field_flags & fitz.PDF_FIELD_FLAG_READ_ONLY != 0,
                }

                # Add choices for combo/list boxes
                if type_name in ["combobox", "listbox"]:
                    field_info["choices"] = widget.choice_values or []

                fields.append(field_info)

        doc.close()

        return {
            "fields": fields,
            "has_acroform": True,
            "is_fillable": len(fields) > 0
        }

    except Exception as e:
        logger.error(f"Error extracting form fields: {e}")
        return {"error": str(e)}
