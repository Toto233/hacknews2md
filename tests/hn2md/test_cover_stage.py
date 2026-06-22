from pathlib import Path
from unittest.mock import patch

from hn2md.constants import Stage
from hn2md.stages.cover import CoverStage


def _machine(md: Path):
    return type("M", (), {"job": type("J", (), {"stages": {Stage.RENDERING.value: {"output_summary": {"markdown_file": str(md)}}}})()})()


def test_cover_ai_calls_reusable_api(tmp_path) -> None:
    md = tmp_path / "a.md"
    with patch("scripts.generate_wechat_cover_ai.generate_cover_ai", return_value="ai.png") as generate:
        result = CoverStage().execute(object(), _machine(md), mode="ai", target_word="短标题")
    generate.assert_called_once_with(str(md), target_word="短标题")
    assert result["cover_image"] == "ai.png"


def test_cover_pillow_calls_reusable_api(tmp_path) -> None:
    md = tmp_path / "a.md"
    with patch("scripts.generate_wechat_cover.generate_cover", return_value="pillow.png") as generate:
        result = CoverStage().execute(object(), _machine(md), markdown_file=str(md), mode="pillow")
    generate.assert_called_once_with(str(md))
    assert result["cover_image"] == "pillow.png"
