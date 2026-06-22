"""ApplyStage is the single plan-to-database implementation."""

import json
import sqlite3
from pathlib import Path

import pytest

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.stages.apply import ApplyStage


def _ctx(tmp_path: Path) -> RuntimeContext:
    db_path = tmp_path / "data" / "hacknews.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE news (id INTEGER PRIMARY KEY, title_chs TEXT, content_summary TEXT, discuss_summary TEXT)"
        )
        conn.executemany("INSERT INTO news (id) VALUES (?)", [(1,), (2,)])
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


def _plan(tmp_path: Path, items: list[dict] | None = None) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "items": items
                or [
                    {"id": 1, "title_chs": "标题", "content_summary": "正文摘要", "discuss_summary": "讨论摘要"},
                    {"id": 2, "title_chs": "标题二", "content_summary": "正文摘要二", "discuss_summary": "讨论摘要二"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_apply_accepts_explicit_plan_file(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(tmp_path)

    result = ApplyStage().execute(ctx, object(), plan_file=str(plan))

    assert result == {"updated": 2, "plan_file": str(plan.resolve())}


def test_apply_falls_back_to_planning_receipt(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(tmp_path)
    machine = type(
        "Machine",
        (),
        {"job": type("Job", (), {"stages": {Stage.PLANNING.value: {"output_summary": {"plan_file": str(plan)}}}})()},
    )()

    result = ApplyStage().execute(ctx, machine)

    assert result["updated"] == 2


def test_apply_rejects_unknown_id_without_partial_writes(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    plan = _plan(
        tmp_path,
        [
            {"id": 1, "title_chs": "会回滚", "content_summary": "摘要", "discuss_summary": "讨论"},
            {"id": 999, "title_chs": "不存在", "content_summary": "摘要", "discuss_summary": "讨论"},
        ],
    )

    with pytest.raises(ValueError, match="unknown news ids"):
        ApplyStage().execute(ctx, object(), plan_file=str(plan))

    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT title_chs FROM news WHERE id=1").fetchone()[0] is None
