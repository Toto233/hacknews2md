from PIL import Image
from unittest.mock import Mock

from scripts.publish_wechat import build_cover_crop_fields, publish_to_wechat, verify_wechat_draft


def test_verify_wechat_draft_checks_retained_remote_body_images() -> None:
    wechat = Mock()
    wechat.get_draft_list.return_value = {
        "item": [
            {
                "media_id": "draft-id",
                "content": {
                    "news_item": [
                        {
                            "title": "Story",
                            "thumb_media_id": "thumb-id",
                            "content": '<p><img data-src="https://mmbiz.qpic.cn/body.jpg"></p>',
                        }
                    ]
                },
            }
        ]
    }

    assert verify_wechat_draft(wechat, "draft-id", "Story", 1) is True
    wechat.get_draft_list.assert_called_once_with(offset=0, count=20, no_content=0)

    wechat.get_draft_list.return_value["item"][0]["content"]["news_item"][0]["content"] = (
        '<p><img src="C:/local/body.jpg"></p>'
    )
    assert verify_wechat_draft(wechat, "draft-id", "Story", 1) is False

    wechat.get_draft_list.return_value["item"][0]["content"]["news_item"][0]["content"] = (
        "<p>Body without image</p>"
    )
    assert verify_wechat_draft(wechat, "draft-id", "Story", 1) is False

    wechat.get_draft_list.return_value["item"][0]["content"]["news_item"][0]["content"] = (
        '<p><img src="https://mmbiz.qpic.cn/body.jpg"></p>'
    )
    wechat.get_draft_list.return_value["item"][0]["content"]["news_item"][0]["thumb_media_id"] = ""
    assert verify_wechat_draft(wechat, "draft-id", "Story", 1) is False


def test_publish_wechat_status_output_is_ascii_safe() -> None:
    source = open("scripts/publish_wechat.py", encoding="utf-8").read()

    assert "✓" not in source
    assert "✗" not in source


def test_build_cover_crop_fields_for_wechat_wide_cover(tmp_path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (900, 383), "white").save(cover)

    assert build_cover_crop_fields(str(cover)) == {
        "pic_crop_235_1": "0_0_1_1",
        "pic_crop_1_1": "0.287222_0_0.712778_1",
    }


def test_build_cover_crop_fields_for_wechat_square_cover(tmp_path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (500, 500), "white").save(cover)

    assert build_cover_crop_fields(str(cover)) == {
        "pic_crop_235_1": "0_0.287234_1_0.712766",
        "pic_crop_1_1": "0_0_1_1",
    }


def test_publish_to_wechat_adds_cover_crop_fields_to_draft(tmp_path, monkeypatch) -> None:
    md = tmp_path / "article.md"
    md.write_text(
        "---\ntitle: Test Title\nauthor: tester\ndigest: digest\n---\n\n# Test Title\n\nBody",
        encoding="utf-8",
    )
    cover = tmp_path / "cover.png"
    Image.new("RGB", (900, 383), "white").save(cover)

    class FakeConfig:
        def get_wechat_config(self):
            return {"appid": "appid", "appsec": "secret"}

    class FakeWechat:
        def __init__(self, appid, appsec):
            self.appid = appid
            self.appsec = appsec
            self.calls = []

        def add_draft_smart(
            self, articles, default_thumb_media_id=None, thumb_image_path=None, strict_images=False
        ):
            self.calls.append((articles, default_thumb_media_id, thumb_image_path, strict_images))
            return "draft-media-id"

        def get_draft_list(self, *, offset, count, no_content):
            return {
                "item": [
                    {
                        "media_id": "draft-media-id",
                        "content": {
                            "news_item": [
                                {
                                    "title": "Test Title",
                                    "thumb_media_id": "thumb-id",
                                    "content": "<p>Body</p>",
                                }
                            ]
                        },
                    }
                ]
            }

    fake_wechat = FakeWechat("appid", "secret")
    monkeypatch.setitem(publish_to_wechat.__globals__, "Config", lambda: FakeConfig())
    monkeypatch.setitem(publish_to_wechat.__globals__, "WeChatAccessToken", lambda appid, appsec: fake_wechat)

    assert publish_to_wechat(
        str(md), cover_image=str(cover), auto_cover=False, strict_images=True
    ) == "draft-media-id"

    articles, default_thumb_media_id, thumb_image_path, strict_images = fake_wechat.calls[0]
    assert default_thumb_media_id is None
    assert thumb_image_path == str(cover)
    assert strict_images is True
    assert articles[0]["pic_crop_235_1"] == "0_0_1_1"
    assert articles[0]["pic_crop_1_1"] == "0.287222_0_0.712778_1"
