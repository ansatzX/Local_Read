# Local Read MCP — Architecture

## Tools

MCP tools are registered at startup after loading repository-root `.env` values:
- Always expose `process_binary_file`
- Expose vision tools only when vision configuration is available (`VISION_API_KEY` or `OPENAI_API_KEY`):
  - `analyze_image`
  - `analyze_images_batch`

| Tool | Purpose |
|------|---------|
| `process_binary_file` | Converts supported binary/document/archive files to structured output and saves to `.local_read_mcp/`. |
| `analyze_image` | Vision API analysis of images, result saved to `.local_read_mcp/analysis/`. Only registered when vision is enabled at startup. |
| `analyze_images_batch` | Batched vision analysis with content-hash cache. Saves results under `.local_read_mcp/analysis/`. Only registered when vision is enabled at startup. |

All output is written to `.local_read_mcp/` in the current working directory. No files are written outside the working directory.

## Architecture

```
process_binary_file(file)
  │
  ├─ format detection → BackendRegistry.select_best()
  │    priority: VLM_HYBRID > SIMPLE
  │
  ├─ SIMPLE  (local converters, no model/API dependency)
  │   └─ Built-in converters + MarkItDown fallback: PyMuPDF, mammoth, openpyxl, python-pptx, etc.
  │
  ├─ VLM_HYBRID  (requires MinerU + models, PDF only)
  │   └─ MinerU hybrid-auto-engine
  │       VLM layout → pipeline OCR/formula/table → middle_json
  │       Engine: vLLM > LMDeploy > MLX-VLM > transformers (auto)
  │
  └─ chapter_split + range controls (internal)
      ├─ page_range_mode: physical | logical
      ├─ strict_page_range: optional forced range-only processing
      ├─ TocExtractor: TOC/page-label mapping + diagnostics
      │   mode, confidence, offset, evidence_pages
      ├─ low-confidence fallback (opt-in): fixed-size chunks
      ├─ ChunkPlanner: page ranges with overlap
      ├─ per-chunk backend processing → sliced PDF → intermediate.json
      └─ merged output.md + structural_toc.json

Result → .local_read_mcp/<file>_<timestamp>/
  ├── intermediate.json    (structured block representation)
  ├── output.md            (markdown conversion)
  ├── index.json           (section/table/figure index)
  └── images/              (extracted images)
```

## Backend System

```python
class BackendType(Enum):
    AUTO = "auto"
    SIMPLE = "simple"
    VLM_HYBRID = "vlm-hybrid"
```

- **SIMPLE**: Always available. Handles supported formats through built-in converters and the MarkItDown fallback.
- **VLM_HYBRID**: PDF only, requires MinerU + downloaded models. Calls `hybrid_analyze.doc_analyze()` directly — no `do_parse` callback/tempdir pattern.
- **Selection**: `VLM_HYBRID > SIMPLE` (by available + format support).

## Chapter Detection (`src/local_read_mcp/segmenter/`)

Built into `process_binary_file`. Triggers when `chapter_split != False` and format is PDF.

Calibration of logical page numbers (TOC) to physical page indices:
1. `page.get_label()` — PDF /PageLabels structure
2. Multi-anchor heuristic calibration — median offset from multiple title matches + confidence
3. `logical - 1` — fallback

Chunk planning with configurable `overlap` and `min_chunk_pages`. Falls back to fixed-size chunks when no TOC or headings are detected.

TOC diagnostics are threaded into `process_binary_file` responses:
- `toc_confidence`
- `toc_resolution_mode`
- `toc_offset`
- `toc_evidence_pages`

Range resolution fields are also returned:
- `resolved_start_page`
- `resolved_end_page`
- `resolved_page_map`

When `enable_toc_auto_fallback=true` and confidence is below `toc_confidence_threshold`, chunking falls back to fixed-size plan with a warning.

## PDF Quality Signals

