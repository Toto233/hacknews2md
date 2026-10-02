from __future__ import annotations

import tomllib
from pathlib import Path
from packaging.requirements import Requirement


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pdf_aes_dependency_is_declared_in_both_dependency_files() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {
        Requirement(item).name.lower()
        for item in pyproject["project"]["optional-dependencies"]["hackernews"]
    }
    requirements = {
        line.strip().lower().split("[", 1)[0].split("=", 1)[0]
        for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "pycryptodome" in dependencies
    assert "pycryptodome" in requirements


def test_legacy_requirements_match_all_runtime_features() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    expected = set(project["dependencies"])
    for extra in ("hackernews", "producthunt"):
        expected.update(project["optional-dependencies"][extra])
    actual = {
        line.strip()
        for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {str(Requirement(item)) for item in actual} == {str(Requirement(item)) for item in expected}


def test_ph_install_does_not_require_hn_browser_or_llm_providers() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = project["dependencies"] + project["optional-dependencies"]["producthunt"]
    names = {Requirement(item).name.lower() for item in dependencies}
    assert names.isdisjoint({"selenium", "playwright", "crawl4ai", "scrapling", "google-genai", "twscrape"})
