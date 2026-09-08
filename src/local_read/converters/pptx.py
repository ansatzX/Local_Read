import html
import os
import re

from .base import DocumentConverterResult
from ._compat import pptx
from .utils import apply_content_limit
from .html import convert_html_to_md


def PptxConverter(local_path: str, **kwargs) -> DocumentConverterResult:
    """
    Converts PPTX files to Markdown. Supports headings, tables and images with alt text.

    Args:
        local_path: Path to the PPTX file

    Returns:
        DocumentConverterResult containing the converted Markdown text
    """
    if pptx is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: python-pptx not installed]",
            error="python-pptx not installed"
        )

    try:
        def is_picture(shape):
            """Check if a shape is a picture"""
            if shape.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PICTURE:
                return True
            if shape.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PLACEHOLDER:
                if hasattr(shape, "image"):
                    return True
            return False

        def is_table(shape):
            """Check if a shape is a table"""
            if shape.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.TABLE:
                return True
            return False

        if not local_path.endswith(".pptx"):
            return DocumentConverterResult(
                title=None,
                text_content=f"Error: Expected .pptx file, got: {local_path}",
            )

        md_content = ""
        presentation = pptx.Presentation(local_path)
        slide_num = 0

        for slide in presentation.slides:
            slide_num += 1
            md_content += f"\n\n<!-- Slide number: {slide_num} -->\n"
            title = slide.shapes.title

            for shape in slide.shapes:
                # Pictures
                if is_picture(shape):
                    # https://github.com/scanny/python-pptx/pull/512#issuecomment-1713100069
                    alt_text = ""
                    try:
                        alt_text = shape._element._nvXxPr.cNvPr.attrib.get("descr", "")
                    except Exception:
                        pass
                    # A placeholder name
                    filename = re.sub(r"\W", "", shape.name) + ".jpg"
                    md_content += (
                        "\n!["
                        + (alt_text if alt_text else shape.name)
                        + "]("
                        + filename
                        + ")\n"
                    )

                # Tables
                if is_table(shape):
                    html_table = "<html><body><table>"
                    first_row = True
                    for row in shape.table.rows:
                        html_table += "<tr>"
                        for cell in row.cells:
                            if first_row:
                                html_table += "<th>" + html.escape(cell.text) + "</th>"
                            else:
                                html_table += "<td>" + html.escape(cell.text) + "</td>"
                        html_table += "</tr>"
                        first_row = False
                    html_table += "</table></body></html>"

                    md_content += (
                        "\n" + convert_html_to_md(html_table).text_content.strip() + "\n"
                    )

                # Text areas
                elif shape.has_text_frame:
                    if shape == title:
                        md_content += "# " + shape.text.lstrip() + "\n"
                    else:
                        md_content += shape.text + "\n"

            md_content = md_content.strip()
            if slide.has_notes_slide:
                md_content += "\n\n### Notes:\n"
                notes_frame = slide.notes_slide.notes_text_frame
                if notes_frame is not None:
                    md_content += notes_frame.text
                md_content = md_content.strip()

        # Apply content limit
        final_content = apply_content_limit(md_content.strip())

        # Use filename without extension as title
        filename = os.path.basename(local_path)
        title = os.path.splitext(filename)[0]

        return DocumentConverterResult(
            title=title,
            text_content=final_content,
        )

    except Exception as e:
        return DocumentConverterResult(
            title=None,
            text_content=f"Error converting PPTX: {str(e)}",
            error=str(e)
        )
