#!/usr/bin/env python3
"""Build a portable skill archive using an explicit file allowlist."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package_skill() -> Path:
    root = Path(__file__).resolve().parents[1]
    output = Path.cwd() / ".local_read_mcp" / "dist" / "Local_Read.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [
        root / name
        for name in (
            "SKILL.md",
            "agents/openai.yaml",
            "references/usage.md",
            "LICENSE",
        )
    ]
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or unsafe release input: {path}")
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "local-read/" + path.relative_to(root).as_posix())
    return output


if __name__ == "__main__":
    print(package_skill())