PDF extraction evaluates text quality and emits additive signals without hard-failing by default:
- `quality_state`: `ok | warn | unreadable`
- `quality_metrics`: control-char ratio, printable ratio, alphanumeric density, avg readable chars/page
- `requires_ocr`: `true` when quality is unreadable

Quality warnings are added to the response `warnings` list. Existing backend-provided quality fields are preserved when present.

## Merge Deduplication

Merged chunk markdown deduplicates only overlap-window content between adjacent overlapping chunks (no global document dedupe). This reduces repeated paragraphs caused by chunk overlap while preserving non-overlap repeats.

## Image Manifest and Matching

When PDF image extraction is enabled, `process_binary_file` now builds a top-level image manifest:

- `image_manifest.json` under the output directory
- `figure_mapping_template.json` as editable mapping skeleton
- `figure_mapping_decision.example.json` as a minimal worked example
- checksum-based dedupe (`sha256`) across chunk outputs
- optional perceptual near-duplicate grouping (`dHash`) when Pillow is available
- canonical image groups with all occurrences preserved (no default denoising)
- kind-aware metadata (`raster`, `vector_region`, etc.)

The response may include:
- `image_manifest` (inline object)
- `figure_slots` (text-derived figure references/captions from merged markdown)
- `figure_image_matches` (ranked candidate mappings from slots to canonical images)
- `files.figure_mapping_template`
- `files.figure_mapping_decision_example`
- `files.figure_mapping_validation` and `figure_mapping_validation` when a user-provided `figure_mapping_decision.json` exists and is validated

This creates a stable bridge between chunked extraction and downstream figure alignment workflows.

## MinerU Integration

MinerU is an external dependency (`pip install local-read-mcp[mineru]`). Models (~4.5GB total) are downloaded by MinerU's own tool, configured via `mineru.json` in the project root. The backend sets `MINERU_TOOLS_CONFIG_JSON` automatically at import time.

Calls MinerU APIs directly:
- `hybrid_analyze.doc_analyze()` for VLM-HYBRID
- Engine auto-selection is handled inside MinerU
- Output converted from MinerU's `middle_json` to `IntermediateJSON`

## Configuration Files

| File | Purpose | Tracked |
|------|---------|:-------:|
| `.env` | Vision API key, base URL, model (used at startup for tool registration) | gitignored |
| `.env.example` | Template for .env | yes |
| `mineru.json` | MinerU model paths | gitignored |
| `mineru.json.template` | Template for mineru.json | yes |

The server loads `.env` from the project root, independent of the current working directory.
Existing process environment variables are not overwritten by `.env` values.

## Source Layout

```
src/local_read_mcp/
├── server/
│   ├── app.py              MCP tools registration entrypoint
│   │                       process_binary_file always, vision tools optional
│   ├── orchestrator.py     Chunk planning, processing, merging
│   ├── utils.py            Parameter compatibility helper
│   ├── vision.py           Vision API integration + shared helpers
│   └── vision_batch.py     Batched vision analysis + cache
├── backends/
│   ├── base.py             BackendType enum, registry
│   ├── simple.py           SimpleBackend (all formats)
│   └── mineru.py           VlmHybridBackend (MinerU hybrid)
├── segmenter/
│   ├── toc_extractor.py    TOC extraction + page calibration
│   └── chunk_planner.py    Page range planning + overlap
├── converters/
│   ├── _compat.py          Optional dependency imports (centralized)
│   ├── base.py             DocumentConverterResult + constants
│   ├── utils.py            apply_content_limit, html_to_markdown_result
│   ├── section_extractor.py  extract_sections_from_markdown
│   ├── latex_fixer.py      fix_latex_formulas
│   ├── pdf.py, docx.py, xlsx.py, pptx.py, html.py, ...
│   └── simple.py           TextConverter, JsonConverter, YamlConverter, ...
├── output_manager.py       .local_read_mcp/ directory management
├── markdown_converter.py   Intermediate JSON → markdown
├── index_generator.py      Section/table/figure index
└── intermediate_json.py    Structured intermediate representation
```
