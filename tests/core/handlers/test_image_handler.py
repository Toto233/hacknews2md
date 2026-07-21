"""Tests for article image handling."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from PIL import Image

from src.core.handlers.image_handler import (
    get_extension_from_content_type,
    is_low_signal_article_image_url,
    save_article_image,
)


# ---------------------------------------------------------------------------
# get_extension_from_content_type
# ---------------------------------------------------------------------------


class TestGetExtensionFromContentType:
    """Tests for get_extension_from_content_type(content_type)."""

    # --- JPEG ---------------------------------------------------------------

    def test_jpeg(self):
        assert get_extension_from_content_type("image/jpeg") == ".jpg"

    def test_jpg_in_type(self):
        assert get_extension_from_content_type("image/jpg") == ".jpg"

    def test_jpeg_uppercase(self):
        assert get_extension_from_content_type("IMAGE/JPEG") == ".jpg"

    def test_jpeg_with_charset(self):
        assert get_extension_from_content_type("image/jpeg; charset=utf-8") == ".jpg"

    # --- PNG ----------------------------------------------------------------

    def test_png(self):
        assert get_extension_from_content_type("image/png") == ".png"

    def test_png_uppercase(self):
        assert get_extension_from_content_type("IMAGE/PNG") == ".png"

    # --- GIF ----------------------------------------------------------------

    def test_gif(self):
        assert get_extension_from_content_type("image/gif") == ".gif"

    # --- WebP ---------------------------------------------------------------

    def test_webp(self):
        assert get_extension_from_content_type("image/webp") == ".webp"

    # --- AVIF ---------------------------------------------------------------

    def test_avif(self):
        assert get_extension_from_content_type("image/avif") == ".avif"

    # --- SVG ----------------------------------------------------------------

    def test_svg(self):
        assert get_extension_from_content_type("image/svg+xml") == ".svg"

    def test_svg_plain(self):
        assert get_extension_from_content_type("image/svg") == ".svg"

    # --- Unknown / edge cases -----------------------------------------------

    def test_unknown_type_returns_none(self):
        assert get_extension_from_content_type("image/bmp") is None

    def test_tiff_returns_none(self):
        assert get_extension_from_content_type("image/tiff") is None

    def test_empty_string(self):
        assert get_extension_from_content_type("") is None

    def test_non_image_type(self):
        assert get_extension_from_content_type("text/html") is None

    def test_application_octet_stream(self):
        assert get_extension_from_content_type("application/octet-stream") is None


class TestIsLowSignalArticleImageUrl:
    """Tests for decorative article image URL filtering."""

    def test_filters_logos_and_badges(self):
        assert is_low_signal_article_image_url("https://assets.apnews.com/ap-logo-176-by-208.svg")
        assert is_low_signal_article_image_url("https://img.shields.io/badge/Postgres-18.3-brightgreen")
        assert is_low_signal_article_image_url(
            "https://static.example.com/getitongoogleplay-badge-web-color-english.png"
        )
        assert is_low_signal_article_image_url(
            "https://camo.githubusercontent.com/d10e57/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f506f7374677265732d31382e332d333336373931"
        )
        assert is_low_signal_article_image_url("https://github.com/project/repo/raw/main/assets/mark.svg")

    def test_filters_branding_and_social_decoration(self):
        assert is_low_signal_article_image_url("https://techcrunch.com/wp-content/uploads/2026/05/tc-lockup-hp.svg")
        assert is_low_signal_article_image_url(
            "https://terrytao.wordpress.com/wp-content/uploads/2020/03/cropped-covid-19-curves-graphic-social-v3.gif"
        )
        assert is_low_signal_article_image_url("https://www.gstatic.com/images/branding/googlelogo/svg/googlelogo_clr_74x24px.svg")
        assert is_low_signal_article_image_url("https://nebusec.ai/static/nebula_security.svg")
        assert is_low_signal_article_image_url("https://nebusec.ai/_astro/race-timeline.light.BdOWiamE.svg")
        assert is_low_signal_article_image_url(
            "https://static.wixstatic.com/media/d3c6c2_6cb311b23d384e589472df9b57ce7e21~mv2.jpg/v1/fill/w_94,h_73,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/IMG_4008.jpg"
        )
        assert is_low_signal_article_image_url(
            "https://static.wixstatic.com/media/d3c6c2_a5bf2bded3f24154963d832491833e70~mv2.png/v1/fill/w_40,h_47,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/SN_Certified_ART.png"
        )

    def test_filters_all_svg_images(self):
        assert is_low_signal_article_image_url("https://example.com/diagrams/architecture.svg")
        assert is_low_signal_article_image_url(
            "https://jj-vcs.github.io/jj/latest/images/operation-log/fixup-before-light.svg"
        )
        assert is_low_signal_article_image_url("https://example.com/image.svg?width=1200")

    def test_keeps_likely_article_images(self):
        assert not is_low_signal_article_image_url("https://cdn.example.com/photos/article-photo.jpg")
        assert not is_low_signal_article_image_url("https://example.com/images/chart-of-results.png")
        assert not is_low_signal_article_image_url(
            "https://static.wixstatic.com/media/d3c6c2_real_chart.png/v1/fill/w_900,h_700,al_c,q_85,enc_avif,quality_auto/chart.png"
        )

    def test_filters_known_runtime_noise_assets(self):
        assert is_low_signal_article_image_url(
            "https://pbs.twimg.com/profile_images/1234/avatar_normal.jpg"
        )
        assert is_low_signal_article_image_url("https://news.ycombinator.com/s.gif")
        assert is_low_signal_article_image_url("https://static.example.com/images/grey-placeholder.png")


class _ImageResponse:
    status_code = 200
    headers = {"Content-Type": "image/webp"}

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def iter_content(self, chunk_size: int):
        yield self.payload


def _png_payload() -> bytes:
    output = BytesIO()
    Image.new("RGB", (120, 120), "white").save(output, "PNG")
    return output.getvalue()


def test_save_article_image_converts_from_temp_file_and_keeps_unique_paths(monkeypatch, tmp_path) -> None:
    from src.core.handlers import image_handler

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(image_handler, "validate_url", lambda _url: None)
    monkeypatch.setattr(image_handler.requests, "get", lambda *args, **kwargs: _ImageResponse(_png_payload()))

    with ThreadPoolExecutor(max_workers=3) as executor:
        paths = list(
            executor.map(
                lambda _: save_article_image("https://example.com/article.webp", "https://example.com", "Same title"),
                range(3),
            )
        )

    assert all(paths)
    assert len(set(paths)) == 3
    assert all(path.endswith(".png") for path in paths)
    assert not list((tmp_path / "output" / "images").rglob("*.part"))
