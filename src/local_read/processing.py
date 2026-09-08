# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
Local_Read processing service, independent of any agent protocol.
Converts documents to markdown/text without requiring external APIs.
"""

import json
import logging
import os
import re
import hashlib
from pathlib import Path
from typing import Any


from .backends import BackendType, get_registry
from .config import get_config as _get_config
from .converters.pdf import evaluate_pdf_text_quality, get_pdf_quality_warning
from .output_manager import OutputManager
from .index_generator import IndexGenerator
from .markdown_converter import MarkdownConverter
from .orchestrator import (
    merge_chunk_intermediates,
    merge_chunk_markdowns,
    plan_chunks,
    process_and_save,
    resolve_page_range,
    save_structural_toc,
)
from .vision import analyze_image_with_config, save_analysis_markdown
from .vision_batch import analyze_images_batch_with_cache

logger = logging.getLogger(__name__)


# Initialize config to check if vision features should be enabled
_config = _get_config()
VISION_ENABLED = _config.vision_enabled

if VISION_ENABLED:
    logger.info(f"Vision features ENABLED (model: {_config.model})")
else:
    logger.info("Vision features DISABLED - configure VISION_API_KEY or OPENAI_API_KEY in .env file to enable")


_FORMAT_BY_EXTENSION: dict[str, str] = {
    # Text formats
    ".txt": "text",
    ".md": "text",
    ".py": "text",
    ".sh": "text",
    ".log": "text",
    ".rst": "text",
    ".json": "json",
    ".csv": "csv",
    ".yaml": "yaml",
    ".yml": "yaml",
    # Binary/document formats
    ".pdf": "pdf",
    ".docx": "word",
    ".doc": "word",
    ".xlsx": "excel",
    ".xls": "excel",
    ".pptx": "ppt",
    ".ppt": "ppt",
    ".html": "html",
    ".htm": "html",
    ".zip": "zip",
}

def detect_format(file_path: str) -> str | None:
    """Detect file format from extension.

    Returns:
        Format string or None for unknown (use markitdown fallback)
    """
    ext = os.path.splitext(file_path)[1].lower()

    return _FORMAT_BY_EXTENSION.get(ext)


_IMAGE_NAME_PATTERN = re.compile(r"page(\d+)_img(\d+)", re.IGNORECASE)
_IMAGE_KIND_PATTERN = re.compile(r"page\d+_img\d+_([a-zA-Z0-9_]+)\.", re.IGNORECASE)
_FIGURE_REF_PATTERN = re.compile(r"\bFigure\s+(\d+)\b", re.IGNORECASE)
_CHUNK_HEADER_PATTERN = re.compile(r"^# .*\(pages\s+(\d+)[–-](\d+)\)\s*$")
_FIGURE_CAPTION_PATTERN = re.compile(r"^\s*\*{0,2}(?:Figure|Fig\.?)\s+(\d+)\s*[:.\-]\s*(.+?)\s*\*{0,2}\s*$", re.IGNORECASE)


def _build_image_metadata(
    image_files: list[Path],
    phys_start: int,
    phys_end: int,
    chunk_index: int | None = None,
    chunk_title: str | None = None,
) -> list[dict[str, Any]]:
    """Build image metadata from extracted file paths."""
    metadata: list[dict[str, Any]] = []
    for image_path in sorted(image_files, key=lambda p: p.name):
        item: dict[str, Any] = {
            "path": str(image_path),
            "phys_start": phys_start,
            "phys_end": phys_end,
        }
        if chunk_index is not None:
            item["chunk_index"] = chunk_index
        if chunk_title:
            item["chunk_title"] = chunk_title

        match = _IMAGE_NAME_PATTERN.search(image_path.name)
        if match:
            page_in_chunk = int(match.group(1))
            image_index_in_page = int(match.group(2))
            item["page_in_chunk"] = page_in_chunk
            item["image_index_in_page"] = image_index_in_page
            # Convert 0-based physical page index to human-readable 1-based page number.
            item["estimated_pdf_page"] = phys_start + page_in_chunk + 1

        kind_match = _IMAGE_KIND_PATTERN.search(image_path.name)
        if kind_match:
            token = kind_match.group(1).lower()
            if token == "raster":
                item["kind"] = "raster"
            elif token in {"cluster", "drawing", "image_block"}:
                item["kind"] = "vector_region"
                item["region_source"] = token
            else:
                item["kind"] = token
        else:
            item["kind"] = "unknown"

        metadata.append(item)

    return metadata


def _extract_figure_references(markdown: str) -> list[int]:
    """Extract unique figure numbers referenced in markdown text."""
    figure_numbers = {int(m.group(1)) for m in _FIGURE_REF_PATTERN.finditer(markdown or "")}
    return sorted(figure_numbers)


def _compute_sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _compute_image_phash(path: str, hash_size: int = 8) -> str | None:
    """Compute a lightweight perceptual hash (dHash) for an image."""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None

    try:
        with Image.open(path) as img:
            gray = img.convert("L").resize((hash_size + 1, hash_size))
            pixels = list(gray.getdata())
    except Exception:
        return None

    bits: list[int] = []
    width = hash_size + 1
    for row in range(hash_size):
        offset = row * width
        for col in range(hash_size):
            left = pixels[offset + col]
            right = pixels[offset + col + 1]
            bits.append(1 if left > right else 0)

    value = 0
    for bit in bits:
        value = (value << 1) | bit
    hex_len = (hash_size * hash_size) // 4
    return f"{value:0{hex_len}x}"


def _phash_hamming_distance(left: str, right: str) -> int | None:
    if not left or not right or len(left) != len(right):
        return None
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except Exception:
        return None


def _classify_candidate_labels(item: dict[str, Any]) -> list[str]:
    labels: set[str] = set()
    kind = str(item.get("kind", "unknown"))
    region_source = str(item.get("region_source", "")).lower()
    path_text = str(item.get("path", "")).lower()

    if kind == "raster":
        labels.add("figure_like")
    elif kind == "vector_region":
        if region_source == "image_block":
            labels.add("figure_like")
        elif region_source in {"drawing", "cluster"}:
            labels.add("unknown")
    else:
        labels.add("unknown")

    if "table" in path_text:
        labels.add("table_like")
    if "formula" in path_text or "math" in path_text:
        labels.add("formula_like")
    if "icon" in path_text:
        labels.add("icon_like")

    if not labels:
        labels.add("unknown")
    return sorted(labels)


def _extract_figure_slots(markdown: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    if not markdown:
        return slots

    current_page_hint: int | None = None
    lines = markdown.splitlines()

    for line_no, line in enumerate(lines, start=1):
        header_match = _CHUNK_HEADER_PATTERN.match(line.strip())
        if header_match:
            current_page_hint = int(header_match.group(1))
            continue

        caption_match = _FIGURE_CAPTION_PATTERN.match(line)
        if caption_match:
            slots.append(
                {
                    "slot_id": f"slot_{len(slots) + 1:04d}",
                    "figure_number": int(caption_match.group(1)),
                    "caption": caption_match.group(2).strip(),
                    "line_no": line_no,
                    "page_hint": current_page_hint,
                }
            )
            continue

        for ref in _FIGURE_REF_PATTERN.finditer(line):
            slots.append(
                {
                    "slot_id": f"slot_{len(slots) + 1:04d}",
                    "figure_number": int(ref.group(1)),
                    "caption": "",
                    "line_no": line_no,
                    "page_hint": current_page_hint,
                }
            )

    return slots


def _build_image_manifest(image_metadata: list[dict[str, Any]], markdown: str) -> dict[str, Any]:
    ordered_items = sorted(
        image_metadata,
        key=lambda m: (
            int(m.get("estimated_pdf_page", m.get("phys_start", 0) + 1)),
            int(m.get("page_in_chunk", 0)),
            int(m.get("image_index_in_page", 0)),
            str(m.get("path", "")),
        ),
    )

    groups: dict[str, dict[str, Any]] = {}
    unknown_key_index = 0
    phash_seen = False
    for idx, item in enumerate(ordered_items):
        source_path = str(item.get("linked_path") or item.get("path") or "")
        checksum = _compute_sha256(source_path) if source_path else None
        phash = _compute_image_phash(source_path) if source_path else None
        if phash:
            phash_seen = True
        if checksum is None:
            unknown_key_index += 1
            checksum = f"missing_{unknown_key_index:06d}"

        occurrence = {
            "path": str(item.get("path", "")),
            "linked_path": str(item.get("linked_path", "")) if item.get("linked_path") else None,
            "kind": str(item.get("kind", "unknown")),
            "region_source": item.get("region_source"),
            "chunk_index": item.get("chunk_index"),
            "chunk_title": item.get("chunk_title"),
            "estimated_pdf_page": item.get("estimated_pdf_page"),
            "page_in_chunk": item.get("page_in_chunk"),
            "image_index_in_page": item.get("image_index_in_page"),
            "order_index": idx,
            "labels": _classify_candidate_labels(item),
            "phash": phash,
        }

        if checksum not in groups:
            groups[checksum] = {
                "checksum_sha256": checksum if not checksum.startswith("missing_") else None,
                "phash": phash,
                "representative_path": occurrence["linked_path"] or occurrence["path"],
                "kinds": sorted({occurrence["kind"]}),
                "labels": occurrence["labels"][:],
                "occurrences": [occurrence],
            }
        else:
            g = groups[checksum]
            g["occurrences"].append(occurrence)
            g["kinds"] = sorted(set(g.get("kinds", [])) | {occurrence["kind"]})
            g["labels"] = sorted(set(g.get("labels", [])) | set(occurrence["labels"]))
            if g.get("phash") is None and phash is not None:
                g["phash"] = phash

    canonical_images: list[dict[str, Any]] = []
    for idx, group in enumerate(
        sorted(
            groups.values(),
            key=lambda g: (
                int(g["occurrences"][0].get("estimated_pdf_page") or 10**9),
                int(g["occurrences"][0].get("order_index", 0)),
            ),
        ),
        start=1,
    ):
        first = group["occurrences"][0]
        canonical_images.append(
            {
                "canonical_image_id": f"image_{idx:04d}",
                "checksum_sha256": group["checksum_sha256"],
                "phash": group.get("phash"),
                "representative_path": group["representative_path"],
                "kinds": group["kinds"],
                "labels": group["labels"],
                "first_seen": {
                    "page": first.get("estimated_pdf_page"),
                    "y": None,
                    "x": None,
                    "order_index": first.get("order_index"),
                },
                "occurrences": group["occurrences"],
            }
        )

    near_duplicate_groups: list[dict[str, Any]] = []
    if phash_seen and canonical_images:
        threshold = 8
        visited: set[int] = set()
        for i, anchor in enumerate(canonical_images):
            if i in visited:
                continue
            a_hash = anchor.get("phash")
            if not isinstance(a_hash, str):
                continue
            members = [i]
            for j in range(i + 1, len(canonical_images)):
                b_hash = canonical_images[j].get("phash")
                if not isinstance(b_hash, str):
                    continue
                dist = _phash_hamming_distance(a_hash, b_hash)
                if dist is not None and dist <= threshold:
                    members.append(j)
            if len(members) <= 1:
                continue
            for midx in members:
                visited.add(midx)
            near_duplicate_groups.append(
                {
                    "group_id": f"near_dup_{len(near_duplicate_groups) + 1:04d}",
                    "method": "dhash",
                    "threshold": threshold,
                    "members": [
                        {
                            "canonical_image_id": canonical_images[midx]["canonical_image_id"],
                            "phash": canonical_images[midx].get("phash"),
                        }
                        for midx in members
                    ],
                }
            )

    near_duplicate_index: dict[str, dict[str, Any]] = {}
    for group in near_duplicate_groups:
        members = group.get("members", [])
        if not isinstance(members, list):
            continue
        canonical_ids = [m.get("canonical_image_id") for m in members if isinstance(m, dict)]
        normalized_ids = [cid for cid in canonical_ids if isinstance(cid, str)]
        for cid in normalized_ids:
            near_duplicate_index[cid] = {
                "group_id": group.get("group_id"),
                "member_ids": normalized_ids,
                "method": group.get("method"),
                "threshold": group.get("threshold"),
            }

    figure_slots = _extract_figure_slots(markdown)
    figure_matches: list[dict[str, Any]] = []
    for slot in figure_slots:
        page_hint = slot.get("page_hint")
        fig_num = slot.get("figure_number")
        ranked: list[tuple[float, dict[str, Any]]] = []
        for cidx, image in enumerate(canonical_images, start=1):
            score = 0.0
            candidate_page = image.get("first_seen", {}).get("page")
            if isinstance(page_hint, int) and isinstance(candidate_page, int):
                dist = abs(candidate_page - page_hint)
                score += max(0.0, 1.0 - (min(dist, 12) / 12.0)) * 0.7
            labels = set(image.get("labels", []))
            if "figure_like" in labels:
                score += 0.2
            if isinstance(fig_num, int) and fig_num == cidx:
                score += 0.1
            ranked.append((score, image))
        ranked.sort(key=lambda x: x[0], reverse=True)
        top = [
            {
                "canonical_image_id": c["canonical_image_id"],
                "score": round(s, 4),
                "first_seen_page": c.get("first_seen", {}).get("page"),
                "labels": c.get("labels", []),
                "kinds": c.get("kinds", []),
                "near_duplicate_group": near_duplicate_index.get(c["canonical_image_id"]),
            }
            for s, c in ranked[:3]
            if s > 0
        ]
        primary_candidate_id = top[0]["canonical_image_id"] if top else None
        cluster_ids: list[str] = []
        for candidate in top:
            group = candidate.get("near_duplicate_group")
            if isinstance(group, dict):
                gid = group.get("group_id")
                if isinstance(gid, str) and gid not in cluster_ids:
                    cluster_ids.append(gid)
        figure_matches.append(
            {
                "slot_id": slot["slot_id"],
                "figure_number": slot["figure_number"],
                "caption": slot.get("caption", ""),
                "page_hint": slot.get("page_hint"),
                "primary_candidate_id": primary_candidate_id,
                "candidate_cluster_ids": cluster_ids,
                "candidates": top,
            }
        )

    return {
        "version": "1",
        "dedupe": {"method": "sha256", "phash_method": "dhash", "phash_enabled": phash_seen},
        "totals": {
            "raw_occurrences": len(ordered_items),
            "unique_images": len(canonical_images),
            "figure_slots": len(figure_slots),
            "near_duplicate_groups": len(near_duplicate_groups),
        },
        "images": canonical_images,
        "near_duplicate_groups": near_duplicate_groups,
        "figure_slots": figure_slots,
        "figure_matches": figure_matches,
    }


def _build_figure_mapping_template(image_manifest: dict[str, Any]) -> dict[str, Any]:
    matches = image_manifest.get("figure_matches", [])
    entries: list[dict[str, Any]] = []
    for match in matches if isinstance(matches, list) else []:
        if not isinstance(match, dict):
            continue
        entries.append(
            {
                "slot_id": match.get("slot_id"),
                "figure_number": match.get("figure_number"),
                "caption": match.get("caption", ""),
                "page_hint": match.get("page_hint"),
                "primary_candidate_id": match.get("primary_candidate_id"),
                "candidate_cluster_ids": match.get("candidate_cluster_ids", []),
                "candidates": match.get("candidates", []),
                "selected_image_id": None,
                "selected_cluster_id": None,
                "decision_status": "pending",
                "notes": "",
            }
        )

    return {
        "version": "1",
        "instructions": (
            "For each slot, choose selected_image_id (and optionally selected_cluster_id). "
            "Set decision_status to matched/ambiguous/unmatched and add notes when needed."
        ),
        "decision_file": "figure_mapping_decision.json",
        "entries": entries,
    }


def _build_figure_mapping_decision_example(template: dict[str, Any]) -> dict[str, Any]:
    entries = template.get("entries", []) if isinstance(template, dict) else []
    example_entries: list[dict[str, Any]] = []
    for entry in entries[:2] if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        candidates = entry.get("candidates", [])
        primary_id = entry.get("primary_candidate_id")
        selected_image_id = primary_id
        selected_cluster_id = None
        if isinstance(candidates, list) and candidates:
            top = candidates[0] if isinstance(candidates[0], dict) else {}
            selected_image_id = top.get("canonical_image_id", primary_id)
            group = top.get("near_duplicate_group") if isinstance(top, dict) else None
            if isinstance(group, dict):
                selected_cluster_id = group.get("group_id")

        example_entries.append(
            {
                "slot_id": entry.get("slot_id"),
                "selected_image_id": selected_image_id,
                "selected_cluster_id": selected_cluster_id,
                "decision_status": "matched" if selected_image_id else "ambiguous",
                "notes": "Example decision entry. Adjust based on your review.",
            }
        )

    return {
        "version": "1",
        "source_template": "figure_mapping_template.json",
        "entries": example_entries,
    }


def _maybe_validate_figure_mapping_decision(
    *,
    output_path: Path,
    image_manifest: dict[str, Any],
    files_result: dict[str, Any],
    payload: dict[str, Any],
    warnings: list[str],
) -> None:
    decision_path = output_path / "figure_mapping_decision.json"
    if not decision_path.exists():
        return
    try:
        decision_data = json.loads(decision_path.read_text(encoding="utf-8"))
        validation = _validate_figure_mapping_decision(image_manifest, decision_data)
        validation_path = output_path / "figure_mapping_validation.json"
        with open(validation_path, "w", encoding="utf-8") as f:
            json.dump(validation, f, ensure_ascii=False, indent=2)
        files_result["figure_mapping_validation"] = str(validation_path)
        payload["figure_mapping_validation"] = validation
    except Exception as e:
        warnings.append(f"Failed to validate figure mapping decision: {e}")


def _validate_figure_mapping_decision(
    image_manifest: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(decision, dict):
        return {
            "valid": False,
            "issues": [{"error": "decision is not an object"}],
            "summary": {
                "entries": 0,
                "matched": 0,
                "ambiguous": 0,
                "unmatched": 0,
            },
        }

    valid_slot_ids = {
        str(slot.get("slot_id"))
        for slot in (image_manifest.get("figure_slots", []) if isinstance(image_manifest.get("figure_slots"), list) else [])
        if isinstance(slot, dict) and slot.get("slot_id") is not None
    }
    valid_image_ids = {
        str(img.get("canonical_image_id"))
        for img in (image_manifest.get("images", []) if isinstance(image_manifest.get("images"), list) else [])
        if isinstance(img, dict) and img.get("canonical_image_id") is not None
    }
    valid_cluster_ids = {
        str(group.get("group_id"))
        for group in (
            image_manifest.get("near_duplicate_groups", [])
            if isinstance(image_manifest.get("near_duplicate_groups"), list)
            else []
        )
        if isinstance(group, dict) and group.get("group_id") is not None
    }

    entries_raw = decision.get("entries")
    entries: list[Any] = []
    issues: list[dict[str, Any]] = []
    matched = 0
    ambiguous = 0
    unmatched = 0

    if entries_raw is None:
        issues.append({"error": "entries is required"})
    elif not isinstance(entries_raw, list):
        issues.append({"error": "entries must be a list"})
    else:
        entries = entries_raw

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            issues.append({"index": idx, "error": "entry is not an object"})
            continue
        slot_id = str(entry.get("slot_id", ""))
        selected_image_id = entry.get("selected_image_id")
        selected_cluster_id = entry.get("selected_cluster_id")
        status = str(entry.get("decision_status", "pending")).lower()

        if slot_id and slot_id not in valid_slot_ids:
            issues.append({"slot_id": slot_id, "error": "unknown slot_id"})
        if selected_image_id is not None and str(selected_image_id) not in valid_image_ids:
            issues.append({"slot_id": slot_id, "error": "unknown selected_image_id"})
        if selected_cluster_id is not None and str(selected_cluster_id) not in valid_cluster_ids:
            issues.append({"slot_id": slot_id, "error": "unknown selected_cluster_id"})

        if status == "matched":
            matched += 1
        elif status == "ambiguous":
            ambiguous += 1
        elif status == "unmatched":
            unmatched += 1

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "summary": {
            "entries": len(entries),
            "matched": matched,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
        },
    }


async def analyze_image(
    image_path: str,
    question: str = "Describe this image in detail. What type of content is it?",
) -> dict[str, Any]:
    """Analyze an image using OpenAI-compatible vision API and save result to .local_read_mcp/analysis/.

    Args:
        image_path: Path to the image file to analyze
        question: Question to ask about the image

    Returns:
        Dict with analysis result and saved file path

    Environment Variables (.env):
        VISION_API_KEY: Your API key (or OPENAI_API_KEY)
        VISION_BASE_URL: API base URL (or OPENAI_BASE_URL)
        VISION_MODEL: Model name (or OPENAI_VISION_MODEL, default: gpt-4o)
        VISION_MAX_IMAGE_SIZE_MB: Max image size in MB (default: 20)
    """
    if not _config.vision_enabled:
        return {"success": False, "error": "Vision is not configured. Set VISION_API_KEY and install Local_Read[vision]."}
    result = await analyze_image_with_config(
        image_path=image_path,
        question=question,
        api_key=_config.api_key,
        base_url=_config.base_url,
        model=_config.model,
        max_size_mb=_config.vision_max_image_size_mb,
    )
    if not result.get("success"):
        return result

    result_text = result["analysis"]
    result_path = save_analysis_markdown(
        image_path=image_path,
        question=question,
        result_text=result_text,
    )

    return {
        "success": True,
        "analysis": result_text,
        "saved_path": str(result_path),
    }

async def analyze_images_batch(
    image_paths: list[str],
    question: str = "Describe this image in detail. What type of content is it?",
    batch_size: int = 6,
) -> dict[str, Any]:
    """Analyze images in small batches with content-hash cache."""
    if not _config.vision_enabled:
        return {"success": False, "error": "Vision is not configured. Set VISION_API_KEY and install Local_Read[vision]."}
    return await analyze_images_batch_with_cache(
        image_paths=image_paths,
        question=question,
        batch_size=batch_size,
        api_key=_config.api_key,
        base_url=_config.base_url,
        model=_config.model,
        max_size_mb=_config.vision_max_image_size_mb,
    )









def _fallback_to_simple(registry, backend_instance, warnings, failure):
    """Return Simple backend if the current backend failed, else None."""
    if backend_instance.name == 'Simple':
        return None
    simple = registry.get(BackendType.SIMPLE)
    if simple is None:
        return None
    warnings.append(
        f"{backend_instance.name} failed: {failure}. Falling back to Simple backend."
    )
    return simple


async def process_binary_file(
    file_path: str,
    format: str | None = None,
    backend: str = "auto",
    mineru_engine: str = "auto",
    mineru_effort: str = "medium",
    # Page range control
    chapter_split: bool | str | int = "auto",
    start_page: int | None = None,
    end_page: int | None = None,
    page_batch_size: int = 64,
    page_range_mode: str = "physical",
    strict_page_range: bool = False,
    enable_toc_auto_fallback: bool = False,
    toc_confidence_threshold: float = 0.55,
    fail_on_unreadable: bool = False,
    skip_quality_check: bool = False,
    # PDF-specific
    extract_images: bool | None = None,
    render_images: bool = False,
    render_dpi: int = 200,
    render_format: str = "png",
    extract_forms: bool = False,
    inspect_struct: bool = False,
    include_coords: bool = False,
) -> dict[str, Any]:
    """Convert a local document to structured artifacts for selective reading.

    Results are saved in .local_read_mcp/<file>_<timestamp>/
    with intermediate.json, output.md and index.json.
    For large PDFs, chapter_split detects sections and processes each chunk
    independently, then merges the results.

    Args:
        file_path: Path to the file to process.
        format: Override auto-detected format.
        backend: Backend (auto/simple/vlm-hybrid). Default: auto.
        chapter_split: "auto" (split >30p), "chapter", N (fixed pages), False (off).
        start_page: Inclusive 0-based start page. In `physical` mode this is a physical page
            index. In `logical` mode (PDF only) this is a logical page number mapped to a
            physical index before chunking.
        end_page: Inclusive end page. In `physical` mode this is a physical 0-based index.
            In `logical` mode (PDF only) this is a logical page number mapped to physical.
            `None` means open-ended (through the last page).
        page_batch_size: Pages per batch (default: 64).
        page_range_mode: `physical` or `logical` (case-insensitive). Non-PDF inputs use
            physical semantics.
        strict_page_range: Disable chapter splitting and process only resolved span.
        enable_toc_auto_fallback: Enable TOC auto fallback behavior.
        toc_confidence_threshold: TOC confidence threshold.
        fail_on_unreadable: Fail when unreadable segments are encountered.
        skip_quality_check: Skip quality checks in processing pipeline.
        extract_images: Extract images from PDF (auto if vision configured).
        render_images: Render PDF pages to images.
        render_dpi: Render DPI (default: 200).
        render_format: png or jpeg (default: png).
        extract_forms: Extract PDF form fields.
        inspect_struct: Get PDF structure metadata.
        include_coords: Include text with bounding boxes.
    """
    # ── 1. Format detection ──────────────────────────────────────
    if format is None:
        format = detect_format(file_path)
    if format is None:
        format = "text"

    # Auto-enable extract_images for PDF if vision is configured
    if format == "pdf" and extract_images is None:
        extract_images = bool(VISION_ENABLED)

    # ── 2. Backend selection ─────────────────────────────────────
    registry = get_registry()
    try:
        backend_type = BackendType(backend)
    except ValueError:
        backend_type = BackendType.AUTO

    if backend_type == BackendType.AUTO:
        backend_instance = registry.select_best(format)
    else:
        backend_instance = registry.get(backend_type)

    if backend_instance is None:
        backend_instance = registry.get(BackendType.SIMPLE)

    warnings: list[str] = []
    if backend_instance.warning:
        warnings.append(backend_instance.warning)

    if not backend_instance.supports_format(format):
        raise ValueError(
            f"Backend '{backend_instance.name}' does not support format '{format}'"
        )

    if fail_on_unreadable or skip_quality_check:
        warnings.append(
            "Reliability controls are accepted but enforced in later phases; current behavior remains additive-only."
        )

    normalized_page_range_mode = (page_range_mode or "physical").lower()
    if normalized_page_range_mode not in {"physical", "logical"}:
        normalized_page_range_mode = "physical"

    additive_fields: dict[str, Any] = {
        "warnings": warnings,
        "quality_state": "not_evaluated",
        "quality_metrics": {},
        "requires_ocr": False,
        "toc_confidence": None,
        "toc_resolution_mode": "not_evaluated",
        "toc_offset": None,
        "toc_evidence_pages": [],
        "resolved_start_page": start_page,
        "resolved_end_page": end_page,
        "resolved_page_map": {
            "mode": normalized_page_range_mode,
            "strategy": "identity",
            "requested": {"start_page": start_page, "end_page": end_page},
            "resolved": {"start_page": start_page, "end_page": end_page},
        },
    }

    def _apply_additive_defaults(payload: dict[str, Any]) -> None:
        existing_warnings = payload.get("warnings")
        if isinstance(existing_warnings, list):
            for warning in warnings:
                if warning not in existing_warnings:
                    existing_warnings.append(warning)
        else:
            payload["warnings"] = list(warnings)
        payload.setdefault("quality_state", additive_fields["quality_state"])
        payload.setdefault("quality_metrics", additive_fields["quality_metrics"])
        payload.setdefault("requires_ocr", additive_fields["requires_ocr"])
        payload.setdefault("toc_confidence", additive_fields["toc_confidence"])
        payload.setdefault("toc_resolution_mode", additive_fields["toc_resolution_mode"])
        payload.setdefault("toc_offset", additive_fields["toc_offset"])
        payload.setdefault("toc_evidence_pages", additive_fields["toc_evidence_pages"])
        payload.setdefault("resolved_start_page", additive_fields["resolved_start_page"])
        payload.setdefault("resolved_end_page", additive_fields["resolved_end_page"])
        payload.setdefault("resolved_page_map", additive_fields["resolved_page_map"])

    def _extract_quality_text_from_intermediate(intermediate: Any) -> tuple[str, bool]:
        """Prefer raw extracted block text from intermediate output for quality scoring."""
        if not isinstance(intermediate, dict):
            return "", False

        blocks = intermediate.get("blocks")
        if not isinstance(blocks, dict):
            return "", True

        parts: list[str] = []
        reading_order = intermediate.get("reading_order")
        if isinstance(reading_order, list):
            for block_id in reading_order:
                block = blocks.get(block_id)
                if not isinstance(block, dict):
                    continue
                content = block.get("content")
                if isinstance(content, str):
                    parts.append(content)
        else:
            for block in blocks.values():
                if not isinstance(block, dict):
                    continue
                content = block.get("content")
                if isinstance(content, str):
                    parts.append(content)

        return "\n".join(parts), True

    def _apply_pdf_quality(
        payload: dict[str, Any],
        page_count: int | None,
        *,
        intermediate: dict[str, Any] | None = None,
        fallback_text: str = "",
    ) -> None:
        if format != "pdf":
            return

        existing_state = payload.get("quality_state")
        existing_metrics = payload.get("quality_metrics")
        if existing_state in {"ok", "warn", "unreadable"}:
            if isinstance(existing_metrics, dict):
                payload["quality_metrics"] = existing_metrics
            current_requires_ocr = payload.get("requires_ocr")
            if isinstance(current_requires_ocr, bool):
                payload["requires_ocr"] = current_requires_ocr
            else:
                payload["requires_ocr"] = existing_state == "unreadable"
            warning_text = payload.get("quality_warning")
            if not isinstance(warning_text, str) or not warning_text:
                warning_text = get_pdf_quality_warning(existing_state)
        else:
            intermediate_obj = intermediate if isinstance(intermediate, dict) else payload.get("intermediate")
            metadata = intermediate_obj.get("metadata", {}) if isinstance(intermediate_obj, dict) else {}
            metadata_state = metadata.get("quality_state") if isinstance(metadata, dict) else None
            metadata_metrics = metadata.get("quality_metrics") if isinstance(metadata, dict) else None
            metadata_requires_ocr = metadata.get("requires_ocr") if isinstance(metadata, dict) else None
            metadata_warning = metadata.get("quality_warning") if isinstance(metadata, dict) else None
            metadata_has_quality = (
                metadata_state in {"ok", "warn", "unreadable"}
                or isinstance(metadata_metrics, dict)
                or isinstance(metadata_requires_ocr, bool)
            )

            if metadata_has_quality:
                if metadata_state in {"ok", "warn", "unreadable"}:
                    payload["quality_state"] = metadata_state
                if isinstance(metadata_metrics, dict):
                    payload["quality_metrics"] = metadata_metrics
                if isinstance(metadata_requires_ocr, bool):
                    payload["requires_ocr"] = metadata_requires_ocr
                elif metadata_state in {"ok", "warn", "unreadable"}:
                    payload["requires_ocr"] = metadata_state == "unreadable"
                warning_text = metadata_warning if isinstance(metadata_warning, str) and metadata_warning else None
                if not warning_text and metadata_state in {"warn", "unreadable"}:
                    warning_text = get_pdf_quality_warning(metadata_state)
            else:
                raw_text, has_raw_source = _extract_quality_text_from_intermediate(intermediate_obj)
                quality_text = raw_text if has_raw_source else str(fallback_text or "")
                quality = evaluate_pdf_text_quality(quality_text, page_count)
                payload["quality_state"] = quality["quality_state"]
                payload["quality_metrics"] = quality["quality_metrics"]
                payload["requires_ocr"] = quality["requires_ocr"]
                warning_text = quality.get("quality_warning")

        if warning_text:
            existing_warnings = payload.get("warnings")
            if not isinstance(existing_warnings, list):
                existing_warnings = []
                payload["warnings"] = existing_warnings
            if warning_text not in existing_warnings:
                existing_warnings.append(warning_text)

    # ── 3. Resolve page range and plan chunks (segmenter integration) ──
    resolved_start_page, resolved_end_page, resolved_page_map = resolve_page_range(
        file_path=file_path,
        format=format,
        start_page=start_page,
        end_page=end_page,
        page_range_mode=normalized_page_range_mode,
    )
    additive_fields["resolved_start_page"] = resolved_start_page
    additive_fields["resolved_end_page"] = resolved_end_page
    additive_fields["resolved_page_map"] = resolved_page_map

    effective_start_page = start_page
    effective_end_page = end_page
    effective_chapter_split = chapter_split
    if normalized_page_range_mode == "logical":
        effective_start_page = resolved_start_page
        effective_end_page = resolved_end_page
    if strict_page_range:
        effective_chapter_split = False
        effective_start_page = resolved_start_page
        effective_end_page = resolved_end_page

    chunks_result = plan_chunks(
        file_path=file_path,
        format=format,
        backend_name=backend_instance.name,
        chapter_split=effective_chapter_split,
        start_page=effective_start_page,
        end_page=effective_end_page,
        page_batch_size=page_batch_size,
        enable_toc_auto_fallback=enable_toc_auto_fallback,
        toc_confidence_threshold=toc_confidence_threshold,
        return_diagnostics=True,
    )
    chunk_diagnostics: dict[str, Any] = {
        "mode": "not_evaluated",
        "confidence": None,
        "offset": None,
        "evidence_pages": [],
    }
    if isinstance(chunks_result, tuple) and len(chunks_result) == 2:
        chunks, planned_diagnostics = chunks_result
        if isinstance(planned_diagnostics, dict):
            chunk_diagnostics.update(planned_diagnostics)
    else:
        chunks = chunks_result

    toc_confidence = chunk_diagnostics.get("confidence")
    toc_mode = str(chunk_diagnostics.get("mode", "not_evaluated"))
    toc_offset = chunk_diagnostics.get("offset")
    evidence_pages = chunk_diagnostics.get("evidence_pages")
    toc_evidence_pages = evidence_pages if isinstance(evidence_pages, list) else []

    # In logical range mode, resolved_page_map may carry TOC diagnostics from range resolver.
    # Prefer those when chunk planning diagnostics are not evaluated.
    if normalized_page_range_mode == "logical" and isinstance(resolved_page_map, dict):
        if toc_mode == "not_evaluated":
            resolved_mode = resolved_page_map.get("toc_resolution_mode")
            if isinstance(resolved_mode, str) and resolved_mode:
                toc_mode = resolved_mode
        if toc_confidence is None and isinstance(resolved_page_map.get("toc_confidence"), (int, float)):
            toc_confidence = float(resolved_page_map["toc_confidence"])
        if toc_offset is None and resolved_page_map.get("offset") is not None:
            toc_offset = resolved_page_map.get("offset")
        if not toc_evidence_pages:
            resolved_evidence = resolved_page_map.get("toc_evidence_pages")
            if isinstance(resolved_evidence, list):
                toc_evidence_pages = resolved_evidence

    additive_fields["toc_confidence"] = toc_confidence
    additive_fields["toc_resolution_mode"] = toc_mode
    additive_fields["toc_offset"] = toc_offset
    additive_fields["toc_evidence_pages"] = toc_evidence_pages
    fallback_reason = chunk_diagnostics.get("fallback_reason")
    if isinstance(fallback_reason, str) and fallback_reason:
        warnings.append(fallback_reason)

    # ── 4. Create output directory ───────────────────────────────
    output_manager = OutputManager()
    output_path = output_manager.create_output_dir(file_path)
    images_dir = output_path / "images"

    # ── 5. Build backend kwargs ──────────────────────────────────
    backend_kwargs: dict[str, Any] = {}
    if format == "pdf":
        backend_kwargs["extract_images"] = extract_images
        backend_kwargs["images_output_dir"] = str(images_dir)
        backend_kwargs["render_images"] = render_images
        backend_kwargs["render_dpi"] = render_dpi
        backend_kwargs["render_format"] = render_format
        backend_kwargs["extract_forms"] = extract_forms
        backend_kwargs["inspect_struct"] = inspect_struct
        backend_kwargs["include_coords"] = include_coords
        backend_kwargs["mineru_engine"] = mineru_engine
        backend_kwargs["mineru_effort"] = mineru_effort

    # ── 6. Process ───────────────────────────────────────────────
    try:
        if len(chunks) == 1:
            # Single-chunk: process in-place, with fallback to Simple
            effective_backend = backend_instance
            try:
                result = process_and_save(
                    file_path=file_path,
                    backend=effective_backend,
                    format=format,
                    output_path=output_path,
                    images_dir=images_dir,
                    chunk=chunks[0],
                    backend_kwargs=backend_kwargs,
                )
            except Exception as e:
                fallback = _fallback_to_simple(registry, backend_instance, warnings, str(e))
                if fallback is None:
                    raise
                effective_backend = fallback
                result = process_and_save(
                    file_path=file_path,
                    backend=effective_backend,
                    format=format,
                    output_path=output_path,
                    images_dir=images_dir,
                    chunk=chunks[0],
                    backend_kwargs=backend_kwargs,
                )
            result["success"] = True
            result["backend_used"] = effective_backend.name
            result["output_directory"] = str(output_path)
            result["files"] = {
                "intermediate_json": str(result["intermediate_path"]),
                "markdown": str(result["markdown_path"]),
                "index_json": str(result["index_path"]),
            }
            result["files"].update(result.get("native_files", {}))
            if "image_files" in result:
                result["files"]["images"] = str(result["image_files"][0].parent)
                image_metadata = _build_image_metadata(
                    result["image_files"],
                    result.get("phys_start", 0),
                    result.get("phys_end", 0),
                )
                result["image_count"] = len(image_metadata)
                result["image_metadata"] = image_metadata
                image_manifest = _build_image_manifest(image_metadata, result.get("markdown_content", ""))
                image_manifest_path = output_path / "image_manifest.json"
                with open(image_manifest_path, "w", encoding="utf-8") as f:
                    json.dump(image_manifest, f, ensure_ascii=False, indent=2)
                figure_mapping_template = _build_figure_mapping_template(image_manifest)
                figure_mapping_template_path = output_path / "figure_mapping_template.json"
                with open(figure_mapping_template_path, "w", encoding="utf-8") as f:
                    json.dump(figure_mapping_template, f, ensure_ascii=False, indent=2)
                figure_mapping_example = _build_figure_mapping_decision_example(figure_mapping_template)
                figure_mapping_example_path = output_path / "figure_mapping_decision.example.json"
                with open(figure_mapping_example_path, "w", encoding="utf-8") as f:
                    json.dump(figure_mapping_example, f, ensure_ascii=False, indent=2)
                result["image_manifest"] = image_manifest
                result["files"]["image_manifest"] = str(image_manifest_path)
                result["files"]["figure_mapping_template"] = str(figure_mapping_template_path)
                result["files"]["figure_mapping_decision_example"] = str(figure_mapping_example_path)
                result["figure_slots"] = image_manifest.get("figure_slots", [])
                result["figure_image_matches"] = image_manifest.get("figure_matches", [])
                _maybe_validate_figure_mapping_decision(
                    output_path=output_path,
                    image_manifest=image_manifest,
                    files_result=result["files"],
                    payload=result,
                    warnings=warnings,
                )
            figure_refs = _extract_figure_references(result.get("markdown_content", ""))
            result["figure_reference_count"] = len(figure_refs)
            result["figure_references"] = figure_refs
            page_count = None
            intermediate = result.get("intermediate")
            if isinstance(intermediate, dict):
                page_count = intermediate.get("source", {}).get("page_count")
            if page_count is None:
                try:
                    page_count = max(1, int(result.get("phys_end", 0)) - int(result.get("phys_start", 0)) + 1)
                except Exception:
                    page_count = 1
            _apply_pdf_quality(
                result,
                page_count,
                intermediate=intermediate if isinstance(intermediate, dict) else None,
                fallback_text=result.get("markdown_content", ""),
            )
            _apply_additive_defaults(result)
            return result

        # Multi-chunk: process each chunk independently, then merge
        chunk_results: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            chunk_dir = output_path / f"chunk_{idx + 1:04d}"
            chunk_dir.mkdir(exist_ok=True)
            chunk_backend_kwargs = dict(backend_kwargs)
            if format == "pdf":
                chunk_backend_kwargs["images_output_dir"] = str(chunk_dir / "images")
            try:
                cr = process_and_save(
                    file_path=file_path,
                    backend=backend_instance,
                    format=format,
                    output_path=chunk_dir,
                    images_dir=chunk_dir / "images",
                    chunk=chunk,
                    backend_kwargs=chunk_backend_kwargs,
                )
                chunk_results.append(cr)
            except Exception as e:
                fallback = _fallback_to_simple(registry, backend_instance, warnings, str(e))
                if fallback is not None:
                    try:
                        cr = process_and_save(
                            file_path=file_path,
                            backend=fallback,
                            format=format,
                            output_path=chunk_dir,
                            images_dir=chunk_dir / "images",
                            chunk=chunk,
                            backend_kwargs=chunk_backend_kwargs,
                        )
                        chunk_results.append(cr)
                        continue
                    except Exception as e2:
                        logger.error("Chunk %d (%s) fallback also failed: %s", idx + 1, chunk.title, e2)
                logger.error("Chunk %d (%s) failed: %s", idx + 1, chunk.title, e)
                chunk_results.append({
                    "error": str(e),
                    "title": chunk.title,
                    "phys_start": chunk.phys_start,
                    "phys_end": chunk.phys_end,
                })

        # Merge and save structural TOC
        save_structural_toc(output_path, chunks)

        # Merge chunk markdowns into a single output.md
        merged_md = merge_chunk_markdowns(chunk_results)
        merged_md_path = output_path / "output.md"
        if merged_md:
            with open(merged_md_path, 'w', encoding='utf-8') as f:
                f.write(merged_md)

        succeeded = [cr for cr in chunk_results if "error" not in cr]

        # Build top-level intermediate.json from chunk intermediates
        merged_intermediate = merge_chunk_intermediates(file_path, format, succeeded)
        intermediate_path = output_path / "intermediate.json"
        with open(intermediate_path, 'w', encoding='utf-8') as f:
            json.dump(merged_intermediate, f, ensure_ascii=False, indent=2)

        # Build top-level index.json
        index_generator = IndexGenerator(merged_intermediate)
        index_path = output_path / "index.json"
        index_generator.save_to_file(str(index_path))

        chunk_files = []
        image_metadata_all: list[dict[str, Any]] = []
        image_dirs: set[str] = set()
        linked_image_paths: list[str] = []
        for cr in chunk_results:
            chunk_index = len(chunk_files) + 1
            info = {"title": cr.get("title", ""), "phys_start": cr.get("phys_start"), "phys_end": cr.get("phys_end")}
            if "error" in cr:
                info["error"] = cr["error"]
            else:
                info["intermediate_json"] = str(cr["intermediate_path"])
                info.update(cr.get("native_files", {}))
                info["provenance"] = cr.get("provenance")
                info["markdown"] = str(cr["markdown_path"])
                image_files = cr.get("image_files", [])
                if image_files:
                    sorted_image_files = sorted(image_files, key=lambda p: p.name)
                    chunk_image_metadata = _build_image_metadata(
                        sorted_image_files,
                        cr.get("phys_start", 0),
                        cr.get("phys_end", 0),
                        chunk_index=chunk_index,
                        chunk_title=cr.get("title", ""),
                    )
                    # Gather all chunk images to top-level images/ using symlinks (no copy).
                    images_dir.mkdir(parents=True, exist_ok=True)
                    for image_idx, image_path in enumerate(sorted_image_files, start=1):
                        link_name = f"chunk-{chunk_index}-images-{image_idx}{image_path.suffix}"
                        link_path = images_dir / link_name
                        try:
                            if link_path.exists() or link_path.is_symlink():
                                link_path.unlink()
                            os.symlink(str(image_path.resolve()), str(link_path))
                            linked_image_paths.append(str(link_path))
                            if image_idx - 1 < len(chunk_image_metadata):
                                chunk_image_metadata[image_idx - 1]["linked_path"] = str(link_path)
                        except OSError as e:
                            warnings.append(f"Failed to link image '{image_path}' -> '{link_path}': {e}")

                    info["images"] = str(sorted_image_files[0].parent)
                    info["image_count"] = len(chunk_image_metadata)
                    image_metadata_all.extend(chunk_image_metadata)
                    image_dirs.add(str(sorted_image_files[0].parent))
            chunk_files.append(info)

        files_result: dict[str, Any] = {
            "intermediate_json": str(intermediate_path),
            "markdown": str(merged_md_path) if merged_md else None,
            "merged_markdown": str(merged_md_path) if merged_md else None,
            "index_json": str(index_path),
            "structural_toc": str(output_path / "structural_toc.json") if (output_path / "structural_toc.json").exists() else None,
            "chunks": chunk_files,
        }
        if linked_image_paths:
            files_result["images"] = str(images_dir)
            files_result["linked_images"] = linked_image_paths
        elif image_dirs:
            files_result["images"] = sorted(image_dirs)

        result_payload: dict[str, Any] = {
            "success": True,
            "output_directory": str(output_path),
            "backend_used": backend_instance.name,
            "chunk_count": len(chunks),
            "chunk_success_count": len(succeeded),
            "chunk_failure_count": len(chunk_results) - len(succeeded),
            "all_chunks_failed": len(succeeded) == 0,
            "files": files_result,
        }
        merged_page_count = None
        if isinstance(merged_intermediate, dict):
            merged_page_count = merged_intermediate.get("source", {}).get("page_count")
        result_payload["markdown_content"] = merged_md
        _apply_pdf_quality(
            result_payload,
            merged_page_count,
            intermediate=merged_intermediate if isinstance(merged_intermediate, dict) else None,
            fallback_text=merged_md,
        )
        result_payload.pop("markdown_content", None)
        _apply_additive_defaults(result_payload)
        if image_metadata_all:
            result_payload["image_count"] = len(image_metadata_all)
            result_payload["image_metadata"] = image_metadata_all
            image_manifest = _build_image_manifest(image_metadata_all, merged_md)
            image_manifest_path = output_path / "image_manifest.json"
            with open(image_manifest_path, "w", encoding="utf-8") as f:
                json.dump(image_manifest, f, ensure_ascii=False, indent=2)
            figure_mapping_template = _build_figure_mapping_template(image_manifest)
            figure_mapping_template_path = output_path / "figure_mapping_template.json"
            with open(figure_mapping_template_path, "w", encoding="utf-8") as f:
                json.dump(figure_mapping_template, f, ensure_ascii=False, indent=2)
            figure_mapping_example = _build_figure_mapping_decision_example(figure_mapping_template)
            figure_mapping_example_path = output_path / "figure_mapping_decision.example.json"
            with open(figure_mapping_example_path, "w", encoding="utf-8") as f:
                json.dump(figure_mapping_example, f, ensure_ascii=False, indent=2)
            files_result["image_manifest"] = str(image_manifest_path)
            files_result["figure_mapping_template"] = str(figure_mapping_template_path)
            files_result["figure_mapping_decision_example"] = str(figure_mapping_example_path)
            result_payload["image_manifest"] = image_manifest
            result_payload["figure_slots"] = image_manifest.get("figure_slots", [])
            result_payload["figure_image_matches"] = image_manifest.get("figure_matches", [])
            _maybe_validate_figure_mapping_decision(
                output_path=output_path,
                image_manifest=image_manifest,
                files_result=files_result,
                payload=result_payload,
                warnings=warnings,
            )
        figure_refs = _extract_figure_references(merged_md)
        result_payload["figure_reference_count"] = len(figure_refs)
        result_payload["figure_references"] = figure_refs
        return result_payload

    except Exception as e:
        logger.error("Processing failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "backend_used": backend_instance.name,
            "warnings": warnings if "warnings" in locals() else [],
            "quality_state": "not_evaluated",
            "quality_metrics": {},
            "requires_ocr": False,
            "toc_confidence": None,
            "toc_resolution_mode": "not_evaluated",
            "toc_offset": None,
            "toc_evidence_pages": [],
            "resolved_start_page": additive_fields.get("resolved_start_page"),
            "resolved_end_page": additive_fields.get("resolved_end_page"),
            "resolved_page_map": additive_fields.get("resolved_page_map"),
        }
