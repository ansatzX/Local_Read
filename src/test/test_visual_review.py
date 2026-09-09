"""Synthetic PDF evidence and mocked VLM contracts; no external service calls."""

import asyncio
import copy
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from local_read import visual_review as review


def region(identifier, box, kind="image", caption=None):
    return {
        "id": identifier,
        "original": {"bbox": box, "type": kind, "caption_id": caption},
    }


def page(regions=None, captions=None):
    return {
        "page": 1,
        "width": 600,
        "height": 800,
        "regions": regions or [region("r1", [50, 80, 300, 300])],
        "captions": captions or [],
    }


def caption(identifier="c1", box=None, kind="figure"):
    return {
        "id": identifier,
        "bbox": box or [50, 310, 300, 340],
        "kind": kind,
        "label": "1",
        "text": "Figure 1: Example",
    }


def test_rules_keep_category_conflicts_and_preserve_original():
    value = page([region("r1", [50, 80, 300, 300], "table")], [caption()])
    before = copy.deepcopy(value["regions"][0]["original"])
    review.check_page(value)
    r = value["regions"][0]
    assert r["original"] == before
    assert r["effective"]["caption_id"] == "c1"
    assert r["effective"]["type"] == "table"
    assert "caption_category_conflict" in r["checks"]["category"]["issues"]
    assert r["status"] == "needs_review"


def test_rules_reject_cross_column_and_ambiguous_association():
    value = page(captions=[caption("right", [400, 310, 590, 340])])
    assert review.check_page(value)["regions"][0]["effective"]["caption_id"] is None
    value = page(captions=[caption(), caption("c2", [50, 315, 300, 345])])
    r = review.check_page(value)["regions"][0]
    assert "ambiguous_captions" in r["checks"]["association"]["issues"]
    assert r["effective"]["caption_id"] is None


def test_rules_detect_overlap_shared_caption_and_invalid_bounds():
    value = page(
        [region("a", [50, 80, 300, 300]), region("b", [51, 81, 301, 301])], [caption()]
    )
    review.check_page(value)
    assert all(
        "overlapping_regions" in r["checks"]["boundary"]["issues"]
        for r in value["regions"]
    )
    assert all(
        "shared_caption_possible_panels" in r["checks"]["association"]["issues"]
        for r in value["regions"]
    )
    value = page([region("bad", [-1, 0, 10, 10])])
    assert (
        "invalid_bounds"
        in review.check_page(value)["regions"][0]["checks"]["boundary"]["issues"]
    )


def decision(identifier="r1", **kwargs):
    return {
        "region_id": identifier,
        "type": "image",
        "bbox": [50, 80, 300, 300],
        "caption_id": None,
        "status": "confirmed",
        "reason": "Visible region checked",
        **kwargs,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"region_id": "invented"},
        {"caption_id": "invented"},
        {"bbox": [0, 0, float("nan"), 200]},
        {"bbox": [0, 0, 999, 999]},
        {"type": "secret"},
        {"reason": ""},
        {"merge_with": ["invented"]},
        {"split_boxes": [[0, 0, 1, 1]]},
    ],
)
def test_response_validation_rejects_bad_proposals(change):
    with pytest.raises(ValueError):
        review.validate_response({"regions": [decision(**change)]}, page())


def test_response_must_cover_page_without_duplicates():
    for items in ([], [decision(), decision()]):
        with pytest.raises(ValueError):
            review.validate_response({"regions": items}, page())
    item = decision()
    del item["caption_id"]
    with pytest.raises(ValueError):
        review.validate_response({"regions": [item]}, page())


