from pathlib import Path
from unittest.mock import Mock

from src.integrations.wechat.draft import DraftManager
from src.integrations.wechat_access_token import WeChatAccessToken


def test_facade_forwards_strict_images_to_draft_manager() -> None:
    client = object.__new__(WeChatAccessToken)
    client._draft_mgr = Mock()
    client._draft_mgr.add_draft_smart.return_value = "draft-id"
    articles = [{"title": "Test", "content": "<p>Body</p>"}]

    result = client.add_draft_smart(
        articles,
        default_thumb_media_id="existing-cover",
        thumb_image_path="cover.png",
        strict_images=True,
    )

    assert result == "draft-id"
    client._draft_mgr.add_draft_smart.assert_called_once_with(
        articles,
        default_thumb_media_id="existing-cover",
        thumb_image_path="cover.png",
        strict_images=True,
    )


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


def test_smart_draft_does_not_create_draft_after_body_image_upload_failure(tmp_path: Path) -> None:
    image = tmp_path / "body.jpg"
    image.write_bytes(b"image")
    media_manager = Mock()
    media_manager.upload_image_for_article.return_value = None
    media_manager.upload_permanent_material.return_value = {"media_id": "thumb-id"}
    manager = DraftManager(Mock(), media_manager)
    manager.add_draft = Mock(return_value="draft-id")

    result = manager.add_draft_smart(
        [{"title": "Test", "content": f'<p><img src="{image}"></p>'}],
        thumb_image_path=str(image),
        strict_images=True,
    )

    assert result is None
    manager.add_draft.assert_not_called()


def test_smart_draft_does_not_create_draft_after_cover_upload_failure(tmp_path: Path) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    media_manager = Mock()
    media_manager.upload_permanent_material.return_value = None
    manager = DraftManager(Mock(), media_manager)
    manager.add_draft = Mock(return_value="draft-id")

    result = manager.add_draft_smart(
        [{"title": "Test", "content": "<p>Body</p>"}],
        thumb_image_path=str(cover),
        strict_images=True,
    )

    assert result is None
    manager.add_draft.assert_not_called()
