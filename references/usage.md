# Local_Read CLI reference

The portable launcher is `python3 "$SKILL_DIR/scripts/local_read.py"`. An installed runtime also provides `local-read` and `python -m local_read` with the same commands. Conversion never requires MCP.

Run `python3 "$SKILL_DIR/scripts/local_read.py" setup` online once for the full runtime. The launcher runs ordinary conversions with `uv --offline --no-sync`, retaining installed dependencies. Rerun setup after changing skill code/lockfiles. The prepared runtime is shared across workspaces under `~/.cache/local-read/runtime/` (absolute `LOCAL_READ_RUNTIME_DIR` override). Identical skill releases share a content-keyed environment even when relocated. A new project can read offline immediately; a new code/lock version needs setup once. Missing runtime returns an actionable failure instead of attempting installation. Legacy project-local virtual environments are not moved; run setup once to create the shared runtime. Operations using the same runtime are serialized, including setup, to avoid changing packages during a read.

## Documents

```bash
python3 "$SKILL_DIR/scripts/local_read.py" convert report.docx --backend simple
python3 "$SKILL_DIR/scripts/local_read.py" convert book.pdf --chapter-split chapter
python3 "$SKILL_DIR/scripts/local_read.py" convert book.pdf --chapter-split 32
python3 "$SKILL_DIR/scripts/local_read.py" convert book.pdf --chapter-split off
python3 "$SKILL_DIR/scripts/local_read.py" convert book.pdf --page-range-mode logical --start-page 1 --end-page 8 --strict-page-range
```

`auto` splits PDFs longer than 30 pages, using TOC, detected headings, or fixed chunks. `--page-batch-size` defaults to 64 for the fixed fallback. Processing includes overlap between chunks. Integer chapter split requests pass through the existing planner, which may prioritize an available TOC; inspect returned chunk ranges rather than assuming a fixed size.

Physical pages use 0-based inclusive indices. Logical page resolution can use page labels or inferred offsets; inspect `resolved_page_map` and `toc_confidence`. For precise excerpts, use physical indices and `--strict-page-range`.

PDF options: `--extract-images`, `--render-images`, `--render-dpi 200`, `--render-format png|jpeg`, `--include-coords`, `--extract-forms`, `--inspect-struct`. Simple image extraction is explicit. MinerU writes image/table crop assets required by its output reconstruction even without this flag. `--no-page-breaks` and `--no-metadata` regenerate Markdown through the generic IR converter; leave them unset to preserve MinerU's native Markdown reconstruction.

Supported format overrides include `pdf`, `word`, `excel`, `ppt`, `html`, `zip`. Extension detection is the default; legacy Office support depends on the available converter. A failed conversion is not evidence that a document is empty.

## Artifacts and recovery

Each run uses `.local_read_mcp/<safe-stem>_<timestamp>_<id>/` containing `output.md`, `intermediate.json`, `index.json`, and `result.json`. Chunked documents additionally have per-chunk outputs and `structural_toc.json`. Image extraction can produce `images/`, `image_manifest.json`, and figure mapping templates.

MinerU additionally saves `mineru_middle.json` (full upstream page/element structure) and `mineru_content_list.json` (upstream reading-order list), available through `files` or per-chunk file entries. Its native Markdown builder preserves formulas/tables; IR blocks retain the original MinerU block and unknown confidence as null. Provenance records the engine, model paths, version, effort and offline mode.

JSON stdout omits full Markdown, block dictionaries, and image manifests. Follow the file paths to read those on demand. `partial` means some chunks failed: inspect `files.chunks`, disclose missing ranges, and retry only those ranges. `failed` means no usable completion was reported. `quality_state=unreadable` can accompany a completed conversion; text quality is a separate check.

Current limitations: block confidence defaults in the underlying IR are not calibrated probabilities; figure mappings are heuristic; a multi-chunk `backend_used` may name the original backend even after fallback. Use warnings and source checks rather than inferring guarantees from these fields.

Unified intermediate JSON uses original-document **1-based physical pages**, including per-chunk files. Do not add offsets again. Unknown page/bbox is null, not page 1 or a zero rectangle. Native MinerU files retain upstream local numbering. Use the unified page field when citing the original PDF.

## Optional MinerU

```bash
python3 "$SKILL_DIR/scripts/local_read.py" models prepare --source huggingface
python3 "$SKILL_DIR/scripts/local_read.py" models status
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --backend vlm-hybrid --mineru-effort medium
```

`models prepare` explicitly goes online and reuses MinerU 3.4.5's `mineru.cli.models_download --model_type all`, with the standard pipeline and VLM inference dependencies. Source choices are huggingface, modelscope, or auto. Dependencies and model weights can be large. An interrupted download retains upstream caches for retry. `setup` installs MinerU, PyTorch, Transformers and OpenAI SDK without model weights. The legacy `--with-mineru` launcher flag is accepted as a no-op.

Model weights and inference caches live in the user-global `~/.cache/local-read/models/`; preparation writes `mineru.json` and `model_manifest.json` there. Set `LOCAL_READ_MODEL_DIR` to an absolute path (for example `/Volumes/models/local-read`) to share another disk. The launcher and direct CLI use the same resolver for preparation and inference. Projects share these files; document output remains project-local and Python environments are also user-shared. Use `setup` once per skill version to install dependencies; new projects reuse them. Stick to the same download source to reuse its hub cache; different sources/revisions can occupy separate cache entries. Existing project-local model configs remain a fallback when no shared config exists, or select one explicitly with `MINERU_TOOLS_CONFIG_JSON`; old weights are not moved or copied automatically. Readiness checks verify required component weights, VLM configuration/tokenizer/shards, and recorded file sizes. They do not load models, verify weight hashes, or prove adequate hardware or OCR accuracy.

To reuse existing models, set `MINERU_TOOLS_CONFIG_JSON` to an absolute configuration path with `models-dir.pipeline` and `models-dir.vlm`. Relative model paths resolve against that config file. Selection is explicit config → managed config → legacy project-local config → skill-root mineru.json. The old independent `LRMCP_MINERU_MODELS_DIR` probe is no longer used. Preparation always writes the managed config; an explicit override remains authoritative until unset.

Conversion materializes a sanitized local inference config, sets `MINERU_MODEL_SOURCE=local`, enables Hugging Face/Transformers offline settings and disables upstream LLM API postprocessing. Python outbound DNS/sockets are blocked during conversion; loopback is allowed for local engines. This is not an OS network sandbox for native code or subprocesses. Missing models fail locally or fall back to Simple with warnings, never to a hosted API.

`--mineru-engine auto|transformers|mlx|vllm|lmdeploy` uses MinerU's engine resolver; the standard installation includes the transformers route, while accelerated engines require their own compatible installations. `--mineru-effort medium|high` controls upstream hybrid effort. Hardware and real model inference need separate verification.

## Optional image analysis

Set `VISION_API_KEY`, optionally `VISION_BASE_URL`, and `VISION_MODEL` in the environment. `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_VISION_MODEL` are fallbacks. A `.env` beside the skill's pyproject.toml is loaded without overriding existing environment values. Do not place credentials in skill instructions or command arguments.

```bash
python3 "$SKILL_DIR/scripts/local_read.py" analyze figure.png --question "Explain the axes and legend."
python3 "$SKILL_DIR/scripts/local_read.py" analyze a.png b.png --question "Describe each figure."
```

OpenAI SDK is installed by the standard setup; the command still requires explicit API configuration. Saved analyses and the content cache live in `.local_read_mcp/analysis/`; stdout returns paths and per-image errors. The batch helper currently processes entries sequentially. No credentials produces a structured failure and no API call.
