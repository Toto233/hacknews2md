import os
import sys

import pytest
from PIL import Image

from scripts import publish_wechat


def _write_article(tmp_path, image_src: str) -> None:
    (tmp_path / "article.md").write_text(
        "---\n"
        "title: September products\n"
        "author: PH\n"
        "digest: Ten products from September\n"
        "source_url: https://www.producthunt.com/leaderboard/monthly/2026/9\n"
        "---\n\n"
        "## 1. Product\n\nA concrete description.\n\n"
        f"![Product]({image_src})\n",
        encoding="utf-8",
    )


def _colorful_image(path, size=(1200, 520)) -> None:
    image = Image.new("RGB", size)
    for x in range(size[0]):
        color = (x * 255 // size[0], 40, 255 - x * 255 // size[0])
        for y in range(size[1]):
            image.putpixel((x, y), color)
    image.save(path)


def test_preview_converts_and_checks_content_without_wechat_calls(tmp_path, monkeypatch, capsys) -> None:
    logo = tmp_path / "logo.png"
    cover = tmp_path / "cover.png"
    _colorful_image(logo, (100, 100))
    _colorful_image(cover)
    _write_article(tmp_path, str(logo))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview must not use WeChat, config, or cover generation")

    monkeypatch.setattr(publish_wechat, "Config", forbidden)
    monkeypatch.setattr(publish_wechat, "WeChatAccessToken", forbidden)
    monkeypatch.setattr(publish_wechat, "generate_cover", forbidden)
    monkeypatch.setattr(sys, "argv", ["publish_wechat.py", str(tmp_path / "article.md"), "--cover-image", str(cover), "--preview"])

    publish_wechat.main()

    output = capsys.readouterr().out
    assert "文章: September products | 作者: PH" in output
    assert "图片: 1 本地 / 0 远程" in output
    assert "封面裁剪: 2.35:1=" in output
    assert "1:1=" in output
    assert "预检结果: 通过" in output


@pytest.mark.parametrize("image_state", ["missing", "corrupt"])
def test_preview_rejects_unusable_article_image(tmp_path, monkeypatch, capsys, image_state) -> None:
    logo = tmp_path / "logo.png"
    if image_state == "corrupt":
        logo.write_text("not an image", encoding="utf-8")
    _write_article(tmp_path, str(logo))
    monkeypatch.setattr(sys, "argv", ["publish_wechat.py", str(tmp_path / "article.md"), "--preview", "--no-auto-cover"])

    with pytest.raises(SystemExit) as result:
        publish_wechat.main()

    assert result.value.code == 1
    output = capsys.readouterr().out
    assert ("正文图片不存在" if image_state == "missing" else "正文图片无法读取") in output
    assert "预检结果: 失败" in output


def test_preview_rejects_blank_cover_and_reports_both_crops(tmp_path, capsys) -> None:
    logo = tmp_path / "logo.png"
    cover = tmp_path / "cover.png"
    _colorful_image(logo, (100, 100))
    Image.new("RGB", (900, 383), "white").save(cover)
    _write_article(tmp_path, str(logo))

    assert not publish_wechat.preview_wechat_article(
        str(tmp_path / "article.md"), cover_image=str(cover)
    )

    output = capsys.readouterr().out
    assert "封面 2.35:1 缩略图对比度过低" in output
    assert "封面 1:1 缩略图对比度过低" in output
    assert "封面裁剪: 2.35:1=" in output


def test_preview_rejects_article_image_format_not_supported_by_uploader(tmp_path, capsys) -> None:
    logo = tmp_path / "logo.gif"
    Image.new("RGB", (100, 100), "red").save(logo)
    _write_article(tmp_path, str(logo))

    assert not publish_wechat.preview_wechat_article(str(tmp_path / "article.md"), auto_cover=False)
    assert "正文图片格式不受微信自动上传支持" in capsys.readouterr().out


def test_preview_rejects_article_image_over_uploader_limit(tmp_path, capsys) -> None:
    logo = tmp_path / "large.png"
    Image.frombytes("RGB", (700, 700), os.urandom(700 * 700 * 3)).save(logo)
    assert logo.stat().st_size > 1024 * 1024
    _write_article(tmp_path, str(logo))

    assert not publish_wechat.preview_wechat_article(str(tmp_path / "article.md"), auto_cover=False)
    assert "正文图片超过微信自动上传 1MB 限制" in capsys.readouterr().out


def test_preview_rejects_missing_cover_and_empty_body(tmp_path, capsys) -> None:
    (tmp_path / "article.md").write_text(
        "---\ntitle: Empty\nauthor: PH\n---\n", encoding="utf-8"
    )

    assert not publish_wechat.preview_wechat_article(
        str(tmp_path / "article.md"), cover_image=str(tmp_path / "missing.png")
    )

    output = capsys.readouterr().out
    assert "转换后的文章正文为空" in output
    assert "指定封面不存在" in output
