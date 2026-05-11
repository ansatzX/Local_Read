# Local Read MCP Server

MCP server for local document processing — structured extraction from PDFs, Office documents, HTML, ZIP archives, and optional image analysis. Designed to complement an agent's built-in Read tool, not duplicate it.

## Tools

Tool exposure is startup-time conditional:
- Always available: `process_binary_file`
- Available only when vision config exists (`VISION_API_KEY` or `OPENAI_API_KEY`): `analyze_image`, `analyze_images_batch`

| Tool | When to use |
|------|-------------|
| `process_binary_file` | Convert supported binary/document/archive files to structured output before reading. Saves to `.local_read_mcp/`. |
| `analyze_image` | Analyze images via Vision API (Doubao, GPT-4o, etc.). Result saved to `.local_read_mcp/analysis/`. |
| `analyze_images_batch` | Analyze multiple images with cache-aware batching. Results saved to `.local_read_mcp/analysis/`. |

## Quick Start

```bash
git clone https://github.com/ansatzX/Local_Read_MCP.git
cd Local_Read_MCP

uv venv .venv && source .venv/bin/activate
uv pip install -e .
```

Configure MCP in `~/.claude/settings.json`:

```json
{
  "mcpServers": [{
    "command": "uv",
    "args": ["--directory", "/path/to/Local_Read_MCP", "run", "python", "-m", "local_read_mcp.server"]
  }]
}
```

## Vision API (Optional)

Create `.env` in the repository root:

```
VISION_API_KEY=sk-xxx
VISION_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VISION_MODEL=doubao-seed-1-8-251228
```

At startup, the server loads the repository-root `.env` and then reads environment variables.
Existing process environment variables take precedence over `.env` values.
`analyze_image` is registered only if the server sees vision API key env vars at startup.
After changing env values, restart the MCP server.

## MinerU VLM-HYBRID Backend (Optional)

For high-quality PDF parsing with layout analysis, formula recognition, and table detection:

```bash
pip install "local-read-mcp[mineru]"

# Download models into the project directory
mineru-models-download --models-dir ./models

# Configure model paths
cp mineru.json.template mineru.json
# Edit mineru.json if models are elsewhere
```

Models downloaded (~4.5GB total):
- `models/pipeline/` — layout detection, OCR, formula recognition, table structure
- `models/vlm/` — fine-tuned Qwen2-VL for document understanding

## How It Works

```
process_binary_file(file.pdf)
  ├─ format detection → backend selection
  │
  ├─ SIMPLE (local converters, no model/API dependency)
  │   └─ Built-in converters + MarkItDown fallback: PyMuPDF / mammoth / openpyxl / python-pptx
  │
  ├─ VLM-HYBRID (MinerU required, PDF only)
  │   └─ MinerU hybrid-auto-engine: VLM layout + pipeline OCR/formula/table
  │
  └─ chapter_split (auto for large PDFs)
      ├─ Detect sections via TOC / heading scan / fixed chunks
      ├─ Process each chunk independently (with page overlap)
      └─ Merge output.md + structural_toc.json
```

All results saved to `.local_read_mcp/<file>_<timestamp>/`:
- `intermediate.json` — structured block representation
- `output.md` — converted markdown
- `index.json` — section/table/figure index
- `images/` — extracted images (when requested)
- `image_manifest.json` — canonical image inventory with dedupe/occurrence metadata (when images extracted)
- `figure_mapping_template.json` — slot-to-image mapping template for agent decisions
- `figure_mapping_decision.example.json` — minimal example decision payload

Figure extraction and mapping policy (current):
- PDF image extraction is intentionally recall-first: it extracts embedded rasters and suspicious vector/image regions.
- Dedupe is checksum-based (`sha256`) with all occurrences preserved; no default denoising.
- Optional perceptual near-duplicate grouping (`dHash`) is included when Pillow is available.
- If user provides `figure_mapping_decision.json`, the server validates it and writes `figure_mapping_validation.json`.
- Multi-chunk responses include additive health fields: `chunk_success_count`, `chunk_failure_count`, `all_chunks_failed` (`success` semantics unchanged).

## Development

```bash
uv run pytest          # Run tests
uv run ruff format .   # Format code
uv run ruff check .    # Lint
```

## License

MIT
