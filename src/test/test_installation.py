"""One explicit installation; document reads and skill copies never install."""

import json
import os
import runpy
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from local_read import cli
from local_read.config import Config
from local_read.installation import doctor
from local_read.local_runtime import cli_path, installed_environment

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def user_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(tmp_path)
    return home


def test_doctor_reports_conflicts_without_writing(monkeypatch, user_home, tmp_path):
    alternate = tmp_path / "other/local-read"
    alternate.parent.mkdir()
    alternate.write_text("#!/bin/sh\n")
    alternate.chmod(0o755)
    entry = cli_path()
    entry.parent.mkdir(parents=True)
    binary = installed_environment() / "bin/local-read"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    entry.symlink_to(binary)
    old = user_home / ".cache/local-read/runtime/old/pyvenv.cfg"
    old.parent.mkdir(parents=True)
    old.touch()
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(alternate.parent), str(entry.parent)])
    )
    before = set(tmp_path.rglob("*"))
    report = doctor()
    assert len(report["path_candidates"]) == 2
    assert report["legacy_environments"] == [str(old.parent)]
    assert any("PATH selects" in w for w in report["warnings"])
    assert before == set(tmp_path.rglob("*"))


def test_doctor_cli_json_and_no_output_directory(user_home, capsys):
    assert cli.main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "installation_source" in report and "canonical_cli" in report
    assert not Path(".local_read_mcp").exists()


def test_two_projects_read_without_uv_or_new_environments(
    monkeypatch, user_home, tmp_path, capsys
):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("must not install")
    )
    for name in ("one", "two"):
        project = tmp_path / name
        project.mkdir()
        (project / "note.txt").write_text("Shared CLI reads this local document.")
        monkeypatch.chdir(project)
        assert cli.main(["convert", "note.txt", "--backend", "simple"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert Path(result["files"]["markdown"]).is_relative_to(project)
    assert not (user_home / ".local/share/local-read").exists()


def test_config_is_global_and_does_not_load_project_dotenv(
    monkeypatch, user_home, tmp_path
):
    monkeypatch.delenv("LOCAL_READ_CONFIG_DIR", raising=False)
    monkeypatch.delenv("VISION_MODEL", raising=False)
    (tmp_path / ".env").write_text("VISION_MODEL=project-value\n")
    config = user_home / ".config/local-read/.env"
    config.parent.mkdir(parents=True)
    config.write_text("VISION_MODEL=global-value\n")
    assert Config().model == "global-value"


def test_skill_archive_has_no_installer_or_runtime(user_home):
    output = runpy.run_path(str(ROOT / "scripts/package_skill.py"))["package_skill"]()
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "local-read/SKILL.md",
            "local-read/references/usage.md",
            "local-read/agents/openai.yaml",
            "local-read/LICENSE",
        }


def installer(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: "/fake/uv")
    return runpy.run_path(str(ROOT / "scripts/install_cli.py"))["main"]


def test_install_is_explicit_and_uses_single_location(monkeypatch, user_home):
    install = installer(monkeypatch)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs["env"]))
        if args[1:3] == ["tool", "install"]:
            binary = installed_environment() / "bin/local-read"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("installed snapshot")
            cli_path().parent.mkdir(parents=True, exist_ok=True)
            if not cli_path().is_symlink():
                cli_path().symlink_to(binary)

    monkeypatch.setattr(subprocess, "run", run)
    assert install([]) == 0
    assert install([]) == 1  # No implicit replacement.
    assert len(calls) == 2
    assert install(["--upgrade"]) == 0
    args, env = calls[-1]
    assert "--force" in args and "--editable" not in args
    assert env["UV_TOOL_BIN_DIR"] == str(cli_path().parent)
    assert env["UV_TOOL_DIR"] == str(installed_environment().parent)
    assert calls[0][0][1] == "export" and "--locked" in calls[0][0]


def test_installer_refuses_unmanaged_entry(monkeypatch, user_home):
    install = installer(monkeypatch)
    cli_path().parent.mkdir(parents=True)
    cli_path().write_text("another installation")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("must not overwrite")
    )
    assert install(["--upgrade"]) == 1
    assert cli_path().read_text() == "another installation"


def test_failed_export_does_not_start_install(monkeypatch, user_home):
    install = installer(monkeypatch)
    calls = []

    def fail(args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", fail)
    assert install([]) == 1
    assert len(calls) == 1 and calls[0][1] == "export"
    assert not cli_path().exists()
