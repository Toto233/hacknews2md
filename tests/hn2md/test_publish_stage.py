from pathlib import Path
from unittest.mock import patch

from hn2md.constants import Stage
from hn2md.stages.publish import PublishStage


def test_publish_calls_reusable_api_with_explicit_paths(tmp_path) -> None:
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    cover = tmp_path / "cover.png"
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()
    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("scripts.publish_wechat.publish_to_wechat", return_value="media-1") as publish,
    ):
        result = PublishStage().execute(
            object(), machine, markdown_file=str(md), cover_image=str(cover)
        )
    publish.assert_called_once_with(str(md), cover_image=str(cover))
    assert result["wechat_media_id"] == "media-1"
