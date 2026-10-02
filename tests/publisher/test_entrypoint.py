"""Compatibility routing and independence from Hacker News runtime dependencies."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from publisher.entrypoint import producthunt_arguments


def test_legacy_ph_arguments_keep_explicit_root_and_period() -> None:
    assert producthunt_arguments(["status", "producthunt", "--year", "2026", "--month", "9", "--root", "state"]) == [
        "--root", "state", "status", "--year", "2026", "--month", "9"
    ]
    assert producthunt_arguments(["publish", "producthunt", "--dry-run", "--year", "2026", "--month", "9"]) == [
        "preview", "--year", "2026", "--month", "9"
    ]
    assert producthunt_arguments(["fetch", "hackernews"]) is None


@pytest.mark.parametrize("command", ["release", "cover", "plan", "apply"])
def test_retired_basic_commands_cannot_create_an_unaudited_draft(command) -> None:
    with pytest.raises(Exception, match="retired"):
        producthunt_arguments([command, "producthunt"])


def test_ph_router_and_shared_api_do_not_import_hn_or_optional_dependencies(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = '''
import importlib.abc
import sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'hn2md', 'selenium', 'playwright', 'crawl4ai', 'scrapling', 'google', 'twscrape', 'scripts'}:
            raise AssertionError('PH imports forbidden module: ' + fullname)
sys.meta_path.insert(0, Forbidden())
from publisher_shared.wechat import publish_article, preview_article
from publisher.entrypoint import main
sys.argv = ['publisher', 'status', 'producthunt', '--root', sys.argv[1], '--year', '2026', '--month', '9']
main()
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], cwd=project_root,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "NOT_STARTED" in result.stdout
    assert not (tmp_path / "data" / "hacknews.db").exists()


def test_skill_documented_ph_commands_exist() -> None:
    import re
    from click.testing import CliRunner
    from ph2md.cli import main

    skill = (Path(__file__).resolve().parents[2] / "skills/publish-producthunt-monthly/SKILL.md").read_text(encoding="utf-8")
    commands = set(re.findall(r"(?:ph2md(?:\.ps1)?|scripts\\ph2md\.ps1)\s+([a-z][a-z-]+)", skill))
    assert {"status", "fetch", "export-plan", "audit", "render", "preview", "publish"} <= commands
    for command in commands:
        result = CliRunner().invoke(main, [command, "--help"])
        assert result.exit_code == 0, result.output
