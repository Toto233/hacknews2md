"""Smoke tests for repository-installed publish-hacknews-codex scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "skills" / "publish-hacknews-codex" / "scripts"


def test_collect_context_script_loads_current_core_modules() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "collect_news_context.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_refetch_discussions_script_loads_current_core_modules() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "refetch_empty_discussions.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
