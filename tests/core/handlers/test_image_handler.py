"""Tests for pure functions in image_handler.py."""

import pytest

from src.core.handlers.image_handler import get_extension_from_content_type, is_low_signal_article_image_url


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

    def test_keeps_likely_article_images(self):
        assert not is_low_signal_article_image_url("https://cdn.example.com/photos/article-photo.jpg")
        assert not is_low_signal_article_image_url("https://example.com/images/chart-of-results.png")
        assert not is_low_signal_article_image_url("https://example.com/diagrams/architecture.svg")
