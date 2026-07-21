from pathlib import Path
from unittest.mock import Mock

from src.integrations.wechat.draft import DraftManager


def test_smart_draft_uploads_local_html_images_with_apostrophes_in_their_paths(tmp_path: Path) -> None:
    first = tmp_path / "Romania's_registry.png"
    second = tmp_path / "Corners_Don't_Look_Like_That.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    media_manager = Mock()
    media_manager.upload_image_for_article.side_effect = ["https://cdn.example/first", "https://cdn.example/second"]
    media_manager.upload_permanent_material.return_value = {"media_id": "thumb-id"}
    token_manager = Mock()
    manager = DraftManager(token_manager, media_manager)
    manager.add_draft = Mock(return_value="draft-id")

    result = manager.add_draft_smart(
        [
            {
                "title": "Test",
                "content": f'<p><img src="{first}"><img src="{second}"></p>',
            }
        ]
    )

    assert result == "draft-id"
    assert media_manager.upload_image_for_article.call_args_list == [
        ((str(first),),),
        ((str(second),),),
    ]
    article = manager.add_draft.call_args.args[0][0]
    assert "https://cdn.example/first" in article["content"]
    assert "https://cdn.example/second" in article["content"]
