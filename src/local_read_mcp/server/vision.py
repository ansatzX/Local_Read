"""Vision-related functionality for the Local Read MCP Server."""

import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def guess_mime_type_from_extension(file_path: str) -> str:
    """Guess MIME type based on file extension."""
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    mime_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
    }
    return mime_types.get(ext, "image/jpeg")


async def call_vision_api(
    image_path: str,
    question: str,
    api_key: str,
    base_url: str,
    model: str
) -> str:
    """Call OpenAI-compatible vision API (Doubao, GPT-4o, etc.)."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return "Error: openai package not installed. Install with: pip install openai"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    mime_type = guess_mime_type_from_extension(image_path)

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}}
        ]
    }]

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Vision API error: {e}")
        return f"Error: Vision API call failed: {str(e)}"


def ensure_analysis_dir() -> Path:
    """Ensure the analysis output directory exists and return it."""
    analysis_dir = Path.cwd() / ".local_read_mcp" / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir


def validate_image_file(image_path: str, max_size_mb: int) -> Optional[str]:
    """Validate image existence and size. Returns error message when invalid."""
    if not os.path.exists(image_path):
        return f"Image file not found: {image_path}"

    file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
    if file_size_mb > max_size_mb:
        return f"Image too large ({file_size_mb:.2f}MB). Maximum: {max_size_mb}MB"

    return None


def build_image_stem(image_path: str) -> str:
    """Build a safe stem name from image path."""
    image_name = Path(image_path).stem
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in image_name)


def build_cache_key(image_path: str, question: str, model: str, prompt_version: str = "v1") -> str:
    """Build cache key based on image content, question, model and prompt version."""
    with open(image_path, "rb") as f:
        image_hash = hashlib.sha256(f.read()).hexdigest()
    key_src = json.dumps(
        {
            "image_hash": image_hash,
            "question": question,
            "model": model,
            "prompt_version": prompt_version,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(key_src.encode("utf-8")).hexdigest()


def save_analysis_markdown(
    image_path: str,
    question: str,
    result_text: str,
    suffix: str | None = None,
    unique_key: str | None = None,
) -> str:
    """Persist an analysis markdown file and return path."""
    analysis_dir = ensure_analysis_dir()
    image_name = Path(image_path).stem
    safe_name = build_image_stem(image_path)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    unique_part = (unique_key or f"{time.time_ns():x}")[:12]
    suffix_part = f"_{suffix}" if suffix else ""
    result_filename = f"{safe_name}{suffix_part}_{timestamp}_{unique_part}.md"
    result_path = analysis_dir / result_filename

    with open(result_path, "w", encoding="utf-8") as f:
        f.write(f"# Image Analysis: {image_name}\n\n")
        f.write(f"- **Source**: `{image_path}`\n")
        f.write(f"- **Question**: {question}\n")
        f.write(f"- **Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Analysis\n\n")
        f.write(result_text)
        f.write("\n")

    return str(result_path)


async def analyze_image_with_config(
    image_path: str,
    question: str,
    api_key: str,
    base_url: str,
    model: str,
    max_size_mb: int,
) -> dict[str, Any]:
    """Validate and analyze one image via the configured vision API."""
    error = validate_image_file(image_path, max_size_mb=max_size_mb)
    if error:
        return {"success": False, "error": error}

    result_text = await call_vision_api(
        image_path=image_path,
        question=question,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    if isinstance(result_text, str) and result_text.startswith("Error:"):
        return {"success": False, "error": result_text}

    return {"success": True, "analysis": result_text}
