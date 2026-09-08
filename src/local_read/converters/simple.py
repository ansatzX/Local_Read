import csv
import json
import os

from .base import DocumentConverterResult
from ._compat import yaml, MarkItDown


def TextConverter(local_path: str, **kwargs) -> DocumentConverterResult:
    """
    Read a text file.

    Args:
        local_path: Path to text file to read.
        **kwargs: Additional keyword arguments (ignored)

    Returns:
        DocumentConverterResult containing text content.
    """
    with open(local_path, "r", encoding="utf-8") as f:
        text_content = f.read()
    return DocumentConverterResult(title=None, text_content=text_content)


def JsonConverter(local_path: str, **kwargs) -> DocumentConverterResult:
    """
    Read and format a JSON file.

    Args:
        local_path: Path to JSON file to read.
        **kwargs: Additional keyword arguments (ignored)

    Returns:
        DocumentConverterResult containing formatted JSON.
    """
    with open(local_path, "r", encoding="utf-8") as f:
        text_content = json.dumps(
            json.load(f), ensure_ascii=False, indent=2
        )
    return DocumentConverterResult(title=None, text_content=text_content)


def YamlConverter(local_path: str, **kwargs) -> DocumentConverterResult:
    """
    Read a YAML file.

    Args:
        local_path: Path to YAML file to read.
        **kwargs: Additional keyword arguments (ignored)

    Returns:
        DocumentConverterResult containing YAML content.
    """
    if yaml is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: pyyaml not installed]"
        )

    with open(local_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        text_content = yaml.dump(data, allow_unicode=True, default_flow_style=False)
    return DocumentConverterResult(title=None, text_content=text_content)


def CsvConverter(local_path: str, **kwargs) -> DocumentConverterResult:
    """
    Convert a CSV file to markdown table format.

    Args:
        local_path: Path to CSV file to convert.
        **kwargs: Additional keyword arguments (ignored)

    Returns:
        DocumentConverterResult containing markdown table.
    """
    with open(local_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return DocumentConverterResult(title=None, text_content="Empty CSV file")

    md_content = ""
    for i, row in enumerate(rows):
        md_content += "| " + " | ".join(row) + " |\n"
        if i == 0:  # Add a separator after header
            md_content += "|" + "---|" * len(row) + "\n"

    return DocumentConverterResult(title=None, text_content=md_content)


def MarkItDownConverter(local_path: str, **kwargs) -> DocumentConverterResult:
    """
    Convert a file using MarkItDown library (universal converter).

    Args:
        local_path: Path to file to convert.
        **kwargs: Additional keyword arguments (ignored)

    Returns:
        DocumentConverterResult containing converted markdown.
    """
    if MarkItDown is None:
        return DocumentConverterResult(
            title=None,
            text_content="[Error: markitdown not installed]"
        )

    md = MarkItDown(enable_plugins=True)
    result = md.convert(local_path)
    text_content = result.text_content if hasattr(result, 'text_content') else ""
    title = result.title if hasattr(result, 'title') else None
    return DocumentConverterResult(title=title, text_content=text_content)
