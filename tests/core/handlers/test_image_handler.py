"""Tests for pure functions in image_handler.py."""

import pytest

from src.core.handlers.image_handler import get_extension_from_content_type


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
