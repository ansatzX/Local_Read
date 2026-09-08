import json
import logging
import os
import time
import zipfile

from .base import (
    DocumentConverterResult,
    IMAGE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from ._compat import pdfminer, MarkItDown
from .utils import apply_content_limit
from .simple import TextConverter, JsonConverter, YamlConverter, CsvConverter, MarkItDownConverter
from .docx import DocxConverter
from .xlsx import XlsxConverter
from .html import HtmlConverter
from .pptx import PptxConverter
from .pdf import PdfConverter


def ZipConverter(local_path: str, **kwargs):
    """
    Extracts ZIP files to a temporary directory and processes each file according to its extension.
    Returns a combined result of all processed files.
    """
    logger = logging.getLogger(__name__)

    from pathlib import Path as _P
    base = _P.cwd() / ".local_read_mcp"
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    temp_dir = str(base / f"zip_extract_{ts}")
    os.makedirs(temp_dir, exist_ok=True)
    md_content = f"# Extracted from ZIP: {os.path.basename(local_path)}\n\n"

    try:
        with zipfile.ZipFile(local_path, "r") as zip_ref:
            # Security fix: prevent path traversal
            for member in zip_ref.infolist():
                # Check for path traversal
                member_path = os.path.normpath(member.filename)
                if member_path.startswith('..') or os.path.isabs(member_path):
                    logger.warning(f"Skipping potentially malicious file: {member.filename}")
                    continue
                # Extract safely
                zip_ref.extract(member, temp_dir)

        # Get all extracted files
        extracted_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_dir)
                extracted_files.append((file_path, rel_path))

        if not extracted_files:
            md_content += "The ZIP file is empty or contains no files.\n"
        else:
            md_content += f"Total files extracted: {len(extracted_files)}\n\n"

            for file_path, rel_path in extracted_files:
                md_content += f"## File: {rel_path}\n\n"

                # Process each file based on its extension
                file_extension = (
                    file_path.rsplit(".", maxsplit=1)[-1].lower()
                    if "." in file_path
                    else ""
                )
                file_result = None

                try:
                    # Use the same processing logic as process_input
                    if file_extension == "py":
                        with open(file_path, "r", encoding="utf-8") as f:
                            file_result = DocumentConverterResult(
                                title=None, text_content=f.read()
                            )

                    elif file_extension in [
                        "txt",
                        "md",
                        "sh",
                        "yaml",
                        "yml",
                        "toml",
                        "csv",
                    ]:
                        if file_extension == "csv":
                            file_result = CsvConverter(local_path=file_path)
                        elif file_extension in ["yaml", "yml"]:
                            file_result = YamlConverter(local_path=file_path)
                        else:
                            file_result = TextConverter(local_path=file_path)

                    elif file_extension in ["jsonld", "json"]:
                        file_result = JsonConverter(local_path=file_path)

                    elif file_extension in ["xlsx", "xls"]:
                        file_result = XlsxConverter(local_path=file_path)

                    elif file_extension == "pdf":
                        if pdfminer is not None:
                            file_result = PdfConverter(local_path=file_path)
                        else:
                            with open(file_path, "rb") as f:
                                # Fallback: just note it's a PDF
                                file_result = DocumentConverterResult(
                                    title=None,
                                    text_content="[PDF file - pdfminer not available]"
                                )

                    elif file_extension in ["docx", "doc"]:
                        file_result = DocxConverter(local_path=file_path)

                    elif file_extension in ["html", "htm"]:
                        file_result = HtmlConverter(local_path=file_path)

                    elif file_extension in ["pptx", "ppt"]:
                        file_result = PptxConverter(local_path=file_path)

                    elif file_extension in IMAGE_EXTENSIONS:
                        # Media files noted but not processed (no external API for captions)
                        md_content += f"[{file_extension.upper()} file - processing not available without external API]\n\n"
                        continue

                    elif file_extension in AUDIO_EXTENSIONS:
                        # Media files noted but not processed (no external API for captions)
                        md_content += f"[{file_extension.upper()} file - processing not available without external API]\n\n"
                        continue

                    elif file_extension in VIDEO_EXTENSIONS:
                        # Media files noted but not processed (no external API for captions)
                        md_content += f"[{file_extension.upper()} file - processing not available without external API]\n\n"
                        continue

                    elif file_extension == "pdb":
                        md_content += "[PDB file - specialized format]\n\n"
                        continue

                    else:
                        # Try MarkItDown as fallback
                        try:
                            file_result = MarkItDownConverter(local_path=file_path)
                        except Exception:
                            md_content += (
                                f"[Unsupported file type: {file_extension}]\n\n"
                            )
                            continue

                    # Add the processed content
                    if file_result and getattr(file_result, "text_content", None):
                        content = file_result.text_content
                        # Limit length for each file
                        max_len = 50_000
                        if len(content) > max_len:
                            content = content[:max_len] + "\n... [Content truncated]"
                        md_content += f"```\n{content}\n```\n\n"

                except Exception as e:
                    md_content += f"[Error processing file: {str(e)}]\n\n"
                    logger.warning(f"Warning: Error processing {rel_path} from ZIP: {e}")

    finally:
        # temp_dir kept under .local_read_mcp/ for agent inspection
        pass

    # Apply content limit
    final_content = apply_content_limit(md_content.strip())

    return DocumentConverterResult(
        title="ZIP Archive Contents",
        text_content=final_content,
        metadata={"extraction_dir": temp_dir},
    )
