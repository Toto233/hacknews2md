"""Plan-driven canonical Markdown rendering tests."""

import json
import sqlite3
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

import pytest

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.stages.render import RenderStage
from src.core.generate_markdown import generate_markdown


def _ctx(tmp_path: Path) -> RuntimeContext:
    db_path = tmp_path / "data" / "hacknews.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE news (
                id INTEGER PRIMARY KEY, title TEXT, title_chs TEXT, news_url TEXT,
                discuss_url TEXT, content_summary TEXT, discuss_summary TEXT,
                largest_image TEXT, image_2 TEXT, image_3 TEXT, screenshot TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO news VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "English One", "中文一", "https://one", "https://hn/1", "摘要一", "讨论一", None, None, None, None),
                (2, 'English: "Two"', '中文："二"', "https://two", "https://hn/2", "摘要二\n第二行", "讨论二", None, None, None, None),
            ],
        )
    output = tmp_path / "output"
    return RuntimeContext(
        project_root=tmp_path,
        db_path=db_path,
        output_dir=output,
        job_dir=output / "jobs",
        markdown_dir=output / "markdown",
        images_dir=output / "images",
        codex_dir=output / "codex",
        config_path=tmp_path / "config" / "config.json",
    )


def _plan(tmp_path: Path) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "ordered_ids": [2, 1],
                "tags": ["AI", "开发", "开源", "安全"],
                "items": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_generate_markdown_preserves_plan_order_and_tags(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(tmp_path)

    result = generate_markdown(
        db_path=ctx.db_path,
        output_dir=ctx.markdown_dir,
        plan_file=plan,
        now=datetime(2026, 6, 22, 12, 30),
    )

    markdown = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert markdown.index("## 1. 中文：\"二\"") < markdown.index("## 2. 中文一")
    for tag in ["AI", "开发", "开源", "安全"]:
        assert f'  - "{tag}"' in markdown
    assert 'title: "中文：\\"二\\" | Hacker News 摘要 (2026-06-22)"' in markdown
    assert Path(result["html_file"]).exists()
    assert result["astro_file"] is None


def test_generate_markdown_astro_file_has_single_terminal_newline(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(tmp_path)
    astro_dir = tmp_path / "astro" / "src" / "data" / "blog"

    result = generate_markdown(
        db_path=ctx.db_path,
        output_dir=ctx.markdown_dir,
        plan_file=plan,
        astro_blog_dir=astro_dir,
        now=datetime(2026, 6, 22, 12, 30),
    )

    astro_text = Path(result["astro_file"]).read_text(encoding="utf-8")
    assert astro_text.endswith("\n")
    assert not astro_text.endswith("\n\n")


def test_render_stage_uses_applying_plan_receipt(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(tmp_path)
    machine = type(
        "Machine",
        (),
        {"job": type("Job", (), {"stages": {Stage.APPLYING.value: {"output_summary": {"plan_file": str(plan)}}}})()},
    )()

    result = RenderStage().execute(ctx, machine)

    assert result["plan_file"] == str(plan.resolve())
    assert Path(result["markdown_file"]).exists()


def test_render_stage_blocks_astro_when_repo_has_staged_changes(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(tmp_path)
    astro_repo = tmp_path / "astro"
    (astro_repo / ".git").mkdir(parents=True)
    astro_blog_dir = astro_repo / "src" / "data" / "blog"
    machine = type(
        "Machine",
        (),
        {"job": type("Job", (), {"stages": {Stage.APPLYING.value: {"output_summary": {"plan_file": str(plan)}}}})()},
    )()
    settings = type("Settings", (), {"astro_blog_dir": astro_blog_dir})()

    completed = type("Completed", (), {"returncode": 0, "stdout": "src/data/blog/old.md\n", "stderr": ""})()
    with (
        patch("src.utils.deployment.load_deployment_settings", return_value=settings),
        patch("subprocess.run", return_value=completed),
    ):
        with pytest.raises(RuntimeError, match="Astro repository has staged changes"):
            RenderStage().execute(ctx, machine)
