"""Batch vision analysis helpers with file-content based caching."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .vision import (
    analyze_image_with_config,
    build_cache_key,
    ensure_analysis_dir,
    save_analysis_markdown,
    validate_image_file,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
_INFLIGHT_LOCK = asyncio.Lock()
_INFLIGHT_BY_KEY: dict[str, asyncio.Task[dict[str, Any]]] = {}


def _cache_path(cache_key: str) -> Path:
    return ensure_analysis_dir() / f"cache_{cache_key}.json"


def _read_cache(cache_key: str) -> dict[str, Any] | None:
    path = _cache_path(cache_key)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed to read vision batch cache %s: %s", path, exc)
        return None

    try:
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("Failed to parse vision batch cache %s: %s", path, exc)
        return None

    if not isinstance(parsed, dict):
        logger.warning("Vision batch cache is not a dict: %s", path)
        return None
    return parsed


def _write_cache(cache_key: str, payload: dict[str, Any]) -> None:
    path = _cache_path(cache_key)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        logger.warning("Failed to write vision batch cache %s: %s", path, exc)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


async def _analyze_and_persist_uncached(
    image_path: str,
    question: str,
    api_key: str,
    base_url: str,
    model: str,
    max_size_mb: int,
    cache_key: str,
) -> dict[str, Any]:
    result = await analyze_image_with_config(
        image_path=image_path,
        question=question,
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_size_mb=max_size_mb,
    )

    if not result.get("success"):
        return {"success": False, "error": result.get("error", "Unknown vision analysis error")}

    analysis = result["analysis"]
    saved_path = save_analysis_markdown(
        image_path=image_path,
        question=question,
        result_text=analysis,
        suffix="batch",
        unique_key=cache_key,
    )

    _write_cache(
        cache_key=cache_key,
        payload={
            "image_path": image_path,
            "question": question,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "analysis": analysis,
            "saved_path": saved_path,
        },
    )

    return {"success": True, "analysis": analysis, "saved_path": saved_path}


async def _get_or_create_inflight(
    cache_key: str,
    image_path: str,
    question: str,
    api_key: str,
    base_url: str,
    model: str,
    max_size_mb: int,
) -> tuple[asyncio.Task[dict[str, Any]], bool]:
    async with _INFLIGHT_LOCK:
        task = _INFLIGHT_BY_KEY.get(cache_key)
        if task is not None:
            return task, False

        task = asyncio.create_task(
            _analyze_and_persist_uncached(
                image_path=image_path,
                question=question,
                api_key=api_key,
                base_url=base_url,
                model=model,
                max_size_mb=max_size_mb,
                cache_key=cache_key,
            )
        )
        _INFLIGHT_BY_KEY[cache_key] = task
        return task, True


async def _analyze_one_with_cache(
    image_path: str,
    question: str,
    api_key: str,
    base_url: str,
    model: str,
    max_size_mb: int,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"image_path": image_path, "cache_hit": False}

    validation_error = validate_image_file(image_path=image_path, max_size_mb=max_size_mb)
    if validation_error:
        entry["error"] = validation_error
        return entry

    try:
        cache_key = build_cache_key(
            image_path=image_path,
            question=question,
            model=model,
            prompt_version=PROMPT_VERSION,
        )
    except Exception as exc:
        entry["error"] = f"Error: failed to build cache key: {exc}"
        return entry

    cached = _read_cache(cache_key)
    if cached and isinstance(cached.get("analysis"), str):
        entry["analysis"] = cached["analysis"]
        entry["cache_hit"] = True
        if cached.get("saved_path"):
            entry["saved_path"] = cached["saved_path"]
        return entry

    task, created = await _get_or_create_inflight(
        cache_key=cache_key,
        image_path=image_path,
        question=question,
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_size_mb=max_size_mb,
    )
    try:
        uncached_result = await task
    finally:
        if created:
            async with _INFLIGHT_LOCK:
                if _INFLIGHT_BY_KEY.get(cache_key) is task:
                    _INFLIGHT_BY_KEY.pop(cache_key, None)

    if not uncached_result.get("success"):
        entry["error"] = uncached_result.get("error", "Unknown vision analysis error")
        return entry

    entry["analysis"] = uncached_result["analysis"]
    entry["saved_path"] = uncached_result["saved_path"]
    if not created:
        entry["cache_hit"] = True
    return entry


async def analyze_images_batch_with_cache(
    image_paths: list[str],
    question: str,
    batch_size: int,
    api_key: str,
    base_url: str,
    model: str,
    max_size_mb: int,
) -> dict[str, Any]:
    """Analyze a list of images in batches while preserving input order."""
    if batch_size <= 0:
        batch_size = 1

    results: list[dict[str, Any]] = []
    for start in range(0, len(image_paths), batch_size):
        batch = image_paths[start:start + batch_size]
        batch_results: list[dict[str, Any]] = []
        for image_path in batch:
            batch_results.append(
                await _analyze_one_with_cache(
                    image_path=image_path,
                    question=question,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    max_size_mb=max_size_mb,
                )
            )
        results.extend(batch_results)

    return {
        "success": True,
        "question": question,
        "batch_size": batch_size,
        "results": results,
    }
