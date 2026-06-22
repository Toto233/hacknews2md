"""PlanStage manual Codex-plan import tests."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hn2md.context import RuntimeContext
from hn2md.stages.plan import PlanStage


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
    return {
        "tags": ["人工智能", "开发工具", "开源项目", "网络安全"],
        "ordered_ids": [2, 1],
        "items": [
            {
                "id": 1,
                "title_chs": "第一篇中文标题",
                "content_summary": "这是一段长度足够的正文摘要，用于验证手工计划能够安全进入发布流水线。",
                "discuss_summary": "社区主要讨论实现方式、适用范围以及潜在限制。",
            },
            {
                "id": 2,
                "title_chs": "第二篇中文标题",
                "content_summary": "这是另一段长度足够的正文摘要，用于验证排序和内容字段不会被遗漏。",
                "discuss_summary": "讨论集中在性能、维护成本以及后续发展方向。",
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


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda plan: plan["items"].append(dict(plan["items"][0])), "duplicate"),
        (lambda plan: plan.update(ordered_ids=[1]), "ordered_ids"),
        (lambda plan: plan.update(tags=["只有一个"]), "four"),
        (lambda plan: plan["items"][0].update(title_chs=""), "title_chs"),
        (lambda plan: plan["items"][0].update(content_summary="太短"), "content_summary"),
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
