"""Pinned MinerU hybrid API and artifact preservation, without loading models."""

import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from local_read.backends import mineru
from local_read.orchestrator import process_and_save
from local_read.segmenter import Chunk


def test_hybrid_uses_local_engine_two_returns_and_native_outputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        mineru,
        "model_status",
        lambda: {
            "models_ready": True,
            "model_paths": {"vlm": str(tmp_path / "models/vlm")},
        },
    )
    config = tmp_path / ".local_read_mcp/models/inference.json"
    monkeypatch.setattr(mineru, "local_inference_config", lambda: config)
    called = {}
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [600, 800],
                "para_blocks": [
                    {
                        "type": "interline_equation",
                        "bbox": [10, 20, 200, 50],
                        "lines": [
                            {
                                "spans": [
                                    {"type": "interline_equation", "content": "E=mc^2"}
                                ]
                            }
                        ],
                    },
                    {
                        "type": "table",
                        "bbox": [10, 60, 200, 100],
                        "lines": [
                            {"spans": [{"html": "<table><tr><td>42</td></tr></table>"}]}
                        ],
                    },
                ],
            }
        ]
    }

    def analyze(**kwargs):
        called.update(kwargs)
        assert os.environ["MINERU_MODEL_SOURCE"] == "local"
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["MINERU_TOOLS_CONFIG_JSON"] == str(config)
        return middle, []

    def render(info, mode, images):
        return (
            "$$E=mc^2$$\n<table><tr><td>42</td></tr></table>"
            if mode == "md"
            else [{"type": "equation", "text": "E=mc^2"}]
        )

    modules = {
        "mineru.backend.hybrid.hybrid_analyze": {"doc_analyze": analyze},
        "mineru.backend.vlm.vlm_middle_json_mkcontent": {"union_make": render},
        "mineru.data.data_reader_writer": {"FileBasedDataWriter": lambda path: path},
        "mineru.utils.engine_utils": {"get_vlm_engine": lambda engine: "transformers"},
        "mineru.utils.enum_class": {
            "MakeMode": SimpleNamespace(MM_MD="md", CONTENT_LIST="list")
        },
    }
    for name, members in modules.items():
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"fake PDF for adapter contract")
    output = tmp_path / ".local_read_mcp/run"
    output.mkdir(parents=True)
    result = process_and_save(
        str(source),
        mineru.VlmHybridBackend(),
        "pdf",
        output,
        output / "images",
        Chunk(phys_start=0, phys_end=0),
        {"images_output_dir": str(output / "images")},
    )
    assert called["backend"] == "transformers"
    assert called["model_path"] == str(tmp_path / "models/vlm")
    assert "server_url" not in called and "language" not in called
    assert called["image_writer"] is not None
    assert "$$E=mc^2$$" in Path(result["markdown_path"]).read_text()
    assert (
        json.loads(Path(result["native_files"]["mineru_middle"]).read_text()) == middle
    )
    ir = json.loads(Path(result["intermediate_path"]).read_text())
    blocks = list(ir["blocks"].values())
    assert blocks[0]["latex"] == "E=mc^2"
    assert blocks[0]["confidence"] is None
    assert "42" in blocks[1]["markdown"]
    assert ir["provenance"]["offline"]
    assert "_mineru_middle_json" not in ir
