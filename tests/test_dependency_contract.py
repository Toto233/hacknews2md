from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pdf_aes_dependency_is_declared_in_both_dependency_files() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {item.lower().split("[", 1)[0].split("=", 1)[0] for item in pyproject["project"]["dependencies"]}
    requirements = {
        line.strip().lower().split("[", 1)[0].split("=", 1)[0]
        for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "pycryptodome" in dependencies
    assert "pycryptodome" in requirements
