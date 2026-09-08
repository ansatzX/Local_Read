"""Standalone CLI contracts, independent of an MCP installation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_read import __version__, cli


def test_version_without_input(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"Local_Read v{__version__}"


def test_convert_real_file_json_and_artifacts(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    Path("sample.txt").write_text("hello\nworld\n", encoding="utf-8")
    code = cli.main(["convert", "sample.txt", "--backend", "simple", "--no-metadata"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["status"] == "complete"
    assert "markdown_content" not in result and "intermediate" not in result
    output = Path(result["output_directory"])
    assert output.parent == tmp_path / ".local_read_mcp"
    assert "hello" in Path(result["files"]["markdown"]).read_text()
    assert json.loads(Path(result["files"]["result_json"]).read_text()) == result


def test_missing_file_json(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["convert", "missing.pdf"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert not (tmp_path / ".local_read_mcp").exists()


@pytest.mark.parametrize(
    "failures, expected, status",
    [(0, 0, "complete"), (1, 2, "partial"), (2, 1, "failed")],
)
def test_chunk_health_controls_cli_exit(
    monkeypatch, tmp_path, capsys, failures, expected, status
):
    from local_read import processing

    monkeypatch.chdir(tmp_path)
    Path("input.pdf").write_bytes(b"fixture")

    async def process(**kwargs):
        return {
            "success": True,
            "chunk_count": 2,
            "chunk_failure_count": failures,
            "chunk_success_count": 2 - failures,
            "all_chunks_failed": failures == 2,
        }

    monkeypatch.setattr(processing, "process_binary_file", process)
    assert cli.main(["convert", "input.pdf"]) == expected
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_cli_real_pdf_range_from_another_cwd(tmp_path):
    import fitz

    source = tmp_path / "source"
    source.mkdir()
    document = fitz.open()
    for text in ("FIRST_PAGE_MARKER", "SECOND_PAGE_MARKER", "THIRD_PAGE_MARKER"):
        document.new_page().insert_text((72, 72), text)
    document.save(source / "sample.pdf")
    document.close()
    caller = tmp_path / "caller"
    caller.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "local_read",
            "convert",
            "../source/sample.pdf",
            "--backend",
            "simple",
            "--start-page",
            "1",
            "--end-page",
            "1",
            "--strict-page-range",
        ],
        cwd=caller,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["output_directory"]).parent == caller / ".local_read_mcp"
    text = Path(payload["files"]["markdown"]).read_text()
    assert "SECOND_PAGE_MARKER" in text
    assert "FIRST_PAGE_MARKER" not in text and "THIRD_PAGE_MARKER" not in text
    assert not (source / ".local_read_mcp").exists()


def test_processing_imports_without_mcp(tmp_path):
    # Use a fresh interpreter so installed/previously imported MCP cannot mask a dependency.
    script = tmp_path / "without_mcp.py"
    script.write_text("""import importlib.abc
import sys
class BlockMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"mcp", "fastmcp"}:
            raise AssertionError("MCP dependency: " + fullname)
sys.meta_path.insert(0, BlockMCP())
from local_read import processing
assert callable(processing.process_binary_file)
assert callable(processing.analyze_images_batch)
""")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, str(script)], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_analyze_without_credentials_does_not_call_api(monkeypatch, capsys):
    from local_read import processing
    from local_read.config import Config

    monkeypatch.setenv("VISION_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(processing, "_config", Config())

    async def forbidden(**kwargs):
        pytest.fail("Vision API must not be called without configuration")

    monkeypatch.setattr(processing, "analyze_images_batch_with_cache", forbidden)
    assert cli.main(["analyze", "image.png"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_convert_blocks_hidden_network(monkeypatch, tmp_path, capsys):
    import socket

    from local_read import processing

    monkeypatch.chdir(tmp_path)
    Path("sample.pdf").write_bytes(b"fixture")

    async def network_parser(**kwargs):
        socket.getaddrinfo("example.com", 443)
        pytest.fail("Offline conversion unexpectedly allowed external DNS")

    monkeypatch.setattr(processing, "process_binary_file", network_parser)
    assert cli.main(["convert", "sample.pdf"]) == 1
    assert "blocked" in json.loads(capsys.readouterr().out)["error"]


def test_converter_error_is_not_successful_text(monkeypatch, tmp_path, capsys):
    from local_read.backends.simple import SimpleBackend
    from local_read.converters import DocumentConverterResult

    monkeypatch.chdir(tmp_path)
    Path("broken.pdf").write_bytes(b"broken PDF")
    monkeypatch.setattr(
        SimpleBackend,
        "_get_converter",
        lambda *args: (
            lambda *a, **kw: DocumentConverterResult(
                title=None, text_content="Error text", error="parser unavailable"
            )
        ),
    )
    assert cli.main(["convert", "broken.pdf", "--backend", "simple"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["error"] == "parser unavailable"