@pytest.fixture
def document(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_READ_MODEL_DIR", str(tmp_path / "models"))
    pdf = tmp_path / "sample.pdf"
    output = tmp_path / ".local_read_mcp/run"
    output.mkdir(parents=True)
    blocks = {}
    with fitz.open() as doc:
        for index in range(2):
            p = doc.new_page(width=600, height=800)
            p.draw_rect(fitz.Rect(50, 80, 300, 300), color=(0, 0, 1))
            p.insert_text((50, 330), f"Figure {index + 1}: Example")
            p.insert_text((50, 500), "We refer to Fig. 99 in this sentence.")
            blocks[str(index)] = {
                "type": "table",
                "page": index + 1,
                "bbox": [50, 80, 300, 300],
            }
        doc.save(pdf)
    intermediate = output / "intermediate.json"
    intermediate.write_text(
        json.dumps({"source": {"processed_pages": [1, 2]}, "blocks": blocks})
    )
    result = {
        "success": True,
        "output_directory": str(output),
        "files": {"intermediate_json": str(intermediate)},
    }
    return pdf, result


def test_offline_builds_context_and_never_calls_api(document, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("Offline review called API")

    monkeypatch.setattr(review, "_request_vlm", forbidden)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result))
    report = json.loads(Path(summary["report"]).read_text())
    assert summary["api_calls"] == 0
    assert summary["unresolved_regions"] == 2
    assert len(report["pages"][0]["captions"]) == 1  # body Fig. 99 is not a caption
    assert Path(report["pages"][0]["page_image"]).exists()
    assert Path(report["pages"][0]["annotated_image"]).exists()
    assert Path(report["pages"][0]["regions"][0]["original_crop"]).exists()


def configure(monkeypatch, enabled=True):
    from local_read import config

    monkeypatch.setattr(
        config,
        "get_config",
        lambda: SimpleNamespace(
            vision_enabled=enabled,
            model="mock-model",
            api_key="secret",
            base_url="https://example.invalid",
            vision_max_image_size_mb=20,
        ),
    )


def test_auto_corrects_with_audit_and_enforces_page_budget(document, monkeypatch):
    configure(monkeypatch)

    async def answer(p, _):
        return {
            "regions": [
                decision(
                    r["id"],
                    status="corrected",
                    bbox=[55, 85, 295, 295],
                    caption_id=p["captions"][0]["id"],
                )
                for r in p["regions"]
            ]
        }

    monkeypatch.setattr(review, "_request_vlm", answer)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result, "auto", 1))
    report = json.loads(Path(summary["report"]).read_text())
    assert summary["api_calls"] == 1
    first = report["pages"][0]["regions"][0]
    assert (
        first["original"]["type"] == "table" and first["effective"]["type"] == "image"
    )
    assert (
        first["status"] == "vlm_reviewed" and first["revisions"][-1]["source"] == "vlm"
    )
    assert first["original_crop"] != first["effective_crop"]
    assert Path(first["effective_crop"]).is_file()
    assert report["pages"][1]["vlm_status"] == "budget_exhausted"
    assert summary["status"] == "needs_review"


@pytest.mark.parametrize("mode", ["auto", "online"])
def test_missing_api_keeps_offline_result(document, monkeypatch, mode):
    configure(monkeypatch, False)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result, mode))
    assert summary["api_calls"] == 0 and summary["status"] == "needs_review"
    assert summary["warnings"]


def test_api_failure_does_not_leak_secret_or_change_offline_result(
    document, monkeypatch
):
    configure(monkeypatch)

    async def failure(*args):
        raise RuntimeError("API key: secret")

    monkeypatch.setattr(review, "_request_vlm", failure)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result, "online"))
    text = Path(summary["report"]).read_text()
    assert "secret" not in text and '"failed"' in text
    assert all(
        r["effective"]["type"] == "table"
        for p in json.loads(text)["pages"]
        for r in p["regions"]
    )


