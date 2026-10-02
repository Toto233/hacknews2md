"""PlanStage manual Codex-plan import tests."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from hn2md.context import RuntimeContext
from hn2md.stages.plan import PlanStage
from src.utils.db_utils import init_database


def _ctx(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "hacknews.db",
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )


def _valid_plan() -> dict:
    content_one = ("正文摘要覆盖事件、机制、关键事实、限制与影响，避免空泛导语。" * 14)[:300]
    content_two = ("另一篇正文同样交代来源事实、实现方式、适用范围和潜在风险。" * 14)[:300]
    discussion_one = ("社区讨论包含支持意见、反对意见、具体案例及尚未解决的问题。" * 10)[:200]
    discussion_two = ("评论重点比较实践经验、维护成本、性能表现和后续发展方向。" * 10)[:200]
    return {
        "tags": ["人工智能", "开发工具", "开源项目", "网络安全"],
        "ordered_ids": [2, 1],
        "items": [
            {
                "id": 1,
                "title_chs": "第一篇中文标题",
                "content_summary": content_one,
                "discuss_summary": discussion_one,
            },
            {
                "id": 2,
                "title_chs": "第二篇中文标题",
                "content_summary": content_two,
                "discuss_summary": discussion_two,
            },
        ],
    }


def _write_plan(tmp_path: Path, plan: object) -> Path:
    path = tmp_path / "manual-plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return path


def test_manual_plan_imports_without_external_llm(tmp_path) -> None:
    source = _write_plan(tmp_path, _valid_plan())
    stage = PlanStage()

    with (
        patch("src.llm.llm_business.generate_summary", side_effect=AssertionError("LLM called")) as summary,
        patch("src.llm.llm_business.translate_title", side_effect=AssertionError("LLM called")) as title,
        patch("src.llm.llm_evaluator.evaluate_news_attraction", side_effect=AssertionError("LLM called")) as rank,
        patch("src.llm.llm_tag_extractor.extract_tags_with_llm", side_effect=AssertionError("LLM called")) as tags,
    ):
        result = stage.execute(_ctx(tmp_path), object(), manual_plan_file=str(source))

    assert result["manual"] is True
    assert result["story_count"] == 2
    imported = Path(result["plan_file"])
    assert imported.parent == _ctx(tmp_path).codex_dir
    assert json.loads(imported.read_text(encoding="utf-8"))["ordered_ids"] == [2, 1]
    summary.assert_not_called()
    title.assert_not_called()
    rank.assert_not_called()
    tags.assert_not_called()


def test_manual_plan_preserves_discussion_summary_source_fields(tmp_path) -> None:
    plan = _valid_plan()
    plan["items"][0]["discuss_summary_source_type"] = "external_hn_snippet"
    plan["items"][0]["discuss_summary_source_url"] = "https://news.ycombinator.com/item?id=1"
    source = _write_plan(tmp_path, plan)

    result = PlanStage().execute(_ctx(tmp_path), object(), manual_plan_file=str(source))

    imported = json.loads(Path(result["plan_file"]).read_text(encoding="utf-8"))
    assert imported["items"][0]["discuss_summary_source_type"] == "external_hn_snippet"
    assert imported["items"][0]["discuss_summary_source_url"] == "https://news.ycombinator.com/item?id=1"


def test_automatic_plan_reads_the_run_period_not_system_today(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    init_database(str(ctx.db_path))
    with sqlite3.connect(ctx.db_path) as conn:
        for news_id, created_at in ((1, "2000-01-02 10:00:00"), (2, "2000-01-03 10:00:00")):
            conn.execute(
                "INSERT INTO news (id, title, title_chs, news_url, content_summary, discuss_summary, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    news_id,
                    f"Story {news_id}",
                    f"标题 {news_id}",
                    f"https://example.com/{news_id}",
                    "正文摘要。" * 60,
                    "讨论摘要。" * 40,
                    created_at,
                ),
            )
    machine = type("M", (), {"job": type("J", (), {"date": "20000102"})()})()

    with (
        patch("src.llm.llm_business.generate_summary", side_effect=AssertionError("LLM called")),
        patch("src.llm.llm_business.translate_title", side_effect=AssertionError("LLM called")),
        patch("src.llm.llm_evaluator.evaluate_news_attraction", return_value=([], None)),
        patch("src.llm.llm_tag_extractor.extract_tags_with_llm", return_value=["标签1", "标签2", "标签3", "标签4"]),
    ):
        result = PlanStage().execute(ctx, machine)

    plan = json.loads(Path(result["plan_file"]).read_text(encoding="utf-8"))
    assert result["story_count"] == 1
    assert plan["ordered_ids"] == [1]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda plan: plan["items"].append(dict(plan["items"][0])), "duplicate"),
        (lambda plan: plan.update(ordered_ids=[1]), "ordered_ids"),
        (lambda plan: plan.update(tags=["只有一个"]), "four"),
        (lambda plan: plan["items"][0].update(title_chs=""), "title_chs"),
        (lambda plan: plan["items"][0].update(content_summary="太短"), "content_summary"),
        (lambda plan: plan["items"][0].update(discuss_summary="太短"), "discuss_summary"),
        (
            lambda plan: plan["items"][0].update(content_summary="As an AI language model, I cannot confirm this article."),
            "hallucination",
        ),
    ],
)
def test_manual_plan_rejects_invalid_content(tmp_path, mutate, message) -> None:
    plan = _valid_plan()
    mutate(plan)
    source = _write_plan(tmp_path, plan)

    with pytest.raises(ValueError, match=message):
        PlanStage().execute(_ctx(tmp_path), object(), manual_plan_file=str(source))
