"""JSON-first command line interface for Local_Read."""

import argparse
import asyncio
import contextlib
import json
import sys
from pathlib import Path


def _summarize(result: dict) -> dict:
    """Keep document bodies on disk and expose actionable run state."""
    failed = bool(result.get("all_chunks_failed")) or not result.get("success", False)
    failures = result.get("chunk_failure_count", 0)
    items = result.get("results")
    if isinstance(items, list):
        failures = sum("error" in item for item in items)
        failed = failed or (bool(items) and failures == len(items))
    status = "failed" if failed else "partial" if failures else "complete"
    keys = (
        "error",
        "output_directory",
        "backend_used",
        "files",
        "warnings",
        "chunk_count",
        "chunk_success_count",
        "chunk_failure_count",
        "all_chunks_failed",
        "quality_state",
        "quality_metrics",
        "requires_ocr",
        "toc_confidence",
        "toc_resolution_mode",
        "resolved_start_page",
        "resolved_end_page",
        "resolved_page_map",
        "image_count",
        "saved_path",
        "provenance",
        "models_ready",
        "readiness",
        "inference_verified",
        "config_path",
        "packages",
        "model_paths",
        "missing",
        "offline",
        "manifest_path",
    )
    summary = {key: result[key] for key in keys if key in result}
    summary.update(schema_version="1.0", status=status, success=status == "complete")
    if isinstance(items, list):
        summary["results"] = [
            {
                key: item[key]
                for key in ("image_path", "saved_path", "cache_hit", "error")
                if key in item
            }
            for item in items
        ]
    if failed and "error" not in summary:
        summary["error"] = "No requested content was processed successfully."
    return summary


def _emit(result: dict) -> int:
    summary = _summarize(result)
    if result.get("output_directory"):
        manifest = Path(result["output_directory"]) / "result.json"
        summary["files"] = dict(summary.get("files", {}), result_json=str(manifest))
        manifest.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return {"complete": 0, "partial": 2, "failed": 1}[summary["status"]]


def convert_file(
    input_path: str,
    include_page_breaks: bool = True,
    include_metadata: bool = True,
    verbose: bool = False,
    **options,
) -> int:
    """Convert in the caller's working directory and emit one JSON result."""
    try:
        path = Path(input_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Input is not a file: {path}")
        from .local_runtime import offline_execution

        with contextlib.redirect_stdout(sys.stderr), offline_execution():
            from .processing import process_binary_file

            result = asyncio.run(process_binary_file(file_path=str(path), **options))
            files = result.get("files", {})
            if result.get("success") and (
                not include_page_breaks or not include_metadata
            ):
                from .markdown_converter import MarkdownConverter

                if files.get("markdown") and files.get("intermediate_json"):
                    intermediate = json.loads(
                        Path(files["intermediate_json"]).read_text(encoding="utf-8")
                    )
                    MarkdownConverter(
                        intermediate,
                        include_page_breaks=include_page_breaks,
                        include_metadata=include_metadata,
                    ).save_to_file(files["markdown"])
        if verbose:
            print(f"Processed: {path}", file=sys.stderr)
        return _emit(result)
    except Exception as exc:
        if verbose:
            import traceback

            traceback.print_exc(file=sys.stderr)
        return _emit({"success": False, "error": str(exc)})


def _chapter_split(value: str):
    if value in {"auto", "chapter", "section"}:
        return value
    if value in {"off", "false"}:
        return False
    try:
        count = int(value)
        if count > 0:
            return count
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(
        "Use auto, chapter, section, off, or a positive page count"
    )


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def main(argv: list[str] | None = None) -> int:
    from . import __version__

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in {
        "convert",
        "analyze",
        "setup",
        "models",
        "--version",
        "--help",
        "-h",
    }:
        argv.insert(0, "convert")
    parser = argparse.ArgumentParser(
        prog="local-read",
        description="Local_Read: local document reading skill runtime",
    )
    parser.add_argument(
        "--version", action="version", version=f"Local_Read v{__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "setup",
        help="Confirm runtime setup (use the skill launcher to install dependencies)",
    )
    models = commands.add_parser(
        "models", help="Inspect local models or explicitly prepare them online"
    )
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser(
        "status", help="Check cached model files and packages without loading models"
    )
    prepare = model_commands.add_parser(
        "prepare", help="Download/cache local models through MinerU"
    )
    prepare.add_argument(
        "--source", choices=("huggingface", "modelscope", "auto"), default="huggingface"
    )
    convert = commands.add_parser(
        "convert", help="Convert a document and return JSON artifact paths"
    )
    convert.add_argument("input_file")
    convert.add_argument(
        "--backend", choices=("auto", "simple", "vlm-hybrid"), default="auto"
    )
    convert.add_argument(
        "--mineru-engine",
        choices=("auto", "transformers", "mlx", "vllm", "lmdeploy"),
        default="auto",
    )
    convert.add_argument(
        "--mineru-effort", choices=("medium", "high"), default="medium"
    )
    convert.add_argument(
        "--format", help="Override detected format (pdf, word, excel, ppt, html, zip)"
    )
    convert.add_argument("--chapter-split", type=_chapter_split, default="auto")
    convert.add_argument(
        "--start-page",
        type=int,
        help="Inclusive physical index (0-based), or logical page number",
    )
    convert.add_argument(
        "--end-page",
        type=int,
        help="Inclusive end page, using the selected page-range mode",
    )
    convert.add_argument(
        "--page-range-mode", choices=("physical", "logical"), default="physical"
    )
    convert.add_argument("--page-batch-size", type=_positive, default=64)
    convert.add_argument("--strict-page-range", action="store_true")
    convert.add_argument(
        "--extract-images",
        action="store_true",
        help="Extract local images; does not call a vision API",
    )
    convert.add_argument("--render-images", action="store_true")
    convert.add_argument("--render-dpi", type=_positive, default=200)
    convert.add_argument("--render-format", choices=("png", "jpeg"), default="png")
    convert.add_argument("--extract-forms", action="store_true")
    convert.add_argument("--inspect-struct", action="store_true")
    convert.add_argument("--include-coords", action="store_true")
    convert.add_argument("--no-page-breaks", action="store_true")
    convert.add_argument("--no-metadata", action="store_true")
    convert.add_argument("-v", "--verbose", action="store_true")
    analyze = commands.add_parser(
        "analyze", help="Send images to the configured vision API and save analyses"
    )
    analyze.add_argument("images", nargs="+")
    analyze.add_argument("--question", default="Describe this image in detail.")
    analyze.add_argument("--batch-size", type=_positive, default=6)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "setup":
        return _emit({"success": True})
    if command == "models":
        try:
            from .models import model_status, prepare_models

            with contextlib.redirect_stdout(sys.stderr):
                result = (
                    prepare_models(args["source"])
                    if args["model_command"] == "prepare"
                    else model_status()
                )
            return _emit(result)
        except Exception as exc:
            return _emit({"success": False, "error": str(exc)})
    if command == "convert":
        input_path = args.pop("input_file")
        return convert_file(
            input_path,
            include_page_breaks=not args.pop("no_page_breaks"),
            include_metadata=not args.pop("no_metadata"),
            **args,
        )
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from .processing import analyze_images_batch

            result = asyncio.run(
                analyze_images_batch(
                    image_paths=[
                        str(Path(path).expanduser().resolve())
                        for path in args["images"]
                    ],
                    question=args["question"],
                    batch_size=args["batch_size"],
                )
            )
        return _emit(result)
    except Exception as exc:
        return _emit({"success": False, "error": str(exc)})


if __name__ == "__main__":
    sys.exit(main())