def test_cli_extraction_offline_review_outside_guard(document, monkeypatch, capsys):
    from local_read import cli, processing

    configure(monkeypatch)
    pdf, result = document
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [("allowed",)])

    async def process(**kwargs):
        with pytest.raises(RuntimeError, match="DNS"):
            socket.getaddrinfo("example.invalid", 443)
        return copy.deepcopy(result)

    monkeypatch.setattr(processing, "process_binary_file", process)

    async def answer(p, _):
        assert socket.getaddrinfo("example.invalid", 443) == [("allowed",)]
        return {
            "regions": [decision(r["id"], status="ambiguous") for r in p["regions"]]
        }

    monkeypatch.setattr(review, "_request_vlm", answer)
    assert cli.main(["convert", str(pdf), "--visual-review", "auto"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["visual_review"]["status"] == "needs_review"
    assert Path(output["files"]["visual_review"]).exists()


def test_auto_skips_rule_passed_pages_but_online_reviews_them(document, monkeypatch):
    configure(monkeypatch)
    pdf, result = document
    path = Path(result["files"]["intermediate_json"])
    data = json.loads(path.read_text())
    for block in data["blocks"].values():
        block["type"] = "image"
    path.write_text(json.dumps(data))
    calls = []

    async def answer(p, _):
        calls.append(p["page"])
        return {
            "regions": [
                decision(r["id"], caption_id=p["captions"][0]["id"])
                for r in p["regions"]
            ]
        }

    monkeypatch.setattr(review, "_request_vlm", answer)
    summary = asyncio.run(review.review_document(pdf, result, "auto"))
    assert summary["status"] == "rule_passed" and calls == []
    summary = asyncio.run(review.review_document(pdf, result, "online"))
    assert summary["status"] == "vlm_reviewed" and calls == [1, 2]


def test_invalid_response_preserves_all_region_states(document, monkeypatch):
    configure(monkeypatch)

    async def invalid(p, _):
        return {"regions": [decision(p["regions"][0]["id"]), decision("invented")]}

    monkeypatch.setattr(review, "_request_vlm", invalid)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result, "online"))
    data = json.loads(Path(summary["report"]).read_text())
    assert all(p["error_stage"] == "response_validation" for p in data["pages"])
    assert all(
        r["effective"]["type"] == "table" for p in data["pages"] for r in p["regions"]
    )


def test_topology_proposals_remain_explicitly_ambiguous(document, monkeypatch):
    configure(monkeypatch)

    async def propose(p, _):
        return {
            "regions": [
                decision(
                    r["id"],
                    status="ambiguous",
                    split_boxes=[[50, 80, 175, 300], [175, 80, 300, 300]],
                )
                for r in p["regions"]
            ]
        }

    monkeypatch.setattr(review, "_request_vlm", propose)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result, "online"))
    data = json.loads(Path(summary["report"]).read_text())
    assert summary["status"] == "needs_review"
    assert all(
        r["status"] == "ambiguous" and r["vlm_decision"]["split_boxes"]
        for p in data["pages"]
        for r in p["regions"]
    )


def test_vlm_receives_full_page_annotated_page_and_crops(document, monkeypatch):
    import sys
    from types import ModuleType

    received = {}

    class Client:
        def __init__(self, **kwargs):
            received["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create(self, **kwargs):
            received["request"] = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content='{"regions": []}'))
                ]
            )

    module = ModuleType("openai")
    module.AsyncOpenAI = Client
    monkeypatch.setitem(sys.modules, "openai", module)
    pdf, result = document
    summary = asyncio.run(review.review_document(pdf, result))
    p = json.loads(Path(summary["report"]).read_text())["pages"][0]
    config = SimpleNamespace(
        api_key="secret",
        base_url="https://example.invalid",
        model="mock",
        vision_max_image_size_mb=20,
    )
    asyncio.run(review._request_vlm(p, config))
    content = received["request"]["messages"][0]["content"]
    assert len([c for c in content if c["type"] == "image_url"]) == 2 + len(
        p["regions"]
    )
    assert "untrusted data" in content[0]["text"]
    assert received["client"]["max_retries"] == 0
    assert received["client"]["timeout"] == 60


def test_explicit_offline_review_enables_images_without_api(
    document, monkeypatch, capsys
):
    from local_read import cli, processing

    pdf, result = document

    async def process(**kwargs):
        assert kwargs["extract_images"] is True
        return copy.deepcopy(result)

    async def forbidden(*args):
        raise AssertionError("Unexpected API")

    monkeypatch.setattr(processing, "process_binary_file", process)
    monkeypatch.setattr(review, "_request_vlm", forbidden)
    assert cli.main(["convert", str(pdf), "--visual-review", "offline"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["visual_review"]["api_calls"] == 0
    assert output["visual_review"]["mode"] == "offline"
