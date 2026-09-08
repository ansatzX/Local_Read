"""Offline MinerU hybrid adapter, reusing upstream engines and output builders."""

from pathlib import Path
from typing import Any

from ..intermediate_json import IntermediateJSONBuilder
from ..local_runtime import offline_execution
from ..models import SUPPORTED_MINERU, local_inference_config, model_status
from .base import DocumentBackend
from .model_detector import get_model_detector


class VlmHybridBackend(DocumentBackend):
    def __init__(self):
        self._detector = get_model_detector()

    @property
    def name(self) -> str:
        return "VLM-Hybrid"

    @property
    def description(self) -> str:
        return "Local MinerU hybrid layout, OCR, formula and table parsing"

    @property
    def available(self) -> bool:
        return self._detector.mineru_available

    @property
    def warning(self) -> str | None:
        return self._detector.mineru_warning

    def supports_format(self, format: str) -> bool:
        return format == "pdf"

    def process(self, file_path: Path, format: str, **kwargs) -> dict[str, Any]:
        if format != "pdf":
            raise ValueError("MinerU hybrid supports PDF only")
        status = model_status()
        if not status["models_ready"]:
            raise RuntimeError(self.warning)
        config = local_inference_config()
        images = Path(kwargs["images_output_dir"]).resolve()
        images.mkdir(parents=True, exist_ok=True)
        engine_choice = kwargs.get("mineru_engine", "auto")
        if engine_choice not in {"auto", "transformers", "mlx", "vllm", "lmdeploy"}:
            raise ValueError("Only local MinerU inference engines are supported")
        effort = kwargs.get("mineru_effort", "medium")
        if effort not in {"medium", "high"}:
            raise ValueError("MinerU effort must be medium or high")
        with offline_execution({"MINERU_TOOLS_CONFIG_JSON": str(config)}):
            # Imports happen after setting local paths/offline mode: upstream config
            # modules capture environment values at import time.
            from mineru.backend.hybrid.hybrid_analyze import doc_analyze
            from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make
            from mineru.data.data_reader_writer import FileBasedDataWriter
            from mineru.utils.engine_utils import get_vlm_engine
            from mineru.utils.enum_class import MakeMode

            engine = get_vlm_engine(engine_choice)
            middle, _inference = doc_analyze(
                pdf_bytes=file_path.read_bytes(),
                image_writer=FileBasedDataWriter(str(images)),
                backend=engine,
                model_path=status["model_paths"]["vlm"],
                parse_method="auto",
                inline_formula_enable=True,
                image_analysis=bool(kwargs.get("extract_images")),
                effort=effort,
            )
            if not isinstance(middle, dict) or not isinstance(
                middle.get("pdf_info"), list
            ):
                raise ValueError(
                    "MinerU returned an incompatible middle JSON structure"
                )
            markdown = union_make(middle["pdf_info"], MakeMode.MM_MD, str(images))
            content_list = union_make(
                middle["pdf_info"], MakeMode.CONTENT_LIST, str(images)
            )
        result = self._convert_mineru_to_intermediate(middle, file_path, format)
        result["_native_markdown"] = markdown
        result["_mineru_middle_json"] = middle
        result["_mineru_content_list"] = content_list
        result["provenance"] = {
            "backend": self.name,
            "mineru_version": SUPPORTED_MINERU,
            "engine": engine,
            "effort": effort,
            "model_paths": status["model_paths"],
            "offline": True,
        }
        return result

    def _convert_mineru_to_intermediate(
        self, native: dict, file_path: Path, format: str
    ) -> dict:
        builder = IntermediateJSONBuilder(
            str(file_path.resolve()),
            format,
            len(native["pdf_info"]),
            file_path.stat().st_size,
        )
        for page in native["pdf_info"]:
            blocks = page.get("para_blocks", page.get("preproc_blocks", []))
            for block in blocks:
                kind = block.get("type", "unknown")
                content = self._extract_block_content(block)
                attributes = {
                    "content": content,
                    "confidence": None,
                    "mineru_block": block,
                    "coordinate_system": "pdf_points",
                    "source_page_size": page.get("page_size"),
                }
                if kind == "title":
                    kind = "header"
                    attributes["level"] = block.get("level", 1)
                elif kind in {"interline_equation", "display_formula"}:
                    kind = "display_formula"
                    attributes["latex"] = content
                elif kind == "table":
                    spans = list(self._spans(block))
                    attributes["markdown"] = "\n".join(
                        str(span["html"]) for span in spans if span.get("html")
                    )
                elif kind in {"image", "chart"}:
                    kind = "image"
                    attributes["path"] = next(
                        (
                            span["image_path"]
                            for span in self._spans(block)
                            if span.get("image_path")
                        ),
                        "",
                    )
                    attributes["caption"] = content
                builder.add_block(
                    type=kind,
                    page=int(page.get("page_idx", 0)) + 1,
                    bbox=block.get("bbox", [0, 0, 0, 0]),
                    **attributes,
                )
        return builder.build()

    @staticmethod
    def _spans(block):
        for line in block.get("lines", []):
            yield from line.get("spans", [])
        for child in block.get("blocks", []):
            yield from VlmHybridBackend._spans(child)

    @staticmethod
    def _extract_block_content(block: dict) -> str:
        if isinstance(block.get("content"), str):
            return block["content"]
        return "\n".join(
            str(span.get("content", ""))
            for span in VlmHybridBackend._spans(block)
            if span.get("content")
        )
