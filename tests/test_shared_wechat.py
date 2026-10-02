"""Shared API checks use disposable files and mocked clients, never live HTTP."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from PIL import Image, ImageDraw

from publisher_shared.wechat import PublishError
from publisher_shared.wechat import article
from publisher_shared.wechat.token import TokenManager
from publisher_shared.wechat.converter import convert_markdown_to_html
from publisher_shared.wechat.draft import DraftManager
from src.db.connection import get_db


@pytest.fixture
def prepared_article(tmp_path: Path) -> tuple[Path, Path]:
    cover = tmp_path / "cover.png"
    image = Image.new("RGB", (1000, 500), "white")
    ImageDraw.Draw(image).rectangle((250, 100, 750, 400), fill="navy")
    image.save(cover)
    Image.new("RGB", (40, 40), "red").save(tmp_path / "body.png")
    markdown = tmp_path / "article.md"
    markdown.write_text("---\ntitle: PH Monthly\n---\n\nBody\n\n![Product](body.png)\n", encoding="utf-8")
    return markdown, cover


def test_preview_never_loads_credentials_or_uses_http(prepared_article, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Preview must stay offline")

    monkeypatch.setattr(article, "_configuration", forbidden)
    monkeypatch.setattr(article, "WeChatAccessToken", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    assert article.preview_article(*prepared_article, config_path=Path("missing-config.json"))


def _mock_client(monkeypatch, *, verified=True):
    client = Mock()
    client.get_access_token.return_value = "test-token"
    client.add_draft_smart.return_value = "draft-123"
    client.get_draft_list.return_value = {
        "item": [{"media_id": "draft-123", "content": {"news_item": [{
            "title": "PH Monthly", "thumb_media_id": "cover-id",
            "content": '<p><img src="https://mmbiz.qpic.cn/body.png"></p>' if verified else "<p>Missing image</p>",
        }]}}]
    }
    client.get_draft.return_value = client.get_draft_list.return_value["item"][0]["content"]
    factory = Mock(return_value=client)
    monkeypatch.setattr(article, "WeChatAccessToken", factory)
    monkeypatch.setenv("WECHAT_APPID", "test-appid")
    monkeypatch.setenv("WECHAT_APPSEC", "test-secret")
    monkeypatch.setenv("WECHAT_DB_PATH", "disposable-cache.db")
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("No live HTTP")))
    return client, factory


def test_publish_uploads_relative_images_and_verifies_remote_draft(prepared_article, monkeypatch) -> None:
    client, factory = _mock_client(monkeypatch)
    result = article.publish_article(*prepared_article)
    assert result.media_id == "draft-123"
    assert result.verified
    client.get_draft.assert_called_once_with("draft-123")
    client.get_draft_list.assert_not_called()
    factory.assert_called_once_with("test-appid", "test-secret", db_path="disposable-cache.db")
    sent = client.add_draft_smart.call_args
    assert sent.kwargs["strict_images"] is True
    assert sent.kwargs["thumb_image_path"] == str(prepared_article[1].resolve())
    assert str(prepared_article[0].parent / "body.png") in sent.args[0][0]["content"]


def test_unverified_creation_retains_media_id(prepared_article, monkeypatch) -> None:
    client, _ = _mock_client(monkeypatch, verified=False)
    with pytest.raises(PublishError) as failure:
        article.publish_article(*prepared_article)
    assert failure.value.media_id == "draft-123"
    client.add_draft_smart.assert_called_once()


def test_missing_image_stops_before_client_creation(prepared_article, monkeypatch) -> None:
    client, factory = _mock_client(monkeypatch)
    (prepared_article[0].parent / "body.png").unlink()
    with pytest.raises(PublishError, match="preflight"):
        article.publish_article(*prepared_article)
    factory.assert_not_called()
    client.add_draft_smart.assert_not_called()


def test_config_supports_legacy_secret_and_explicit_path(tmp_path, monkeypatch) -> None:
    for key in ("WECHAT_APPID", "WECHAT_APPSEC", "WECHAT_APPSECRET", "WECHAT_DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wechat": {"appid": "file-id", "appsec": "file-secret"}}), encoding="utf-8")
    assert article._configuration(config) == ("file-id", "file-secret", str(tmp_path / "data/wechat.db"))
    monkeypatch.setenv("WECHAT_APPSECRET", "env-secret")
    assert article._configuration(config)[1] == "env-secret"


def test_env_only_config_uses_explicit_workspace_for_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WECHAT_APPID", "test-id")
    monkeypatch.setenv("WECHAT_APPSEC", "test-secret")
    monkeypatch.delenv("WECHAT_DB_PATH", raising=False)
    config = tmp_path / "project" / "config" / "config.json"
    assert article._configuration(config) == (
        "test-id", "test-secret", str(tmp_path / "project" / "data" / "wechat.db")
    )


def test_token_cache_creates_directory_and_uses_unified_db(tmp_path) -> None:
    db_path = str(tmp_path / "nested" / "wechat.db")
    manager = TokenManager("test-id", "test-secret", db_path)
    assert manager._save_token_to_db("cached-token", 7200)
    assert manager._load_token_from_db() == "cached-token"
    with get_db(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_exact_draft_request_does_not_log_token_in_transport_error(monkeypatch) -> None:
    token_manager = Mock()
    token_manager.get_access_token.return_value = "credential-marker"
    log = Mock()
    monkeypatch.setattr("publisher_shared.wechat.draft.logger", log)
    request = Mock(side_effect=requests.RequestException("URL contained credential-marker"))
    monkeypatch.setattr("publisher_shared.wechat.draft.requests.post", request)
    assert DraftManager(token_manager, Mock()).get_draft("draft-123") is None
    request.assert_called_once()
    assert "credential-marker" not in repr(log.mock_calls)


def test_converter_escapes_metadata_headings_links_and_image_attributes() -> None:
    converted = convert_markdown_to_html(
        '---\ntitle: </title><script>alert(1)</script>\n---\n'
        '## <script>alert(1)</script>\n'
        '链接：http://example.test <img onerror="run()">\n'
        '![" onerror="run()](body.png)\n'
    )
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(converted, "html.parser")
    assert soup.find("script") is None
    assert soup.find("img").get("onerror") is None


def test_upload_replaces_escaped_local_image_path(tmp_path) -> None:
    image_path = tmp_path / "research & development.png"
    image_path.write_bytes(b"fixture-image")
    converted = convert_markdown_to_html(f"![Product]({image_path})")
    media = Mock()
    media.upload_image_for_article.return_value = "https://mmbiz.qpic.cn/body.png"
    media.upload_permanent_material.return_value = {"media_id": "cover-id"}
    manager = DraftManager(Mock(), media)
    manager.add_draft = Mock(return_value="draft-id")
    assert manager.add_draft_smart(
        [{"title": "Test", "content": converted}], strict_images=True
    ) == "draft-id"
    uploaded_content = manager.add_draft.call_args.args[0][0]["content"]
    assert "https://mmbiz.qpic.cn/body.png" in uploaded_content
    assert "development.png" not in uploaded_content
